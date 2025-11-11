from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import datetime
from typing import Optional, Callable, Dict, List, Tuple

from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.const import STATE_ON, STATE_OFF
from homeassistant.util import dt as dt_util
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    # Modes
    MODE_ECO,
    MODE_START_STOP,
    MODE_MANUAL_AUTO,
    MODE_CHARGE_PLANNER,
    MODE_STARTSTOP_RESET,
    # Entities / config keys
    CONF_CABLE_CONNECTED,
    CONF_CHARGING_ENABLE,
    CONF_CURRENT_SETTING,
    CONF_LOCK_SENSOR,
    CONF_GRID_SINGLE,
    CONF_GRID_POWER,
    CONF_GRID_EXPORT,
    CONF_GRID_IMPORT,
    CONF_WALLBOX_THREE_PHASE,
    DEFAULT_WALLBOX_THREE_PHASE,
    CONF_WALLBOX_STATUS,
    WALLBOX_STATUS_CHARGING,
    CONF_ECO_ON_UPPER,
    CONF_ECO_ON_LOWER,
    CONF_ECO_OFF_UPPER,
    CONF_ECO_OFF_LOWER,
    DEFAULT_ECO_ON_UPPER,
    DEFAULT_ECO_ON_LOWER,
    DEFAULT_ECO_OFF_UPPER,
    DEFAULT_ECO_OFF_LOWER,
    MIN_CHARGE_POWER_SINGLE_PHASE_W,
    MIN_CHARGE_POWER_THREE_PHASE_W,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    CONF_SUSTAIN_SECONDS,
    DEFAULT_SUSTAIN_SECONDS,
    SUSTAIN_MAX_SECONDS,
    CONF_CHARGE_POWER,
    CONF_EV_BATTERY_LEVEL,
    CONF_OPT_MODE_ECO,
    CONF_PLANNER_START_ISO,
    CONF_PLANNER_STOP_ISO,
    CONF_SOC_LIMIT_PERCENT,
    CONF_MAX_CURRENT_LIMIT_A,
    # Supply profile
    CONF_SUPPLY_PROFILE,
    SUPPLY_PROFILES,
    SUPPLY_PROFILE_REG_THRESHOLDS,
    # Net power target
    CONF_NET_POWER_TARGET_W,
    DEFAULT_NET_POWER_TARGET_W,
)

from .priority import (
    async_get_priority,
    async_get_preferred_priority,
    async_set_priority,
    async_advance_priority_to_next,
    async_get_priority_mode_enabled,
    async_get_order,
    async_align_current_with_order,  # nieuw: voor preemptie als gates terug groen worden
)

_LOGGER = logging.getLogger(__name__)

STATE_STORAGE_VERSION = 1
STATE_STORAGE_KEY_PREFIX = "evcm_state"

CONNECT_DEBOUNCE_SECONDS = 1
EXPORT_SUSTAIN_SECONDS = 5
PLANNER_MONITOR_INTERVAL = 1.0

MIN_CURRENT_A = 6

REGULATION_MIN_POWER_3PH_W = 4000
REGULATION_MIN_POWER_1PH_W = 1300

# Unknown/unavailable reporting
UNKNOWN_EVENT_NAME = "evcm_unknown_state"
UNKNOWN_DEBOUNCE_SECONDS = 30.0
REPORT_UNKNOWN_GETTERS = False
REPORT_UNKNOWN_INITIAL = False
REPORT_UNKNOWN_ENFORCE = False
REPORT_UNKNOWN_TRANSITION_NEW = True
REPORT_UNKNOWN_TRANSITION_OLD = False
UNKNOWN_STARTUP_GRACE_SECONDS = 90.0


def _effective_config(entry: ConfigEntry) -> dict:
    return {**entry.data, **entry.options}


class EVLoadController:
    """
    Control logic:
      - Hysteresis start/stop (Manual OFF)
      - Planner & SoC & Priority gating (always)
      - Manual ON: auto-start without thresholds, no ±1A regulation
      - ±1A regulation (Manual OFF only)
      - Sustain timers
      - Net Power Target
      - Start/Stop Reset policy: on cable disconnect, Start/Stop follows Reset switch
      - Baseline to 6A on Start/Stop & Manual toggles and cable connect/disconnect
      - Priority advance on pause by planner/SOC/StartStop and cable disconnect
      - Priority preempt (reclaim) when planner/SOC/StartStop become allowed again
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry

        # Subscriptions & persistence
        self._unsub_listeners: List[Callable[[], None]] = []
        self._state_store: Store = Store(
            hass, STATE_STORAGE_VERSION, f"{STATE_STORAGE_KEY_PREFIX}_{entry.entry_id}"
        )
        self._state_loaded: bool = False
        self._state: Dict[str, Optional[object]] = {}

        # Mode flags
        self._modes: Dict[str, bool] = {
            MODE_ECO: True,
            MODE_START_STOP: True,
            MODE_MANUAL_AUTO: False,
            MODE_CHARGE_PLANNER: False,
            MODE_STARTSTOP_RESET: True,
        }
        self._mode_listeners: List[Callable[[], None]] = []

        # Planner & SoC
        self._planner_start_dt: Optional[datetime] = None
        self._planner_stop_dt: Optional[datetime] = None
        self._soc_limit_percent: Optional[int] = None

        eff = _effective_config(self.entry)

        # Entity references
        self._cable_entity: Optional[str] = eff.get(CONF_CABLE_CONNECTED)
        self._charging_enable_entity: Optional[str] = eff.get(CONF_CHARGING_ENABLE)
        self._current_setting_entity: Optional[str] = eff.get(CONF_CURRENT_SETTING)
        self._lock_entity: Optional[str] = eff.get(CONF_LOCK_SENSOR)
        self._wallbox_status_entity: Optional[str] = eff.get(CONF_WALLBOX_STATUS)
        self._charge_power_entity: Optional[str] = eff.get(CONF_CHARGE_POWER)
        self._ev_soc_entity: Optional[str] = eff.get(CONF_EV_BATTERY_LEVEL) or None

        # Grid sensors
        self._grid_single: bool = bool(eff.get(CONF_GRID_SINGLE, False))
        self._grid_power_entity: Optional[str] = eff.get(CONF_GRID_POWER)
        self._grid_export_entity: Optional[str] = eff.get(CONF_GRID_EXPORT)
        self._grid_import_entity: Optional[str] = eff.get(CONF_GRID_IMPORT)

        # Supply profile migration / fallback
        profile_key = eff.get(CONF_SUPPLY_PROFILE)
        if profile_key == "na_1ph_240":
            _LOGGER.info("Supply profile 'na_1ph_240' migrated to 'eu_1ph_230' (1-phase 230V/240V).")
            profile_key = "eu_1ph_230"
        profile_meta = SUPPLY_PROFILES.get(profile_key) if isinstance(profile_key, str) else None
        if not profile_meta:
            legacy_three = bool(eff.get(CONF_WALLBOX_THREE_PHASE, DEFAULT_WALLBOX_THREE_PHASE))
            profile_meta = SUPPLY_PROFILES["eu_3ph_400"] if legacy_three else SUPPLY_PROFILES["eu_1ph_230"]

        self._supply_profile_key: str = profile_key or ("eu_3ph_400" if profile_meta["phases"] == 3 else "eu_1ph_230")
        self._supply_phases: int = int(profile_meta.get("phases", 1))
        self._supply_phase_voltage_v: int = int(
            profile_meta.get("phase_voltage_v", 235 if self._supply_phases == 1 else 230)
        )
        self._profile_min_power_6a_w: int = int(
            profile_meta.get("min_power_6a_w", 1410 if self._supply_phases == 1 else 4140)
        )
        self._profile_reg_min_w: int = int(
            profile_meta.get("regulation_min_w", 1300 if self._supply_phases == 1 else 4000)
        )
        self._wallbox_three_phase: bool = bool(self._supply_phases == 3)

        # Threshold bands
        self._eco_on_upper: float = float(eff.get(CONF_ECO_ON_UPPER, DEFAULT_ECO_ON_UPPER))
        self._eco_on_lower: float = float(eff.get(CONF_ECO_ON_LOWER, DEFAULT_ECO_ON_LOWER))
        self._eco_off_upper: float = float(eff.get(CONF_ECO_OFF_UPPER, DEFAULT_ECO_OFF_UPPER))
        self._eco_off_lower: float = float(eff.get(CONF_ECO_OFF_LOWER, DEFAULT_ECO_OFF_LOWER))

        # Scan interval & planner values
        self._scan_interval: int = int(eff.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        self._planner_start_dt = self._parse_dt_option(eff.get(CONF_PLANNER_START_ISO))
        self._planner_stop_dt = self._parse_dt_option(eff.get(CONF_PLANNER_STOP_ISO))
        self._soc_limit_percent = self._parse_soc_option(eff.get(CONF_SOC_LIMIT_PERCENT))

        # Net power target (fine-regulation center)
        self._net_power_target_w: int = int(eff.get(CONF_NET_POWER_TARGET_W, DEFAULT_NET_POWER_TARGET_W))

        # Runtime state flags
        self._last_cable_connected: Optional[bool] = None
        self._auto_connect_task: Optional[asyncio.Task] = None
        self._regulation_task: Optional[asyncio.Task] = None
        self._resume_task: Optional[asyncio.Task] = None
        self._planner_monitor_task: Optional[asyncio.Task] = None
        self._charging_active: bool = False

        # Timers
        self._below_lower_since: Optional[float] = None
        self._below_lower_task: Optional[asyncio.Task] = None
        self._no_data_since: Optional[float] = None
        self._no_data_task: Optional[asyncio.Task] = None

        # Priority gating
        self._priority_allowed_cache: bool = True
        self._priority_mode_enabled: bool = False

        # Disconnect reset skip (initial)
        self._skip_next_disconnect_reset: bool = False

        # Unknown state reporting
        self._unknown_last_emit: Dict[Tuple[str, str], float] = {}
        self._init_monotonic: float = time.monotonic()

        # Track last SOC-allow state to detect False->True transitions (voor preemptie)
        self._last_soc_allows: Optional[bool] = None

        _LOGGER.debug(
            "Supply profile %s: phases=%s, phase_voltage=%sV, min_power_6A=%sW, reg_min=%sW, target=%sW",
            self._supply_profile_key,
            self._supply_phases,
            self._supply_phase_voltage_v,
            self._profile_min_power_6a_w,
            self._profile_reg_min_w,
            self._net_power_target_w,
        )

    # -------------------- Unknown / unavailable handling --------------------
    @staticmethod
    def _is_known_state(st) -> bool:
        return bool(st and st.state not in ("unknown", "unavailable"))

    @staticmethod
    def _is_unknownish_state(st) -> bool:
        return bool(st and st.state in ("unknown", "unavailable"))

    def _context_category(self, context: str) -> str:
        if "transition" in context:
            return "transition"
        if "initial" in context:
            return "initial"
        if "ensure_" in context:
            return "enforce"
        if "_get" in context:
            return "get"
        return "other"

    def _should_report_unknown(self, context: str, side: Optional[str]) -> bool:
        if (time.monotonic() - self._init_monotonic) < UNKNOWN_STARTUP_GRACE_SECONDS:
            cat = self._context_category(context)
            if cat == "transition" and side == "new" and REPORT_UNKNOWN_TRANSITION_NEW:
                return True
            return False

        cat = self._context_category(context)
        if cat == "get":
            return REPORT_UNKNOWN_GETTERS
        if cat == "initial":
            return REPORT_UNKNOWN_INITIAL
        if cat == "enforce":
            return REPORT_UNKNOWN_ENFORCE
        if cat == "transition":
            if side == "new":
                return REPORT_UNKNOWN_TRANSITION_NEW
            if side == "old":
                return REPORT_UNKNOWN_TRANSITION_OLD
        return True

    def _report_unknown(
        self,
        entity_id: Optional[str],
        raw_state: Optional[str],
        context: str,
        side: Optional[str] = None,
    ):
        if not entity_id:
            return
        if not self._should_report_unknown(context, side):
            return
        now = time.monotonic()
        key = (entity_id, f"{context}:{side}" if side else context)
        last = self._unknown_last_emit.get(key)
        if last is not None and (now - last) < UNKNOWN_DEBOUNCE_SECONDS:
            return
        self._unknown_last_emit[key] = now
        _LOGGER.warning(
            "Unknown/unavailable detected: entity=%s state=%s context=%s%s entry=%s",
            entity_id,
            raw_state,
            context,
            f":{side}" if side else "",
            self.entry.entry_id,
        )
        with contextlib.suppress(Exception):
            self.hass.bus.async_fire(
                UNKNOWN_EVENT_NAME,
                {
                    "entry_id": self.entry.entry_id,
                    "entity_id": entity_id,
                    "state": raw_state,
                    "context": f"{context}{(':'+side) if side else ''}",
                },
            )

    # -------------------- Persistence (unified state) --------------------
    async def _load_unified_state(self):
        if self._state_loaded:
            return
        data = await self._state_store.async_load()
        if not isinstance(data, dict):
            eff = _effective_config(self.entry)
            eco_opt = eff.get(CONF_OPT_MODE_ECO)
            planner_start_iso = eff.get(CONF_PLANNER_START_ISO)
            planner_stop_iso = eff.get(CONF_PLANNER_STOP_ISO)
            soc_opt = eff.get(CONF_SOC_LIMIT_PERCENT)
            # include target default
            target_opt = eff.get(CONF_NET_POWER_TARGET_W, DEFAULT_NET_POWER_TARGET_W)
            self._state = {
                "version": STATE_STORAGE_VERSION,
                "eco_enabled": True if eco_opt is None else bool(eco_opt),
                "planner_enabled": False,
                "planner_start_iso": planner_start_iso if isinstance(planner_start_iso, str) else None,
                "planner_stop_iso": planner_stop_iso if isinstance(planner_stop_iso, str) else None,
                "soc_limit_percent": self._safe_int(soc_opt),
                "startstop_reset_enabled": True,
                "start_stop_enabled": True,
                "manual_enabled": False,
                "net_power_target_w": int(target_opt) if isinstance(target_opt, (int, float)) else DEFAULT_NET_POWER_TARGET_W,
            }
            await self._state_store.async_save(self._state)
            _LOGGER.debug("Unified state initialized: %s", self._state)
        else:
            self._state = data
            _LOGGER.debug("Unified state loaded: %s", self._state)

        self._modes[MODE_ECO] = bool(self._state.get("eco_enabled", True))
        self._modes[MODE_CHARGE_PLANNER] = bool(self._state.get("planner_enabled", False))
        self._modes[MODE_STARTSTOP_RESET] = bool(self._state.get("startstop_reset_enabled", True))
        self._modes[MODE_START_STOP] = bool(self._state.get("start_stop_enabled", True))
        self._modes[MODE_MANUAL_AUTO] = bool(self._state.get("manual_enabled", False))

        self._planner_start_dt = self._parse_dt_option(self._state.get("planner_start_iso"))
        self._planner_stop_dt = self._parse_dt_option(self._state.get("planner_stop_iso"))
        soc = self._safe_int(self._state.get("soc_limit_percent"))
        self._soc_limit_percent = soc if soc is not None and 0 <= soc <= 100 else None

        # load target
        try:
            self._net_power_target_w = int(self._state.get("net_power_target_w", DEFAULT_NET_POWER_TARGET_W))
        except Exception:
            self._net_power_target_w = DEFAULT_NET_POWER_TARGET_W

        self._state_loaded = True

    async def _save_unified_state(self):
        to_save = {
            "version": STATE_STORAGE_VERSION,
            "eco_enabled": self.get_mode(MODE_ECO),
            "planner_enabled": self.get_mode(MODE_CHARGE_PLANNER),
            "planner_start_iso": self._planner_start_dt.isoformat() if self._planner_start_dt else None,
            "planner_stop_iso": self._planner_stop_dt.isoformat() if self._planner_stop_dt else None,
            "soc_limit_percent": self._soc_limit_percent,
            "startstop_reset_enabled": self.get_mode(MODE_STARTSTOP_RESET),
            "start_stop_enabled": self.get_mode(MODE_START_STOP),
            "manual_enabled": self.get_mode(MODE_MANUAL_AUTO),
            "net_power_target_w": self._net_power_target_w,
        }
        with contextlib.suppress(Exception):
            await self._state_store.async_save(to_save)
        _LOGGER.debug("Unified state persisted: %s", to_save)

    @staticmethod
    def _safe_int(v) -> Optional[int]:
        try:
            if v in (None, ""):
                return None
            return int(round(float(v)))
        except Exception:
            return None

    # -------------------- Priority helpers --------------------
    async def _refresh_priority_mode_flag(self):
        self._priority_mode_enabled = await async_get_priority_mode_enabled(self.hass)

    async def _is_priority_allowed(self) -> bool:
        if not self._priority_mode_enabled:
            return True
        pid = await async_get_priority(self.hass)
        if pid is None:
            return True
        return pid == self.entry.entry_id

    async def _is_current_priority(self) -> bool:
        pid = await async_get_priority(self.hass)
        return pid == self.entry.entry_id

    def on_global_priority_changed(self):
        if not self._state_loaded:
            return
        self.hass.async_create_task(self._refresh_priority_and_apply())

    async def _refresh_priority_and_apply(self):
        await self._refresh_priority_mode_flag()
        self._priority_allowed_cache = await self._is_priority_allowed()
        await self._apply_priority_gating()
        await self._hysteresis_apply()

    async def _apply_priority_gating(self):
        if not self._priority_mode_enabled:
            self._priority_allowed_cache = True
        if not self._priority_allowed_cache:
            self._stop_regulation_loop()
            self._stop_resume_monitor()
        else:
            self._start_regulation_loop_if_needed()
            self._start_resume_monitor_if_needed()

    # -------------------- Parse helpers --------------------
    def _parse_dt_option(self, s: Optional[str]) -> Optional[datetime]:
        if not s or not isinstance(s, str):
            return None
        try:
            dt = dt_util.parse_datetime(s)
        except Exception:
            return None
        return dt_util.as_local(dt) if dt else None

    def _parse_soc_option(self, v) -> Optional[int]:
        if v in (None, ""):
            return None
        try:
            iv = int(round(float(v)))
        except Exception:
            return None
        return max(0, min(100, iv))

    # Public helper used by priority code
    def is_cable_connected(self) -> bool:
        return self._is_cable_connected()

    def _max_current_a(self) -> int:
        eff = _effective_config(self.entry)
        try:
            v = int(eff.get(CONF_MAX_CURRENT_LIMIT_A, 16))
        except Exception:
            v = 16
        return max(MIN_CURRENT_A, min(32, v))

    # -------------------- Net Power Target API --------------------
    @property
    def net_power_target_w(self) -> int:
        return int(self._net_power_target_w)

    def set_net_power_target_w(self, value: Optional[float | int]):
        try:
            iv = int(round(float(value if value is not None else DEFAULT_NET_POWER_TARGET_W)))
        except Exception:
            iv = DEFAULT_NET_POWER_TARGET_W
        # clamp to reasonable range without needing const imports here
        if iv < -50000:
            iv = -50000
        if iv > 50000:
            iv = 50000
        if iv != self._net_power_target_w:
            self._net_power_target_w = iv
            self.hass.async_create_task(self._save_unified_state())
            _LOGGER.info("Net power target updated → %s W", iv)

    # -------------------- Planner & SoC public API --------------------
    @property
    def planner_start_dt(self) -> Optional[datetime]:
        return self._planner_start_dt

    @property
    def planner_stop_dt(self) -> Optional[datetime]:
        return self._planner_stop_dt

    def set_planner_start_dt(self, dt: Optional[datetime]):
        if dt:
            dt = dt_util.as_local(dt)
        self._planner_start_dt = dt
        self.hass.async_create_task(self._save_unified_state())
        _LOGGER.debug("Planner start set: %s", dt)
        if self._planner_enabled():
            self.hass.async_create_task(self._hysteresis_apply())

    def set_planner_stop_dt(self, dt: Optional[datetime]):
        if dt:
            dt = dt_util.as_local(dt)
        self._planner_stop_dt = dt
        self.hass.async_create_task(self._save_unified_state())
        _LOGGER.debug("Planner stop set: %s", dt)
        if self._planner_enabled():
            self.hass.async_create_task(self._hysteresis_apply())

    @property
    def soc_limit_percent(self) -> Optional[int]:
        return self._soc_limit_percent

    def set_soc_limit_percent(self, percent: Optional[float | int]):
        if percent is None:
            self._soc_limit_percent = None
        else:
            try:
                self._soc_limit_percent = max(0, min(100, int(round(float(percent)))))
            except Exception:
                self._soc_limit_percent = None
        self.hass.async_create_task(self._save_unified_state())
        _LOGGER.debug("SoC limit set: %s", self._soc_limit_percent)
        self.hass.async_create_task(self._hysteresis_apply())

    # -------------------- Mode listeners --------------------
    def add_mode_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._mode_listeners.append(cb)

        def _remove():
            with contextlib.suppress(Exception):
                self._mode_listeners.remove(cb)

        return _remove

    def _notify_mode_listeners(self):
        for cb in list(self._mode_listeners):
            with contextlib.suppress(Exception):
                cb()

    # -------------------- Planner gating --------------------
    def _planner_enabled(self) -> bool:
        return self.get_mode(MODE_CHARGE_PLANNER)

    def _planner_window_valid(self) -> bool:
        if not self._planner_enabled():
            return True
        if self._planner_start_dt is None or self._planner_stop_dt is None:
            return False
        return self._planner_start_dt < self._planner_stop_dt

    def _is_within_planner_window(self) -> bool:
        if not self._planner_enabled():
            return True
        if not self._planner_window_valid():
            return False
        now = dt_util.as_local(dt_util.utcnow())
        return self._planner_start_dt <= now < self._planner_stop_dt

    def _planner_window_allows_start(self) -> bool:
        if not self._planner_enabled():
            return True
        return self._planner_window_valid() and self._is_within_planner_window()

    # -------------------- SoC gating --------------------
    def _get_ev_soc_percent(self) -> Optional[float]:
        if not self._ev_soc_entity:
            return None
        st = self.hass.states.get(self._ev_soc_entity)
        if not self._is_known_state(st):
            self._report_unknown(self._ev_soc_entity, getattr(st, "state", None), "soc_get")
            return None
        try:
            val = float(st.state)
        except Exception:
            return None
        if val < 0 or val > 110:
            return None
        return val

    def _soc_limit_reached(self) -> bool:
        if self._ev_soc_entity is None:
            return False
        if self._soc_limit_percent is None:
            return False
        soc = self._get_ev_soc_percent()
        return bool(soc is not None and soc >= self._soc_limit_percent)

    def _soc_allows_start(self) -> bool:
        if self._ev_soc_entity is None:
            return True
        if self._soc_limit_percent is None:
            return True
        soc = self._get_ev_soc_percent()
        if soc is None:
            return True
        return soc < self._soc_limit_percent

    # -------------------- Supply-profile derived minima --------------------
    def _effective_regulation_min_power(self) -> int:
        """Profile-dependent minimum power for A-step regulation."""
        if self._supply_phases == 3:
            return self._profile_reg_min_w or REGULATION_MIN_POWER_3PH_W
        return self._profile_reg_min_w or REGULATION_MIN_POWER_1PH_W

    def _effective_min_charge_power(self) -> int:
        """Profile-dependent minimum indicative charging power at 6A."""
        if self._supply_phases == 3:
            return max(self._profile_min_power_6a_w, MIN_CHARGE_POWER_THREE_PHASE_W)
        return max(self._profile_min_power_6a_w, MIN_CHARGE_POWER_SINGLE_PHASE_W)

    # -------------------- Initialization / Shutdown --------------------
    async def async_initialize(self):
        await self._load_unified_state()
        await self._refresh_priority_mode_flag()
        self._priority_allowed_cache = await self._is_priority_allowed()
        self._skip_next_disconnect_reset = True
        self._init_monotonic = time.monotonic()
        # Init SOC-allow tracker (om False->True te kunnen detecteren)
        with contextlib.suppress(Exception):
            self._last_soc_allows = self._soc_allows_start()
        self._subscribe_listeners()
        _LOGGER.info(
            "EVLoadController init (priority_mode=%s, priority_allowed=%s, ECO=%s, planner=%s, StartStop=%s, Manual=%s, SoC_limit=%s%%, SoC_sensor=%s, profile=%s, target=%sW)",
            self._priority_mode_enabled,
            self._priority_allowed_cache,
            self.get_mode(MODE_ECO),
            self.get_mode(MODE_CHARGE_PLANNER),
            self.get_mode(MODE_START_STOP),
            self.get_mode(MODE_MANUAL_AUTO),
            self._soc_limit_percent,
            self._ev_soc_entity,
            self._supply_profile_key,
            self._net_power_target_w,
        )
        await self._enforce_start_stop_policy()
        await self._apply_cable_state_initial()
        self._start_planner_monitor_if_needed()
        if self._priority_allowed_cache:
            self._start_regulation_loop_if_needed()
            self._start_resume_monitor_if_needed()
        self._evaluate_missing_and_start_no_data_timer()

    async def async_shutdown(self):
        self._cancel_auto_connect_task()
        self._stop_regulation_loop()
        self._stop_resume_monitor()
        self._stop_planner_monitor()
        self._cancel_below_lower_timer()
        self._cancel_no_data_timer()
        for unsub in list(self._unsub_listeners):
            with contextlib.suppress(Exception):
                unsub()
        self._unsub_listeners = []

    # -------------------- Subscriptions --------------------
    def _subscribe_listeners(self):
        for unsub in list(self._unsub_listeners):
            with contextlib.suppress(Exception):
                unsub()
        self._unsub_listeners = []
        if self._cable_entity:
            self._unsub_listeners.append(
                async_track_state_change_event(self.hass, self._cable_entity, self._async_cable_event)
            )
        if self._charging_enable_entity:
            self._unsub_listeners.append(
                async_track_state_change_event(self.hass, self._charging_enable_entity, self._async_charging_enable_event)
            )
        if self._lock_entity:
            self._unsub_listeners.append(
                async_track_state_change_event(self.hass, self._lock_entity, self._async_lock_event)
            )
        if self._wallbox_status_entity:
            self._unsub_listeners.append(
                async_track_state_change_event(self.hass, self._wallbox_status_entity, self._async_wallbox_status_event)
            )
        if self._charge_power_entity:
            self._unsub_listeners.append(
                async_track_state_change_event(self.hass, self._charge_power_entity, self._async_charge_power_event)
            )
        if self._grid_single and self._grid_power_entity:
            self._unsub_listeners.append(
                async_track_state_change_event(self.hass, self._grid_power_entity, self._async_net_power_event)
            )
        else:
            if self._grid_export_entity:
                self._unsub_listeners.append(
                    async_track_state_change_event(self.hass, self._grid_export_entity, self._async_net_power_event)
                )
            if self._grid_import_entity:
                self._unsub_listeners.append(
                    async_track_state_change_event(self.hass, self._grid_import_entity, self._async_net_power_event)
                )
        if self._ev_soc_entity:
            self._unsub_listeners.append(
                async_track_state_change_event(self.hass, self._ev_soc_entity, self._async_ev_soc_event)
            )

    # -------------------- Missing data / timers evaluation --------------------
    def _evaluate_missing_and_start_no_data_timer(self):
        if self._planner_enabled() and (
            not self._planner_window_valid() or not self._is_within_planner_window()
        ):
            if self._no_data_since is not None:
                _LOGGER.debug("No-data timer reset (planner inactive)")
            self._no_data_since = None
            self._cancel_no_data_timer()
            return

        missing = self._current_missing_components()
        if not self._conditions_for_timers():
            if self._no_data_since is not None:
                _LOGGER.debug("No-data timer reset (conditions invalid)")
            self._no_data_since = None
            self._cancel_no_data_timer()
            return

        if missing:
            if self._no_data_since is None and self._sustain_seconds() > 0:
                self._no_data_since = time.monotonic()
                _LOGGER.debug("No-data timer start (missing: %s)", ", ".join(missing))
                self._schedule_no_data_timer()
        else:
            if self._no_data_since is not None:
                _LOGGER.debug("No-data timer cancel (data OK)")
            self._no_data_since = None
            self._cancel_no_data_timer()

    # -------------------- Event callbacks --------------------
    @callback
    def _async_cable_event(self, event: Event):
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        self.hass.async_create_task(self._refresh_priority_mode_flag())
        if not (self._is_known_state(old) and self._is_known_state(new)):
            if self._is_unknownish_state(new):
                self._report_unknown(
                    self._cable_entity, getattr(new, "state", None), "cable_transition", side="new"
                )
            elif self._is_unknownish_state(old):
                if self._should_report_unknown("cable_transition", side="old"):
                    self._report_unknown(
                        self._cable_entity, getattr(old, "state", None), "cable_transition", side="old"
                    )
            return
        self._handle_cable_change(old, new)
        self._evaluate_missing_and_start_no_data_timer()

    @callback
    def _async_charging_enable_event(self, event: Event):
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        self.hass.async_create_task(self._refresh_priority_mode_flag())
        if not (self._is_known_state(old) and self._is_known_state(new)):
            if self._is_unknownish_state(new):
                self._report_unknown(
                    self._charging_enable_entity,
                    getattr(new, "state", None),
                    "charging_enable_transition",
                    side="new",
                )
            elif self._is_unknownish_state(old):
                if self._should_report_unknown("charging_enable_transition", side="old"):
                    self._report_unknown(
                        self._charging_enable_entity,
                        getattr(old, "state", None),
                        "charging_enable_transition",
                        side="old",
                    )
            return
        if not self.get_mode(MODE_START_STOP):
            self.hass.async_create_task(self._ensure_charging_enable_off())
            return
        self.hass.async_create_task(self._hysteresis_apply())
        self._evaluate_missing_and_start_no_data_timer()
        if (
            self._is_charging_enabled()
            and not self.get_mode(MODE_MANUAL_AUTO)
            and self._is_cable_connected()
        ):
            self._start_regulation_loop_if_needed()

    @callback
    def _async_net_power_event(self, event: Event):
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        ent = event.data.get("entity_id")
        if not (self._is_known_state(old) and self._is_known_state(new)):
            if self._is_unknownish_state(new):
                self._report_unknown(ent, getattr(new, "state", None), "net_power_transition", side="new")
            elif self._is_unknownish_state(old):
                if self._should_report_unknown("net_power_transition", side="old"):
                    self._report_unknown(ent, getattr(old, "state", None), "net_power_transition", side="old")
            return
        if self.get_mode(MODE_START_STOP) and not self.get_mode(MODE_MANUAL_AUTO):
            self.hass.async_create_task(self._hysteresis_apply())
        self._evaluate_missing_and_start_no_data_timer()

    @callback
    def _async_wallbox_status_event(self, event: Event):
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        if not (self._is_known_state(old) and self._is_known_state(new)):
            if self._is_unknownish_state(new):
                self._report_unknown(
                    self._wallbox_status_entity, getattr(new, "state", None), "status_transition", side="new"
                )
            elif self._is_unknownish_state(old):
                if self._should_report_unknown("status_transition", side="old"):
                    self._report_unknown(
                        self._wallbox_status_entity, getattr(old, "state", None), "status_transition", side="old"
                    )
            return
        self._start_regulation_loop_if_needed()
        if self.get_mode(MODE_START_STOP):
            self.hass.async_create_task(self._hysteresis_apply())
        self._evaluate_missing_and_start_no_data_timer()

    @callback
    def _async_charge_power_event(self, event: Event):
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        if not (self._is_known_state(old) and self._is_known_state(new)):
            if self._is_unknownish_state(new):
                self._report_unknown(
                    self._charge_power_entity, getattr(new, "state", None), "charge_power_transition", side="new"
                )
            elif self._is_unknownish_state(old):
                if self._should_report_unknown("charge_power_transition", side="old"):
                    self._report_unknown(
                        self._charge_power_entity, getattr(old, "state", None), "charge_power_transition", side="old"
                    )
            return
        self._start_regulation_loop_if_needed()
        if self.get_mode(MODE_START_STOP):
            self.hass.async_create_task(self._hysteresis_apply())
        self._evaluate_missing_and_start_no_data_timer()

    @callback
    def _async_lock_event(self, event: Event):
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        if not (self._is_known_state(old) and self._is_known_state(new)):
            if self._is_unknownish_state(new):
                self._report_unknown(
                    self._lock_entity, getattr(new, "state", None), "lock_transition", side="new"
                )
            elif self._is_unknownish_state(old):
                if self._should_report_unknown("lock_transition", side="old"):
                    self._report_unknown(
                        self._lock_entity, getattr(old, "state", None), "lock_transition", side="old"
                    )
            return
        if old.state == "locked" and new.state == "unlocked":
            if self.get_mode(MODE_START_STOP) and self._is_cable_connected():
                if (
                    self._essential_data_available()
                    and self._planner_window_allows_start()
                    and self._soc_allows_start()
                ):
                    self.hass.async_create_task(self._ensure_charging_enable_on())
                    self._start_regulation_loop_if_needed()
        self._evaluate_missing_and_start_no_data_timer()

    @callback
    def _async_ev_soc_event(self, event: Event):
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        if not (self._is_known_state(old) and self._is_known_state(new)):
            if self._is_unknownish_state(new):
                self._report_unknown(
                    self._ev_soc_entity, getattr(new, "state", None), "soc_transition", side="new"
                )
            elif self._is_unknownish_state(old):
                if self._should_report_unknown("soc_transition", side="old"):
                    self._report_unknown(
                        self._ev_soc_entity, getattr(old, "state", None), "soc_transition", side="old"
                    )
            return
        allows = self._soc_allows_start()
        prev = self._last_soc_allows
        self._last_soc_allows = allows
        _LOGGER.debug(
            "EV SOC change: %s -> %s (limit=%s, allows_start=%s, prev=%s)",
            old.state if old else None,
            new.state if new else None,
            self._soc_limit_percent,
            allows,
            prev,
        )
        # Preempt: SOC False->True → align current naar first eligible
        if allows and prev is False and self._priority_mode_enabled:
            self.hass.async_create_task(async_align_current_with_order(self.hass))
        self.hass.async_create_task(self._hysteresis_apply())
        self._evaluate_missing_and_start_no_data_timer()

    # -------------------- Cable handling --------------------
    def _handle_cable_change(self, old_state, new_state):
        connected = (new_state.state if new_state else None) == STATE_ON
        if self._last_cable_connected is not None and connected == self._last_cable_connected:
            return
        self._last_cable_connected = connected
        if connected:
            self.hass.async_create_task(self._on_cable_connected())
        else:
            self.hass.async_create_task(self._on_cable_disconnected())

    async def _apply_cable_state_initial(self):
        if not self._cable_entity:
            return
        st = self.hass.states.get(self._cable_entity)
        if not self._is_known_state(st):
            if self._is_unknownish_state(st):
                if self._should_report_unknown("cable_initial", side="new"):
                    self._report_unknown(
                        self._cable_entity, getattr(st, "state", None), "cable_initial", side="new"
                    )
            return
        self._last_cable_connected = st.state == STATE_ON
        if self._last_cable_connected:
            await self._on_cable_connected()
        else:
            await self._on_cable_disconnected()

    async def _on_cable_connected(self):
        self._reset_timers()
        if self._current_setting_entity:
            with contextlib.suppress(Exception):
                dom, _ = self._current_setting_entity.split(".", 1)
                if dom == "number":
                    await self.hass.services.async_call(
                        "number",
                        "set_value",
                        {"entity_id": self._current_setting_entity, "value": MIN_CURRENT_A},
                        blocking=True,
                    )

        # Priority restore / takeover / advance
        try:
            if self._priority_mode_enabled:
                preferred = await async_get_preferred_priority(self.hass)
                current = await async_get_priority(self.hass)
                if preferred == self.entry.entry_id and current not in (None, self.entry.entry_id):
                    await async_set_priority(self.hass, self.entry.entry_id)
                    self._priority_allowed_cache = await self._is_priority_allowed()
        except Exception:
            _LOGGER.debug("Preemptive priority restore failed", exc_info=True)

        try:
            if self._priority_mode_enabled:
                order = await async_get_order(self.hass)
                if order and order[0] == self.entry.entry_id:
                    current = await async_get_priority(self.hass)
                    if current != self.entry.entry_id:
                        await async_set_priority(self.hass, self.entry.entry_id)
                        self._priority_allowed_cache = await self._is_priority_allowed()
        except Exception:
            _LOGGER.debug("Top-of-order takeover failed", exc_info=True)

        try:
            if self._priority_mode_enabled:
                pid = await async_get_priority(self.hass)
                if pid and pid != self.entry.entry_id:
                    data = (self.hass.data.get(DOMAIN, {}) or {}).get(pid) or {}
                    cur_ctl = data.get("controller")
                    if cur_ctl and not cur_ctl.is_cable_connected():
                        await async_advance_priority_to_next(self.hass, pid)
                        self._priority_allowed_cache = await self._is_priority_allowed()
        except Exception:
            _LOGGER.debug("Proactive advance failed", exc_info=True)

        if self.get_mode(MODE_MANUAL_AUTO):
            if self.get_mode(MODE_START_STOP):
                if (
                    self._priority_allowed_cache
                    and self._essential_data_available()
                    and self._planner_window_allows_start()
                    and self._soc_allows_start()
                ):
                    await self._ensure_charging_enable_on()
                    self._charging_active = True
                else:
                    await self._ensure_charging_enable_off()
            else:
                await self._ensure_charging_enable_off()
                self._charging_active = False
            self._stop_resume_monitor()
            self._stop_regulation_loop()
            self._evaluate_missing_and_start_no_data_timer()
            return

        if not self.get_mode(MODE_START_STOP):
            await self._ensure_charging_enable_off()
            self._evaluate_missing_and_start_no_data_timer()
            return

        if (not self._planner_window_allows_start()) or (not self._soc_allows_start()):
            self._start_resume_monitor_if_needed()
            self._evaluate_missing_and_start_no_data_timer()
            return

        if not self._priority_allowed_cache:
            self._start_resume_monitor_if_needed()
            self._evaluate_missing_and_start_no_data_timer()
            return

        self._start_auto_connect_routine()
        await self._hysteresis_apply()
        self._start_regulation_loop_if_needed()
        self._start_resume_monitor_if_needed()
        self._evaluate_missing_and_start_no_data_timer()

    async def _on_cable_disconnected(self):
        self._cancel_auto_connect_task()
        self._stop_regulation_loop()
        self._stop_resume_monitor()
        self._charging_active = False
        self._reset_timers()
        await self._ensure_charging_enable_off()
        if self._current_setting_entity:
            with contextlib.suppress(Exception):
                dom, _ = self._current_setting_entity.split(".", 1)
                if dom == "number":
                    await self.hass.services.async_call(
                        "number",
                        "set_value",
                        {"entity_id": self._current_setting_entity, "value": MIN_CURRENT_A},
                        blocking=True,
                    )

        # Advance to next priority if this entry was current
        try:
            if self._priority_mode_enabled:
                cur = await async_get_priority(self.hass)
                if cur == self.entry.entry_id:
                    await async_advance_priority_to_next(self.hass, self.entry.entry_id)
        except Exception:
            _LOGGER.debug("Advance on disconnect failed", exc_info=True)

        # Start/Stop Reset policy: align Start/Stop with reset switch on disconnect
        desired = self.get_mode(MODE_STARTSTOP_RESET)
        if self.get_mode(MODE_START_STOP) != desired:
            prev = self.get_mode(MODE_START_STOP)
            self._modes[MODE_START_STOP] = desired
            await self._save_unified_state()
            _LOGGER.debug(
                "Start/Stop Reset applied on disconnect: start_stop=%s (was %s)",
                desired,
                prev,
            )
            self._notify_mode_listeners()
            if not desired:
                await self._ensure_charging_enable_off()
                self._charging_active = False

        self._evaluate_missing_and_start_no_data_timer()

    # -------------------- Auto-connect routine --------------------
    def _cancel_auto_connect_task(self):
        t = self._auto_connect_task
        self._auto_connect_task = None
        if t and not t.done():
            t.cancel()

    def _start_auto_connect_routine(self):
        if self.get_mode(MODE_MANUAL_AUTO):
            return
        self._cancel_auto_connect_task()
        self._auto_connect_task = self.hass.async_create_task(self._auto_connect_task_run())

    async def _auto_connect_task_run(self):
        try:
            await asyncio.sleep(CONNECT_DEBOUNCE_SECONDS)
            if (
                not self._is_cable_connected()
                or self.get_mode(MODE_MANUAL_AUTO)
                or not self.get_mode(MODE_START_STOP)
            ):
                return
            if not self._priority_allowed_cache:
                return
            if not self._planner_window_allows_start() or not self._soc_allows_start():
                return
            if not self._essential_data_available():
                return
            up = self._current_upper()
            if up <= self._current_lower():
                return
            net = self._get_net_power_w()
            if net is not None and net >= up:
                await self._ensure_charging_enable_on()
                self._charging_active = True
                self._start_regulation_loop_if_needed()
                return
            above_since: Optional[float] = None
            while True:
                if (
                    not self._is_cable_connected()
                    or self.get_mode(MODE_MANUAL_AUTO)
                    or not self.get_mode(MODE_START_STOP)
                ):
                    return
                if not self._priority_allowed_cache:
                    return
                if (not self._planner_window_allows_start()) or (not self._soc_allows_start()):
                    above_since = None
                    await asyncio.sleep(1)
                    continue
                if not self._essential_data_available():
                    above_since = None
                    await asyncio.sleep(1)
                    continue
                up = self._current_upper()
                net = self._get_net_power_w()
                now = time.monotonic()
                if net is not None and net >= up:
                    if above_since is None:
                        above_since = now
                    elif (now - above_since) >= EXPORT_SUSTAIN_SECONDS:
                        await self._ensure_charging_enable_on()
                        self._charging_active = True
                        self._start_regulation_loop_if_needed()
                        return
                else:
                    above_since = None
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            _LOGGER.warning("Auto-connect error: %s", exc)

    # -------------------- Planner monitor --------------------
    def _start_planner_monitor_if_needed(self):
        if not self._planner_enabled():
            self._stop_planner_monitor()
            return
        if self._planner_monitor_task and not self._planner_monitor_task.done():
            return
        self._planner_monitor_task = self.hass.async_create_task(self._planner_monitor_loop())

    def _stop_planner_monitor(self):
        task = self._planner_monitor_task
        self._planner_monitor_task = None
        if task and not task.done():
            task.cancel()

    async def _planner_monitor_loop(self):
        previous_allows: Optional[bool] = None
        try:
            while self._planner_enabled():
                allows = self._planner_window_allows_start()
                if self.get_mode(MODE_START_STOP):
                    if self._charging_active and not allows:
                        _LOGGER.info("Planner monitor: window ended/invalid → pause.")
                        self._charging_active = False
                        await self._ensure_charging_enable_off()
                        with contextlib.suppress(Exception):
                            if self._current_setting_entity:
                                await self._set_current_setting_a(MIN_CURRENT_A)
                        self._stop_regulation_loop()
                        # Advance bij gating
                        try:
                            if self._priority_mode_enabled:
                                cur = await async_get_priority(self.hass)
                                if cur == self.entry.entry_id:
                                    await async_advance_priority_to_next(self.hass, self.entry.entry_id)
                        except Exception:
                            _LOGGER.debug("Advance on planner gating failed", exc_info=True)
                    # Venster opent net → preempt/align en dan lokale logica
                    elif allows and previous_allows is False:
                        if self._priority_mode_enabled:
                            with contextlib.suppress(Exception):
                                await async_align_current_with_order(self.hass)
                        await self._hysteresis_apply()
                previous_allows = allows
                await asyncio.sleep(PLANNER_MONITOR_INTERVAL)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            _LOGGER.warning("Planner monitor error: %s", exc)

    # -------------------- Hysteresis --------------------
    def _current_upper(self) -> float:
        return self._eco_on_upper if self.get_mode(MODE_ECO) else self._eco_off_upper

    def _current_lower(self) -> float:
        return self._eco_on_lower if self.get_mode(MODE_ECO) else self._eco_off_lower

    async def _hysteresis_apply(self, preserve_current: bool = False):
        if not self.get_mode(MODE_START_STOP):
            self._reset_timers()
            await self._ensure_charging_enable_off()
            self._charging_active = False
            self._stop_regulation_loop()
            self._stop_resume_monitor()
            return

        # Manual ON
        if self.get_mode(MODE_MANUAL_AUTO):
            self._reset_timers()
            self._stop_regulation_loop()
            self._stop_resume_monitor()

            if not self._is_cable_connected():
                self._charging_active = False
                await self._ensure_charging_enable_off()
                return

            if not self._planner_window_allows_start():
                if self._charging_active:
                    _LOGGER.info("Planner window inactive (manual) → pause.")
                    self._charging_active = False
                    await self._ensure_charging_enable_off()
                    if not preserve_current and self._current_setting_entity:
                        with contextlib.suppress(Exception):
                            await self._set_current_setting_a(MIN_CURRENT_A)
                    # Advance
                    try:
                        if self._priority_mode_enabled:
                            cur = await async_get_priority(self.hass)
                            if cur == self.entry.entry_id:
                                await async_advance_priority_to_next(self.hass, self.entry.entry_id)
                    except Exception:
                        _LOGGER.debug("Advance on manual planner gating failed", exc_info=True)
                return

            if not self._soc_allows_start():
                if self._charging_active:
                    _LOGGER.info("SOC gating (manual) → pause.")
                    self._charging_active = False
                    await self._ensure_charging_enable_off()
                    if not preserve_current and self._current_setting_entity:
                        with contextlib.suppress(Exception):
                            await self._set_current_setting_a(MIN_CURRENT_A)
                    # Advance
                    try:
                        if self._priority_mode_enabled:
                            cur = await async_get_priority(self.hass)
                            if cur == self.entry.entry_id:
                                await async_advance_priority_to_next(self.hass, self.entry.entry_id)
                    except Exception:
                        _LOGGER.debug("Advance on manual soc gating failed", exc_info=True)
                return

            if not self._priority_allowed_cache:
                if self._charging_active:
                    _LOGGER.info("Priority gating (manual) → pause.")
                    self._charging_active = False
                    await self._ensure_charging_enable_off()
                    if not preserve_current and self._current_setting_entity:
                        with contextlib.suppress(Exception):
                            await self._set_current_setting_a(MIN_CURRENT_A)
                return

            if (not self._charging_active) and self._essential_data_available():
                await self._ensure_charging_enable_on()
                self._charging_active = True
            return

        # Manual OFF
        if not self._is_cable_connected():
            self._reset_timers()
            self._charging_active = False
            self._stop_regulation_loop()
            self._stop_resume_monitor()
            await self._ensure_charging_enable_off()
            return

        if not self._planner_window_allows_start():
            if self._charging_active:
                _LOGGER.info("Planner window inactive → pause.")
                self._charging_active = False
                await self._ensure_charging_enable_off()
                if not preserve_current and self._current_setting_entity:
                    with contextlib.suppress(Exception):
                        await self._set_current_setting_a(MIN_CURRENT_A)
                self._stop_regulation_loop()
                # Advance
                try:
                    if self._priority_mode_enabled:
                        cur = await async_get_priority(self.hass)
                        if cur == self.entry.entry_id:
                            await async_advance_priority_to_next(self.hass, self.entry.entry_id)
                except Exception:
                    _LOGGER.debug("Advance on planner gating failed", exc_info=True)
            self._start_resume_monitor_if_needed()
            self._evaluate_missing_and_start_no_data_timer()
            return

        if not self._soc_allows_start():
            if self._charging_active:
                _LOGGER.info("SOC gating → pause.")
                self._charging_active = False
                await self._ensure_charging_enable_off()
                if not preserve_current and self._current_setting_entity:
                    with contextlib.suppress(Exception):
                        await self._set_current_setting_a(MIN_CURRENT_A)
                self._stop_regulation_loop()
                # Advance
                try:
                    if self._priority_mode_enabled:
                        cur = await async_get_priority(self.hass)
                        if cur == self.entry.entry_id:
                            await async_advance_priority_to_next(self.hass, self.entry.entry_id)
                except Exception:
                    _LOGGER.debug("Advance on soc gating failed", exc_info=True)
            self._start_resume_monitor_if_needed()
            self._evaluate_missing_and_start_no_data_timer()
            return

        if not self._priority_allowed_cache:
            if self._charging_active:
                self._charging_active = False
                await self._ensure_charging_enable_off()
                if not preserve_current and self._current_setting_entity:
                    with contextlib.suppress(Exception):
                        await self._set_current_setting_a(MIN_CURRENT_A)
                self._stop_regulation_loop()
            self._start_resume_monitor_if_needed()
            self._evaluate_missing_and_start_no_data_timer()
            return

        net = self._get_net_power_w()
        if net is None or not self._essential_data_available():
            if not self._charging_active:
                await self._ensure_charging_enable_off()
            self._start_resume_monitor_if_needed()
            self._start_regulation_loop_if_needed()
            return

        upper = self._current_upper()
        lower = self._current_lower()
        if not self._charging_active:
            self._reset_timers()
            if net >= upper:
                await self._ensure_charging_enable_on()
                self._charging_active = True
                self._stop_resume_monitor()
                self._start_regulation_loop_if_needed()
            else:
                self._start_resume_monitor_if_needed()
                self._start_regulation_loop_if_needed()
            return

        if net < lower:
            if self._sustain_seconds() > 0 and self._below_lower_since is None:
                self._below_lower_since = time.monotonic()
                self._schedule_below_lower_timer()
        else:
            if self._below_lower_since is not None:
                self._below_lower_since = None
                self._cancel_below_lower_timer()

    # -------------------- Timers --------------------
    def _reset_timers(self):
        self._below_lower_since = None
        self._no_data_since = None
        self._cancel_below_lower_timer()
        self._cancel_no_data_timer()

    def _cancel_below_lower_timer(self):
        task = self._below_lower_task
        self._below_lower_task = None
        if task and not task.done():
            task.cancel()

    def _cancel_no_data_timer(self):
        task = self._no_data_task
        self._no_data_task = None
        if task and not task.done():
            task.cancel()

    def _sustain_seconds(self) -> int:
        eff = _effective_config(self.entry)
        try:
            val = int(eff.get(CONF_SUSTAIN_SECONDS, DEFAULT_SUSTAIN_SECONDS))
        except Exception:
            val = DEFAULT_SUSTAIN_SECONDS
        return max(0, min(SUSTAIN_MAX_SECONDS, val))

    def _schedule_below_lower_timer(self):
        self._cancel_below_lower_timer()
        if self._below_lower_since is None:
            return
        duration = self._sustain_seconds()
        if duration <= 0:
            return

        async def _runner():
            try:
                remaining = duration - (time.monotonic() - self._below_lower_since)
                if remaining > 0:
                    await asyncio.sleep(remaining)
                if (
                    self._below_lower_since is not None
                    and self._conditions_for_timers()
                    and self._is_still_below_lower()
                ):
                    await self._pause_due_below_lower(duration)
            except asyncio.CancelledError:
                return
            finally:
                self._below_lower_task = None

        self._below_lower_task = self.hass.async_create_task(_runner())

    def _schedule_no_data_timer(self):
        self._cancel_no_data_timer()
        if self._no_data_since is None:
            return
        duration = self._sustain_seconds()
        if duration <= 0:
            return

        async def _runner():
            try:
                remaining = duration - (time.monotonic() - self._no_data_since)
                if remaining > 0:
                    await asyncio.sleep(remaining)
                if (
                    self._no_data_since is not None
                    and self._conditions_for_timers()
                    and self._is_still_no_data()
                ):
                    await self._pause_due_no_data(duration)
            except asyncio.CancelledError:
                return
            finally:
                self._no_data_task = None

        self._no_data_task = self.hass.async_create_task(_runner())

    def _conditions_for_timers(self) -> bool:
        return (
            not self.get_mode(MODE_MANUAL_AUTO)
            and self.get_mode(MODE_START_STOP)
            and self._is_cable_connected()
            and self._is_charging_enabled()
            and self._planner_window_allows_start()
            and self._soc_allows_start()
        )

    def _is_still_below_lower(self) -> bool:
        net = self._get_net_power_w()
        return net is not None and net < self._current_lower()

    def _is_still_no_data(self) -> bool:
        if self._get_net_power_w() is None:
            return True
        if self._wallbox_status_entity and self._get_wallbox_status() is None:
            return True
        if self._charge_power_entity and self._get_charge_power_w() is None:
            return True
        return False

    async def _pause_due_below_lower(self, duration: int):
        _LOGGER.info("Pause: net < lower for >= %ds", duration)
        self._below_lower_since = None
        self._cancel_below_lower_timer()
        self._charging_active = False
        await self._ensure_charging_enable_off()
        self._stop_regulation_loop()
        self._start_resume_monitor_if_needed()

    async def _pause_due_no_data(self, duration: int):
        _LOGGER.info("Pause: missing data for >= %ds", duration)
        self._no_data_since = None
        self._cancel_no_data_timer()
        self._charging_active = False
        await self._ensure_charging_enable_off()
        self._stop_regulation_loop()
        self._start_resume_monitor_if_needed()

    # -------------------- Missing component helpers --------------------
    def _current_missing_components(self) -> List[str]:
        items: List[str] = []
        if self._get_net_power_w() is None:
            items.append("net")
        if self._wallbox_status_entity and self._get_wallbox_status() is None:
            items.append("status")
        if self._charge_power_entity and self._get_charge_power_w() is None:
            items.append("charge_power")
        return items

    def _essential_data_available(self) -> bool:
        return not self._current_missing_components()

    # -------------------- Regulation loop --------------------
    def _start_regulation_loop_if_needed(self):
        if self._regulation_task and not self._regulation_task.done():
            return
        if not self._should_regulate():
            return
        self._regulation_task = self.hass.async_create_task(self._regulation_loop())

    def _stop_regulation_loop(self):
        task = self._regulation_task
        self._regulation_task = None
        if task and not task.done():
            task.cancel()

    def _should_regulate(self) -> bool:
        return (
            not self.get_mode(MODE_MANUAL_AUTO)
            and self.get_mode(MODE_START_STOP)
            and self._is_cable_connected()
            and self._is_charging_enabled()
            and self._planner_window_allows_start()
            and self._soc_allows_start()
            and self._priority_allowed_cache
        )

    async def _regulation_loop(self):
        first_adjust_ready_at: Optional[float] = None
        try:
            while True:
                if not self._should_regulate():
                    if self._charging_active and (
                        not self._planner_window_allows_start() or not self._soc_allows_start()
                    ):
                        parts: List[str] = []
                        if not self._planner_window_allows_start():
                            parts.append("planner")
                        if not self._soc_allows_start():
                            parts.append("soc")
                        _LOGGER.info(
                            "RegLoop gating (%s) → pause to 6A.", "/".join(parts)
                        )
                        self._charging_active = False
                        await self._ensure_charging_enable_off()
                        if self._current_setting_entity:
                            with contextlib.suppress(Exception):
                                await self._set_current_setting_a(MIN_CURRENT_A)
                        # Advance
                        try:
                            if self._priority_mode_enabled:
                                cur = await async_get_priority(self.hass)
                                if cur == self.entry.entry_id:
                                    await async_advance_priority_to_next(self.hass, self.entry.entry_id)
                        except Exception:
                            _LOGGER.debug("Advance on regloop gating failed", exc_info=True)
                    break

                if first_adjust_ready_at is None:
                    first_adjust_ready_at = time.monotonic() + self._scan_interval

                self._evaluate_missing_and_start_no_data_timer()

                net = self._get_net_power_w()
                charge_power = self._get_charge_power_w()
                status = self._get_wallbox_status()
                current_a_dbg = await self._get_current_setting_a()
                missing = self._current_missing_components()
                soc = self._get_ev_soc_percent()
                conf_max_a = self._max_current_a()

                reg_min = self._effective_regulation_min_power()
                _LOGGER.debug(
                    "RegTick: net=%s target=%s currentA=%s status=%s enable=%s charge_power=%s soc=%s limit=%s active=%s missing=%s maxA=%s regMin=%s profile=%s",
                    net,
                    self._net_power_target_w,
                    current_a_dbg,
                    status,
                    self._is_charging_enabled(),
                    charge_power,
                    soc,
                    self._soc_limit_percent,
                    self._charging_active,
                    ",".join(missing) if missing else "-",
                    conf_max_a,
                    reg_min,
                    self._supply_profile_key,
                )

                if net is not None:
                    lower = self._current_lower()
                    if net < lower:
                        if self._sustain_seconds() > 0:
                            if self._below_lower_since is None:
                                self._below_lower_since = time.monotonic()
                                self._schedule_below_lower_timer()
                        else:
                            if self._below_lower_since is not None:
                                self._below_lower_since = None
                                self._cancel_below_lower_timer()
                    else:
                        if self._below_lower_since is not None:
                            self._below_lower_since = None
                            self._cancel_below_lower_timer()

                thr = SUPPLY_PROFILE_REG_THRESHOLDS.get(self._supply_profile_key)
                if not thr:
                    if self._wallbox_three_phase:
                        inc_export = 700
                        dec_import = 200
                    else:
                        inc_export = 250
                        dec_import = 0
                else:
                    inc_export = thr["export_inc_w"]
                    dec_import = thr["import_dec_w"]

                if (
                    net is not None
                    and status == WALLBOX_STATUS_CHARGING
                    and self._current_setting_entity
                    and not missing
                    and self._soc_allows_start()
                ):
                    now = time.monotonic()
                    if charge_power is not None:
                        if charge_power >= reg_min and now >= (first_adjust_ready_at or 0):
                            # Deviation = net - target
                            deviation = net - self._net_power_target_w
                            export_w = deviation if deviation > 0 else 0.0
                            import_w = -deviation if deviation < 0 else 0.0
                            current_a = await self._get_current_setting_a()
                            if current_a is not None:
                                new_a = current_a
                                if export_w >= inc_export and current_a < conf_max_a:
                                    new_a = min(conf_max_a, current_a + 1)
                                elif import_w >= dec_import and current_a > MIN_CURRENT_A:
                                    new_a = max(MIN_CURRENT_A, current_a - 1)
                                if new_a != current_a:
                                    _LOGGER.debug(
                                        "Adjust current: dev=%s export=%s import=%s inc_thr=%s dec_thr=%s %s→%sA",
                                        deviation,
                                        export_w,
                                        import_w,
                                        inc_export,
                                        dec_import,
                                        current_a,
                                        new_a,
                                    )
                                    await self._set_current_setting_a(new_a)

                await asyncio.sleep(self._scan_interval)

        except asyncio.CancelledError:
            return
        except Exception as exc:
            _LOGGER.warning("Regulation loop error: %s", exc)

    # -------------------- Resume monitor --------------------
    def _start_resume_monitor_if_needed(self):
        if self._resume_task and not self._resume_task.done():
            return
        if not self._should_resume_monitor():
            return
        self._resume_task = self.hass.async_create_task(self._resume_monitor_loop())

    def _stop_resume_monitor(self):
        task = self._resume_task
        self._resume_task = None
        if task and not task.done():
            task.cancel()

    def _should_resume_monitor(self) -> bool:
        return (
            not self.get_mode(MODE_MANUAL_AUTO)
            and self.get_mode(MODE_START_STOP)
            and self._is_cable_connected()
            and not self._is_charging_enabled()
            and self._priority_allowed_cache
        )

    async def _resume_monitor_loop(self):
        try:
            while self._should_resume_monitor():
                if (not self._planner_window_allows_start()) or (not self._soc_allows_start()):
                    await asyncio.sleep(self._scan_interval)
                    continue
                if not self._essential_data_available():
                    await asyncio.sleep(self._scan_interval)
                    continue
                net = self._get_net_power_w()
                if net is not None:
                    upper = self._current_upper()
                    if net >= upper and self.get_mode(MODE_START_STOP):
                        await self._ensure_charging_enable_on()
                        self._charging_active = True
                        self._stop_resume_monitor()
                        self._start_regulation_loop_if_needed()
                        return
                await asyncio.sleep(self._scan_interval)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            _LOGGER.warning("Resume loop error: %s", exc)

    # -------------------- Sensor getters / ensure helpers --------------------
    def _get_wallbox_status(self) -> Optional[str]:
        if not self._wallbox_status_entity:
            return None
        st = self.hass.states.get(self._wallbox_status_entity)
        if not self._is_known_state(st):
            self._report_unknown(self._wallbox_status_entity, getattr(st, "state", None), "status_get")
            return None
        return st.state

    async def _get_current_setting_a(self) -> Optional[int]:
        if not self._current_setting_entity:
            return None
        st = self.hass.states.get(self._current_setting_entity)
        if not self._is_known_state(st):
            self._report_unknown(self._current_setting_entity, getattr(st, "state", None), "current_get")
            return None
        try:
            return int(round(float(st.state)))
        except Exception:
            return None

    async def _set_current_setting_a(self, amps: int) -> None:
        if not self._current_setting_entity:
            return
        conf_max = self._max_current_a()
        amps = max(MIN_CURRENT_A, min(conf_max, int(amps)))
        with contextlib.suppress(Exception):
            dom, _ = self._current_setting_entity.split(".", 1)
            if dom == "number":
                await self.hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": self._current_setting_entity, "value": amps},
                    blocking=True,
                )

    def _is_cable_connected(self) -> bool:
        if not self._cable_entity:
            return False
        st = self.hass.states.get(self._cable_entity)
        if not self._is_known_state(st):
            self._report_unknown(self._cable_entity, getattr(st, "state", None), "cable_get")
            return False
        return st.state == STATE_ON

    def _is_charging_enabled(self) -> bool:
        if not self._charging_enable_entity:
            return False
        st = self.hass.states.get(self._charging_enable_entity)
        if not self._is_known_state(st):
            self._report_unknown(
                self._charging_enable_entity, getattr(st, "state", None), "charging_enable_get"
            )
            return False
        return st.state == STATE_ON

    def _get_sensor_float(self, entity_id: Optional[str]) -> Optional[float]:
        if not entity_id:
            return None
        st = self.hass.states.get(entity_id)
        if not self._is_known_state(st):
            self._report_unknown(entity_id, getattr(st, "state", None), "sensor_float_get")
            return None
        try:
            return float(st.state)
        except Exception:
            return None

    def _get_net_power_w(self) -> Optional[float]:
        if self._grid_single:
            return self._get_sensor_float(self._grid_power_entity)
        exp = self._get_sensor_float(self._grid_export_entity)
        imp = self._get_sensor_float(self._grid_import_entity)
        if exp is None or imp is None:
            return None
        if exp < 0:
            exp = 0.0
        if imp < 0:
            imp = 0.0
        return exp - imp

    def _get_charge_power_w(self) -> Optional[float]:
        return self._get_sensor_float(self._charge_power_entity)

    async def _ensure_charging_enable_off(self):
        if not self._charging_enable_entity:
            return
        with contextlib.suppress(Exception):
            dom, _ = self._charging_enable_entity.split(".", 1)
            if dom != "switch":
                return
            st = self.hass.states.get(self._charging_enable_entity)
            if self._is_known_state(st) and st.state == STATE_OFF:
                return
            if not self._is_known_state(st):
                self._report_unknown(
                    self._charging_enable_entity, getattr(st, "state", None), "enable_ensure_off"
                )
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": self._charging_enable_entity}, blocking=True
            )

    async def _ensure_charging_enable_on(self):
        if not self._charging_enable_entity or not self.get_mode(MODE_START_STOP):
            return
        with contextlib.suppress(Exception):
            dom, _ = self._charging_enable_entity.split(".", 1)
            if dom != "switch":
                return
            st = self.hass.states.get(self._charging_enable_entity)
            if self._is_known_state(st) and st.state == STATE_ON:
                return
            if not self._is_known_state(st):
                self._report_unknown(
                    self._charging_enable_entity, getattr(st, "state", None), "enable_ensure_on"
                )
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": self._charging_enable_entity}, blocking=True
            )

    async def _enforce_start_stop_policy(self):
        if not self.get_mode(MODE_START_STOP):
            self._cancel_auto_connect_task()
            self._stop_regulation_loop()
            self._stop_resume_monitor()
            self._stop_planner_monitor()
            self._charging_active = False
            self._reset_timers()
            await self._ensure_charging_enable_off()

    # -------------------- Mode management --------------------
    def get_mode(self, mode: str) -> bool:
        return bool(self._modes.get(mode, False))

    def set_mode(self, mode: str, enabled: bool):
        previous = self._modes.get(mode)
        self._modes[mode] = bool(enabled)
        try:
            if mode == MODE_START_STOP:
                if previous != enabled:
                    self.hass.async_create_task(self._save_unified_state())
                    _LOGGER.debug("Start/Stop toggle updated → %s", enabled)
                    # Baseline to 6A on any Start/Stop toggle
                    if self._current_setting_entity:
                        self.hass.async_create_task(self._set_current_setting_a(MIN_CURRENT_A))
                if not enabled and previous:
                    # Enforce policy and advance to next if current
                    self.hass.async_create_task(self._enforce_start_stop_policy())
                    if self._priority_mode_enabled:
                        self.hass.async_create_task(async_advance_priority_to_next(self.hass, self.entry.entry_id))
                if enabled and previous is False:
                    # Preempt/align naar first eligible (kan onszelf of een andere zijn)
                    if self._priority_mode_enabled:
                        self.hass.async_create_task(async_align_current_with_order(self.hass))
                    if self.get_mode(MODE_MANUAL_AUTO):
                        if (
                            self._is_cable_connected()
                            and self._essential_data_available()
                            and self._planner_window_allows_start()
                            and self._soc_allows_start()
                            and self._priority_allowed_cache
                        ):
                            self.hass.async_create_task(self._ensure_charging_enable_on())
                            self._charging_active = True
                        else:
                            self.hass.async_create_task(self._ensure_charging_enable_off())
                            if not self._essential_data_available():
                                _LOGGER.debug(
                                    "Manual start blocked: missing %s",
                                    ",".join(self._current_missing_components()),
                                )
                        self._stop_regulation_loop()
                        self._stop_resume_monitor()
                    self.hass.async_create_task(self._hysteresis_apply())
                    self._start_regulation_loop_if_needed()
                return

            if mode == MODE_ECO:
                if previous != enabled and not self.get_mode(MODE_MANUAL_AUTO):
                    self.hass.async_create_task(
                        self._hysteresis_apply(preserve_current=True)
                    )
                if previous != enabled:
                    self.hass.async_create_task(self._save_unified_state())
                    _LOGGER.debug("ECO toggle updated → %s", enabled)
                return

            if mode == MODE_MANUAL_AUTO:
                if previous != enabled:
                    self.hass.async_create_task(self._save_unified_state())
                    _LOGGER.debug("Manual toggle updated → %s", enabled)
                    # Baseline to 6A on any Manual toggle
                    if self._current_setting_entity:
                        self.hass.async_create_task(self._set_current_setting_a(MIN_CURRENT_A))
                if enabled:
                    self._reset_timers()
                    if (
                        self._is_cable_connected()
                        and self.get_mode(MODE_START_STOP)
                        and self._essential_data_available()
                        and self._planner_window_allows_start()
                        and self._soc_allows_start()
                        and self._priority_allowed_cache
                    ):
                        self.hass.async_create_task(self._ensure_charging_enable_on())
                        self._charging_active = True
                    else:
                        self.hass.async_create_task(self._ensure_charging_enable_off())
                        if not self._essential_data_available():
                            _LOGGER.debug(
                                "Manual start blocked: missing %s",
                                ",".join(self._current_missing_components()),
                            )
                    self._stop_regulation_loop()
                    self._stop_resume_monitor()
                else:
                    self.hass.async_create_task(self._hysteresis_apply())
                return

            if mode == MODE_CHARGE_PLANNER:
                if previous != enabled:
                    self.hass.async_create_task(self._save_unified_state())
                    _LOGGER.debug("Planner toggle updated → %s", enabled)
                if enabled:
                    self._start_planner_monitor_if_needed()
                else:
                    self._stop_planner_monitor()
                self.hass.async_create_task(self._hysteresis_apply())
                return

            if mode == MODE_STARTSTOP_RESET:
                if previous != enabled:
                    self.hass.async_create_task(self._save_unified_state())
                    _LOGGER.debug("Start/Stop Reset toggle updated → %s", enabled)
                return
        finally:
            self._notify_mode_listeners()

    # -------------------- Public helper --------------------
    def get_min_charge_power_w(self) -> int:
        return self._effective_min_charge_power()
