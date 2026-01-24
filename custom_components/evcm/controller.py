from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import datetime, timedelta
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
    SUPPLY_PROFILE_MIN_BAND,
    MIN_BAND_230,
    MIN_BAND_400,
    CONF_NET_POWER_TARGET_W,
    DEFAULT_NET_POWER_TARGET_W,
    PLANNER_DATETIME_UPDATED_EVENT,
    DEFAULT_SOC_LIMIT_PERCENT,
    EXT_IMPORT_LIMIT_MAX_W,
    OPT_EXTERNAL_OFF_LATCHED,
    OPT_EXTERNAL_LAST_OFF_TS,
    OPT_EXTERNAL_LAST_ON_TS,
    CONF_PHASE_SWITCH_SUPPORTED,
    CONF_PHASE_SWITCH_AUTO_ENABLED,
    CONF_PHASE_SWITCH_FORCED_PROFILE,
    PHASE_SWITCH_MODE_AUTO,
    PHASE_SWITCH_MODE_FORCE_1P,
    PHASE_SWITCH_MODE_FORCE_3P,
    CONF_PHASE_MODE_FEEDBACK_SENSOR,
    PHASE_PROFILE_PRIMARY,
    PHASE_PROFILE_ALTERNATE,
    PHASE_SWITCH_REQUEST_EVENT,
    PHASE_SWITCH_SOURCE_FORCE,
    PHASE_SWITCH_SOURCE_AUTO,
    PHASE_SWITCH_CE_VETO_SECONDS_DEFAULT,
    PHASE_SWITCH_WAIT_FOR_STOP_SECONDS_DEFAULT,
    PHASE_SWITCH_STOPPED_POWER_W_DEFAULT,
    PHASE_SWITCH_REQUEST_FEEDBACK_TIMEOUT_S,
    PHASE_SWITCH_COOLDOWN_SECONDS,
    OPT_PHASE_SWITCH_COOLDOWN_UNTIL_ISO,
    OPT_PHASE_SWITCH_COOLDOWN_TARGET,
    CONF_ECO_ON_UPPER_ALT,
    CONF_ECO_ON_LOWER_ALT,
    CONF_ECO_OFF_UPPER_ALT,
    CONF_ECO_OFF_LOWER_ALT,
    DEFAULT_ECO_ON_UPPER_ALT,
    DEFAULT_ECO_ON_LOWER_ALT,
    DEFAULT_ECO_OFF_UPPER_ALT,
    DEFAULT_ECO_OFF_LOWER_ALT,
    CONF_AUTO_PHASE_SWITCH_DELAY_MIN,
    AUTO_PHASE_SWITCH_DELAY_MIN_MIN,
    AUTO_PHASE_SWITCH_DELAY_MIN_MAX,
    DEFAULT_AUTO_PHASE_SWITCH_DELAY_MIN,
    CE_ENABLE_RETRY_INTERVAL_S,
    CE_ENABLE_MAX_RETRIES,
    CE_DISABLE_RETRY_INTERVAL_S,
    CE_DISABLE_MAX_RETRIES,
    CONNECT_DEBOUNCE_SECONDS,
    EXPORT_SUSTAIN_SECONDS,
    PLANNER_MONITOR_INTERVAL_S,
    RELOCK_AFTER_CHARGING_SECONDS,
    MIN_CURRENT_A,
    UNKNOWN_DEBOUNCE_SECONDS,
    UNKNOWN_STARTUP_GRACE_SECONDS,
    DEFAULT_UPPER_DEBOUNCE_SECONDS,
    UPPER_DEBOUNCE_MIN_SECONDS,
    UPPER_DEBOUNCE_MAX_SECONDS,
    CE_MIN_TOGGLE_INTERVAL_S,
    AUTO_RESET_DEBOUNCE_SECONDS,
    AUTO_1P_TO_3P_MARGIN_W,
    CHARGING_POWER_THRESHOLD_W,
    CHARGING_WAIT_TIMEOUT_S,
    CHARGING_DETECTION_TIMEOUT_S,
    STATE_STORAGE_VERSION,
    STATE_STORAGE_KEY_PREFIX,
    STATE_SAVE_DEBOUNCE_DELAY_S,
    POST_START_LOCK_DELAY_S,
    LATE_START_INITIAL_DELAY_S,
    MQTT_READY_TIMEOUT_S,
    MQTT_READY_POLL_INTERVAL_S,
    UNLOCK_TIMEOUT_S,
    LOCK_WAIT_POLL_INTERVAL_S,
    PRIORITY_REFRESH_POLL_INTERVAL_S,
    PRIORITY_REFRESH_RETRIES,
    OTHER_CHARGING_CHECK_RETRIES,
    OTHER_CHARGING_CHECK_INTERVAL_S,
    CE_VERIFY_DELAY_S,
    CONF_PHASE_SWITCH_CONTROL_MODE,
    PHASE_CONTROL_INTEGRATION,
    PHASE_CONTROL_WALLBOX,
    DEFAULT_PHASE_SWITCH_CONTROL_MODE,
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

REPORT_UNKNOWN_GETTERS = False
REPORT_UNKNOWN_INITIAL = False
REPORT_UNKNOWN_ENFORCE = False
REPORT_UNKNOWN_TRANSITION_NEW = False
REPORT_UNKNOWN_TRANSITION_OLD = False

OPT_UPPER_DEBOUNCE_SECONDS = "upper_debounce_seconds"

# Auto phase switching storage keys (internal)
AUTO_STOP_REASON_BELOW_LOWER = "below_lower"
AUTO_STATE_KEY_1P_TO_3P_SINCE = "auto_1p_to_3p_candidate_since_iso"
AUTO_STATE_KEY_3P_TO_1P_SINCE = "auto_3p_to_1p_candidate_since_iso"
AUTO_STATE_KEY_STOP_REASON = "auto_last_stop_reason"
AUTO_STATE_KEY_STOP_TS = "auto_last_stop_ts_iso"

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
        self._profile_reg_min_w: int = int(profile_meta.get("regulation_min_w", 1300 if self._supply_phases == 1 else 3900))
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

        # External import limit (Max peak avg)
        self._ext_import_limit_w: Optional[int] = None

        # Runtime flags / tasks
        self._last_cable_connected: Optional[bool] = None
        self._auto_connect_task: Optional[asyncio.Task] = None
        self._regulation_task: Optional[asyncio.Task] = None
        self._resume_task: Optional[asyncio.Task] = None
        self._planner_monitor_task: Optional[asyncio.Task] = None
        self._reclaim_task: Optional[asyncio.Task] = None
        self._relock_task: Optional[asyncio.Task] = None
        self._relock_enabled: bool = False

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

        # Phase switching mode (persisted in unified store)
        # Persist ALWAYS, but select entity is only created if CONF_PHASE_SWITCH_SUPPORTED is True.
        self._phase_switch_auto_enabled: bool = False
        self._phase_switch_forced_profile: str = PHASE_PROFILE_PRIMARY

        # Phase switching: feedback + request runtime state
        self._phase_feedback_entity: Optional[str] = eff.get(CONF_PHASE_MODE_FEEDBACK_SENSOR)
        self._phase_feedback_value: str = "unknown"  # "1p" / "3p" / "unknown"
        self._phase_status_value: str = "Unknown"    # "1p" / "3p" / "Switching to 1p/3p" / "Unknown"
        self._phase_target: Optional[str] = None
        self._phase_last_requested_target: Optional[str] = None
        self._phase_last_request_ts: Optional[float] = None
        self._phase_notify_active: bool = False

        # Phase switching: cooldown (persisted, no queue)
        self._phase_switch_lock: asyncio.Lock = asyncio.Lock()
        self._phase_switch_in_progress: bool = False

        # Phase switching control mode (from config)
        self._phase_switch_control_mode: str = eff.get(
            CONF_PHASE_SWITCH_CONTROL_MODE, 
            DEFAULT_PHASE_SWITCH_CONTROL_MODE
        )

        # Wallclock UTC datetime (persisted via unified Store)
        self._phase_cooldown_until_utc: Optional[datetime] = None
        self._phase_cooldown_active_target: Optional[str] = None  # "1p"/"3p" for UI revert/context

        # Phase switching: fallback
        self._phase_fallback_active: bool = False
        self._phase_fallback_timer_task: Optional[asyncio.Task] = None

        # Auto phase switching (v1: stopped-based)
        # persistent candidate timers (stored in unified Store as UTC ISO)
        self._auto_1p_to_3p_candidate_since_utc: Optional[datetime] = None
        self._auto_3p_to_1p_candidate_since_utc: Optional[datetime] = None

        # reset debounce helpers (monotonic; NOT persisted)
        self._auto_1p_to_3p_reset_since_ts: Optional[float] = None
        self._auto_3p_to_1p_reset_since_ts: Optional[float] = None

        # last stop reason latch (persisted)
        self._auto_last_stop_reason: Optional[str] = None
        self._auto_last_stop_ts_utc: Optional[datetime] = None

        # charging_enable hard veto window during safe switching
        self._ce_phase_veto_until_ts: float = 0.0

        # charging_enable single-writer (minimal)
        self._ce_lock: asyncio.Lock = asyncio.Lock()
        self._ce_last_desired: Optional[bool] = None
        self._ce_last_write_ts: float = 0.0

        # charging_enable retry (no-effect / sticky state handling)
        self._ce_enable_retry_task: Optional[asyncio.Task] = None
        self._ce_enable_retry_active: bool = False
        self._ce_enable_retry_count: int = 0

        # charging_enable retry OFF (ONLY for user Start/Stop OFF)
        self._ce_disable_retry_task: Optional[asyncio.Task] = None
        self._ce_disable_retry_active: bool = False
        self._ce_disable_retry_count: int = 0

        # External OFF detection and latch
        self._ce_last_intent_desired: Optional[bool] = None
        self._ce_last_intent_ts: float = 0.0
        self._ce_external_off_last_notify_ts: float = 0.0
        self._ce_external_off_latched: bool = False
        self._ce_on_blocked_logged = False
        self._ce_external_last_off_ts: Optional[float] = None
        self._ce_external_last_on_ts: Optional[float] = None

        # Task tracking for cleanup
        self._tracked_tasks: set[asyncio.Task] = set()

        # State save debouncing
        self._save_pending: bool = False
        self._save_debounce_task: Optional[asyncio.Task] = None
        self._save_debounce_delay: float = STATE_SAVE_DEBOUNCE_DELAY_S  # seconds

        # Restore external OFF/ON state from config entry options (survives reload + HA restart)
        with contextlib.suppress(Exception):
            self._ce_external_off_latched = bool(self.entry.options.get(OPT_EXTERNAL_OFF_LATCHED, False))
            self._ce_external_last_off_ts = self.entry.options.get(OPT_EXTERNAL_LAST_OFF_TS)
            self._ce_external_last_on_ts = self.entry.options.get(OPT_EXTERNAL_LAST_ON_TS)

        if self._ce_external_off_latched:
            if self._phase_switch_control_mode == PHASE_CONTROL_WALLBOX:
                _LOGGER.debug("EVCM %s: restored external OFF latch from previous run (wallbox-controlled mode)", self._log_name())
            else:
                _LOGGER.warning("EVCM %s: restored external OFF latch from previous run", self._log_name())

        # Recreate persistent notifications after restart/reload (HA may not restore them)
        try:
            device_name = self._device_name_for_notify()

            def _fmt_ts(ts: Optional[float]) -> str:
                if not ts:
                    return "unknown"
                # Show local time for user clarity
                return dt_util.as_local(dt_util.utc_from_timestamp(float(ts))).strftime("%Y-%m-%d %H:%M:%S")

            if self._ce_external_last_on_ts:
                # Suppress notification in wallbox-controlled phase switch mode
                if self._phase_switch_control_mode != PHASE_CONTROL_WALLBOX:
                    msg_on = (
                        f"External charging_enable ON detected for {device_name}\n"
                        f"Last external ON: {_fmt_ts(self._ce_external_last_on_ts)}\n"
                        "External OFF latch cleared: yes\n"
                        "Charging can resume."
                    )
                    self.hass.async_create_task(
                        self.hass.services.async_call(
                            "persistent_notification",
                            "create",
                            {
                                "title": "EVCM: External ON detected",
                                "message": msg_on,
                                "notification_id": f"evcm_external_on_{self.entry.entry_id}",
                            },
                            blocking=False,
                        )
                    )

            if self._ce_external_last_off_ts or self._ce_external_off_latched:
                # Suppress notification in wallbox-controlled phase switch mode
                if self._phase_switch_control_mode != PHASE_CONTROL_WALLBOX:
                    msg_off = (
                        f"External charging_enable OFF detected for {device_name}\n"
                        f"Last external OFF: {_fmt_ts(self._ce_external_last_off_ts)}\n"
                        f"Latched until cable disconnect: {'yes' if self._ce_external_off_latched else 'no'}\n"
                        "To reset, unplug the EV.\n"
                        "You can manually turn charging_enable ON but this is NOT ADVISED!\n"
                        "If you did not manually turn charging_enable OFF, check your wallbox before turning back ON."
                    )
                    self.hass.async_create_task(
                        self.hass.services.async_call(
                            "persistent_notification",
                            "create",
                            {
                                "title": "EVCM: External OFF detected",
                                "message": msg_off,
                                "notification_id": f"evcm_external_off_{self.entry.entry_id}",
                            },
                            blocking=False,
                        )
                    )
        except Exception:
            _LOGGER.debug("EVCM: failed to recreate external ON/OFF notifications on init", exc_info=True)

        # Time-change unsubscribe handle
        self._midnight_unsub: Optional[Callable[[], None]] = None

        # Startup listener unsub handle
        self._started_unsub: Optional[Callable[[], None]] = None

        # Track whether the started-listener is still active to avoid double removal on reload
        self._ha_started_listener_active: bool = False

        # Startup guards
        self._post_start_done: bool = False
        self._startup_ts: datetime = dt_util.utcnow()

        # Startup grace reconcile timer
        self._startup_grace_recheck_handle: Optional[asyncio.Handle] = None

    # ---------------- Startup grace helper ----------------
    def _is_startup_grace_active(self) -> bool:
        try:
            return (dt_util.utcnow() - self._startup_ts).total_seconds() < UNKNOWN_STARTUP_GRACE_SECONDS
        except Exception:
            return True

    def _schedule_startup_grace_recheck(self) -> None:
        # schedule exactly once
        if self._startup_grace_recheck_handle is not None:
            return

        def _cb():
            self._startup_grace_recheck_handle = None
            # run async reconcile in background
            self._create_task(self._after_startup_grace_reconcile())

        try:
            delay = float(UNKNOWN_STARTUP_GRACE_SECONDS) + 0.5
            self._startup_grace_recheck_handle = self.hass.loop.call_later(delay, _cb)
        except Exception:
            # fallback: run soon
            self._create_task(self._after_startup_grace_reconcile())

    async def _after_startup_grace_reconcile(self) -> None:
        """Run once after startup grace ends to avoid missing planner/export/SoC transitions."""
        try:
            # If grace is somehow still active, skip (another call will happen via enforce reschedule)
            if self._is_startup_grace_active():
                return

            _LOGGER.info("Startup grace ended -> reconciling state (planner/hysteresis/regulation)")

            # Apply current realities
            await self._enforce_start_stop_policy()
            await self._apply_cable_state_initial()
            await self._hysteresis_apply()

            # Ensure loops are started if needed
            if self._priority_allowed_cache:
                self._start_regulation_loop_if_needed()
                self._start_resume_monitor_if_needed()

            # Re-evaluate missing-data timers (they were disabled during grace)
            self._evaluate_missing_and_start_no_data_timer()

        except Exception:
            _LOGGER.debug("Startup grace reconcile failed", exc_info=True)

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

        self._upper_timer_task = self._create_task(_runner())

    # ---------------- Post-start lock enforce (non-blocking wrapper) ----------------
    async def async_post_start(self):
        """Run post-start routine once; avoid blocking HA startup."""
        if self._post_start_done:
            _LOGGER.debug("Post-start already executed; skipping for entry_id=%s", self.entry.entry_id)
            return
        self._post_start_done = True

        # Run inner in background (never block HA startup)
        try:
            self._create_task(self._async_post_start_inner())
        except Exception:
            _LOGGER.debug("Failed to schedule _async_post_start_inner", exc_info=True)

        # Defer lock enforcement to avoid immediate I/O on startup
        def _schedule_lock_enforce():
            try:
                self._create_task(self._ensure_lock_locked())
            except Exception:
                _LOGGER.debug("Failed to schedule _ensure_lock_locked", exc_info=True)

        try:
            self.hass.loop.call_later(POST_START_LOCK_DELAY_S, _schedule_lock_enforce)
        except Exception:
            _schedule_lock_enforce()

    async def _async_post_start_inner(self):
        if not self._lock_entity:
            self._install_midnight_daily_listener()
            return
        try:
            deadline = time.monotonic() + POST_START_LOCK_DELAY_S
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
        """Install exactly one midnight listener; avoid duplicates."""
        if self._midnight_unsub:
            _LOGGER.debug("Midnight daily listener already installed; skipping duplicate")
            return

        try:
            self._midnight_unsub = async_track_time_change(
                self.hass,
                self._midnight_time_change_callback,
                hour=0,
                minute=0,
                second=0,
            )
            _LOGGER.info("Midnight daily listener installed (local 00:00:00)")
        except Exception:
            _LOGGER.debug("Failed to install midnight listener", exc_info=True)

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
                self._create_task(_persist_and_notify())
            else:
                loop.call_soon_threadsafe(lambda: self._create_task(_persist_and_notify()))
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
            "EVCM %s: Unknown/unavailable: entity=%s state=%s context=%s%s",
            self._log_name(),
            entity_id, 
            raw_state, 
            context, 
            f":{side}" if side else ""
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
                "ext_import_limit_w": None,
                CONF_PHASE_SWITCH_AUTO_ENABLED: False,
                CONF_PHASE_SWITCH_FORCED_PROFILE: PHASE_PROFILE_PRIMARY,
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

        # External import limit
        try:
            ext = self._safe_int(self._state.get("ext_import_limit_w"))
            self._ext_import_limit_w = ext if (ext is not None and ext > 0) else None
        except Exception:
            self._ext_import_limit_w = None

        # Phase switching mode (stored)
        try:
            self._phase_switch_auto_enabled = bool(self._state.get(CONF_PHASE_SWITCH_AUTO_ENABLED, False))
        except Exception:
            self._phase_switch_auto_enabled = False

        forced = self._state.get(CONF_PHASE_SWITCH_FORCED_PROFILE, PHASE_PROFILE_PRIMARY)
        forced = str(forced) if forced is not None else PHASE_PROFILE_PRIMARY
        if forced not in (PHASE_PROFILE_PRIMARY, PHASE_PROFILE_ALTERNATE):
            forced = PHASE_PROFILE_PRIMARY
        self._phase_switch_forced_profile = forced

        # Phase switching cooldown (persisted)
        try:
            iso = self._state.get(OPT_PHASE_SWITCH_COOLDOWN_UNTIL_ISO)
            if isinstance(iso, str) and iso.strip():
                dt = dt_util.parse_datetime(iso)
                # parse_datetime returns aware or naive; normalize to UTC aware
                if dt is not None:
                    dt_utc = dt_util.as_utc(dt) if dt.tzinfo else dt_util.as_utc(dt.replace(tzinfo=dt_util.UTC))
                    self._phase_cooldown_until_utc = dt_utc
                else:
                    self._phase_cooldown_until_utc = None
            else:
                self._phase_cooldown_until_utc = None
        except Exception:
            self._phase_cooldown_until_utc = None

        try:
            tgt = self._state.get(OPT_PHASE_SWITCH_COOLDOWN_TARGET)
            tgt = str(tgt).strip().lower() if tgt is not None else ""
            self._phase_cooldown_active_target = tgt if tgt in ("1p", "3p") else None
        except Exception:
            self._phase_cooldown_active_target = None

        # Auto switching timers (persisted)
        try:
            iso = self._state.get(AUTO_STATE_KEY_1P_TO_3P_SINCE)
            if isinstance(iso, str) and iso.strip():
                dt = dt_util.parse_datetime(iso)
                self._auto_1p_to_3p_candidate_since_utc = dt_util.as_utc(dt) if dt else None
            else:
                self._auto_1p_to_3p_candidate_since_utc = None
        except Exception:
            self._auto_1p_to_3p_candidate_since_utc = None

        try:
            iso = self._state.get(AUTO_STATE_KEY_3P_TO_1P_SINCE)
            if isinstance(iso, str) and iso.strip():
                dt = dt_util.parse_datetime(iso)
                self._auto_3p_to_1p_candidate_since_utc = dt_util.as_utc(dt) if dt else None
            else:
                self._auto_3p_to_1p_candidate_since_utc = None
        except Exception:
            self._auto_3p_to_1p_candidate_since_utc = None

        try:
            rsn = self._state.get(AUTO_STATE_KEY_STOP_REASON)
            self._auto_last_stop_reason = str(rsn) if rsn is not None else None
        except Exception:
            self._auto_last_stop_reason = None

        try:
            iso = self._state.get(AUTO_STATE_KEY_STOP_TS)
            if isinstance(iso, str) and iso.strip():
                dt = dt_util.parse_datetime(iso)
                self._auto_last_stop_ts_utc = dt_util.as_utc(dt) if dt else None
            else:
                self._auto_last_stop_ts_utc = None
        except Exception:
            self._auto_last_stop_ts_utc = None

        # Phase last requested target (for auto mode mismatch detection)
        try:
            tgt = self._state.get("phase_last_requested_target")
            tgt = str(tgt).strip().lower() if tgt else None
            self._phase_last_requested_target = tgt if tgt in ("1p", "3p") else None
        except Exception:
            self._phase_last_requested_target = None

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
            "ext_import_limit_w": self._ext_import_limit_w if self._ext_import_limit_w is not None else None,
            "phase_last_requested_target": self._phase_last_requested_target,
            CONF_PHASE_SWITCH_AUTO_ENABLED: bool(self._phase_switch_auto_enabled),
            CONF_PHASE_SWITCH_FORCED_PROFILE: self._phase_switch_forced_profile,

            # Auto switching persistence
            AUTO_STATE_KEY_1P_TO_3P_SINCE: (
                self._auto_1p_to_3p_candidate_since_utc.isoformat()
                if self._auto_1p_to_3p_candidate_since_utc else None
            ),
            AUTO_STATE_KEY_3P_TO_1P_SINCE: (
                self._auto_3p_to_1p_candidate_since_utc.isoformat()
                if self._auto_3p_to_1p_candidate_since_utc else None
            ),
            AUTO_STATE_KEY_STOP_REASON: self._auto_last_stop_reason,
            AUTO_STATE_KEY_STOP_TS: (
                self._auto_last_stop_ts_utc.isoformat()
                if self._auto_last_stop_ts_utc else None
            ),
        }
        _LOGGER.debug(
            "Persist planner datetimes: start=%s stop=%s (planner_enabled=%s)",
            to_save["planner_start_iso"], to_save["planner_stop_iso"], to_save["planner_enabled"]
        )
        with contextlib.suppress(Exception):
            await self._state_store.async_save(to_save)

    async def _save_unified_state_debounced(self) -> None:
        """Save state with debouncing to avoid rapid consecutive writes."""
        self._save_pending = True
        
        # If a debounce task is already scheduled, let it handle the save
        if self._save_debounce_task and not self._save_debounce_task.done():
            return
        
        async def _debounced_save():
            try:
                await asyncio.sleep(self._save_debounce_delay)
                if self._save_pending:
                    self._save_pending = False
                    await self._save_unified_state()
            except asyncio.CancelledError:
                return
            except Exception:
                _LOGGER.debug("Debounced save failed", exc_info=True)
            finally:
                self._save_debounce_task = None
        
        self._save_debounce_task = self._create_task(_debounced_save())
        
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
        self._create_task(self._refresh_priority_and_apply())

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
            self._create_task(self._save_unified_state_debounced())
            self._notify_mode_listeners()

    # ---------------- Phase switching: helpers ----------------
    def _phase_switch_supported(self) -> bool:
        eff = _effective_config(self.entry)
        return bool(eff.get(CONF_PHASE_SWITCH_SUPPORTED, False))

    def _is_wallbox_controlled_phase_switch(self) -> bool:
        """Check if phase switching is controlled by the wallbox (not integration)."""
        if not self._phase_switch_supported():
            return False
        return self._phase_switch_control_mode == PHASE_CONTROL_WALLBOX

    def _expected_phase_for_mismatch_check(self) -> Optional[str]:
        """Return the expected phase for mismatch detection (integration-controlled only)."""
        if self._is_wallbox_controlled_phase_switch():
            return None
        
        if not self._phase_switch_supported():
            return None
        
        # During active request, use the request target
        if self._phase_target in ("1p", "3p"):
            return self._phase_target
        
        # Auto mode check
        if self._phase_switch_auto_enabled:
            if self._phase_last_requested_target in ("1p", "3p"):
                return self._phase_last_requested_target
            # No previous request in auto mode: expect primary profile (3p)
            return "3p"
        
        # Forced mode: expect feedback to match the forced profile
        return "1p" if self._phase_switch_forced_profile == PHASE_PROFILE_ALTERNATE else "3p"

    def get_phase_switch_mode(self) -> str:
        # Wallbox-controlled: return descriptive mode based on current feedback
        if self._is_wallbox_controlled_phase_switch():
            if self._phase_feedback_value == "1p":
                return PHASE_SWITCH_MODE_FORCE_1P
            elif self._phase_feedback_value == "3p":
                return PHASE_SWITCH_MODE_FORCE_3P
            return PHASE_SWITCH_MODE_AUTO  # or "Unknown" - feedback not yet known

        # Integration-controlled: existing logic
        if not self._phase_switch_supported():
            return "Force 3p"

        if self._phase_switch_auto_enabled:
            return "Auto"

        return "Force 1p" if self._phase_switch_forced_profile == PHASE_PROFILE_ALTERNATE else "Force 3p"

    def set_phase_switch_auto_enabled(self, enabled: bool) -> None:
        self._phase_switch_auto_enabled = bool(enabled)
        
        if enabled:
            # If there's an active switch request, adopt that target
            # Otherwise, accept current feedback as the starting point
            if self._phase_target in ("1p", "3p"):
                self._phase_last_requested_target = self._phase_target
            elif self._phase_feedback_value in ("1p", "3p"):
                self._phase_last_requested_target = self._phase_feedback_value
            else:
                self._phase_last_requested_target = None
        else:
            # Switching to forced mode, clear auto's last request
            self._phase_last_requested_target = None

        self._create_task(self._save_unified_state())
        self._reconcile_phase_feedback_notify()
        self._notify_mode_listeners()
        
        # Re-evaluate thresholds
        self._create_task(self._hysteresis_apply())

    async def async_force_phase_profile(self, *, alternate: bool) -> None:
        """Set the forced phase profile (user intent via UI)."""
        new_profile = PHASE_PROFILE_ALTERNATE if alternate else PHASE_PROFILE_PRIMARY
        self._phase_switch_forced_profile = new_profile
        
        # Set last_requested_target for mismatch tracking
        self._phase_last_requested_target = "1p" if alternate else "3p"
        
        self._create_task(self._save_unified_state_debounced())
        self._reconcile_phase_feedback_notify()
        self._notify_mode_listeners()
        
        # Re-evaluate thresholds with new expectation
        self._create_task(self._hysteresis_apply())

    def _phase_cooldown_active(self) -> bool:
        until = self._phase_cooldown_until_utc
        return bool(until and dt_util.utcnow() < until)

    def _phase_cooldown_remaining_s(self) -> int:
        until = self._phase_cooldown_until_utc
        if not until:
            return 0
        return max(0, int((until - dt_util.utcnow()).total_seconds()))

    def _phase_expected_from_config(self) -> Optional[str]:
        """Expected phase purely from stored forced mode (no active request)."""
        if not self._phase_switch_supported():
            return None

        if self._phase_switch_auto_enabled:
            return None

        return "1p" if self._phase_switch_forced_profile == PHASE_PROFILE_ALTERNATE else "3p"

    async def _persist_phase_cooldown_state(self) -> None:
        """Persist cooldown wallclock timestamps in unified store."""
        try:
            # Ensure state loaded so self._state exists
            await self._load_unified_state()

            to_save = dict(self._state) if isinstance(self._state, dict) else {}
            to_save[OPT_PHASE_SWITCH_COOLDOWN_UNTIL_ISO] = (
                self._phase_cooldown_until_utc.isoformat() if self._phase_cooldown_until_utc else None
            )
            to_save[OPT_PHASE_SWITCH_COOLDOWN_TARGET] = self._phase_cooldown_active_target or None

            await self._state_store.async_save(to_save)
            self._state = to_save
        except Exception:
            _LOGGER.debug("Failed to persist phase cooldown state", exc_info=True)

    def _notify_phase_switch_cooldown_active(self) -> None:
        """User-facing notification when a request is rejected due to cooldown."""
        try:
            device_name = self._device_name_for_notify()
            timeout_s = int(float(PHASE_SWITCH_COOLDOWN_SECONDS))
            if timeout_s % 60 == 0:
                dur = f"{timeout_s // 60} minute(s)"
            else:
                dur = f"{timeout_s} seconds"
            msg = (
                f"Phase switching cooldown active for {device_name}\n\n"
                f"For safety, phase switching is locked for up to {dur} "
                "after a request.\n"
                "Please try again after the cooldown.\n"
                "This message will disappear when the cooldown ends."
            )

            # Create notification
            self._notify_persistent_fire_and_forget(
                "EVCM: Phase switching cooldown active",
                msg,
                self._phase_cooldown_notification_id(),
            )

            # Auto-dismiss when cooldown ends
            remaining = self._phase_cooldown_remaining_s()
            if remaining > 0:
                async def _auto_dismiss():
                    await asyncio.sleep(float(remaining) + 1.0)
                    if not self._phase_cooldown_active():
                        await self._dismiss_phase_switch_cooldown()
                self._create_task(_auto_dismiss())

        except Exception:
            _LOGGER.debug("Failed to create phase cooldown notification", exc_info=True)

    def _phase_notify_problem_active(self) -> bool:
        """Check if there's a phase-related problem that should trigger notification."""
        new_val = self._phase_feedback_value

        # Wallbox-controlled: only notify on unknown feedback
        if self._is_wallbox_controlled_phase_switch():
            return new_val not in ("1p", "3p")

        # Integration-controlled: notify on unknown OR mismatch
        if new_val not in ("1p", "3p"):
            return True

        expected = self._expected_phase_for_mismatch_check()
        if expected in ("1p", "3p") and new_val != expected:
            return True

        return False

    def _reconcile_phase_feedback_notify(self) -> None:
        """Start/cancel the delayed 'phase feedback uncertain' notify timer based on current state.

        - Starts timer if a problem is active and no timer is running.
        - Cancels timer + dismisses notification if problem is not active.
        - Does NOT restart timer if already running (as requested).
        """
        problem = self._phase_notify_problem_active()

        # If everything is OK -> cancel timer & dismiss notification
        if not problem:
            self._phase_notify_active = False
            self._cancel_phase_fallback_timer()
            self._create_task(self._dismiss_phase_feedback_uncertain())
            return

        # Problem is active
        self._phase_notify_active = True

        # Start timer only if not already running
        if self._phase_fallback_timer_task is None or self._phase_fallback_timer_task.done():
            self._start_phase_fallback_timer()

    def _phase_cooldown_notification_id(self) -> str:
        return f"evcm_phase_switch_cooldown_{self.entry.entry_id}"

    async def _dismiss_phase_switch_cooldown(self) -> None:
        await self._dismiss_persistent(self._phase_cooldown_notification_id())

    # ---------------- External OFF notification helpers ----------------
    def _external_off_notification_id(self) -> str:
        return f"evcm_external_off_{self.entry.entry_id}"

    def _external_on_notification_id(self) -> str:
        return f"evcm_external_on_{self.entry.entry_id}"

    async def _dismiss_external_off_notification(self) -> None:
        await self._dismiss_persistent(self._external_off_notification_id())

    async def _dismiss_external_on_notification(self) -> None:
        await self._dismiss_persistent(self._external_on_notification_id())

    # ---------------- Phase switching: status getters ----------------
    def get_phase_status_value(self) -> str:
        return self._phase_status_value

    def get_phase_status_attrs(self) -> dict:
        mismatch = bool(
            self._phase_target in ("1p", "3p")
            and self._phase_feedback_value in ("1p", "3p")
            and self._phase_feedback_value != self._phase_target
        )

        return {
            "mismatch": mismatch,
            "fallback_active": bool(self._phase_fallback_active),
            "cooldown_active": self._phase_cooldown_active(),
            "cooldown_remaining_s": self._phase_cooldown_remaining_s(),
        }

    def _phase_uncertain_notification_id(self) -> str:
        return f"evcm_phase_feedback_uncertain_{self.entry.entry_id}"

    def _notify_phase_feedback_uncertain(self) -> None:
        try:
            device_name = self._device_name_for_notify()
            timeout_s = int(float(PHASE_SWITCH_REQUEST_FEEDBACK_TIMEOUT_S))
            if timeout_s % 60 == 0:
                dur = f"{timeout_s // 60} minute(s)"
            else:
                dur = f"{timeout_s} seconds"
            auto_note = ""
            if self._phase_switch_auto_enabled:
                auto_note = "\n\nAuto phase switching is disabled while phase feedback is unknown."

            msg = (
                f"Phase feedback uncertain for {device_name}\n\n"
                f"Phase feedback has been unknown or inconsistent for more than {dur}.\n"
                "EVCM will operate with conservative assumptions until feedback becomes available."
                f"{auto_note}"
            )
            self._notify_persistent_fire_and_forget(
                "EVCM: Phase feedback uncertain",
                msg,
                self._phase_uncertain_notification_id(),
            )
        except Exception:
            _LOGGER.debug("Failed to create phase feedback uncertain notification", exc_info=True)

    async def _dismiss_phase_feedback_uncertain(self) -> None:
        await self._dismiss_persistent(self._phase_uncertain_notification_id())

    def _cancel_phase_fallback_timer(self) -> None:
        t = self._phase_fallback_timer_task
        self._phase_fallback_timer_task = None
        if t and not t.done():
            t.cancel()

    def _start_phase_fallback_timer(self) -> None:
        """Start delayed notify when we enter fallback; notify only if still in fallback after timeout."""
        self._cancel_phase_fallback_timer()

        async def _runner():
            try:
                # Wait AFTER grace has ended (if grace is active when we start)
                # If grace is currently active, we just wait the remaining grace first.
                try:
                    # remaining grace (best-effort)
                    remaining_grace = max(
                        0.0,
                        float(UNKNOWN_STARTUP_GRACE_SECONDS)
                        - (dt_util.utcnow() - self._startup_ts).total_seconds(),
                    )
                except Exception:
                    remaining_grace = 0.0

                if remaining_grace > 0:
                    await asyncio.sleep(remaining_grace)

                # Now start the real fallback notify delay
                await asyncio.sleep(float(PHASE_SWITCH_REQUEST_FEEDBACK_TIMEOUT_S))

                # Only notify if the problem is STILL active (unknown OR mismatch)
                if self._phase_notify_problem_active():
                    self._notify_phase_feedback_uncertain()
                    self._notify_mode_listeners()
            except asyncio.CancelledError:
                return
            except Exception:
                _LOGGER.debug("Phase fallback timer failed", exc_info=True)
            finally:
                self._phase_fallback_timer_task = None

        self._phase_fallback_timer_task = self._create_task(_runner())

    def _parse_phase_feedback(self, raw_state) -> str:
        s = str(raw_state or "").strip().lower()
        if s == "1p":
            return "1p"
        if s == "3p":
            return "3p"
        # Treat anything else (including 'unavailable') as unknown
        return "unknown"

    @callback
    def _async_phase_feedback_event(self, event: Event):
        new = event.data.get("new_state")

        # Normalize new feedback
        if not self._is_known_state(new):
            new_val = "unknown"
        else:
            new_val = self._parse_phase_feedback(getattr(new, "state", None))

        # No change -> nothing to do
        if new_val == self._phase_feedback_value:
            return

        prev_val = self._phase_feedback_value
        
        # Update feedback
        self._phase_feedback_value = new_val

        # Wallbox-controlled: internal profile follows feedback automatically
        if self._is_wallbox_controlled_phase_switch() and new_val in ("1p", "3p"):
            new_profile = PHASE_PROFILE_ALTERNATE if new_val == "1p" else PHASE_PROFILE_PRIMARY
            if self._phase_switch_forced_profile != new_profile:
                self._phase_switch_forced_profile = new_profile
                self._create_task(self._save_unified_state_debounced())
                _LOGGER.info(
                    "EVCM %s: Wallbox-controlled phase switch detected: feedback=%s -> internal profile=%s",
                    self._log_name(), new_val, new_profile
                )
            
            # Wallbox-controlled: no mismatch concept, just follow feedback
            self._phase_fallback_active = (new_val not in ("1p", "3p"))
            
            # UI status update
            if new_val in ("1p", "3p"):
                self._phase_status_value = new_val
            else:
                self._phase_status_value = "Unknown"
            
            # Sync notification timer
            self._reconcile_phase_feedback_notify()
            
            # Apply control changes
            self._create_task(self._hysteresis_apply())
            self._start_regulation_loop_if_needed()
            self._notify_mode_listeners()
            self._create_task(self._auto_evaluate_and_maybe_switch())
            return

        # Integration-controlled: check for mismatch with expected phase
        expected = self._expected_phase_for_mismatch_check()
        
        mismatch = (
            expected in ("1p", "3p")
            and new_val in ("1p", "3p")
            and new_val != expected
        )

        # Fallback active if unknown OR mismatch
        self._phase_fallback_active = (new_val not in ("1p", "3p")) or mismatch

        if mismatch:
            _LOGGER.warning(
                "EVCM %s: Phase mismatch detected: expected=%s, feedback=%s -> using conservative 3p thresholds",
                self._log_name(), expected, new_val
            )

        # UI status update
        if new_val in ("1p", "3p"):
            if mismatch:
                self._phase_status_value = f"{new_val} (mismatch)"
            else:
                self._phase_status_value = new_val
        else:
            # Only show Unknown if we are not actively switching
            if self._phase_target is None:
                self._phase_status_value = "Unknown"

        # Sync notification timer with current problem state (unknown OR mismatch)
        self._reconcile_phase_feedback_notify()

        # If feedback now matches what we expected, clear the pending request markers
        # BUT: in Auto mode, keep last_requested_target as our reference
        if expected in ("1p", "3p") and new_val == expected:
            self._phase_target = None
            self._phase_last_request_ts = None
            
            # Only clear last_requested_target in forced mode, not in auto mode
            if not self._phase_switch_auto_enabled:
                self._phase_last_requested_target = None

            # Now that mismatch is resolved, sync timer/notification again
            self._reconcile_phase_feedback_notify()

        # Apply control changes
        self._create_task(self._hysteresis_apply())
        self._start_regulation_loop_if_needed()
        self._notify_mode_listeners()
        self._create_task(self._auto_evaluate_and_maybe_switch())

    async def async_request_phase_switch(self, *, target: str, source: str) -> bool:
        target_norm = str(target).strip().lower()
        
        _LOGGER.debug("EVCM %s: async_request_phase_switch called - target=%s, feedback=%s, in_progress=%s, phase_target=%s", 
            self._log_name(), target_norm, self._phase_feedback_value, self._phase_switch_in_progress, self._phase_target)
        
        if target_norm not in ("1p", "3p"):
            return False

        if not self._phase_switch_supported():
            _LOGGER.debug("EVCM %s: Phase switch request ignored (feature disabled)", self._log_name())
            return False

        # Wallbox-controlled: reject all phase switch requests from integration
        if self._is_wallbox_controlled_phase_switch():
            _LOGGER.debug("EVCM %s: Phase switch request rejected (wallbox-controlled mode)", self._log_name())
            return False

        # Quick reject if switch already in progress (don't wait for lock)
        if self._phase_switch_in_progress or self._phase_target is not None:
            _LOGGER.debug("EVCM %s: Phase switch request rejected (switch in progress to %s)", self._log_name(), self._phase_target)
            self._notify_phase_switch_cooldown_active()
            return False

        # NOOP: already in requested phase (confirmed by feedback)
        if self._phase_feedback_value in ("1p", "3p") and self._phase_feedback_value == target_norm:
            _LOGGER.debug("EVCM %s: Phase switch NOOP - feedback already matches target=%s", 
                self._log_name(), target_norm)
            # Ensure UI status is clean
            self._phase_target = None
            self._phase_last_requested_target = None
            self._phase_last_request_ts = None
            self._phase_status_value = self._phase_feedback_value
            self._reconcile_phase_feedback_notify()
            self._notify_mode_listeners()
            return True

        async with self._phase_switch_lock:
            if self._phase_cooldown_active():
                # Reject: cooldown is active (no queue)
                self._notify_phase_switch_cooldown_active()

                # Optional: show a clean status; keep actual phase status if known
                if self._phase_target is None:
                    if self._phase_feedback_value in ("1p", "3p"):
                        self._phase_status_value = self._phase_feedback_value
                    else:
                        self._phase_status_value = "Cooldown active"

                self._notify_mode_listeners()
                return False

            # Accept: start cooldown NOW (persisted)
            self._phase_cooldown_until_utc = dt_util.utcnow() + timedelta(seconds=int(PHASE_SWITCH_COOLDOWN_SECONDS))
            self._phase_cooldown_active_target = target_norm
            self._create_task(self._persist_phase_cooldown_state())
            self._phase_target = target_norm
            self._phase_last_requested_target = target_norm
            self._phase_last_request_ts = time.monotonic()
            self._phase_switch_in_progress = True
            self._reconcile_phase_feedback_notify()

            _LOGGER.debug("EVCM %s: Phase switch request accepted, in_progress=%s, cooldown_active=%s, target=%s", 
                self._log_name(), 
                self._phase_switch_in_progress, 
                self._phase_cooldown_active(),
                target_norm
            )

        # From here on, ensure we clear _phase_switch_in_progress on any exit
        try:
            # Mark pending request immediately
            self._phase_target = target_norm
            self._phase_status_value = f"Switching to {target_norm}"
            self._notify_mode_listeners()

            # Stop loops/timers to avoid interference while stopping charge
            self._stop_regulation_loop()
            self._stop_resume_monitor()
            self._cancel_upper_timer()

            # Ensure charging is OFF and reset current to 6A (best effort)
            await self._ensure_charging_enable_off()
            if self._current_setting_entity:
                with contextlib.suppress(Exception):
                    await self._set_current_setting_a(MIN_CURRENT_A)

            # Wait for power down unless cable disconnected
            if self._is_cable_connected():
                ok = await self._phase_wait_for_power_stopped()
                if not ok:
                    self._phase_target = None
                    self._phase_status_value = "Unknown"
                    self._notify_phase_feedback_uncertain()
                    self._notify_mode_listeners()
                    return False

            # Re-anchor/extend cooldown at actual switching moment (never shorten)
            async with self._phase_switch_lock:
                new_until = dt_util.utcnow() + timedelta(seconds=int(PHASE_SWITCH_COOLDOWN_SECONDS))
                if self._phase_cooldown_until_utc is None or new_until > self._phase_cooldown_until_utc:
                    self._phase_cooldown_until_utc = new_until
                    self._phase_cooldown_active_target = target_norm
                    self._create_task(self._persist_phase_cooldown_state())

            # Fire request event for user's automation
            self.hass.bus.async_fire(
                PHASE_SWITCH_REQUEST_EVENT,
                {
                    "entry_id": self.entry.entry_id,
                    "target": target_norm,
                    "source": str(source),
                },
            )

            # Short safety veto after command moment
            self._ce_phase_veto_until_ts = time.monotonic() + float(PHASE_SWITCH_CE_VETO_SECONDS_DEFAULT)

            # After veto ends, resume normal control logic
            self._schedule_phase_post_veto_reconcile()

            return True

        finally:
            self._phase_switch_in_progress = False

    async def _phase_wait_for_power_stopped(self) -> bool:
        threshold = float(PHASE_SWITCH_STOPPED_POWER_W_DEFAULT)
        deadline = time.monotonic() + float(PHASE_SWITCH_WAIT_FOR_STOP_SECONDS_DEFAULT)

        while time.monotonic() < deadline:
            if not self._is_cable_connected():
                return True
            pw = self._get_charge_power_w()
            if pw is not None and pw <= threshold:
                return True
            await asyncio.sleep(LOCK_WAIT_POLL_INTERVAL_S)

        return False

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
        # Policy: never force-lock while cable is connected; only lock on disconnect.
        # This keeps charging/retries unaffected during runtime and after HA restart.
        if self._is_cable_connected():
            return
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

    async def _ensure_unlocked_for_start(self, timeout_s: float = UNLOCK_TIMEOUT_S) -> bool:
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
        deadline = time.monotonic() + max(LOCK_WAIT_POLL_INTERVAL_S, float(timeout_s))
        while time.monotonic() < deadline:
            if self._is_lock_unlocked():
                return True
            await asyncio.sleep(LOCK_WAIT_POLL_INTERVAL_S)
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
        return bool(status_ok or (power is not None and power > CHARGING_POWER_THRESHOLD_W))

    async def _wait_for_charging_detection(self, timeout_s: float = CHARGING_WAIT_TIMEOUT_S) -> bool:
        deadline = time.monotonic() + max(LOCK_WAIT_POLL_INTERVAL_S, float(timeout_s))
        while time.monotonic() < deadline:
            if not self._is_cable_connected():
                return False
            if self._charging_detected_now():
                return True
            await asyncio.sleep(LOCK_WAIT_POLL_INTERVAL_S)
        return False

    def _schedule_relock_after_charging_start(self, already_detected: bool = False):
        if not getattr(self, "_relock_enabled", False):
            return
        self._cancel_relock_task()

        async def _runner():
            try:
                if not already_detected:
                    deadline = time.monotonic() + CHARGING_DETECTION_TIMEOUT_S
                    while time.monotonic() < deadline:
                        if not self._is_cable_connected():
                            _LOGGER.debug("Relock monitor aborted: cable disconnected")
                            return
                        status = self._get_wallbox_status()
                        power = self._get_charge_power_w()
                        if self._is_status_charging() or (power is not None and power > CHARGING_POWER_THRESHOLD_W):
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

        self._relock_task = self._create_task(_runner())

    # ---------------- Auto phase switching (v1: stopped-based) ----------------
    def _auto_delay_seconds(self) -> int:
        eff = _effective_config(self.entry)
        try:
            v = int(eff.get(CONF_AUTO_PHASE_SWITCH_DELAY_MIN, DEFAULT_AUTO_PHASE_SWITCH_DELAY_MIN))
        except Exception:
            v = DEFAULT_AUTO_PHASE_SWITCH_DELAY_MIN
        v = max(AUTO_PHASE_SWITCH_DELAY_MIN_MIN, min(AUTO_PHASE_SWITCH_DELAY_MIN_MAX, v))
        return int(v * 60)

    def _auto_clear_candidate_1p_to_3p(self) -> None:
        self._auto_1p_to_3p_candidate_since_utc = None
        self._auto_1p_to_3p_reset_since_ts = None

    def _auto_clear_candidate_3p_to_1p(self) -> None:
        self._auto_3p_to_1p_candidate_since_utc = None
        self._auto_3p_to_1p_reset_since_ts = None

    def _auto_set_stop_reason_below_lower(self) -> None:
        self._auto_last_stop_reason = AUTO_STOP_REASON_BELOW_LOWER
        self._auto_last_stop_ts_utc = dt_util.utcnow()
        self._create_task(self._save_unified_state_debounced())

    def _auto_clear_stop_reason(self) -> None:
        if self._auto_last_stop_reason is not None or self._auto_last_stop_ts_utc is not None:
            self._auto_last_stop_reason = None
            self._auto_last_stop_ts_utc = None
            self._create_task(self._save_unified_state_debounced())

    def _auto_blocked(self) -> bool:
        # Feature gating
        if not self._phase_switch_supported():
            return True

        # Wallbox-controlled: integration should never auto-switch
        if self._is_wallbox_controlled_phase_switch():
            return True

        # Auto only runs if user selected Auto in the select entity (persisted flag)
        if not bool(self._phase_switch_auto_enabled):
            return True

        # ... rest van de methode blijft ongewijzigd ...

        # Start/Stop must be ON (otherwise we should not act at all)
        if not self.get_mode(MODE_START_STOP):
            return True

        # Must be connected (avoid switching while unplugged)
        if not self._is_cable_connected():
            return True

        # "May I charge?" gating: if charging is not allowed, do not phase switch
        # (minimize switching and avoid cooldown usage while planner/SoC/priority/missing data blocks charging)
        if not self._planner_window_allows_start():
            return True
        if not self._soc_allows_start():
            return True
        if not self._priority_allowed_cache:
            return True
        if not self._essential_data_available():
            return True

        # unknown feedback OR fallback => no auto
        if self._phase_feedback_value not in ("1p", "3p"):
            return True
        if bool(self._phase_fallback_active):
            return True

        # cooldown/switch in progress
        if self._phase_cooldown_active():
            return True
        if self._phase_target is not None:
            return True

        return False

    def _auto_upper_3p(self) -> float:
        eff = _effective_config(self.entry)
        if self.get_mode(MODE_ECO):
            return float(eff.get(CONF_ECO_ON_UPPER, DEFAULT_ECO_ON_UPPER))
        return float(eff.get(CONF_ECO_OFF_UPPER, DEFAULT_ECO_OFF_UPPER))

    def _auto_upper_alt(self) -> float:
        eff = _effective_config(self.entry)
        if self.get_mode(MODE_ECO):
            return float(eff.get(CONF_ECO_ON_UPPER_ALT, DEFAULT_ECO_ON_UPPER_ALT))
        return float(eff.get(CONF_ECO_OFF_UPPER_ALT, DEFAULT_ECO_OFF_UPPER_ALT))

    def _auto_is_at_max_current(self, current_a: Optional[int]) -> bool:
        if current_a is None:
            return False
        conf_max = self._max_current_a()
        return int(current_a) >= int(conf_max)

    def _auto_candidate_update(
        self,
        *,
        active: bool,
        since_utc: Optional[datetime],
        reset_since_ts: Optional[float],
    ) -> tuple[Optional[datetime], Optional[float], bool]:
        """Debounced candidate timer update (T_reset=180s)."""
        now_mono = time.monotonic()
        changed = False

        if active:
            if reset_since_ts is not None:
                reset_since_ts = None
                changed = True
            if since_utc is None:
                since_utc = dt_util.utcnow()
                changed = True
            return since_utc, reset_since_ts, changed

        # Not active
        if since_utc is None:
            if reset_since_ts is not None:
                reset_since_ts = None
                changed = True
            return None, reset_since_ts, changed

        if reset_since_ts is None:
            reset_since_ts = now_mono
            changed = True
            return since_utc, reset_since_ts, changed

        if (now_mono - float(reset_since_ts)) >= float(AUTO_RESET_DEBOUNCE_SECONDS):
            since_utc = None
            reset_since_ts = None
            changed = True

        return since_utc, reset_since_ts, changed

    def _auto_elapsed_ok(self, since_utc: Optional[datetime]) -> bool:
        if not since_utc:
            return False
        try:
            return (dt_util.utcnow() - since_utc).total_seconds() >= float(self._auto_delay_seconds())
        except Exception:
            return False

    async def _auto_evaluate_and_maybe_switch(self) -> None:
        """Evaluate stopped-based Auto switching (persistent timers)."""
        try:
            if self._auto_blocked():
                self._auto_clear_candidate_1p_to_3p()
                self._auto_clear_candidate_3p_to_1p()
                self._create_task(self._save_unified_state_debounced())
                return

            net = self._get_net_power_w()
            chg = self._get_charge_power_w()
            cur_a = await self._get_current_setting_a()

            # 1p -> 3p: max current + headroom >= upper_3p + margin
            headroom = None
            if net is not None and chg is not None:
                headroom = float(net) + float(chg)

            cond_1p_to_3p = (
                self._phase_feedback_value == "1p"
                and self.get_mode(MODE_START_STOP)
                and self._is_cable_connected()
                and self._auto_is_at_max_current(cur_a)
                and headroom is not None
                and headroom >= (self._auto_upper_3p() + float(AUTO_1P_TO_3P_MARGIN_W))
            )

            new_since, new_reset, changed = self._auto_candidate_update(
                active=bool(cond_1p_to_3p),
                since_utc=self._auto_1p_to_3p_candidate_since_utc,
                reset_since_ts=self._auto_1p_to_3p_reset_since_ts,
            )
            self._auto_1p_to_3p_candidate_since_utc = new_since
            self._auto_1p_to_3p_reset_since_ts = new_reset

            if changed:
                self._create_task(self._save_unified_state_debounced())

            if self._auto_elapsed_ok(self._auto_1p_to_3p_candidate_since_utc):
                ok = await self.async_request_phase_switch(
                    target="3p",
                    source=PHASE_SWITCH_SOURCE_AUTO,
                )
                self._auto_clear_candidate_1p_to_3p()
                self._create_task(self._save_unified_state_debounced())
                if ok:
                    return

            # 3p -> 1p: stopped by below_lower + net >= upper_alt
            charging_enabled = self._is_charging_enabled()
            stop_reason_ok = (self._auto_last_stop_reason == AUTO_STOP_REASON_BELOW_LOWER)
            net_ok_for_1p_start = (net is not None and net >= self._auto_upper_alt())

            # If charging can resume now (or is already above upper), resuming has priority over switching to 1p.
            resume_has_priority = False
            try:
                if (
                    self.get_mode(MODE_START_STOP)
                    and self._is_cable_connected()
                    and (not charging_enabled)
                    and self._planner_window_allows_start()
                    and self._soc_allows_start()
                    and self._priority_allowed_cache
                    and self._essential_data_available()
                    and net is not None
                ):
                    # "Can resume now" OR "above upper (debounce pending)" => don't switch
                    if self._sustained_above_upper(net) or (net >= self._current_upper()):
                        resume_has_priority = True
            except Exception:
                resume_has_priority = False

            if resume_has_priority:
                # Clear any pending 3p->1p candidate so it cannot fire on this event.
                if (
                    self._auto_3p_to_1p_candidate_since_utc is not None
                    or self._auto_3p_to_1p_reset_since_ts is not None
                ):
                    self._auto_clear_candidate_3p_to_1p()
                    self._create_task(self._save_unified_state_debounced())
                # Do not attempt auto 3p->1p switching on this tick.
                return

            cond_3p_to_1p = (
                self._phase_feedback_value == "3p"
                and self.get_mode(MODE_START_STOP)
                and self._is_cable_connected()
                and (not charging_enabled)
                and stop_reason_ok
                and net_ok_for_1p_start
            )

            # IMPORTANT: for 3p->1p we want "continuous true for delay",
            # so reset immediately when the condition is not active.
            changed = False
            if cond_3p_to_1p:
                if self._auto_3p_to_1p_candidate_since_utc is None:
                    self._auto_3p_to_1p_candidate_since_utc = dt_util.utcnow()
                    self._auto_3p_to_1p_reset_since_ts = None
                    changed = True
            else:
                if (
                    self._auto_3p_to_1p_candidate_since_utc is not None
                    or self._auto_3p_to_1p_reset_since_ts is not None
                ):
                    self._auto_clear_candidate_3p_to_1p()
                    changed = True

            if changed:
                self._create_task(self._save_unified_state_debounced())

            if self._auto_elapsed_ok(self._auto_3p_to_1p_candidate_since_utc):
                ok = await self.async_request_phase_switch(
                    target="1p",
                    source=PHASE_SWITCH_SOURCE_AUTO,
                )
                self._auto_clear_candidate_3p_to_1p()
                self._create_task(self._save_unified_state_debounced())
                if ok:
                    return

        except asyncio.CancelledError:
            return
        except Exception:
            _LOGGER.debug("Auto phase switch evaluate failed", exc_info=True)

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
            self._create_task(self._save_unified_state_debounced())
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
        self._create_task(self._save_unified_state_debounced())
        self._create_task(self._hysteresis_apply())

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
        return self._profile_reg_min_w or (3900 if self._supply_phases == 3 else 1300)

    def _effective_min_charge_power(self) -> int:
        base = self._profile_min_power_6a_w
        return max(base, MIN_CHARGE_POWER_THREE_PHASE_W if self._supply_phases == 3 else MIN_CHARGE_POWER_SINGLE_PHASE_W)

    # ---------------- Initialization / Shutdown ----------------
    async def async_initialize(self):
        await self._load_unified_state()
        self._cancel_relock_task()

        # Backfill default SoC limit for older entries that had no value
        if self._soc_limit_percent is None:
            self._soc_limit_percent = DEFAULT_SOC_LIMIT_PERCENT
            self._create_task(self._save_unified_state_debounced())

        await self._refresh_priority_mode_flag()
        self._priority_allowed_cache = await self._is_priority_allowed()
        self._init_monotonic = time.monotonic()
        with contextlib.suppress(Exception):
            self._last_soc_allows = self._soc_allows_start()
            self._last_missing_nonempty = bool(self._current_missing_components())

        # Defer any service calls and monitors until HA has started
        if self.hass.is_running:
            self._ha_started_listener_active = False
            self._started_unsub = None
            await self._on_ha_started(None)
        else:
            self._started_unsub = self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, self._on_ha_started
            )
            self._ha_started_listener_active = True
        self._create_task(self._auto_evaluate_and_maybe_switch())

    async def _on_ha_started(self, _event):
        self._ha_started_listener_active = False
        self._started_unsub = None
        self._cancel_relock_task()

        # Defer all heavy/event-driven work a bit to let HA finalize startup
        self._create_task(self._late_start_after_ha_started())

        # Install midnight listener and start monitors after HA is running
        self._install_midnight_daily_listener()
        # Schedule potentially blocking routines
        self._create_task(self._enforce_start_stop_policy())
        self._create_task(self._apply_cable_state_initial())
        self._start_planner_monitor_if_needed()
        if self._priority_allowed_cache:
            self._start_regulation_loop_if_needed()
            self._start_resume_monitor_if_needed()
        self._evaluate_missing_and_start_no_data_timer()
        self._schedule_startup_grace_recheck()

    async def _late_start_after_ha_started(self) -> None:
        # Small minimum delay: give HA a breath even on fast systems
        await asyncio.sleep(LATE_START_INITIAL_DELAY_S)

        # Wait until MQTT entities are actually available/known (bounded)
        ready_ids = self._startup_ready_entity_ids()
        timeout_s = MQTT_READY_TIMEOUT_S
        deadline = time.monotonic() + timeout_s
        last_log = 0.0

        while time.monotonic() < deadline:
            missing = [eid for eid in ready_ids if not self._is_entity_known(eid)]
            if not missing:
                break

            now = time.monotonic()
            # Log every 10 seconds max
            if now - last_log > 10.0:
                last_log = now
                _LOGGER.debug(
                    "Late-start waiting for MQTT entities (%ds left): %s",
                    int(deadline - now),
                    ", ".join(missing),
                )
            await asyncio.sleep(1)

        # Now start the integration work
        self._install_midnight_daily_listener()
        self._subscribe_listeners()
        self._create_task(self._enforce_start_stop_policy())
        self._create_task(self._apply_cable_state_initial())
        self._start_planner_monitor_if_needed()
        if self._priority_allowed_cache:
            self._start_regulation_loop_if_needed()
            self._start_resume_monitor_if_needed()
        self._evaluate_missing_and_start_no_data_timer()
        self._schedule_startup_grace_recheck()

    async def async_shutdown(self):
        # Cancel all tracked background tasks first
        cancelled_count = self._cancel_tracked_tasks()
        # Cancel pending debounced save
        if self._save_debounce_task and not self._save_debounce_task.done():
            self._save_debounce_task.cancel()
        self._save_debounce_task = None
        if cancelled_count > 0:
            _LOGGER.debug("EVCM %s: cancelled %d tracked tasks on shutdown", self._log_name(), cancelled_count)

        self._cancel_auto_connect_task()
        self._stop_regulation_loop()
        self._cancel_phase_fallback_timer()
        self._cancel_ce_enable_retry()
        self._cancel_ce_disable_retry()
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
                if self._ha_started_listener_active:
                    self._started_unsub()
            self._started_unsub = None
        self._ha_started_listener_active = False
        self._post_start_done = False

        if self._startup_grace_recheck_handle is not None:
            with contextlib.suppress(Exception):
                self._startup_grace_recheck_handle.cancel()
            self._startup_grace_recheck_handle = None

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

        if self._phase_feedback_entity:
            self._unsub_listeners.append(
                async_track_state_change_event(self.hass, self._phase_feedback_entity, self._async_phase_feedback_event)
            )

            # Prime phase feedback state immediately (otherwise we only update on change events)
            st = self.hass.states.get(self._phase_feedback_entity)
            if self._is_known_state(st):
                self._phase_feedback_value = self._parse_phase_feedback(getattr(st, "state", None))
            else:
                self._phase_feedback_value = "unknown"

            if self._phase_feedback_value in ("1p", "3p"):
                self._phase_status_value = self._phase_feedback_value
            else:
                if self._phase_target is None:
                    self._phase_status_value = "Unknown"

            # In Auto mode without a previous request, accept current feedback as starting point
            if self._phase_switch_auto_enabled and self._phase_last_requested_target is None:
                if self._phase_feedback_value in ("1p", "3p"):
                    self._phase_last_requested_target = self._phase_feedback_value
                    _LOGGER.debug(
                        "EVCM %s: Startup auto mode: setting last_requested_target=%s from feedback",
                        self._log_name(), self._phase_feedback_value
                    )

            # fallback is active when unknown OR mismatch
            self._phase_fallback_active = self._phase_notify_problem_active()

            # start/cancel timer based on current state (startup/reload)
            self._reconcile_phase_feedback_notify()

        self._notify_mode_listeners()

        # Apply immediately so thresholds/loops match current phase at startup
        self._create_task(self._hysteresis_apply())
        self._start_regulation_loop_if_needed()

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
        self._auto_clear_stop_reason()

    async def _pause_basic(self, set_current_to_min: bool):
        self._auto_clear_stop_reason()
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
                self._create_task(async_clear_priority_pause(self.hass, self.entry.entry_id, "no_data", notify=False))
                self._create_task(async_align_current_with_order(self.hass))

        self._last_missing_nonempty = now_missing

    # ---------------- Check if essential entities ready at startup ----------------
    def _is_entity_known(self, entity_id: Optional[str]) -> bool:
        if not entity_id:
            return False
        st = self.hass.states.get(entity_id)
        return bool(st and st.state not in ("unknown", "unavailable"))

    def _startup_ready_entity_ids(self) -> list[str]:
        ids: list[str] = []
        # command + main trigger
        if self._charging_enable_entity:
            ids.append(self._charging_enable_entity)
        if self._cable_entity:
            ids.append(self._cable_entity)

        # grid inputs
        if self._grid_single:
            if self._grid_power_entity:
                ids.append(self._grid_power_entity)
        else:
            if self._grid_export_entity:
                ids.append(self._grid_export_entity)
            if self._grid_import_entity:
                ids.append(self._grid_import_entity)

        return ids

    # ---------------- External import limit (Max peak avg) ----------------
    @property
    def ext_import_limit_w(self) -> Optional[int]:
        return self._ext_import_limit_w

    def set_ext_import_limit_w(self, value: Optional[float | int]):
        """Set external import limit (positive W). 0 or None disables."""
        try:
            iv = int(round(float(value if value is not None else 0)))
        except Exception:
            iv = 0
        iv = max(0, min(EXT_IMPORT_LIMIT_MAX_W, iv))
        new_val = iv if iv > 0 else None
        if new_val != self._ext_import_limit_w:
            self._ext_import_limit_w = new_val
            self._create_task(self._save_unified_state_debounced())
            _LOGGER.info("External import limit (Max peak avg) updated → %s W", new_val or 0)
            # Re-apply hysteresis with new thresholds
            self._create_task(self._hysteresis_apply())
            self._evaluate_missing_and_start_no_data_timer()

    # ---------------- Helper: profile min band ----------------
    def _profile_min_band_w(self) -> int:
        try:
            band = SUPPLY_PROFILE_MIN_BAND.get(self._supply_profile_key)
            if band is None:
                band = MIN_BAND_400 if self._supply_phases == 3 else MIN_BAND_230
            return int(band)
        except Exception:
            return 4500 if self._supply_phases == 3 else 1700

    def _max_peak_override_active(self) -> bool:
        """True if Max peak avg is stricter than the currently active lower threshold."""
        ext = self._ext_import_limit_w
        if not ext or ext <= 0:
            return False

        # Use the correct lower threshold based on current phase mode
        if self._use_alt_thresholds():
            eff = _effective_config(self.entry)
            if self.get_mode(MODE_ECO):
                base_lower = float(eff.get(CONF_ECO_ON_LOWER_ALT, DEFAULT_ECO_ON_LOWER_ALT))
            else:
                base_lower = float(eff.get(CONF_ECO_OFF_LOWER_ALT, DEFAULT_ECO_OFF_LOWER_ALT))
        else:
            base_lower = self._eco_on_lower if self.get_mode(MODE_ECO) else self._eco_off_lower

        ext_lower = float(-ext)

        # Only apply if ext is stricter (less negative / closer to zero) than base lower.
        # Example: base=-7000, ext=-5000 -> active (True)
        # Example: base=-2000, ext=-5000 -> NOT active (False)
        return ext_lower > float(base_lower)

    def _device_name_for_notify(self) -> str:
        device_name = None
        with contextlib.suppress(Exception):
            device_name = getattr(self, "name", None) or getattr(self, "_name", None)
        if not device_name:
            with contextlib.suppress(Exception):
                device_name = getattr(self.entry, "title", None)
        return device_name or self.entry.entry_id

    def _log_name(self) -> str:
        """Short, user-friendly name for logs (prefer configured name/title over entry_id)."""
        try:
            return self._device_name_for_notify()
        except Exception:
            return self.entry.entry_id

    async def _persist_external_off_state(self) -> None:
        """Persist external-off state (latch + last event timestamps) in config entry options."""
        try:
            new_opts = {
                **self.entry.options,
                OPT_EXTERNAL_OFF_LATCHED: bool(self._ce_external_off_latched),
                OPT_EXTERNAL_LAST_OFF_TS: self._ce_external_last_off_ts,
                OPT_EXTERNAL_LAST_ON_TS: self._ce_external_last_on_ts,
            }
            self.hass.config_entries.async_update_entry(self.entry, options=new_opts)
        except Exception:
            _LOGGER.debug("EVCM: failed to persist external OFF state", exc_info=True)

    # ---------------- Task tracking helpers ----------------
    def _track_task(self, task: asyncio.Task) -> asyncio.Task:
        """Track a task for cleanup on shutdown."""
        if task is None:
            return task
        self._tracked_tasks.add(task)
        task.add_done_callback(self._tracked_tasks.discard)
        return task

    def _create_task(self, coro) -> asyncio.Task:
        """Create and track a task."""
        task = self.hass.async_create_task(coro)
        return self._track_task(task)

    def _cancel_tracked_tasks(self) -> int:
        """Cancel all tracked tasks. Returns count of cancelled tasks."""
        cancelled = 0
        for task in list(self._tracked_tasks):
            if task and not task.done():
                task.cancel()
                cancelled += 1
        self._tracked_tasks.clear()
        return cancelled

    # ---------------- Notification helpers ----------------
    async def _notify_persistent(
        self,
        title: str,
        message: str,
        notification_id: str,
    ) -> None:
        """Create a persistent notification."""
        with contextlib.suppress(Exception):
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": title,
                    "message": message,
                    "notification_id": notification_id,
                },
                blocking=False,
            )

    async def _dismiss_persistent(self, notification_id: str) -> None:
        """Dismiss a persistent notification."""
        with contextlib.suppress(Exception):
            await self.hass.services.async_call(
                "persistent_notification",
                "dismiss",
                {"notification_id": notification_id},
                blocking=False,
            )

    def _notify_persistent_fire_and_forget(
        self,
        title: str,
        message: str,
        notification_id: str,
    ) -> None:
        """Create a persistent notification without awaiting (fire and forget)."""
        self._create_task(
            self._notify_persistent(title, message, notification_id)
        )

    # ---------------- Helper: phase switch reconcile ----------------
    def _schedule_phase_post_veto_reconcile(self) -> None:
        async def _runner():
            try:
                await asyncio.sleep(float(PHASE_SWITCH_CE_VETO_SECONDS_DEFAULT) + 0.2)
                # If another phase switch happened, this timestamp will have moved
                if time.monotonic() < float(self._ce_phase_veto_until_ts or 0.0):
                    return

                # Back to normal control: re-evaluate and restart loops
                await self._hysteresis_apply()
                self._start_regulation_loop_if_needed()
                self._start_resume_monitor_if_needed()
            except asyncio.CancelledError:
                return
            except Exception:
                _LOGGER.debug("Phase post-veto reconcile failed", exc_info=True)

        self._create_task(_runner())

    # ---------------- Helper: phase switch effective phase mode ----------------
    def _effective_phase_mode(self) -> str:
        """Return '1p', '3p' or 'unknown' based on confirmed feedback."""
        if not self._phase_switch_supported():
            return "3p"
        if self._phase_feedback_value in ("1p", "3p"):
            return self._phase_feedback_value
        return "unknown"

    # ---------------- Helper: effective profile ----------------
    def _effective_reg_profile_key(self) -> str:
        """EU-only phase-switch aware profile key for regulation math (regMin + inc/dec thresholds).

        - If phase switching isn't supported: use configured profile.
        - For wallbox-controlled: follow feedback directly.
        - For integration-controlled: use conservative 3p profile on mismatch/unknown.
        - If feedback confirms 1p (and no mismatch): use EU 1p profile.
        - Otherwise: use configured profile (typically EU 3p profile).
        """
        if not self._phase_switch_supported():
            return self._supply_profile_key
        
        # Wallbox-controlled: always follow feedback
        if self._is_wallbox_controlled_phase_switch():
            if self._phase_feedback_value == "1p":
                return "eu_1ph_230"
            return self._supply_profile_key
        
        # Integration-controlled: use conservative profile on mismatch/unknown
        # This must match the logic in _use_alt_thresholds()
        
        # Unknown feedback -> conservative 3p
        if self._phase_feedback_value not in ("1p", "3p"):
            return self._supply_profile_key
        
        # Check for mismatch
        expected = self._expected_phase_for_mismatch_check()
        if expected is not None and self._phase_feedback_value != expected:
            return self._supply_profile_key  # Mismatch -> conservative 3p
        
        # Fallback flag active -> conservative 3p
        if self._phase_fallback_active:
            return self._supply_profile_key
        
        # No mismatch, feedback is valid -> follow feedback
        if self._phase_feedback_value == "1p":
            return "eu_1ph_230"
        return self._supply_profile_key

    # ---------------- Event callbacks ----------------
    @callback
    def _async_cable_event(self, event: Event):
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        self._create_task(self._refresh_priority_mode_flag())
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

        # Keep single-writer cache aligned with actual entity state to avoid stale suppression
        try:
            if self._is_known_state(new):
                # reflect the actual HA state in the cache immediately
                self._ce_last_desired = True if new.state == STATE_ON else False
                self._ce_last_write_ts = time.monotonic()

                if new.state == STATE_ON:
                    # If we see ON, any enable-retry loop is no longer needed.
                    self._cancel_ce_enable_retry()
        except Exception:
            # don't let cache-sync break event processing
            _LOGGER.debug("Failed to sync CE cache from event", exc_info=True)

        self._create_task(self._refresh_priority_mode_flag())

        device_name = None
        with contextlib.suppress(Exception):
            device_name = getattr(self, "name", None) or getattr(self, "_name", None)
        if not device_name:
            with contextlib.suppress(Exception):
                device_name = getattr(self.entry, "title", None)
        if not device_name:
            device_name = self.entry.entry_id

        # External OFF latch + external ON clears latch (two separate notifications)
        # External OFF detection is ONLY meaningful if EVCM currently wants charging_enable ON.
        try:
            if self._is_known_state(new):
                now = time.monotonic()

                # External ON: if user/MQTT turns charging_enable ON while latched, clear the latch
                if str(new.state) == STATE_ON and self._ce_external_off_latched:
                    self._ce_external_off_latched = False
                    self._ce_on_blocked_logged = False
                    self._ce_external_last_on_ts = dt_util.utcnow().timestamp()
                    self._create_task(self._persist_external_off_state())
                    
                    if self._is_wallbox_controlled_phase_switch():
                        _LOGGER.debug(
                            "EVCM %s: external OFF latch cleared by external ON (wallbox-controlled mode, entity=%s)",
                            self._log_name(), self._charging_enable_entity
                        )
                    else:
                        _LOGGER.warning(
                            "EVCM %s: external OFF latch cleared by external ON (entity=%s)",
                            self._log_name(), self._charging_enable_entity
                        )

                    # Suppress notification in wallbox-controlled phase switch mode
                    if not self._is_wallbox_controlled_phase_switch():
                        msg = (
                            f"External charging_enable ON detected for {device_name}\n"
                            f"Last external ON: {dt_util.as_local(dt_util.utcnow()).strftime('%Y-%m-%d %H:%M:%S')}\n"
                            "External OFF latch cleared: yes\n"
                            "Charging can resume."
                        )
                        self._notify_persistent_fire_and_forget(
                            "EVCM: External ON detected",
                            msg,
                            self._external_on_notification_id(),
                        )

                # External OFF detection + latch (only when EVCM wants ON now)
                if str(new.state) == STATE_OFF:
                    wants_on_now = False
                    try:
                        wants_on_now = bool(self._ce_wants_enable_on_now())
                    except Exception:
                        wants_on_now = False

                    if wants_on_now:
                        # "Expected OFF" if our last intent was OFF very recently (race protection).
                        expected_off_recent = (
                            self._ce_last_intent_desired is False
                            and (now - float(self._ce_last_intent_ts or 0.0)) <= 5.0
                        )

                        if not expected_off_recent:
                            cable_connected = False
                            try:
                                cable_connected = self._is_cable_connected()
                            except Exception:
                                cable_connected = False

                            if cable_connected:
                                # Latch on ANY external OFF (we did not recently intend OFF)
                                if not self._ce_external_off_latched:
                                    self._ce_external_off_latched = True
                                    self._ce_on_blocked_logged = False
                                    self._ce_external_last_off_ts = dt_util.utcnow().timestamp()
                                    self._create_task(self._persist_external_off_state())
                                    last_intent = (
                                        "on" if self._ce_last_intent_desired is True
                                        else "off" if self._ce_last_intent_desired is False
                                        else "unknown"
                                    )
                                    age_s = now - float(self._ce_last_intent_ts or 0.0)
                                    
                                    if self._is_wallbox_controlled_phase_switch():
                                        _LOGGER.debug(
                                            "EVCM %s: external OFF latched (wallbox-controlled mode). entity=%s last_intent=%s age=%.1fs",
                                            self._log_name(), 
                                            self._charging_enable_entity, 
                                            last_intent, age_s
                                        )
                                    else:
                                        _LOGGER.warning(
                                            "EVCM %s: external OFF latched until cable disconnect. entity=%s last_intent=%s age=%.1fs",
                                            self._log_name(), 
                                            self._charging_enable_entity, 
                                            last_intent, age_s
                                        )

                                # Notify OFF (dedupe with cooldown)
                                if (now - float(self._ce_external_off_last_notify_ts or 0.0)) >= 30.0:
                                    self._ce_external_off_last_notify_ts = now

                                    # Suppress notification in wallbox-controlled phase switch mode
                                    if self._is_wallbox_controlled_phase_switch():
                                        _LOGGER.debug(
                                            "EVCM %s: External OFF notification suppressed (wallbox-controlled mode)",
                                            self._log_name()
                                        )
                                    else:
                                        msg = (
                                            f"External charging_enable OFF detected for {device_name}\n"
                                            f"Last external OFF: {dt_util.as_local(dt_util.utcnow()).strftime('%Y-%m-%d %H:%M:%S')}\n"
                                            f"Latched until cable disconnect: {'yes' if self._ce_external_off_latched else 'no'}\n"
                                            "To reset, unplug the EV.\n"
                                            "You can manually turn charging_enable ON but this is NOT ADVISED!\n"
                                            "If you did not manually turn charging_enable OFF, check your wallbox before turning back ON."
                                        )

                                        _LOGGER.warning("EVCM %s: %s", self._log_name(), msg.replace("\n", " | "))

                                        self._notify_persistent_fire_and_forget(
                                            "EVCM: External OFF detected",
                                            msg,
                                            self._external_off_notification_id(),
                                        )

        except Exception:
            _LOGGER.debug("EVCM: external OFF detection/latch failed", exc_info=True)

        # Start/Stop OFF: always enforce OFF and exit early
        if not self.get_mode(MODE_START_STOP):
            self._create_task(self._ce_write(False, reason="startstop_off", force=True))
            self._create_task(self._enforce_start_stop_policy())
            return

        # Unknown transitions: report and exit
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

        # If charging_enable turns ON while EVCM does NOT allow charging now (planner/soc/priority/data),
        # immediately enforce OFF (single-shot). This prevents late/stale ON feedback from keeping charging enabled.
        try:
            if str(new.state) == STATE_ON:
                allowed = (
                    self.get_mode(MODE_START_STOP)
                    and self._is_cable_connected()
                    and self._planner_window_allows_start()
                    and self._soc_allows_start()
                    and self._priority_allowed_cache
                    and self._essential_data_available()
                )
                if not allowed:
                    _LOGGER.warning(
                        "EVCM %s: charging_enable became ON while charging is not allowed -> enforcing OFF",
                        self._device_name_for_notify(),
                    )
                    self._cancel_ce_enable_retry()
                    self._create_task(self._ce_write(False, reason="disallowed_on_event", force=True))
        except Exception:
            _LOGGER.debug("Failed to enforce OFF on disallowed ON state", exc_info=True)

        # Normal path
        self._create_task(self._hysteresis_apply())
        self._evaluate_missing_and_start_no_data_timer()
        if self._is_charging_enabled() and not self.get_mode(MODE_MANUAL_AUTO) and self._is_cable_connected():
            self._start_regulation_loop_if_needed()
        self._create_task(self._auto_evaluate_and_maybe_switch())

    @callback
    def _async_net_power_event(self, event: Event):
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        ent = event.data.get("entity_id")
        self._create_task(self._refresh_priority_mode_flag())
        if not (self._is_known_state(old) and self._is_known_state(new)):
            if self._is_unknownish_state(new):
                self._report_unknown(ent, getattr(new, "state", None), "net_power_transition", side="new")
            elif self._is_unknownish_state(old):
                if self._should_report_unknown("net_power_transition", side="old"):
                    self._report_unknown(ent, getattr(old, "state", None), "net_power_transition", side="old")
            return
        if self.get_mode(MODE_START_STOP) and not self.get_mode(MODE_MANUAL_AUTO):
            self._create_task(self._hysteresis_apply())
        self._evaluate_missing_and_start_no_data_timer()
        self._create_task(self._auto_evaluate_and_maybe_switch())

    @callback
    def _async_wallbox_status_event(self, event: Event):
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        self._create_task(self._refresh_priority_mode_flag())

        if not self.get_mode(MODE_START_STOP):
            self._create_task(self._ensure_charging_enable_off())
            self._create_task(self._enforce_start_stop_policy())
            return

        if not (self._is_known_state(old) and self._is_known_state(new)):
            if self._is_unknownish_state(new):
                self._report_unknown(self._wallbox_status_entity, getattr(new, "state", None), "status_transition", side="new")
            elif self._is_unknownish_state(old):
                if self._should_report_unknown("status_transition", side="old"):
                    self._report_unknown(self._wallbox_status_entity, getattr(old, "state", None), "status_transition", side="old")
            return

        self._start_regulation_loop_if_needed()
        if self.get_mode(MODE_START_STOP):
            self._create_task(self._hysteresis_apply())
        self._evaluate_missing_and_start_no_data_timer()

    @callback
    def _async_charge_power_event(self, event: Event):
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        self._create_task(self._refresh_priority_mode_flag())

        if not self.get_mode(MODE_START_STOP):
            self._create_task(self._ensure_charging_enable_off())
            self._create_task(self._enforce_start_stop_policy())
            return

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

        self._start_regulation_loop_if_needed()
        if self.get_mode(MODE_START_STOP):
            self._create_task(self._hysteresis_apply())
        self._evaluate_missing_and_start_no_data_timer()
        self._create_task(self._auto_evaluate_and_maybe_switch())

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
                    self._create_task(_try_start_after_unlock())

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
            self._create_task(async_align_current_with_order(self.hass))
        self._create_task(self._hysteresis_apply())
        self._evaluate_missing_and_start_no_data_timer()

    # ---------------- Cable handling ----------------
    def _handle_cable_change(self, old_state, new_state):
        connected = (new_state.state if new_state else None) == STATE_ON
        if self._last_cable_connected is not None and connected == self._last_cable_connected:
            return
        self._last_cable_connected = connected
        if connected:
            self._create_task(self._on_cable_connected())
        else:
            self._create_task(self._on_cable_disconnected())

    async def _apply_cable_state_initial(self):
        if not self._cable_entity:
            return
        st = self.hass.states.get(self._cable_entity)
        if not self._is_known_state(st):
            if self._is_unknownish_state(st) and self._should_report_unknown("cable_initial", side="new"):
                self._report_unknown(self._cable_entity, getattr(st, "state", None), "cable_initial", side="new")
            return
        self._last_cable_connected = st.state == STATE_ON

        try:
            if self._last_cable_connected:
                self._charging_active = bool(self._charging_detected_now())
            else:
                self._charging_active = False
        except Exception:
            self._charging_active = False

        if self._last_cable_connected:
            self._create_task(self._on_cable_connected())
        else:
            self._create_task(self._on_cable_disconnected(initial=True))

    async def _on_cable_connected(self):
        self._reset_timers()
        self._pending_initial_start = True
        await self._ensure_lock_locked()

        # Ensure priority flags are fresh before making manual-start decisions
        try:
            await self._refresh_priority_mode_flag()
            self._priority_allowed_cache = await self._is_priority_allowed()
            if not self._priority_mode_enabled:
                for _ in range(PRIORITY_REFRESH_RETRIES):
                    await asyncio.sleep(PRIORITY_REFRESH_POLL_INTERVAL_S)
                    await self._refresh_priority_mode_flag()
                    self._priority_allowed_cache = await self._is_priority_allowed()
                    if self._priority_mode_enabled:
                        break
        except Exception:
            pass

        # Reflect whether the vehicle is actually charging at startup
        try:
            if self._last_cable_connected:
                self._charging_active = bool(self._charging_detected_now())
            else:
                self._charging_active = False
        except Exception:
            self._charging_active = False

        # If possible, set current to MIN on connect according to existing policy (non-blocking)
        if self._current_setting_entity:
            with contextlib.suppress(Exception):
                dom, _ = self._current_setting_entity.split(".", 1)
                if dom == "number":
                    should_set_min = (
                        not self.get_mode(MODE_START_STOP)
                        or self.get_mode(MODE_MANUAL_AUTO)
                        or not self._charging_detected_now()
                    )
                    if should_set_min:
                        try:
                            self._create_task(
                                self.hass.services.async_call(
                                    "number",
                                    "set_value",
                                    {"entity_id": self._current_setting_entity, "value": MIN_CURRENT_A},
                                )
                            )
                        except Exception:
                            pass

        # Priority preemption chain
        try:
            if self._priority_mode_enabled:
                preferred = await async_get_preferred_priority(self.hass)
                current = await async_get_priority(self.hass)
                if preferred == self.entry.entry_id and current not in (None, self.entry.entry_id):
                    await async_set_priority(self.hass, self.entry.entry_id)
                    self._priority_allowed_cache = await self._is_priority_allowed()
        except Exception:
            pass

        try:
            if self._priority_mode_enabled:
                order = await async_get_order(self.hass)
                if order and order[0] == self.entry.entry_id:
                    current = await async_get_priority(self.hass)
                    if current != self.entry.entry_id:
                        await async_set_priority(self.hass, self.entry.entry_id)
                        self._priority_allowed_cache = await self._is_priority_allowed()
        except Exception:
            pass

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
            pass

        if self._priority_mode_enabled:
            with contextlib.suppress(Exception):
                await async_align_current_with_order(self.hass)
                self._priority_allowed_cache = await self._is_priority_allowed()

        # Robust detection whether any other controller is currently charging (bounded poll)
        someone_charging_else = False

        async def _other_is_charging(other_data) -> bool:
            try:
                other_ctl = other_data.get("controller")
                other_flag = False
                try:
                    other_flag = bool(getattr(other_ctl, "_charging_active", False))
                except Exception:
                    other_flag = False

                ce = other_data.get("charging_enable_entity") or getattr(other_ctl, "_charging_enable_entity", None)
                status_e = other_data.get("wallbox_status_entity") or getattr(other_ctl, "_wallbox_status_entity", None)
                power_e = other_data.get("charge_power_entity") or getattr(other_ctl, "_charge_power_entity", None)

                if other_flag:
                    return True

                if ce:
                    st = self.hass.states.get(ce)
                    if st is not None and st.state == STATE_ON:
                        return True

                if status_e:
                    st = self.hass.states.get(status_e)
                    if st is not None and st.state and str(st.state).strip().lower() == str(WALLBOX_STATUS_CHARGING).strip().lower():
                        return True

                if power_e:
                    st = self.hass.states.get(power_e)
                    if st is not None:
                        try:
                            pw = float(st.state)
                            if pw > CHARGING_POWER_THRESHOLD_W:
                                return True
                        except Exception:
                            pass

            except Exception:
                pass
            return False

        try:
            for _ in range(OTHER_CHARGING_CHECK_RETRIES):
                controllers_data = (self.hass.data.get(DOMAIN, {}) or {}).copy()
                someone_charging_else = False
                for pid, data in controllers_data.items():
                    if pid == self.entry.entry_id:
                        continue
                    try:
                        if await _other_is_charging(data):
                            someone_charging_else = True
                            break
                    except Exception:
                        continue
                if someone_charging_else:
                    break
                await asyncio.sleep(OTHER_CHARGING_CHECK_INTERVAL_S)
        except Exception:
            someone_charging_else = False

        # Manual handling (strict: manual does NOT preempt an actual ongoing charge)
        if self.get_mode(MODE_MANUAL_AUTO):
            if self.get_mode(MODE_START_STOP):
                if someone_charging_else:
                    await self._ensure_charging_enable_off()
                    self._stop_resume_monitor()
                    self._stop_regulation_loop()
                    self._evaluate_missing_and_start_no_data_timer()
                    return

                if (self._priority_allowed_cache and self._essential_data_available()
                    and self._planner_window_allows_start() and self._soc_allows_start()):
                    if (not self._priority_mode_enabled) or (await self._have_priority_now()):
                        await self._start_charging_and_reclaim()
                    else:
                        await self._ensure_charging_enable_off()
                else:
                    await self._ensure_charging_enable_off()
            else:
                await self._ensure_charging_enable_off()
                self._charging_active = False
            self._stop_resume_monitor()
            self._stop_regulation_loop()
            self._evaluate_missing_and_start_no_data_timer()
            return

        # rest unchanged
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

        if self._is_startup_grace_active() and not self._charging_active:
            _LOGGER.debug("Startup grace active: deferring auto-start/hysteresis for new cable connect")
            # Ensure monitors exist so we'll resume checks later
            self._start_resume_monitor_if_needed()
            # Save missing-data / timer evaluation
            self._evaluate_missing_and_start_no_data_timer()
            return

        # Normal flow once grace is not active (or if we were already charging)
        self._start_auto_connect_routine()
        await self._hysteresis_apply()
        self._start_regulation_loop_if_needed()
        self._start_resume_monitor_if_needed()
        self._evaluate_missing_and_start_no_data_timer()

    async def _on_cable_disconnected(self, initial: bool = False):
        if self._ce_external_off_latched or self._ce_external_last_off_ts or self._ce_external_last_on_ts:
            _LOGGER.info(
                "EVCM %s: external OFF/ON state cleared (cable disconnected)",
                self._log_name()
            )

        self._ce_external_off_latched = False
        self._ce_on_blocked_logged = False
        self._ce_external_last_off_ts = None
        self._ce_external_last_on_ts = None
        self._create_task(self._persist_external_off_state())

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

        # Only apply Start/Stop Reset on a real runtime disconnect (not during initial apply/reconnect on startup)
        if not initial:
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
        self._reclaim_task = self._create_task(self._reclaim_monitor_loop())

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
        # Do not start auto-connect during startup grace for new starts
        if self._is_startup_grace_active():
            _LOGGER.debug("Auto-connect suppressed: startup grace active")
            return
        self._cancel_auto_connect_task()
        self._auto_connect_task = self._create_task(self._auto_connect_task_run())

    async def _auto_connect_task_run(self):
        try:
            # Defensive: if grace is active when this task actually runs, do not proceed
            if self._is_startup_grace_active():
                _LOGGER.debug("Auto-connect task aborted: startup grace still active")
                return
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
        self._planner_monitor_task = self._create_task(self._planner_monitor_loop())

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
                    if previous_allows is not False and not allows:
                        # Only act on transition into "not allowed" to avoid spamming pause every second
                        if self._charging_active or self._is_charging_enabled() or self._charging_detected_now():
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
                await asyncio.sleep(PLANNER_MONITOR_INTERVAL_S)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            _LOGGER.warning("Planner monitor error: %s", exc)

    # ---------------- Hysteresis logic ----------------
    def _use_alt_thresholds(self) -> bool:
        """ALT thresholds are for EU 1P. Use them only when:
        - Phase feedback is explicitly '1p' AND
        - There is no mismatch/fallback active (for integration-controlled)
        
        For wallbox-controlled: always follow feedback directly (no mismatch concept).
        For integration-controlled: fallback to 3p (primary/conservative) when uncertain.
        """
        if not self._phase_switch_supported():
            return False
        
        # Wallbox-controlled: always follow feedback directly
        if self._is_wallbox_controlled_phase_switch():
            return self._phase_feedback_value == "1p"
        
        # Unknown feedback -> conservative 3p
        if self._phase_feedback_value not in ("1p", "3p"):
            return False
        
        # Check for mismatch with expected phase
        expected = self._expected_phase_for_mismatch_check()
        if expected is not None and self._phase_feedback_value != expected:
            return False
        
        # Explicit fallback flag
        if self._phase_fallback_active:
            return False
        
        return self._phase_feedback_value == "1p"

    def _current_lower(self) -> float:
        if self._max_peak_override_active():
            return float(-self._ext_import_limit_w)

        if self._use_alt_thresholds():
            eff = _effective_config(self.entry)
            if self.get_mode(MODE_ECO):
                return float(eff.get(CONF_ECO_ON_LOWER_ALT, DEFAULT_ECO_ON_LOWER_ALT))
            return float(eff.get(CONF_ECO_OFF_LOWER_ALT, DEFAULT_ECO_OFF_LOWER_ALT))

        return self._eco_on_lower if self.get_mode(MODE_ECO) else self._eco_off_lower

    def _current_upper(self) -> float:
        if self._max_peak_override_active():
            return float(self._current_lower() + self._profile_min_band_w())

        if self._use_alt_thresholds():
            eff = _effective_config(self.entry)
            if self.get_mode(MODE_ECO):
                return float(eff.get(CONF_ECO_ON_UPPER_ALT, DEFAULT_ECO_ON_UPPER_ALT))
            return float(eff.get(CONF_ECO_OFF_UPPER_ALT, DEFAULT_ECO_OFF_UPPER_ALT))

        return self._eco_on_upper if self.get_mode(MODE_ECO) else self._eco_off_upper

    async def _hysteresis_apply(self, preserve_current: bool = False):
        # Skip hysteresis during initial startup grace to avoid blocking HA bootstrap
        if self._is_startup_grace_active():
            return

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

        # Treat "enabled" or "detected charging" as active too
        is_effectively_active = (
            self._charging_active
            or self._is_charging_enabled()
            or self._charging_detected_now()
        )

        manual_enabled = self._is_charging_enabled()
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
                if manual_enabled or self._charging_active:
                    _LOGGER.info("Manual pause: %s", "/".join(reasons))
                    await self._pause_basic(set_current_to_min=not preserve_current)
                    if self._priority_mode_enabled and (not planner_ok or not soc_ok):
                        await self._advance_if_current()
                else:
                    if self._priority_mode_enabled and (not planner_ok or not soc_ok):
                        await self._advance_if_current()
                return

            # allowed in manual
            if not manual_enabled:
                if self._priority_mode_enabled and not await self._have_priority_now():
                    self._start_resume_monitor_if_needed()
                    return
                if self._essential_data_available():
                    await self._start_charging_and_reclaim()
                else:
                    await self._ensure_charging_enable_off()
            return

        # Planner gating
        if not planner_ok:
            if is_effectively_active:
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

        # SoC gating
        if not soc_ok:
            if is_effectively_active:
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

        # Priority gating
        if not priority_ok:
            if is_effectively_active:
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

        self._below_lower_task = self._create_task(_runner())

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

        self._no_data_task = self._create_task(_runner())

    def _conditions_for_timers(self) -> bool:
        if self._is_startup_grace_active():
            return False
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
        self._auto_set_stop_reason_below_lower()
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
        self._auto_clear_stop_reason()
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
                self._create_task(async_handover_after_pause(self.hass, self.entry.entry_id))
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
        if self._is_startup_grace_active():
            return
        if self._regulation_task and not self._regulation_task.done():
            return
        if not self._should_regulate():
            return
        self._regulation_task = self._create_task(self._regulation_loop())

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
                # Phase-aware regulation:
                # - inc/dec thresholds: use effective profile (conservative 3p on mismatch/unknown)
                # - regMin: follows FEEDBACK (actual charging state) to know if wallbox is stable
                
                reg_profile_key = self._effective_reg_profile_key()
                thr = SUPPLY_PROFILE_REG_THRESHOLDS.get(reg_profile_key) or {}
                inc_export = float(thr.get("export_inc_w", 250))
                dec_import = float(thr.get("import_dec_w", 0))

                # regMin: use lowest value when fallback/mismatch to ensure regulation can work
                # Conservative inc/dec thresholds (3p) already prevent aggressive adjustments
                if self._phase_switch_supported():
                    if self._phase_fallback_active or self._phase_feedback_value not in ("1p", "3p"):
                        # Mismatch or unknown: use lowest regMin so regulation can work
                        reg_min = int(SUPPLY_PROFILES["eu_1ph_230"].get("regulation_min_w", 1300))
                    elif self._phase_feedback_value == "1p":
                        reg_min = int(SUPPLY_PROFILES["eu_1ph_230"].get("regulation_min_w", 1300))
                    else:
                        # feedback = 3p, no mismatch
                        reg_min = int(SUPPLY_PROFILES["eu_3ph_400"].get("regulation_min_w", 3900))
                else:
                    # No phase switching: use configured profile
                    reg_min = int((SUPPLY_PROFILES.get(self._supply_profile_key) or {}).get("regulation_min_w", self._effective_regulation_min_power()))
                    
                _LOGGER.debug(
                    "RegTick: net=%s target=%s currentA=%s status=%s enable=%s charge_power=%s soc=%s limit=%s active=%s missing=%s maxA=%s regMin=%s reg_profile=%s inc=%s dec=%s feedback=%s",
                    net, self._net_power_target_w, current_a_dbg, status,
                    self._is_charging_enabled(), charge_power, soc, self._soc_limit_percent,
                    self._charging_active, ",".join(missing) if missing else "-", conf_max_a,
                    reg_min, reg_profile_key, inc_export, dec_import, self._phase_feedback_value
                )

                # NIEUWE DEBUG LOG:
                _LOGGER.debug(
                    "RegTick ADJUST CHECK: net_ok=%s status_ok=%s (status=%s, expected=%s) current_entity=%s missing=%s soc_ok=%s charge_power=%s reg_min=%s power_ok=%s",
                    net is not None,
                    status == WALLBOX_STATUS_CHARGING,
                    status,
                    WALLBOX_STATUS_CHARGING,
                    bool(self._current_setting_entity),
                    missing,
                    self._soc_allows_start(),
                    charge_power,
                    reg_min,
                    charge_power is not None and charge_power >= reg_min if charge_power is not None else False
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

                if net is not None and status == WALLBOX_STATUS_CHARGING and self._current_setting_entity and not missing and self._soc_allows_start():
                    now = time.monotonic()
                    time_ok = now >= (first_adjust_ready_at or 0)
                    
                    if time_ok:
                        # regMin check only for increasing (stable charging confirmation)
                        # Decreasing is always allowed for safety (reduce load when importing)
                        power_ok_for_increase = charge_power is not None and charge_power >= reg_min
                        
                        deviation = net - self._net_power_target_w
                        export_w = deviation if deviation > 0 else 0.0
                        import_w = -deviation if deviation < 0 else 0.0
                        current_a = await self._get_current_setting_a()
                        
                        if current_a is not None:
                            new_a = current_a
                            
                            # Increase: requires stable charging (regMin check)
                            if export_w >= inc_export and current_a < conf_max_a and power_ok_for_increase:
                                new_a = min(conf_max_a, current_a + 1)
                            # Decrease: always allowed when importing (safety first)
                            elif import_w >= dec_import and current_a > MIN_CURRENT_A:
                                new_a = max(MIN_CURRENT_A, current_a - 1)
                            
                            if new_a != current_a:
                                _LOGGER.debug(
                                    "Adjust current: dev=%s export=%s import=%s inc_thr=%s dec_thr=%s power_ok_inc=%s %s→%sA",
                                    deviation, export_w, import_w, inc_export, dec_import, power_ok_for_increase, current_a, new_a
                                )
                                await self._set_current_setting_a(new_a)
                                
                # Keep auto phase switching evaluation alive while regulating
                self._create_task(self._auto_evaluate_and_maybe_switch())

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
        self._resume_task = self._create_task(self._resume_monitor_loop())

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

    # ---------------- Charging_enable retry ON ----------------
    def _cancel_ce_enable_retry(self) -> None:
        """Stop any pending enable retry loop."""
        was_active = bool(self._ce_enable_retry_active) or (self._ce_enable_retry_task is not None)
        self._ce_enable_retry_active = False
        self._ce_enable_retry_count = 0
        t = self._ce_enable_retry_task
        self._ce_enable_retry_task = None
        if t and not t.done():
            t.cancel()
        if was_active:
            _LOGGER.debug("EVCM %s: CE ON retry stopped: retry no longer desired", self._log_name())

    def _start_ce_enable_retry_if_needed(self) -> None:
        """Start retry loop if enabling was requested but state doesn't follow."""
        t = self._ce_enable_retry_task
        if t and not t.done():
            # If it's still around but retry is not active, cancel and replace it.
            if not self._ce_enable_retry_active:
                t.cancel()
            else:
                return
        self._ce_enable_retry_active = True
        self._ce_enable_retry_count = 0
        self._ce_enable_retry_task = self._create_task(self._ce_enable_retry_loop())

    async def _notify_ce_enable_no_effect(self) -> None:
        """Notify user that enabling charging had no effect."""
        try:
            device_name = self._device_name_for_notify()
            msg = (
                f"Charging enable seems to have no effect for {device_name}.\n\n"
                f"EVCM tried to turn charging_enable ON every {int(CE_ENABLE_RETRY_INTERVAL_S)}s "
                f"for {int(CE_ENABLE_MAX_RETRIES)} attempts, but the entity state did not become ON.\n\n"
                "Possible causes:\n"
                "- Wallbox offline/rebooting while HA entities remain sticky\n"
                "- Integration not updating charging_enable state\n"
                "- Command not reaching the wallbox\n\n"
                "EVCM will stop retrying for safety. You can trigger a new attempt by toggling cable "
                "or by re-enabling Start/Stop (or when conditions change)."
            )
            await self._notify_persistent(
                "EVCM: charging_enable has no effect",
                msg,
                f"evcm_ce_no_effect_{self.entry.entry_id}",
            )
        except Exception:
            _LOGGER.debug("Failed to create CE no-effect notification", exc_info=True)

    async def _ce_enable_retry_loop(self) -> None:
        """Retry enabling charging_enable if desired ON but state stays OFF."""
        try:
            while self._ce_enable_retry_active:
                await asyncio.sleep(float(CE_ENABLE_RETRY_INTERVAL_S))

                # Stop conditions
                if not self._ce_wants_enable_on_now():
                    self._cancel_ce_enable_retry()
                    return

                # Stop retry during below-lower only in AUTO mode (thresholds do not apply in manual).
                if not self.get_mode(MODE_MANUAL_AUTO):
                    try:
                        net = self._get_net_power_w()
                        lower = float(self._current_lower())
                    except Exception:
                        net = None
                        lower = None

                    if (
                        (net is not None and lower is not None and net < lower)
                        or (self._below_lower_since is not None)
                        or (self._auto_last_stop_reason == AUTO_STOP_REASON_BELOW_LOWER)
                    ):
                        _LOGGER.debug(
                            "CE ON retry stopped: below-lower active (auto mode) (net=%s lower=%s since=%s stop_reason=%s)",
                            net, lower, self._below_lower_since, self._auto_last_stop_reason
                        )
                        self._cancel_ce_enable_retry()
                        return

                # Auto mode: retry-enable only when the upper threshold is *sustained* (debounce passed).
                if not self.get_mode(MODE_MANUAL_AUTO):
                    net = self._get_net_power_w()
                    if net is None or not self._sustained_above_upper(net):
                        _LOGGER.debug(
                            "CE ON retry stopped: upper debounce not satisfied (auto mode) (net=%s upper=%s)",
                            net, self._current_upper() if net is not None else None
                        )
                        self._cancel_ce_enable_retry()
                        return

                # Soft veto: phase switching safety window (delay, don't cancel)
                if time.monotonic() < float(self._ce_phase_veto_until_ts or 0.0):
                    _LOGGER.debug("CE ON retry delayed: phase switching veto active")
                    continue

                # Success check
                st = self.hass.states.get(self._charging_enable_entity) if self._charging_enable_entity else None
                if st and self._is_known_state(st) and st.state == STATE_ON:
                    _LOGGER.debug("CE ON retry done: state is ON")
                    self._cancel_ce_enable_retry()
                    return

                # Retry budget
                self._ce_enable_retry_count += 1
                if self._ce_enable_retry_count > int(CE_ENABLE_MAX_RETRIES):
                    _LOGGER.warning(
                        "EVCM %s: CE ON retries exhausted (%s attempts) entity=%s",
                        self._log_name(),
                        CE_ENABLE_MAX_RETRIES,
                        self._charging_enable_entity,
                    )
                    await self._notify_ce_enable_no_effect()
                    self._cancel_ce_enable_retry()
                    return

                _LOGGER.warning(
                    "EVCM %s: CE ON retry attempt %s/%s: charging_enable still OFF -> re-sending ON (entity=%s)",
                    self._log_name(),
                    self._ce_enable_retry_count,
                    CE_ENABLE_MAX_RETRIES,
                    self._charging_enable_entity,
                )

                # Force a re-send even if internal dedup thinks it was already requested.
                await self._ce_write(True, reason="retry_enable_no_effect", force=True)

        except asyncio.CancelledError:
            return
        except Exception:
            _LOGGER.debug("CE ON retry loop failed", exc_info=True)
        finally:
            self._ce_enable_retry_task = None

    def _ce_wants_enable_on_now(self) -> bool:
        return (
            self.get_mode(MODE_START_STOP)
            and self._is_cable_connected()
            and self._planner_window_allows_start()
            and self._soc_allows_start()
            and self._priority_allowed_cache
            and self._essential_data_available()
            and (not self._ce_external_off_latched)
        )

    # ---------------- charging_enable retry OFF (Start/Stop OFF only) ----------------
    def _cancel_ce_disable_retry(self) -> None:
        """Stop any pending disable retry loop."""
        self._ce_disable_retry_active = False
        self._ce_disable_retry_count = 0
        t = self._ce_disable_retry_task
        self._ce_disable_retry_task = None
        if t and not t.done():
            t.cancel()

    def _ce_wants_disable_off_now(self) -> bool:
        """
        True if charging_enable should be OFF right now.
        - Always when Start/Stop is OFF (with cable connected).
        - Also when Start/Stop is ON but charging is not allowed (planner window, SoC limit,
        priority disallowed, missing data).
        - In auto mode: only after below-lower pause has actually triggered (not during sustain timer).
        """
        if not self._charging_enable_entity or not self._is_cable_connected():
            return False

        # Start/Stop OFF: always enforce OFF
        if not self.get_mode(MODE_START_STOP):
            return True

        # Planner / SoC / priority / missing data block charging
        if not self._planner_window_allows_start():
            return True
        if not self._soc_allows_start():
            return True
        if not self._priority_allowed_cache:
            return True
        if not self._essential_data_available():
            return True

        # Auto mode: below-lower pause (only after sustain timer has actually paused charging)
        if not self.get_mode(MODE_MANUAL_AUTO):
            # Only consider below-lower as "OFF desired" if:
            # 1. We actually stopped due to below-lower (stop reason is set), AND
            # 2. Charging is no longer active (pause has been executed), AND
            # 3. Net power hasn't recovered above upper yet
            if self._auto_last_stop_reason == AUTO_STOP_REASON_BELOW_LOWER and not self._charging_active:
                net = self._get_net_power_w()
                try:
                    upper = self._current_upper()
                except Exception:
                    upper = None

                if net is not None and upper is not None and net < upper:
                    return True

        return False

    def _start_ce_disable_retry_if_needed(self) -> None:
        """Start retry loop when charging_enable should be OFF but isn't."""
        if not self._ce_wants_disable_off_now():
            return

        t = self._ce_disable_retry_task
        if t and not t.done():
            if not self._ce_disable_retry_active:
                t.cancel()
            else:
                return

        self._ce_disable_retry_active = True
        self._ce_disable_retry_count = 0
        self._ce_disable_retry_task = self._create_task(self._ce_disable_retry_loop())

    async def _notify_ce_disable_no_effect(self) -> None:
        """Notify user that disabling charging had no effect."""
        try:
            device_name = self._device_name_for_notify()
            msg = (
                f"Charging disable seems to have no effect for {device_name}.\n\n"
                f"EVCM tried to turn charging_enable OFF every {int(CE_DISABLE_RETRY_INTERVAL_S)}s "
                f"for {int(CE_DISABLE_MAX_RETRIES)} attempts, but the entity state did not become OFF.\n\n"
                "Possible causes:\n"
                "- Wallbox/integration not updating charging_enable state\n"
                "- Command not reaching the wallbox\n"
                "- Wallbox refusing the OFF command\n\n"
                "EVCM will stop retrying. Start/Stop is still OFF, so EVCM will not attempt to charge."
            )
            await self._notify_persistent(
                "EVCM: charging_enable OFF has no effect",
                msg,
                f"evcm_ce_off_no_effect_{self.entry.entry_id}",
            )
        except Exception:
            _LOGGER.debug("Failed to create CE OFF no-effect notification", exc_info=True)

    async def _ce_disable_retry_loop(self) -> None:
        """Retry disabling charging_enable if desired OFF but state stays ON."""
        try:
            while self._ce_disable_retry_active:
                await asyncio.sleep(float(CE_DISABLE_RETRY_INTERVAL_S))

                # Stop conditions: only enforce OFF while Start/Stop is OFF and cable is connected
                if not self._ce_wants_disable_off_now():
                    _LOGGER.debug("CE OFF retry stopped: retry no longer desired")
                    self._cancel_ce_disable_retry()
                    return

                # Success check
                st = self.hass.states.get(self._charging_enable_entity) if self._charging_enable_entity else None
                if st and self._is_known_state(st) and st.state == STATE_OFF:
                    _LOGGER.debug("CE OFF retry done: state is OFF")
                    self._cancel_ce_disable_retry()
                    return

                # Retry budget
                self._ce_disable_retry_count += 1
                if self._ce_disable_retry_count > int(CE_DISABLE_MAX_RETRIES):
                    _LOGGER.warning(
                        "EVCM %s: CE OFF retries exhausted (%s attempts) entity=%s",
                        self._log_name(),
                        CE_DISABLE_MAX_RETRIES, 
                        self._charging_enable_entity
                    )
                    await self._notify_ce_disable_no_effect()
                    self._cancel_ce_disable_retry()
                    return

                _LOGGER.warning(
                    "EVCM %s: CE OFF retry attempt %s/%s: charging_enable still not OFF -> re-sending OFF. (entity=%s)",
                    self._log_name(),
                    self._ce_disable_retry_count, 
                    CE_DISABLE_MAX_RETRIES,
                    self._charging_enable_entity
                )

                # Force a re-send even if internal dedup thinks it was already requested.
                await self._ce_write(False, reason="retry_disable_no_effect", force=True)

        except asyncio.CancelledError:
            return
        except Exception:
            _LOGGER.debug("CE OFF retry loop failed", exc_info=True)
        finally:
            self._ce_disable_retry_task = None

    async def _ce_write(self, desired_on: bool, *, reason: str = "", force: bool = False) -> None:
        """
        Single-writer for charging_enable:
        - serializes turn_on/turn_off to avoid concurrent flapping
        - deduplicates repeated requests
        - hard veto: never turn ON if Start/Stop is OFF
        """
        if not self._charging_enable_entity:
            return

        # If we are explicitly turning OFF, stop any pending enable retry.
        if not desired_on:
            self._cancel_ce_enable_retry()

        async with self._ce_lock:
            # PoC: remember our last intent (even if later dedup/veto prevents a call)
            self._ce_last_intent_desired = bool(desired_on)
            self._ce_last_intent_ts = time.monotonic()

            # Hard veto: if Start/Stop is OFF, never send ON
            if desired_on and not self.get_mode(MODE_START_STOP):
                _LOGGER.debug("CE veto ON (start_stop off) reason=%s", reason)
                return

            # Extra veto: if wallbox externally disabled, do not try to re-enable until unplug
            if desired_on and self._ce_external_off_latched:
                _LOGGER.debug("CE veto ON (external OFF latch active) reason=%s", reason)
                return

            # Extra veto: if wallbox phase switching active, do not try to re-enable charging
            if desired_on and time.monotonic() < float(self._ce_phase_veto_until_ts or 0.0):
                _LOGGER.debug("CE veto ON (phase switching safety window) reason=%s", reason)
                return

            dom, _ = self._charging_enable_entity.split(".", 1)
            if dom != "switch":
                return

            now = time.monotonic()

            # Min toggle interval dampener (apply for ON and OFF)
            if (now - self._ce_last_write_ts) < CE_MIN_TOGGLE_INTERVAL_S:
                try:
                    st = self.hass.states.get(self._charging_enable_entity)
                    if self._is_known_state(st):
                        if desired_on and st.state == STATE_ON:
                            _LOGGER.debug("CE suppress ON (min interval) reason=%s", reason)
                            return
                        if (not desired_on) and st.state == STATE_OFF:
                            _LOGGER.debug("CE suppress OFF (min interval) reason=%s", reason)
                            return

                    # If state is unknown or mismatched, be conservative:
                    # still suppress repeated writes within the interval to avoid spam.
                    _LOGGER.debug(
                        "CE suppress %s (min interval; state unknown/mismatch) reason=%s",
                        "ON" if desired_on else "OFF",
                        reason,
                    )
                    return
                except Exception:
                    # If we cannot read state for any reason, be conservative and suppress
                    _LOGGER.debug("CE dampener: failed to read state, suppressing write", exc_info=True)
                    return

            # Internal dedup (prevents spam). Allow forced writes (retry loop).
            if (not force) and (self._ce_last_desired is not None) and (self._ce_last_desired == desired_on):
                st_cur = self.hass.states.get(self._charging_enable_entity)
                if self._is_known_state(st_cur):
                    if desired_on and st_cur.state == STATE_ON:
                        return
                    if (not desired_on) and st_cur.state == STATE_OFF:
                        return
                # state mismatched/unknown -> allow a new write

            # State-based dedup (prevents unnecessary service calls)
            st = self.hass.states.get(self._charging_enable_entity)
            if self._is_known_state(st):
                if desired_on and st.state == STATE_ON:
                    self._ce_last_desired = True
                    self._ce_last_write_ts = now
                    return
                if (not desired_on) and st.state == STATE_OFF:
                    self._ce_last_desired = False
                    self._ce_last_write_ts = now
                    return
            else:
                self._report_unknown(self._charging_enable_entity, getattr(st, "state", None), "charging_enable_ce_write_get")

            svc = "turn_on" if desired_on else "turn_off"
            _LOGGER.debug(
                "CE write: sending %s to %s (reason=%s force=%s)",
                "ON" if desired_on else "OFF",
                self._charging_enable_entity,
                reason or "-",
                bool(force),
            )

            call_succeeded = False
            try:
                await self.hass.services.async_call("switch", svc, {"entity_id": self._charging_enable_entity}, blocking=True)
                call_succeeded = True

                # Mark intended result after successful call
                self._ce_last_desired = desired_on
                self._ce_last_write_ts = time.monotonic()

                if desired_on:
                    st_after = self.hass.states.get(self._charging_enable_entity)

                    if (
                        self._ce_wants_enable_on_now()
                        and not (st_after and self._is_known_state(st_after) and st_after.state == STATE_ON)
                    ):
                        self._start_ce_enable_retry_if_needed()
                    else:
                        # Either state already ON, or enable is no longer desired -> don't keep retrying.
                        self._cancel_ce_enable_retry()

            except Exception:
                _LOGGER.warning(
                    "CE write failed: %s to %s (reason=%s)",
                    "ON" if desired_on else "OFF",
                    self._charging_enable_entity,
                    reason or "-",
                    exc_info=True,
                )

            if call_succeeded and not desired_on:
                self._cancel_relock_task()

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
            st = self.hass.states.get(self._charging_enable_entity)
            if self._is_known_state(st) and st.state == STATE_OFF:
                self._cancel_ce_disable_retry()
                return
            if not self._is_known_state(st):
                self._report_unknown(self._charging_enable_entity, getattr(st, "state", None), "enable_ensure_off")
            await self._ce_write(False, reason="ensure_off")
        self._cancel_relock_task()
        self._start_ce_disable_retry_if_needed()

    async def _ensure_charging_enable_on(self):
        if not self._charging_enable_entity or not self.get_mode(MODE_START_STOP):
            return

        if self._ce_external_off_latched:
            if not self._ce_on_blocked_logged:
                self._ce_on_blocked_logged = True
                if self._is_wallbox_controlled_phase_switch():
                    _LOGGER.debug(
                        "EVCM %s: charging_enable ON blocked (external OFF latch active, wallbox-controlled mode) entity=%s",
                        self._log_name(), 
                        self._charging_enable_entity
                    )
                else:
                    _LOGGER.warning(
                        "EVCM %s: charging_enable ON blocked (external OFF latch active) entity=%s",
                        self._log_name(), 
                        self._charging_enable_entity
                    )
            else:
                _LOGGER.debug(
                    "EVCM %s: charging_enable ON blocked (external OFF latch active) reason=dedup entity=%s",
                    self._log_name(), 
                    self._charging_enable_entity
                )
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
                        _LOGGER.debug("Initial start: Auto unlock is OFF -> no unlock attempt")
                        return
                    if (self._essential_data_available() and self._planner_window_allows_start()
                            and self._soc_allows_start() and self._priority_allowed_cache):
                        ok = await self._ensure_unlocked_for_start()
                        if not ok:
                            _LOGGER.info("Initial start: unlock failed, aborting enable ON")
                            return
                        did_unlock = True
                        self._pending_initial_start = False
                    else:
                        return
                else:
                    if not (self._is_known_state(st) and st.state == STATE_ON):
                        await self._ce_write(True, reason="ensure_on_resume_pre_unlock")
                    self._pending_initial_start = False

                    if await self._wait_for_charging_detection(timeout_s=5.0):
                        return
                    if not self._auto_unlock_enabled:
                        _LOGGER.debug("Resume: Auto unlock is OFF -> no unlock fallback")
                        return
                    ok = await self._ensure_unlocked_for_start()
                    if not ok:
                        _LOGGER.info("Resume fallback unlock failed; start aborted")
                        return
                    did_unlock = True

            st = self.hass.states.get(self._charging_enable_entity)
            if not (self._is_known_state(st) and st.state == STATE_ON):
                await self._ce_write(True, reason="ensure_on_final")
            self._pending_initial_start = False
            self._auto_clear_stop_reason()

            if did_unlock:
                # before: self._schedule_relock_after_charging_start()
                # now: relock disabled
                self._cancel_relock_task()

    async def _enforce_start_stop_policy(self):
        """Apply start/stop policy. Skip during startup grace to avoid blocking HA startup."""
        if self._is_startup_grace_active():
            def _reschedule():
                try:
                    self._create_task(self._enforce_start_stop_policy())
                except Exception:
                    _LOGGER.debug("Failed to reschedule _enforce_start_stop_policy", exc_info=True)
            try:
                remaining = max(1.0, min(5.0, UNKNOWN_STARTUP_GRACE_SECONDS))
                self.hass.loop.call_later(remaining, _reschedule)
            except Exception:
                _reschedule()
            return

        try:
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
                return
        except Exception:
            with contextlib.suppress(Exception):
                await self._ensure_charging_enable_off()
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
            return

    # ---------------- Mode management ----------------
    def get_mode(self, mode: str) -> bool:
        return bool(self._modes.get(mode, False))

    def set_mode(self, mode: str, enabled: bool):
        previous = self._modes.get(mode)
        self._modes[mode] = bool(enabled)
        try:
            if mode == MODE_START_STOP:
                if previous != enabled:
                    self._create_task(self._save_unified_state_debounced())
                    _LOGGER.debug("Start/Stop toggle -> %s", enabled)
                    if self._current_setting_entity:
                        self._create_task(self._set_current_setting_a(MIN_CURRENT_A))
                if not enabled and previous:
                    # User turned Start/Stop OFF -> enforce charging_enable OFF.
                    self._ce_last_desired = None

                    # Clear external OFF latch + dismiss related notifications
                    try:
                        if self._ce_external_off_latched or self._ce_external_last_off_ts or self._ce_external_last_on_ts:
                            _LOGGER.debug("Clearing external OFF/ON state due to Start/Stop OFF (user action)")
                        self._ce_external_off_latched = False
                        self._ce_on_blocked_logged = False
                        self._ce_external_last_off_ts = None
                        self._ce_external_last_on_ts = None
                        self._create_task(self._persist_external_off_state())
                    except Exception:
                        _LOGGER.debug("Failed to clear external OFF state on Start/Stop OFF", exc_info=True)

                    # Dismiss old notifications (best effort)
                    self._create_task(self._dismiss_external_off_notification())
                    self._create_task(self._dismiss_external_on_notification())

                    # Enforce OFF (retry is now handled inside _ensure_charging_enable_off)
                    self._create_task(self._ensure_charging_enable_off())
                    self._create_task(self._enforce_start_stop_policy())

                    async def _verify_enable_off_later():
                        try:
                            await asyncio.sleep(CE_VERIFY_DELAY_S)
                            st = self.hass.states.get(self._charging_enable_entity)
                            if (not self.get_mode(MODE_START_STOP)) and (not self._is_known_state(st) or st.state != STATE_OFF):
                                await self._ensure_charging_enable_off()
                        except Exception:
                            pass
                    self._create_task(_verify_enable_off_later())

                    self._create_task(self._advance_if_current())
                    return
                    
                if enabled and previous is False:
                    # Clean up stale external notifications (best effort)
                    self._create_task(self._dismiss_external_off_notification())
                    self._create_task(self._dismiss_external_on_notification())
                    self._cancel_ce_disable_retry()
                    async def _after_enable_startstop_on():
                        if self._priority_mode_enabled:
                            await async_align_current_with_order(self.hass)

                        # Manual mode: Start/Stop ON should immediately (re)apply manual behavior
                        if self.get_mode(MODE_MANUAL_AUTO):
                            if (
                                self._is_cable_connected()
                                and self._priority_allowed_cache
                                and self._planner_window_allows_start()
                                and self._soc_allows_start()
                                and self._essential_data_available()
                            ):
                                if (not self._priority_mode_enabled) or (await self._have_priority_now()):
                                    await self._start_charging_and_reclaim()
                                else:
                                    await self._ensure_charging_enable_off()
                            else:
                                await self._ensure_charging_enable_off()

                            # In manual we don't want regulation/resume monitors
                            self._stop_regulation_loop()
                            self._stop_resume_monitor()
                            self._evaluate_missing_and_start_no_data_timer()
                            return

                        # Non-manual: existing behavior
                        await self._hysteresis_apply()
                        self._start_regulation_loop_if_needed()
                        self._start_resume_monitor_if_needed()

                    self._create_task(_after_enable_startstop_on())
                    return

            if mode == MODE_ECO:
                if previous != enabled and not self.get_mode(MODE_MANUAL_AUTO):
                    self._create_task(self._hysteresis_apply(preserve_current=True))
                if previous != enabled:
                    self._create_task(self._save_unified_state_debounced())
                    _LOGGER.debug("ECO toggle -> %s", enabled)
                return

            if mode == MODE_MANUAL_AUTO:
                if previous != enabled:
                    self._create_task(self._save_unified_state_debounced())
                    _LOGGER.debug("Manual toggle -> %s", enabled)
                    if self._current_setting_entity:
                        self._create_task(self._set_current_setting_a(MIN_CURRENT_A))
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
                    self._create_task(_enter_manual())
                else:
                    async def _after_manual_off():
                        await self._hysteresis_apply()
                        self._start_regulation_loop_if_needed()
                        self._start_resume_monitor_if_needed()
                    self._create_task(_after_manual_off())
                return

            if mode == MODE_CHARGE_PLANNER:
                if previous != enabled:
                    self._create_task(self._save_unified_state_debounced())
                    _LOGGER.debug("Planner toggle -> %s", enabled)
                if enabled:
                    self._start_planner_monitor_if_needed()
                else:
                    self._stop_planner_monitor()
                    if self._priority_mode_enabled:
                        self._create_task(async_align_current_with_order(self.hass))
                if self._roll_planner_dates_to_today_if_past():
                    self._persist_planner_dates_notify_threadsafe()
                self._create_task(self._hysteresis_apply())
                return

            if mode == MODE_STARTSTOP_RESET:
                if previous != enabled:
                    self._create_task(self._save_unified_state_debounced())
                    _LOGGER.debug("Start/Stop Reset toggle -> %s", enabled)
                return
        finally:
            self._notify_mode_listeners()

    # ---------------- Public helpers ----------------
    def get_min_charge_power_w(self) -> int:
        return self._effective_min_charge_power()

# EOF
