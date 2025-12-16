from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import datetime
from typing import Optional, Callable, Dict, List, Tuple

from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.const import STATE_ON, STATE_OFF, EVENT_HOMEASSISTANT_STARTED
from homeassistant.util import dt as dt_util
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    MODE_ECO,
    MODE_START_STOP,
    MODE_MANUAL_AUTO,
    MODE_CHARGE_PLANNER,
    MODE_STARTSTOP_RESET,
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
    SUSTAIN_MIN_SECONDS,
    SUSTAIN_MAX_SECONDS,
    CONF_CHARGE_POWER,
    CONF_EV_BATTERY_LEVEL,
    CONF_OPT_MODE_ECO,
    CONF_PLANNER_START_ISO,
    CONF_PLANNER_STOP_ISO,
    CONF_SOC_LIMIT_PERCENT,
    CONF_MAX_CURRENT_LIMIT_A,
    CONF_SUPPLY_PROFILE,
    SUPPLY_PROFILES,
    SUPPLY_PROFILE_REG_THRESHOLDS,
    CONF_NET_POWER_TARGET_W,
    DEFAULT_NET_POWER_TARGET_W,
    PLANNER_DATETIME_UPDATED_EVENT,
    DEFAULT_SOC_LIMIT_PERCENT,
)

from .priority import (
    async_get_priority,
    async_get_preferred_priority,
    async_set_priority,
    async_advance_priority_to_next,
    async_get_priority_mode_enabled,
    async_get_order,
    async_align_current_with_order,
    async_mark_priority_pause,
    async_clear_priority_pause,
    async_handover_after_pause,
)

_LOGGER = logging.getLogger(__name__)

STATE_STORAGE_VERSION = 1
STATE_STORAGE_KEY_PREFIX = "evcm_state"

CONNECT_DEBOUNCE_SECONDS = 1
EXPORT_SUSTAIN_SECONDS = 5
PLANNER_MONITOR_INTERVAL = 1.0

MIN_CURRENT_A = 6

UNKNOWN_DEBOUNCE_SECONDS = 30.0
REPORT_UNKNOWN_GETTERS = False
REPORT_UNKNOWN_INITIAL = False
REPORT_UNKNOWN_ENFORCE = False
REPORT_UNKNOWN_TRANSITION_NEW = False
REPORT_UNKNOWN_TRANSITION_OLD = False
UNKNOWN_STARTUP_GRACE_SECONDS = 90.0

RELOCK_AFTER_CHARGING_SECONDS = 30

OPT_UPPER_DEBOUNCE_SECONDS = "upper_debounce_seconds"
DEFAULT_UPPER_DEBOUNCE_SECONDS = 3
UPPER_DEBOUNCE_MIN_SECONDS = 0
UPPER_DEBOUNCE_MAX_SECONDS = 60


def _effective_config(entry: ConfigEntry) -> dict:
    return {**entry.data, **entry.options}


class EVLoadController:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry
        self._unsub_listeners: List[Callable[[], None]] = []
        self._state_store: Store = Store(hass, STATE_STORAGE_VERSION, f"{STATE_STORAGE_KEY_PREFIX}_{entry.entry_id}")
        self._state_loaded: bool = False
        self._state: Dict[str, Optional[object]] = {}

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
        # Entities
        self._cable_entity: Optional[str] = eff.get(CONF_CABLE_CONNECTED)
        self._charging_enable_entity: Optional[str] = eff.get(CONF_CHARGING_ENABLE)
        self._current_setting_entity: Optional[str] = eff.get(CONF_CURRENT_SETTING)
        self._lock_entity: Optional[str] = eff.get(CONF_LOCK_SENSOR)
        self._wallbox_status_entity: Optional[str] = eff.get(CONF_WALLBOX_STATUS)
        self._charge_power_entity: Optional[str] = eff.get(CONF_CHARGE_POWER)
        self._ev_soc_entity: Optional[str] = eff.get(CONF_EV_BATTERY_LEVEL) or None

        # Grid
        self._grid_single: bool = bool(eff.get(CONF_GRID_SINGLE, False))
        self._grid_power_entity: Optional[str] = eff.get(CONF_GRID_POWER)
        self._grid_export_entity: Optional[str] = eff.get(CONF_GRID_EXPORT)
        self._grid_import_entity: Optional[str] = eff.get(CONF_GRID_IMPORT)

        # Supply profile
        profile_key = eff.get(CONF_SUPPLY_PROFILE)
        if profile_key == "na_1ph_240":
            _LOGGER.info("Supply profile 'na_1ph_240' migrated to 'eu_1ph_230'.")
            profile_key = "eu_1ph_230"
        profile_meta = SUPPLY_PROFILES.get(profile_key) if isinstance(profile_key, str) else None
        if not profile_meta:
            legacy_three = bool(eff.get(CONF_WALLBOX_THREE_PHASE, DEFAULT_WALLBOX_THREE_PHASE))
            profile_meta = SUPPLY_PROFILES["eu_3ph_400"] if legacy_three else SUPPLY_PROFILES["eu_1ph_230"]
        self._supply_profile_key: str = profile_key or ("eu_3ph_400" if profile_meta["phases"] == 3 else "eu_1ph_230")
        self._supply_phases: int = int(profile_meta.get("phases", 1))
        self._supply_phase_voltage_v: int = int(profile_meta.get("phase_voltage_v", 235 if self._supply_phases == 1 else 230))
        self._profile_min_power_6a_w: int = int(
            profile_meta.get("min_power_6a_w", profile_meta["phase_voltage_v"] * 6 * (self._supply_phases if self._supply_phases > 1 else 1))
        )
        self._profile_reg_min_w: int = int(profile_meta.get("regulation_min_w", 1300 if self._supply_phases == 1 else 4000))
        self._wallbox_three_phase: bool = bool(self._supply_phases == 3)

        # Hysteresis thresholds
        self._eco_on_upper: float = float(eff.get(CONF_ECO_ON_UPPER, DEFAULT_ECO_ON_UPPER))
        self._eco_on_lower: float = float(eff.get(CONF_ECO_ON_LOWER, DEFAULT_ECO_ON_LOWER))
        self._eco_off_upper: float = float(eff.get(CONF_ECO_OFF_UPPER, DEFAULT_ECO_OFF_UPPER))
        self._eco_off_lower: float = float(eff.get(CONF_ECO_OFF_LOWER, DEFAULT_ECO_OFF_LOWER))

        # Scan & sustain & planner
        self._scan_interval: int = int(eff.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        self._planner_start_dt = self._parse_dt_option(eff.get(CONF_PLANNER_START_ISO))
        self._planner_stop_dt = self._parse_dt_option(eff.get(CONF_PLANNER_STOP_ISO))
        self._soc_limit_percent = self._parse_soc_option(eff.get(CONF_SOC_LIMIT_PERCENT))
        self._net_power_target_w: int = int(eff.get(CONF_NET_POWER_TARGET_W, DEFAULT_NET_POWER_TARGET_W))

        # Runtime flags / tasks
        self._last_cable_connected: Optional[bool] = None
        self._auto_connect_task: Optional[asyncio.Task] = None
        self._regulation_task: Optional[asyncio.Task] = None
        self._resume_task: Optional[asyncio.Task] = None
        self._planner_monitor_task: Optional[asyncio.Task] = None
        self._reclaim_task: Optional[asyncio.Task] = None
        self._relock_task: Optional[asyncio.Task] = None

        self._charging_active: bool = False

        # Timers (state markers)
        self._below_lower_since: Optional[float] = None
        self._below_lower_task: Optional[asyncio.Task] = None
        self._no_data_since: Optional[float] = None
        self._no_data_task: Optional[asyncio.Task] = None

        # Priority
        self._priority_allowed_cache: bool = True
        self._priority_mode_enabled: bool = False

        # Unknown handling
        self._unknown_last_emit: Dict[Tuple[str, str], float] = {}
        self._init_monotonic: float = time.monotonic()

        # Trackers
        self._last_soc_allows: Optional[bool] = None
        self._last_missing_nonempty: Optional[bool] = None
        self._pending_initial_start: bool = False

        # Debounce above upper
        self._above_upper_since_ts: Optional[float] = None
        self._above_upper_ref: Optional[float] = None
        self._upper_timer_task: Optional[asyncio.Task] = None

        # Auto-unlock toggle
        self._auto_unlock_enabled: bool = True

        # Time-change unsubscribe handle
        self._midnight_unsub: Optional[Callable[[], None]] = None
        # Startup listener unsub handle
        self._started_unsub: Optional[Callable[[], None]] = None

    # ---------------- Upper debounce helpers ----------------
    def _upper_debounce_seconds(self) -> int:
        eff = _effective_config(self.entry)
        try:
            v = int(eff.get(OPT_UPPER_DEBOUNCE_SECONDS, DEFAULT_UPPER_DEBOUNCE_SECONDS))
        except Exception:
            v = DEFAULT_UPPER_DEBOUNCE_SECONDS
        return max(UPPER_DEBOUNCE_MIN_SECONDS, min(UPPER_DEBOUNCE_MAX_SECONDS, v))

    def _cancel_upper_timer(self):
        t = self._upper_timer_task
        self._upper_timer_task = None
        if t and not t.done():
            t.cancel()

    def _reset_above_upper(self):
        self._above_upper_since_ts = None
        self._above_upper_ref = None
        self._cancel_upper_timer()

    def _sustained_above_upper(self, net: Optional[float]) -> bool:
        if net is None:
            self._reset_above_upper()
            return False
        upper = self._current_upper()
        debounce = self._upper_debounce_seconds()
        now = time.monotonic()
        if net >= upper:
            if self._above_upper_ref != upper or self._above_upper_since_ts is None:
                self._above_upper_ref = upper
                self._above_upper_since_ts = now
                return debounce == 0
            return (now - (self._above_upper_since_ts or now)) >= debounce
        self._reset_above_upper()
        return False

    def _schedule_upper_timer(self, remaining_s: float):
        self._cancel_upper_timer()

        async def _runner():
            try:
                await asyncio.sleep(max(0.0, float(remaining_s)))
                if (
                    not self.get_mode(MODE_MANUAL_AUTO)
                    and self.get_mode(MODE_START_STOP)
                    and self._is_cable_connected()
                    and not self._is_charging_enabled()
                    and self._priority_allowed_cache
                    and self._planner_window_allows_start()
                    and self._soc_allows_start()
                    and self._essential_data_available()
                ):
                    net = self._get_net_power_w()
                    if net is not None and net >= self._current_upper():
                        if self._priority_mode_enabled and not await self._have_priority_now():
                            return
                        await self._start_charging_and_reclaim()
                        self._start_regulation_loop_if_needed()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                _LOGGER.debug("Upper debounce timer error: %s", exc)
            finally:
                self._upper_timer_task = None

        self._upper_timer_task = self.hass.async_create_task(_runner())

    # ---------------- Post-start lock enforce (non-blocking wrapper) ----------------
    async def async_post_start(self):
        # Return immediately; run logic in background
        self.hass.async_create_task(self._async_post_start_inner())

    async def _async_post_start_inner(self):
        if not self._lock_entity:
            self._install_midnight_daily_listener()
            return
        try:
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                if self._cable_entity:
                    st_cable = self.hass.states.get(self._cable_entity)
                    if self._is_known_state(st_cable):
                        await self._ensure_lock_locked()
                        _LOGGER.debug("Post-start: lock enforced (cable=%s).", "on" if st_cable.state == STATE_ON else "off")
                        self._install_midnight_daily_listener()
                        return
                await asyncio.sleep(1.0)
            await self._ensure_lock_locked()
            _LOGGER.debug("Post-start: lock enforced (timeout fallback).")
        except asyncio.CancelledError:
            return
        except Exception:
            _LOGGER.debug("Post-start lock enforce failed", exc_info=True)
        finally:
            self._install_midnight_daily_listener()

    # ---------------- Midnight planner date rollover ----------------
    def _install_midnight_daily_listener(self):
        if self._midnight_unsub:
            with contextlib.suppress(Exception):
                self._midnight_unsub()
            self._midnight_unsub = None

        self._midnight_unsub = async_track_time_change(
            self.hass,
            self._midnight_time_change_callback,
            hour=0,
            minute=0,
            second=0,
        )
        _LOGGER.info("Midnight daily listener installed (local 00:00:00)")

    async def _midnight_time_change_callback(self, now: datetime):
        try:
            if self.get_mode(MODE_CHARGE_PLANNER):
                _LOGGER.debug("Midnight rollover: planner mode ON → no change.")
                return
            changed = self._roll_planner_dates_to_today_if_past()
            if changed:
                await self._save_unified_state()
                with contextlib.suppress(Exception):
                    self.hass.bus.async_fire(
                        PLANNER_DATETIME_UPDATED_EVENT,
                        {"entry_id": self.entry.entry_id}
                    )
                _LOGGER.info("Midnight rollover: planner datetimes rolled to today (past dates).")
            else:
                _LOGGER.debug("Midnight rollover: no change (dates already current or future).")
        except Exception:
            _LOGGER.debug("Midnight rollover (time change) failed", exc_info=True)

    def _roll_planner_dates_to_today_if_past(self) -> bool:
        today = dt_util.now().date()
        changed = False

        def _roll_if_past(orig_dt: Optional[datetime]) -> Optional[datetime]:
            if not orig_dt:
                return None
            if orig_dt.date() < today:
                return orig_dt.replace(year=today.year, month=today.month, day=today.day)
            return None

        new_start = _roll_if_past(self._planner_start_dt)
        if new_start:
            self._planner_start_dt = new_start
            changed = True

        new_stop = _roll_if_past(self._planner_stop_dt)
        if new_stop:
            self._planner_stop_dt = new_stop
            changed = True

        return changed

    def _persist_planner_dates_notify_threadsafe(self):
        async def _persist_and_notify():
            await self._save_unified_state()
            with contextlib.suppress(Exception):
                self.hass.bus.async_fire(
                    PLANNER_DATETIME_UPDATED_EVENT,
                    {"entry_id": self.entry.entry_id}
                )

        try:
            loop = self.hass.loop
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None

            if running_loop is loop:
                self.hass.async_create_task(_persist_and_notify())
            else:
                loop.call_soon_threadsafe(lambda: self.hass.async_create_task(_persist_and_notify()))
        except Exception:
            _LOGGER.debug("Failed to persist planner dates in a thread-safe manner", exc_info=True)

    # ---------------- Unknown helpers ----------------
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
            return self._context_category(context) == "transition" and side == "new" and REPORT_UNKNOWN_TRANSITION_NEW
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

    def _report_unknown(self, entity_id: Optional[str], raw_state: Optional[str], context: str, side: Optional[str] = None):
        if not entity_id or not self._should_report_unknown(context, side):
            return
        st = self.hass.states.get(entity_id)
        if st is not None:
            if st.attributes.get("restored"):
                return
            if raw_state in ("unavailable", "unknown") and (time.monotonic() - self._init_monotonic) < UNKNOWN_STARTUP_GRACE_SECONDS:
                return
        now = time.monotonic()
        key = (entity_id, f"{context}:{side}" if side else context)
        last = self._unknown_last_emit.get(key)
        if last and (now - last) < UNKNOWN_DEBOUNCE_SECONDS:
            return
        self._unknown_last_emit[key] = now
        _LOGGER.warning(
            "Unknown/unavailable: entity=%s state=%s context=%s%s entry=%s",
            entity_id, raw_state, context, f":{side}" if side else "", self.entry.entry_id
        )

    # ---------------- Persistence ----------------
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
            soc_init = self._safe_int(soc_opt)
            if soc_init is None:
                soc_init = DEFAULT_SOC_LIMIT_PERCENT
            target_opt = eff.get(CONF_NET_POWER_TARGET_W, DEFAULT_NET_POWER_TARGET_W)
            self._state = {
                "version": STATE_STORAGE_VERSION,
                "eco_enabled": True if eco_opt is None else bool(eco_opt),
                "planner_enabled": False,
                "planner_start_iso": planner_start_iso if isinstance(planner_start_iso, str) else None,
                "planner_stop_iso": planner_stop_iso if isinstance(planner_stop_iso, str) else None,
                "soc_limit_percent": soc_init,
                "startstop_reset_enabled": True,
                "start_stop_enabled": True,
                "manual_enabled": False,
                "net_power_target_w": int(target_opt) if isinstance(target_opt, (int, float)) else DEFAULT_NET_POWER_TARGET_W,
                "auto_unlock_enabled": True,
            }
            await self._state_store.async_save(self._state)
        else:
            self._state = data

        self._modes[MODE_ECO] = bool(self._state.get("eco_enabled", True))
        self._modes[MODE_CHARGE_PLANNER] = bool(self._state.get("planner_enabled", False))
        self._modes[MODE_STARTSTOP_RESET] = bool(self._state.get("startstop_reset_enabled", True))
        self._modes[MODE_START_STOP] = bool(self._state.get("start_stop_enabled", True))
        self._modes[MODE_MANUAL_AUTO] = bool(self._state.get("manual_enabled", False))

        self._planner_start_dt = self._parse_dt_option(self._state.get("planner_start_iso"))
        self._planner_stop_dt = self._parse_dt_option(self._state.get("planner_stop_iso"))
        soc = self._safe_int(self._state.get("soc_limit_percent"))
        self._soc_limit_percent = soc if soc is not None and 0 <= soc <= 100 else None

        try:
            self._net_power_target_w = int(self._state.get("net_power_target_w", DEFAULT_NET_POWER_TARGET_W))
        except Exception:
            self._net_power_target_w = DEFAULT_NET_POWER_TARGET_W

        try:
            self._auto_unlock_enabled = bool(self._state.get("auto_unlock_enabled", True))
        except Exception:
            self._auto_unlock_enabled = True

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
            "auto_unlock_enabled": bool(self._auto_unlock_enabled),
        }
        _LOGGER.debug(
            "Persist planner datetimes: start=%s stop=%s (planner_enabled=%s)",
            to_save["planner_start_iso"], to_save["planner_stop_iso"], to_save["planner_enabled"]
        )
        with contextlib.suppress(Exception):
            await self._state_store.async_save(to_save)

    @staticmethod
    def _safe_int(v) -> Optional[int]:
        try:
            if v in (None, ""):
                return None
            return int(round(float(v)))
        except Exception:
            return None

    # ---------------- Priority helpers ----------------
    async def _refresh_priority_mode_flag(self):
        self._priority_mode_enabled = await async_get_priority_mode_enabled(self.hass)

    async def _is_priority_allowed(self) -> bool:
        if not self._priority_mode_enabled:
            return True
        pid = await async_get_priority(self.hass)
        return pid is None or pid == self.entry.entry_id

    async def _have_priority_now(self) -> bool:
        await self._refresh_priority_mode_flag()
        if not self._priority_mode_enabled:
            return True
        with contextlib.suppress(Exception):
            await async_align_current_with_order(self.hass)
        try:
            pid = await async_get_priority(self.hass)
        except Exception:
            _LOGGER.debug("Priority check failed", exc_info=True)
            return False
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

    # ---------------- Parsing helpers ----------------
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

    def is_cable_connected(self) -> bool:
        return self._is_cable_connected()

    def _max_current_a(self) -> int:
        eff = _effective_config(self.entry)
        try:
            v = int(eff.get(CONF_MAX_CURRENT_LIMIT_A, 16))
        except Exception:
            v = 16
        return max(MIN_CURRENT_A, min(32, v))

    # ---------------- Auto unlock flag ----------------
    def get_auto_unlock_enabled(self) -> bool:
        return bool(self._auto_unlock_enabled)

    def set_auto_unlock_enabled(self, enabled: bool) -> None:
        prev = self._auto_unlock_enabled
        self._auto_unlock_enabled = bool(enabled)
        if prev != self._auto_unlock_enabled:
            _LOGGER.debug("Auto unlock toggle → %s", self._auto_unlock_enabled)
            self.hass.async_create_task(self._save_unified_state())
            self._notify_mode_listeners()

    # ---------------- Planner persist helpers ----------------
    async def async_set_planner_start_dt_persist(self, dt: Optional[datetime]):
        if dt:
            dt = dt_util.as_local(dt)
        self._planner_start_dt = dt
        await self._save_unified_state()
        if self._planner_enabled():
            await self._hysteresis_apply()
        with contextlib.suppress(Exception):
            self.hass.bus.async_fire(PLANNER_DATETIME_UPDATED_EVENT, {"entry_id": self.entry.entry_id})

    async def async_set_planner_stop_dt_persist(self, dt: Optional[datetime]):
        if dt:
            dt = dt_util.as_local(dt)
        self._planner_stop_dt = dt
        await self._save_unified_state()
        if self._planner_enabled():
            await self._hysteresis_apply()
        with contextlib.suppress(Exception):
            self.hass.bus.async_fire(PLANNER_DATETIME_UPDATED_EVENT, {"entry_id": self.entry.entry_id})

    def set_planner_start_dt(self, dt: Optional[datetime]):
        if dt:
            dt = dt_util.as_local(dt)
        self._planner_start_dt = dt
        self._persist_planner_dates_notify_threadsafe()

    def set_planner_stop_dt(self, dt: Optional[datetime]):
        if dt:
            dt = dt_util.as_local(dt)
        self._planner_stop_dt = dt
        self._persist_planner_dates_notify_threadsafe()

    # ---------------- Lock helpers ----------------
    def _is_lock_unlocked(self) -> bool:
        if not self._lock_entity:
            return True
        st = self.hass.states.get(self._lock_entity)
        if not self._is_known_state(st):
            self._report_unknown(self._lock_entity, getattr(st, "state", None), "lock_get")
            return False
        return str(st.state).strip().lower() == "unlocked"

    async def _ensure_lock_locked(self):
        if not self._lock_entity:
            return
        st = self.hass.states.get(self._lock_entity)
        try:
            if self._is_known_state(st) and str(st.state).strip().lower() == "locked":
                return
            dom, _ = self._lock_entity.split(".", 1)
            if dom != "lock":
                return
            await self.hass.services.async_call("lock", "lock", {"entity_id": self._lock_entity}, blocking=True)
            _LOGGER.info("Lock enforced → locked")
        except Exception:
            _LOGGER.debug("Failed to lock entity %s", self._lock_entity, exc_info=True)

    async def _ensure_unlocked_for_start(self, timeout_s: float = 5.0) -> bool:
        if not self._lock_entity:
            return True
        if self._is_lock_unlocked():
            return True
        if not self._is_cable_connected():
            return False
        try:
            dom, _ = self._lock_entity.split(".", 1)
            if dom != "lock":
                return False
            _LOGGER.debug("Attempting lock.unlock for %s", self._lock_entity)
            await self.hass.services.async_call("lock", "unlock", {"entity_id": self._lock_entity}, blocking=True)
        except Exception:
            _LOGGER.debug("Failed to call lock.unlock for %s", self._lock_entity, exc_info=True)
            return False
        deadline = time.monotonic() + max(0.5, float(timeout_s))
        while time.monotonic() < deadline:
            if self._is_lock_unlocked():
                return True
            await asyncio.sleep(0.2)
        _LOGGER.info("Unlock timeout: lock stayed locked after %.1fs", timeout_s)
        return False

    def _cancel_relock_task(self):
        t = self._relock_task
        self._relock_task = None
        if t and not t.done():
            t.cancel()

    def _is_status_charging(self) -> bool:
        st = self._get_wallbox_status()
        if not st:
            return False
        s = str(st).strip().lower()
        exp = str(WALLBOX_STATUS_CHARGING).strip().lower() if WALLBOX_STATUS_CHARGING is not None else "charging"
        return s == "charging" or s == exp

    def _charging_detected_now(self) -> bool:
        status_ok = self._is_status_charging()
        power = self._get_charge_power_w()
        return bool(status_ok or (power is not None and power > 100))

    async def _wait_for_charging_detection(self, timeout_s: float = 5.0) -> bool:
        deadline = time.monotonic() + max(0.5, float(timeout_s))
        while time.monotonic() < deadline:
            if not self._is_cable_connected():
                return False
            if self._charging_detected_now():
                return True
            await asyncio.sleep(0.2)
        return False

    def _schedule_relock_after_charging_start(self, already_detected: bool = False):
        self._cancel_relock_task()

        async def _runner():
            try:
                if not already_detected:
                    deadline = time.monotonic() + 120.0
                    while time.monotonic() < deadline:
                        if not self._is_cable_connected():
                            _LOGGER.debug("Relock monitor aborted: cable disconnected")
                            return
                        status = self._get_wallbox_status()
                        power = self._get_charge_power_w()
                        if self._is_status_charging() or (power is not None and power > 100):
                            _LOGGER.debug(
                                "Relock monitor: charging detected via %s (status=%s, power=%s)",
                                "status" if self._is_status_charging() else "power", status, power
                            )
                            break
                        await asyncio.sleep(1)
                    else:
                        _LOGGER.debug("Relock monitor timeout: no charging within 120s")
                        return
                await asyncio.sleep(RELOCK_AFTER_CHARGING_SECONDS)
                await self._ensure_lock_locked()
                _LOGGER.info("Auto re-lock %ss after charging start executed", RELOCK_AFTER_CHARGING_SECONDS)
            except asyncio.CancelledError:
                return
            except Exception:
                _LOGGER.debug("Re-lock monitor error", exc_info=True)
            finally:
                self._relock_task = None

        self._relock_task = self.hass.async_create_task(_runner())

    # ---------------- Net power target ----------------
    @property
    def net_power_target_w(self) -> int:
        return int(self._net_power_target_w)

    def set_net_power_target_w(self, value: Optional[float | int]):
        try:
            iv = int(round(float(value if value is not None else DEFAULT_NET_POWER_TARGET_W)))
        except Exception:
            iv = DEFAULT_NET_POWER_TARGET_W
        iv = max(-50000, min(50000, iv))
        if iv != self._net_power_target_w:
            self._net_power_target_w = iv
            self.hass.async_create_task(self._save_unified_state())
            _LOGGER.info("Net power target updated → %s W", iv)

    # ---------------- Planner / SoC getters-setters ----------------
    @property
    def planner_start_dt(self) -> Optional[datetime]:
        return self._planner_start_dt

    @property
    def planner_stop_dt(self) -> Optional[datetime]:
        return self._planner_stop_dt

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
        self.hass.async_create_task(self._hysteresis_apply())

    # ---------------- Mode listeners ----------------
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

    # ---------------- Planner gating ----------------
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

    # ---------------- SoC gating ----------------
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

    def _soc_allows_start(self) -> bool:
        if self._ev_soc_entity is None or self._soc_limit_percent is None:
            return True
        soc = self._get_ev_soc_percent()
        if soc is None:
            return True
        return soc < self._soc_limit_percent

    # ---------------- Supply minima ----------------
    def _effective_regulation_min_power(self) -> int:
        return self._profile_reg_min_w or (4000 if self._supply_phases == 3 else 1300)

    def _effective_min_charge_power(self) -> int:
        base = self._profile_min_power_6a_w
        return max(base, MIN_CHARGE_POWER_THREE_PHASE_W if self._supply_phases == 3 else MIN_CHARGE_POWER_SINGLE_PHASE_W)

    # ---------------- Initialization / Shutdown ----------------
    async def async_initialize(self):
        await self._load_unified_state()

        # Backfill default SoC limit for older entries that had no value
        if self._soc_limit_percent is None:
            self._soc_limit_percent = DEFAULT_SOC_LIMIT_PERCENT
            self.hass.async_create_task(self._save_unified_state())

        # Sync Start/Stop with Reset on initialize
        try:
            desired = self.get_mode(MODE_STARTSTOP_RESET)
            if self.get_mode(MODE_START_STOP) != desired:
                self.set_mode(MODE_START_STOP, desired)
        except Exception:
            _LOGGER.debug("Failed to sync Start/Stop with Reset on initialize", exc_info=True)

        await self._refresh_priority_mode_flag()
        self._priority_allowed_cache = await self._is_priority_allowed()
        self._init_monotonic = time.monotonic()
        with contextlib.suppress(Exception):
            self._last_soc_allows = self._soc_allows_start()
            self._last_missing_nonempty = bool(self._current_missing_components())
        self._subscribe_listeners()

        # Defer any service calls and monitors until HA has started
        if self.hass.is_running:
            # During reload after startup
            await self._on_ha_started(None)
        else:
            self._started_unsub = self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, self._on_ha_started
            )

    async def _on_ha_started(self, _event):
        # Install midnight listener and start monitors after HA is running
        self._install_midnight_daily_listener()
        # Schedule potentially blocking routines
        self.hass.async_create_task(self._enforce_start_stop_policy())
        self.hass.async_create_task(self._apply_cable_state_initial())
        self._start_planner_monitor_if_needed()
        if self._priority_allowed_cache:
            self._start_regulation_loop_if_needed()
            self._start_resume_monitor_if_needed()
        self._evaluate_missing_and_start_no_data_timer()

    async def async_shutdown(self):
        self._cancel_auto_connect_task()
        self._stop_regulation_loop()
        for t in [self._resume_task, self._planner_monitor_task, self._below_lower_task, self._no_data_task, self._reclaim_task, self._relock_task, self._upper_timer_task]:
            if t and not t.done():
                t.cancel()
        self._resume_task = self._planner_monitor_task = self._below_lower_task = self._no_data_task = self._reclaim_task = self._relock_task = self._upper_timer_task = None
        for unsub in list(self._unsub_listeners):
            with contextlib.suppress(Exception):
                unsub()
        self._unsub_listeners = []
        if self._midnight_unsub:
            with contextlib.suppress(Exception):
                self._midnight_unsub()
            self._midnight_unsub = None
        if self._started_unsub:
            with contextlib.suppress(Exception):
                self._started_unsub()
            self._started_unsub = None

    # ---------------- Subscriptions ----------------
    def _subscribe_listeners(self):
        for unsub in list(self._unsub_listeners):
            with contextlib.suppress(Exception):
                unsub()
        self._unsub_listeners = []
        if self._cable_entity:
            self._unsub_listeners.append(async_track_state_change_event(self.hass, self._cable_entity, self._async_cable_event))
        if self._charging_enable_entity:
            self._unsub_listeners.append(async_track_state_change_event(self.hass, self._charging_enable_entity, self._async_charging_enable_event))
        if self._lock_entity:
            self._unsub_listeners.append(async_track_state_change_event(self.hass, self._lock_entity, self._async_lock_event))
        if self._wallbox_status_entity:
            self._unsub_listeners.append(async_track_state_change_event(self.hass, self._wallbox_status_entity, self._async_wallbox_status_event))
        if self._charge_power_entity:
            self._unsub_listeners.append(async_track_state_change_event(self.hass, self._charge_power_entity, self._async_charge_power_event))
        if self._grid_single and self._grid_power_entity:
            self._unsub_listeners.append(async_track_state_change_event(self.hass, self._grid_power_entity, self._async_net_power_event))
        else:
            if self._grid_export_entity:
                self._unsub_listeners.append(async_track_state_change_event(self.hass, self._grid_export_entity, self._async_net_power_event))
            if self._grid_import_entity:
                self._unsub_listeners.append(async_track_state_change_event(self.hass, self._grid_import_entity, self._async_net_power_event))
        if self._ev_soc_entity:
            self._unsub_listeners.append(async_track_state_change_event(self.hass, self._ev_soc_entity, self._async_ev_soc_event))

    # ---------------- Core helper routines ----------------
    async def _start_charging_and_reclaim(self):
        await self._ensure_charging_enable_on()
        self._charging_active = True if self._is_charging_enabled() else False
        with contextlib.suppress(Exception):
            await async_clear_priority_pause(self.hass, self.entry.entry_id, "below_lower", notify=False)
        self._stop_reclaim_monitor()
        self._cancel_upper_timer()
        if self._priority_mode_enabled:
            with contextlib.suppress(Exception):
                await async_align_current_with_order(self.hass)

    async def _pause_basic(self, set_current_to_min: bool):
        self._charging_active = False
        await self._ensure_charging_enable_off()
        self._cancel_relock_task()
        self._cancel_upper_timer()
        if set_current_to_min and self._current_setting_entity:
            with contextlib.suppress(Exception):
                await self._set_current_setting_a(MIN_CURRENT_A)
        self._stop_regulation_loop()
        self._start_resume_monitor_if_needed()

    async def _advance_if_current(self):
        if not self._priority_mode_enabled:
            return
        try:
            cur = await async_get_priority(self.hass)
            if cur == self.entry.entry_id:
                await async_advance_priority_to_next(self.hass, self.entry.entry_id)
        except Exception:
            _LOGGER.debug("Advance failed", exc_info=True)

    # ---------------- Missing data / timers eval ----------------
    def _evaluate_missing_and_start_no_data_timer(self):
        if self._planner_enabled() and (not self._planner_window_valid() or not self._is_within_planner_window()):
            if self._no_data_since is not None:
                _LOGGER.debug("No-data timer reset (planner inactive)")
            self._no_data_since = None
            self._cancel_no_data_timer()
            self._last_missing_nonempty = bool(self._current_missing_components())
            return

        missing = self._current_missing_components()
        prev_missing = self._last_missing_nonempty
        now_missing = bool(missing)

        if not self._conditions_for_timers():
            if self._no_data_since is not None:
                _LOGGER.debug("No-data timer reset (conditions invalid)")
            self._no_data_since = None
            self._cancel_no_data_timer()
            self._last_missing_nonempty = now_missing
            return

        if now_missing:
            if self._no_data_since is None and self._sustain_seconds() > 0:
                self._no_data_since = time.monotonic()
                _LOGGER.debug("No-data timer start (missing: %s)", ", ".join(missing))
                self._schedule_no_data_timer()
        else:
            if self._no_data_since is not None:
                _LOGGER.debug("No-data timer cancel (data OK)")
            self._no_data_since = None
            self._cancel_no_data_timer()
            if prev_missing and self._priority_mode_enabled:
                self.hass.async_create_task(async_clear_priority_pause(self.hass, self.entry.entry_id, "no_data", notify=False))
                self.hass.async_create_task(async_align_current_with_order(self.hass))

        self._last_missing_nonempty = now_missing

    # ---------------- Event callbacks ----------------
    @callback
    def _async_cable_event(self, event: Event):
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        self.hass.async_create_task(self._refresh_priority_mode_flag())
        if not (self._is_known_state(old) and self._is_known_state(new)):
            if self._is_unknownish_state(new):
                self._report_unknown(self._cable_entity, getattr(new, "state", None), "cable_transition", side="new")
            elif self._is_unknownish_state(old):
                if self._should_report_unknown("cable_transition", side="old"):
                    self._report_unknown(self._cable_entity, getattr(old, "state", None), "cable_transition", side="old")
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
                self._report_unknown(self._charging_enable_entity, getattr(new, "state", None), "charging_enable_transition", side="new")
            elif self._is_unknownish_state(old):
                if self._should_report_unknown("charging_enable_transition", side="old"):
                    self._report_unknown(self._charging_enable_entity, getattr(old, "state", None), "charging_enable_transition", side="old")
            return
        if not self.get_mode(MODE_START_STOP):
            self.hass.async_create_task(self._ensure_charging_enable_off())
            self.hass.async_create_task(self._enforce_start_stop_policy())
            return
        self.hass.async_create_task(self._hysteresis_apply())
        self._evaluate_missing_and_start_no_data_timer()
        if self._is_charging_enabled() and not self.get_mode(MODE_MANUAL_AUTO) and self._is_cable_connected():
            self._start_regulation_loop_if_needed()

    @callback
    def _async_net_power_event(self, event: Event):
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        ent = event.data.get("entity_id")
        self.hass.async_create_task(self._refresh_priority_mode_flag())
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
        self.hass.async_create_task(self._refresh_priority_mode_flag())
        if not (self._is_known_state(old) and self._is_known_state(new)):
            if self._is_unknownish_state(new):
                self._report_unknown(self._wallbox_status_entity, getattr(new, "state", None), "status_transition", side="new")
            elif self._is_unknownish_state(old):
                if self._should_report_unknown("status_transition", side="old"):
                    self._report_unknown(self._wallbox_status_entity, getattr(old, "state", None), "status_transition", side="old")
            return

        if self._is_cable_connected() and self._is_status_charging():
            if not self._relock_task:
                _LOGGER.debug("Status=CHARGING detected → scheduling relock watcher (direct)")
                self._schedule_relock_after_charging_start(already_detected=True)

        self._start_regulation_loop_if_needed()
        if self.get_mode(MODE_START_STOP):
            self.hass.async_create_task(self._hysteresis_apply())
        self._evaluate_missing_and_start_no_data_timer()

    @callback
    def _async_charge_power_event(self, event: Event):
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        self.hass.async_create_task(self._refresh_priority_mode_flag())
        if not (self._is_known_state(old) and self._is_known_state(new)):
            if self._is_unknownish_state(new):
                self._report_unknown(self._charge_power_entity, getattr(new, "state", None), "charge_power_transition", side="new")
            elif self._is_unknownish_state(old):
                if self._should_report_unknown("charge_power_transition", side="old"):
                    self._report_unknown(self._charge_power_entity, getattr(old, "state", None), "charge_power_transition", side="old")
            return

        try:
            pw = float(new.state)
        except Exception:
            pw = None
        if self._is_cable_connected() and (pw is not None and pw > 100):
            if not self._relock_task:
                _LOGGER.debug("Power>100W detected → scheduling relock watcher (direct)")
                self._schedule_relock_after_charging_start(already_detected=True)

        self._start_regulation_loop_if_needed()
        if self.get_mode(MODE_START_STOP):
            self.hass.async_create_task(self._hysteresis_apply())
        self._evaluate_missing_and_start_no_data_timer()

    @callback
    def _async_lock_event(self, event: Event):
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        if not (self._is_known_state(old) and self._is_known_state(new)):
            return
        if str(old.state).lower() == "locked" and str(new.state).lower() == "unlocked":
            if self.get_mode(MODE_START_STOP) and self._is_cable_connected():
                if self._essential_data_available() and self._planner_window_allows_start() and self._soc_allows_start():
                    async def _try_start_after_unlock():
                        if self._priority_mode_enabled:
                            await async_align_current_with_order(self.hass)
                            cur = await async_get_priority(self.hass)
                            if cur != self.entry.entry_id:
                                _LOGGER.debug("Unlock start skipped: not current priority after align")
                                return
                        await self._start_charging_and_reclaim()
                        self._start_regulation_loop_if_needed()
                    self.hass.async_create_task(_try_start_after_unlock())

    @callback
    def _async_ev_soc_event(self, event: Event):
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        if not (self._is_known_state(old) and self._is_known_state(new)):
            if self._is_unknownish_state(new):
                self._report_unknown(self._ev_soc_entity, getattr(new, "state", None), "soc_transition", side="new")
            elif self._is_unknownish_state(old):
                if self._should_report_unknown("soc_transition", side="old"):
                    self._report_unknown(self._ev_soc_entity, getattr(old, "state", None), "soc_transition", side="old")
            return
        allows = self._soc_allows_start()
        prev = self._last_soc_allows
        self._last_soc_allows = allows
        if allows and prev is False and self._priority_mode_enabled:
            self.hass.async_create_task(async_align_current_with_order(self.hass))
        self.hass.async_create_task(self._hysteresis_apply())
        self._evaluate_missing_and_start_no_data_timer()

    # ---------------- Cable handling ----------------
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
            if self._is_unknownish_state(st) and self._should_report_unknown("cable_initial", side="new"):
                self._report_unknown(self._cable_entity, getattr(st, "state", None), "cable_initial", side="new")
            return
        self._last_cable_connected = st.state == STATE_ON
        if self._last_cable_connected:
            self.hass.async_create_task(self._on_cable_connected())
        else:
            self.hass.async_create_task(self._on_cable_disconnected())

    async def _on_cable_connected(self):
        self._reset_timers()
        self._pending_initial_start = True
        await self._ensure_lock_locked()

        if self._current_setting_entity:
            with contextlib.suppress(Exception):
                dom, _ = self._current_setting_entity.split(".", 1)
                if dom == "number":
                    await self.hass.services.async_call(
                        "number", "set_value",
                        {"entity_id": self._current_setting_entity, "value": MIN_CURRENT_A},
                        blocking=True
                    )

        # Priority preemption chain
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

        if self._priority_mode_enabled:
            with contextlib.suppress(Exception):
                await async_align_current_with_order(self.hass)
                self._priority_allowed_cache = await self._is_priority_allowed()

        # Manual handling
        if self.get_mode(MODE_MANUAL_AUTO):
            if self.get_mode(MODE_START_STOP):
                if (self._priority_allowed_cache and self._essential_data_available()
                    and self._planner_window_allows_start() and self._soc_allows_start()):
                    if (not self._priority_mode_enabled) or (await self._have_priority_now()):
                        await self._start_charging_and_reclaim()
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
        self._pending_initial_start = False
        self._cancel_auto_connect_task()
        self._stop_regulation_loop()
        self._stop_resume_monitor()
        self._stop_reclaim_monitor()
        self._cancel_relock_task()
        self._charging_active = False
        self._reset_timers()
        await self._ensure_charging_enable_off()
        await self._ensure_lock_locked()
        if self._current_setting_entity:
            with contextlib.suppress(Exception):
                dom, _ = self._current_setting_entity.split(".", 1)
                if dom == "number":
                    await self.hass.services.async_call(
                        "number", "set_value",
                        {"entity_id": self._current_setting_entity, "value": MIN_CURRENT_A},
                        blocking=True
                    )

        try:
            desired = self.get_mode(MODE_STARTSTOP_RESET)
            if self.get_mode(MODE_START_STOP) != desired:
                self.set_mode(MODE_START_STOP, desired)
        except Exception:
            _LOGGER.debug("Failed to sync Start/Stop with Reset on disconnect", exc_info=True)

        await self._advance_if_current()
        self._evaluate_missing_and_start_no_data_timer()

    # ---------------- Reclaim monitor ----------------
    def _start_reclaim_monitor_if_needed(self):
        if self._reclaim_task and not self._reclaim_task.done():
            return
        self._reclaim_task = self.hass.async_create_task(self._reclaim_monitor_loop())

    def _stop_reclaim_monitor(self):
        task = self._reclaim_task
        self._reclaim_task = None
        if task and not task.done():
            task.cancel()

    async def _reclaim_monitor_loop(self):
        try:
            while True:
                if not self.get_mode(MODE_START_STOP) or not self._is_cable_connected():
                    break
                net = self._get_net_power_w()
                if net is None:
                    await asyncio.sleep(self._scan_interval)
                    continue

                if self._planner_window_allows_start() and self._soc_allows_start() and self._sustained_above_upper(net):
                    if self._priority_mode_enabled:
                        with contextlib.suppress(Exception):
                            await async_set_priority(self.hass, self.entry.entry_id)
                            await async_align_current_with_order(self.hass)
                    break

                await asyncio.sleep(self._scan_interval)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            _LOGGER.warning("Reclaim monitor error: %s", exc)
        finally:
            self._reclaim_task = None

    # ---------------- Auto-connect routine ----------------
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
            if (not self._is_cable_connected() or self.get_mode(MODE_MANUAL_AUTO) or not self.get_mode(MODE_START_STOP)):
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
                if self._priority_mode_enabled and not await self._have_priority_now():
                    return
                await self._start_charging_and_reclaim()
                self._start_regulation_loop_if_needed()
                return
            above_since: Optional[float] = None
            while True:
                if (not self._is_cable_connected() or self.get_mode(MODE_MANUAL_AUTO) or not self.get_mode(MODE_START_STOP)):
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
                        if self._priority_mode_enabled and not await self._have_priority_now():
                            await asyncio.sleep(1)
                            continue
                        await self._start_charging_and_reclaim()
                        self._start_regulation_loop_if_needed()
                        return
                else:
                    above_since = None
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            _LOGGER.warning("Auto-connect error: %s", exc)

    # ---------------- Planner monitor ----------------
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
                    if not allows:
                        if self._charging_active:
                            _LOGGER.info("Planner monitor: window ended/invalid → pause.")
                            await self._pause_basic(set_current_to_min=True)
                            await self._advance_if_current()
                        else:
                            await self._advance_if_current()
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

    # ---------------- Hysteresis logic ----------------
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
            self._stop_reclaim_monitor()
            self._cancel_relock_task()
            self._reset_above_upper()
            return

        manual = self.get_mode(MODE_MANUAL_AUTO)

        if not self._is_cable_connected():
            self._reset_timers()
            self._charging_active = False
            self._stop_regulation_loop()
            self._stop_resume_monitor()
            self._stop_reclaim_monitor()
            await self._ensure_charging_enable_off()
            self._cancel_relock_task()
            self._reset_above_upper()
            if self._priority_mode_enabled:
                await self._advance_if_current()
            return

        planner_ok = self._planner_window_allows_start()
        soc_ok = self._soc_allows_start()
        priority_ok = self._priority_allowed_cache

        if manual:
            if not (planner_ok and soc_ok and priority_ok):
                reasons = []
                if not planner_ok:
                    reasons.append("planner")
                if not soc_ok:
                    reasons.append("soc")
                if not priority_ok:
                    reasons.append("priority")
                if self._charging_active:
                    _LOGGER.info("Manual pause: %s", "/".join(reasons))
                    await self._pause_basic(set_current_to_min=not preserve_current)
                    if self._priority_mode_enabled and (not planner_ok or not soc_ok):
                        await self._advance_if_current()
                else:
                    if self._priority_mode_enabled and (not planner_ok or not soc_ok):
                        await self._advance_if_current()
                return

            if not self._charging_active:
                if self._priority_mode_enabled and not await self._have_priority_now():
                    self._start_resume_monitor_if_needed()
                    return
                if self._essential_data_available():
                    await self._start_charging_and_reclaim()
                else:
                    await self._ensure_charging_enable_off()
            return

        if not planner_ok:
            if self._charging_active:
                _LOGGER.info("Planner window inactive → pause.")
                await self._pause_basic(set_current_to_min=not preserve_current)
                if self._priority_mode_enabled:
                    await self._advance_if_current()
            else:
                if self._priority_mode_enabled:
                    await self._advance_if_current()
            self._start_resume_monitor_if_needed()
            self._evaluate_missing_and_start_no_data_timer()
            self._reset_above_upper()
            return

        if not soc_ok:
            if self._charging_active:
                _LOGGER.info("SoC limit reached → pause.")
                await self._pause_basic(set_current_to_min=not preserve_current)
                if self._priority_mode_enabled:
                    await self._advance_if_current()
            else:
                if self._priority_mode_enabled:
                    await self._advance_if_current()
            self._start_resume_monitor_if_needed()
            self._evaluate_missing_and_start_no_data_timer()
            self._reset_above_upper()
            return

        if not priority_ok:
            if self._charging_active:
                await self._pause_basic(set_current_to_min=not preserve_current)
            self._start_resume_monitor_if_needed()
            self._evaluate_missing_and_start_no_data_timer()
            self._reset_above_upper()
            return

        net = self._get_net_power_w()
        if net is None or not self._essential_data_available():
            if not self._charging_active:
                await self._ensure_charging_enable_off()
                self._cancel_relock_task()
            self._start_resume_monitor_if_needed()
            self._start_regulation_loop_if_needed()
            self._reset_above_upper()
            return

        upper = self._current_upper()
        lower = self._current_lower()
        charge_power = self._get_charge_power_w()

        if self._is_status_charging() or (charge_power is not None and charge_power > 100):
            if not self._relock_task:
                _LOGGER.debug("Hysteresis: charging detected → relock watcher")
                self._schedule_relock_after_charging_start(already_detected=True)

        if not self._charging_active:
            self._reset_timers()
            if self._sustained_above_upper(net):
                if self._priority_mode_enabled and not await self._have_priority_now():
                    self._start_resume_monitor_if_needed()
                    return
                await self._start_charging_and_reclaim()
                self._stop_resume_monitor()
                self._start_regulation_loop_if_needed()
            else:
                if net is not None and net >= upper:
                    now = time.monotonic()
                    elapsed = 0.0 if self._above_upper_since_ts is None else (now - self._above_upper_since_ts)
                    remaining = max(0.0, self._upper_debounce_seconds() - elapsed)
                    if remaining > 0:
                        self._schedule_upper_timer(remaining)
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

    # ---------------- Timers base ----------------
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
        raw = eff.get(CONF_SUSTAIN_SECONDS)
        try:
            val = int(raw) if raw not in (None, "") else DEFAULT_SUSTAIN_SECONDS
        except Exception:
            val = DEFAULT_SUSTAIN_SECONDS
        return max(SUSTAIN_MIN_SECONDS, min(SUSTAIN_MAX_SECONDS, val))

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
                    and self._timer_base_conditions()
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
                    and self._timer_base_conditions()
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

    def _timer_base_conditions(self) -> bool:
        return (
            not self.get_mode(MODE_MANUAL_AUTO)
            and self.get_mode(MODE_START_STOP)
            and self._is_cable_connected()
            and self._planner_window_allows_start()
            and self._soc_allows_start()
            and (self._is_charging_enabled() or self._charging_active)
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
        _LOGGER.info("Pause: net < lower for ≥ %ds → retain priority (reclaim)", duration)
        self._below_lower_since = None
        self._cancel_below_lower_timer()
        self._charging_active = False
        await self._ensure_charging_enable_off()
        self._cancel_relock_task()
        self._cancel_upper_timer()
        self._stop_regulation_loop()
        self._start_resume_monitor_if_needed()
        self._reset_above_upper()
        try:
            if self._priority_mode_enabled:
                with contextlib.suppress(Exception):
                    await async_set_priority(self.hass, self.entry.entry_id)
                self._start_reclaim_monitor_if_needed()
        except Exception:
            _LOGGER.error("Below-lower reclaim setup failed", exc_info=True)

    async def _pause_due_no_data(self, duration: int):
        _LOGGER.info("Pause: missing data for ≥ %ds → handover", duration)
        self._no_data_since = None
        self._cancel_no_data_timer()
        self._charging_active = False
        await self._ensure_charging_enable_off()
        self._cancel_relock_task()
        self._cancel_upper_timer()
        self._stop_regulation_loop()
        self._start_resume_monitor_if_needed()
        self._reset_above_upper()
        try:
            if self._priority_mode_enabled:
                await async_mark_priority_pause(self.hass, self.entry.entry_id, "no_data", notify=False)
                self.hass.async_create_task(async_handover_after_pause(self.hass, self.entry.entry_id))
        except Exception:
            _LOGGER.error("No-data handover failed", exc_info=True)

    # ---------------- Missing components ----------------
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

    # ---------------- Regulation loop ----------------
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
                    if self._charging_active and (not self._planner_window_allows_start() or not self._soc_allows_start()):
                        parts = []
                        if not self._planner_window_allows_start():
                            parts.append("planner")
                        if not self._soc_allows_start():
                            parts.append("soc")
                        _LOGGER.info("RegLoop gating (%s) → pause.", "/".join(parts))
                        await self._pause_basic(set_current_to_min=True)
                        await self._advance_if_current()
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
                    net, self._net_power_target_w, current_a_dbg, status,
                    self._is_charging_enabled(), charge_power, soc, self._soc_limit_percent,
                    self._charging_active, ",".join(missing) if missing else "-", conf_max_a,
                    reg_min, self._supply_profile_key
                )

                if self._is_status_charging() or (charge_power is not None and charge_power > 100):
                    if not self._relock_task:
                        _LOGGER.debug("RegLoop: charging detected → relock watcher (direct)")
                        self._schedule_relock_after_charging_start(already_detected=True)

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

                thr = SUPPLY_PROFILE_REG_THRESHOLDS.get(self._supply_profile_key) or {}
                inc_export = thr.get("export_inc_w", 700 if self._wallbox_three_phase else 250)
                dec_import = thr.get("import_dec_w", 200 if self._wallbox_three_phase else 0)

                if (
                    net is not None
                    and status == WALLBOX_STATUS_CHARGING
                    and self._current_setting_entity
                    and not missing
                    and self._soc_allows_start()
                ):
                    now = time.monotonic()
                    if charge_power is not None and charge_power >= reg_min and now >= (first_adjust_ready_at or 0):
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
                                    deviation, export_w, import_w, inc_export, dec_import, current_a, new_a
                                )
                                await self._set_current_setting_a(new_a)

                await asyncio.sleep(self._scan_interval)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            _LOGGER.warning("Regulation loop error: %s", exc)

    # ---------------- Resume monitor ----------------
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
                    await asyncio.sleep(self._scan_interval); continue
                if not self._essential_data_available():
                    await asyncio.sleep(self._scan_interval); continue
                net = self._get_net_power_w()
                if net is not None:
                    if self._sustained_above_upper(net) and self.get_mode(MODE_START_STOP):
                        if self._priority_mode_enabled and not await self._have_priority_now():
                            await asyncio.sleep(self._scan_interval)
                            continue
                        await self._start_charging_and_reclaim()
                        self._stop_resume_monitor()
                        self._start_regulation_loop_if_needed()
                        return
                    if net >= self._current_upper() and not self._is_charging_enabled():
                        now = time.monotonic()
                        elapsed = 0.0 if self._above_upper_since_ts is None else (now - self._above_upper_since_ts)
                        remaining = max(0.0, self._upper_debounce_seconds() - elapsed)
                        if remaining > 0:
                            self._schedule_upper_timer(remaining)
                await asyncio.sleep(self._scan_interval)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            _LOGGER.warning("Resume loop error: %s", exc)

    # ---------------- Sensor getters / setters ----------------
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
                    "number", "set_value",
                    {"entity_id": self._current_setting_entity, "value": amps},
                    blocking=True
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
            self._report_unknown(self._charging_enable_entity, getattr(st, "state", None), "charging_enable_get")
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
                self._report_unknown(self._charging_enable_entity, getattr(st, "state", None), "enable_ensure_off")
            await self.hass.services.async_call("switch", "turn_off", {"entity_id": self._charging_enable_entity}, blocking=True)
        self._cancel_relock_task()

    async def _ensure_charging_enable_on(self):
        if not self._charging_enable_entity or not self.get_mode(MODE_START_STOP):
            return

        is_initial_start = self._pending_initial_start
        did_unlock = False

        with contextlib.suppress(Exception):
            dom, _ = self._charging_enable_entity.split(".", 1)
            if dom != "switch":
                return

            st = self.hass.states.get(self._charging_enable_entity)

            if self._lock_entity and not self._is_lock_unlocked() and self._is_cable_connected():
                if is_initial_start:
                    if not self._auto_unlock_enabled:
                        _LOGGER.debug("Initial start: Auto unlock is OFF → no unlock attempt")
                        return
                    if (self._essential_data_available() and self._planner_window_allows_start()
                            and self._soc_allows_start() and self._priority_allowed_cache):
                        ok = await self._ensure_unlocked_for_start(timeout_s=5.0)
                        if not ok:
                            _LOGGER.info("Initial start: unlock failed, aborting enable ON")
                            return
                        did_unlock = True
                        self._pending_initial_start = False
                    else:
                        return
                else:
                    if not (self._is_known_state(st) and st.state == STATE_ON):
                        await self.hass.services.async_call("switch", "turn_on", {"entity_id": self._charging_enable_entity}, blocking=True)
                    self._pending_initial_start = False

                    if await self._wait_for_charging_detection(timeout_s=5.0):
                        return
                    if not self._auto_unlock_enabled:
                        _LOGGER.debug("Resume: Auto unlock is OFF → no unlock fallback")
                        return
                    ok = await self._ensure_unlocked_for_start(timeout_s=5.0)
                    if not ok:
                        _LOGGER.info("Resume fallback unlock failed; start aborted")
                        return
                    did_unlock = True

            st = self.hass.states.get(self._charging_enable_entity)
            if not (self._is_known_state(st) and st.state == STATE_ON):
                await self.hass.services.async_call("switch", "turn_on", {"entity_id": self._charging_enable_entity}, blocking=True)
            self._pending_initial_start = False

            if did_unlock:
                self._schedule_relock_after_charging_start()

    async def _enforce_start_stop_policy(self):
        try:
            if not self.get_mode("start_stop"):
                await self._ensure_charging_enable_off()
                self._reset_timers()
                self._charging_active = False
                return
        except Exception:
            with contextlib.suppress(Exception):
                await self._ensure_charging_enable_off()
            self._reset_timers()
            self._charging_active = False
            return

        if not self.get_mode(MODE_START_STOP):
            self._cancel_auto_connect_task()
            self._stop_regulation_loop()
            self._stop_resume_monitor()
            self._stop_planner_monitor()
            self._stop_reclaim_monitor()
            self._cancel_relock_task()
            self._cancel_upper_timer()
            self._charging_active = False
            self._reset_timers()
            self._reset_above_upper()
            await self._ensure_charging_enable_off()

    # ---------------- Mode management ----------------
    def get_mode(self, mode: str) -> bool:
        return bool(self._modes.get(mode, False))

    def set_mode(self, mode: str, enabled: bool):
        previous = self._modes.get(mode)
        self._modes[mode] = bool(enabled)
        try:
            if mode == MODE_START_STOP:
                if previous != enabled:
                    self.hass.async_create_task(self._save_unified_state())
                    _LOGGER.debug("Start/Stop toggle → %s", enabled)
                    if self._current_setting_entity:
                        self.hass.async_create_task(self._set_current_setting_a(MIN_CURRENT_A))
                if not enabled and previous:
                    self.hass.async_create_task(self._ensure_charging_enable_off())
                    self.hass.async_create_task(self._enforce_start_stop_policy())
                    self.hass.async_create_task(self._advance_if_current())
                    return
                if enabled and previous is False:
                    async def _after_enable_startstop_on():
                        if self._priority_mode_enabled:
                            await async_align_current_with_order(self.hass)
                        await self._hysteresis_apply()
                        self._start_regulation_loop_if_needed()
                        self._start_resume_monitor_if_needed()
                    self.hass.async_create_task(_after_enable_startstop_on())
                    return

            if mode == MODE_ECO:
                if previous != enabled and not self.get_mode(MODE_MANUAL_AUTO):
                    self.hass.async_create_task(self._hysteresis_apply(preserve_current=True))
                if previous != enabled:
                    self.hass.async_create_task(self._save_unified_state())
                    _LOGGER.debug("ECO toggle → %s", enabled)
                return

            if mode == MODE_MANUAL_AUTO:
                if previous != enabled:
                    self.hass.async_create_task(self._save_unified_state())
                    _LOGGER.debug("Manual toggle → %s", enabled)
                    if self._current_setting_entity:
                        self.hass.async_create_task(self._set_current_setting_a(MIN_CURRENT_A))
                if enabled:
                    self._reset_timers()
                    self._stop_reclaim_monitor()
                    self._cancel_relock_task()
                    self._cancel_upper_timer()
                    self._reset_above_upper()
                    async def _enter_manual():
                        if (
                            self._is_cable_connected() and self.get_mode(MODE_START_STOP)
                            and self._essential_data_available() and self._planner_window_allows_start()
                            and self._soc_allows_start() and self._priority_allowed_cache
                        ):
                            if (not self._priority_mode_enabled) or (await self._have_priority_now()):
                                await self._start_charging_and_reclaim()
                        else:
                            await self._ensure_charging_enable_off()
                        self._stop_regulation_loop()
                        self._stop_resume_monitor()
                    self.hass.async_create_task(_enter_manual())
                else:
                    async def _after_manual_off():
                        await self._hysteresis_apply()
                        self._start_regulation_loop_if_needed()
                        self._start_resume_monitor_if_needed()
                    self.hass.async_create_task(_after_manual_off())
                return

            if mode == MODE_CHARGE_PLANNER:
                if previous != enabled:
                    self.hass.async_create_task(self._save_unified_state())
                    _LOGGER.debug("Planner toggle → %s", enabled)
                if enabled:
                    self._start_planner_monitor_if_needed()
                else:
                    self._stop_planner_monitor()
                    if self._priority_mode_enabled:
                        self.hass.async_create_task(async_align_current_with_order(self.hass))
                if self._roll_planner_dates_to_today_if_past():
                    self._persist_planner_dates_notify_threadsafe()
                self.hass.async_create_task(self._hysteresis_apply())
                return

            if mode == MODE_STARTSTOP_RESET:
                if previous != enabled:
                    self.hass.async_create_task(self._save_unified_state())
                    _LOGGER.debug("Start/Stop Reset toggle → %s", enabled)
                return
        finally:
            self._notify_mode_listeners()

    # ---------------- Public helpers ----------------
    def get_min_charge_power_w(self) -> int:
        return self._effective_min_charge_power()
