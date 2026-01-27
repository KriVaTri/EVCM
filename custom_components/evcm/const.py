from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "evcm"

PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.DATETIME,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SELECT,
]

# Legacy option keys
CONF_OPT_MODE_ECO = "mode_eco"

CONF_NAME = "name"

# Grid configuration
CONF_GRID_SINGLE = "grid_single"
CONF_GRID_POWER = "grid_power"
CONF_GRID_IMPORT = "grid_import"
CONF_GRID_EXPORT = "grid_export"

# Entities
CONF_CHARGE_POWER = "charge_power_sensor"
CONF_WALLBOX_STATUS = "wallbox_status_sensor"
CONF_CABLE_CONNECTED = "cable_connected_sensor"
CONF_CHARGING_ENABLE = "charging_enable_entity"
CONF_LOCK_SENSOR = "lock_sensor"
CONF_CURRENT_SETTING = "current_setting_entity"

# Optional EV SoC sensor
CONF_EV_BATTERY_LEVEL = "ev_battery_level_sensor"

CONF_DEVICE_ID = "device_id"

# Interval
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 15

CONF_SUPPLY_PROFILE = "supply_profile"

CONF_WALLBOX_THREE_PHASE = "wallbox_three_phase"
DEFAULT_WALLBOX_THREE_PHASE = False

SUPPLY_PROFILES = {
    "eu_1ph_230": {
        "label": "1-phase 230V/240V",
        "phases": 1,
        "phase_voltage_v": 230,
        "min_power_6a_w": int(220 * 6),
        "regulation_min_w": 1300,
    },
    "eu_3ph_400": {
        "label": "3-phase 400V",
        "phases": 3,
        "phase_voltage_v": 230,
        "min_power_6a_w": int(220 * 6 * 3),
        "regulation_min_w": 3900,
    },
    "na_3ph_208": {
        "label": "3-phase 208V",
        "phases": 3,
        "phase_voltage_v": 120,
        "min_power_6a_w": int(120 * 6 * 3),
        "regulation_min_w": 2000,
    },
    "jp_1ph_200": {
        "label": "1-phase 200V",
        "phases": 1,
        "phase_voltage_v": 200,
        "min_power_6a_w": int(200 * 6),
        "regulation_min_w": 1100,
    },
    "na_1ph_120": {
        "label": "1-phase 120V (Level 1)",
        "phases": 1,
        "phase_voltage_v": 120,
        "min_power_6a_w": int(120 * 6),
        "regulation_min_w": 650,
    },
}

SUPPLY_PROFILE_REG_THRESHOLDS = {
    "eu_1ph_230": {"export_inc_w": 240, "import_dec_w": 70},
    "jp_1ph_200": {"export_inc_w": 205, "import_dec_w": 60},
    "na_1ph_120": {"export_inc_w": 122, "import_dec_w": 35},
    "na_3ph_208": {"export_inc_w": 370, "import_dec_w": 105},
    "eu_3ph_400": {"export_inc_w": 700, "import_dec_w": 200},
}

# Modes
MODE_ECO = "eco"
MODE_START_STOP = "start_stop"
MODE_MANUAL_AUTO = "manual"
MODE_CHARGE_PLANNER = "planner"
MODE_STARTSTOP_RESET = "startstop_reset"

MODES = [MODE_ECO, MODE_START_STOP, MODE_MANUAL_AUTO, MODE_CHARGE_PLANNER, MODE_STARTSTOP_RESET]
MODE_LABELS = {
    MODE_ECO: "ECO",
    MODE_START_STOP: "Start/Stop",
    MODE_MANUAL_AUTO: "Manual",
    MODE_CHARGE_PLANNER: "Planner",
    MODE_STARTSTOP_RESET: "Start/Stop Reset",
}

# Wallbox status values
WALLBOX_STATUS_READY = "Ready"
WALLBOX_STATUS_CHARGING = "Charging"
WALLBOX_STATUS_PAUSED = "Paused"
WALLBOX_STATUS_LOCKED = "Locked"

# Thresholds
CONF_ECO_ON_UPPER = "eco_on_upper_w"
CONF_ECO_ON_LOWER = "eco_on_lower_w"
CONF_ECO_OFF_UPPER = "eco_off_upper_w"
CONF_ECO_OFF_LOWER = "eco_off_lower_w"

DEFAULT_ECO_ON_UPPER = 4000
DEFAULT_ECO_ON_LOWER = -2000
DEFAULT_ECO_OFF_UPPER = -2000
DEFAULT_ECO_OFF_LOWER = -7000

# Alternate (EU 1-phase) thresholds for phase switching
CONF_ECO_ON_UPPER_ALT = "eco_on_upper_alt_w"
CONF_ECO_ON_LOWER_ALT = "eco_on_lower_alt_w"
CONF_ECO_OFF_UPPER_ALT = "eco_off_upper_alt_w"
CONF_ECO_OFF_LOWER_ALT = "eco_off_lower_alt_w"

DEFAULT_ECO_ON_UPPER_ALT = 1700
DEFAULT_ECO_ON_LOWER_ALT = -1000
DEFAULT_ECO_OFF_UPPER_ALT = -1000
DEFAULT_ECO_OFF_LOWER_ALT = -3500

MIN_THRESHOLD_VALUE = -25000
MAX_THRESHOLD_VALUE = 25000

# Historical minimums
MIN_CHARGE_POWER_SINGLE_PHASE_W = 1400
MIN_CHARGE_POWER_THREE_PHASE_W = 4200

# Sustain timers
CONF_SUSTAIN_SECONDS = "sustain_seconds"
DEFAULT_SUSTAIN_SECONDS = 120
SUSTAIN_MIN_SECONDS = 30
SUSTAIN_MAX_SECONDS = 3600

# Planner entity display names
PLANNER_START_ENTITY_NAME = "planner start"
PLANNER_STOP_ENTITY_NAME = "planner stop"

# Persist keys
CONF_PLANNER_START_ISO = "planner_start_iso"
CONF_PLANNER_STOP_ISO = "planner_stop_iso"
CONF_SOC_LIMIT_PERCENT = "soc_limit_percent"

DEFAULT_SOC_LIMIT_PERCENT = 80

# Wallbox current limit
CONF_MAX_CURRENT_LIMIT_A = "max_current_limit_a"
ABS_MIN_CURRENT_A = 6
ABS_MAX_CURRENT_A = 32

# Net power target
CONF_NET_POWER_TARGET_W = "net_power_target_w"
DEFAULT_NET_POWER_TARGET_W = 0
NET_POWER_TARGET_MIN_W = -10000
NET_POWER_TARGET_MAX_W = 10000
NET_POWER_TARGET_STEP_W = 100

# Profile-specific band minimum constants
MIN_BAND_230 = 1700
MIN_BAND_400 = 4500
MIN_BAND_208 = 2600
MIN_BAND_200 = 1500
MIN_BAND_120 = 1000

SUPPLY_PROFILE_MIN_BAND = {
    "eu_1ph_230": MIN_BAND_230,
    "eu_3ph_400": MIN_BAND_400,
    "na_3ph_208": MIN_BAND_208,
    "jp_1ph_200": MIN_BAND_200,
    "na_1ph_120": MIN_BAND_120,
}

PLANNER_DATETIME_UPDATED_EVENT = "evcm_planner_datetime_updated"

# charging_enable retry (when command has no effect / sticky state)
CE_ENABLE_RETRY_INTERVAL_S = 60
CE_ENABLE_MAX_RETRIES = 10
CE_DISABLE_RETRY_INTERVAL_S = 30
CE_DISABLE_MAX_RETRIES = 10

# External import limit (Max peak avg)
CONF_EXT_IMPORT_LIMIT_W = "ext_import_limit_w"
EXT_IMPORT_LIMIT_MIN_W = 0
EXT_IMPORT_LIMIT_MAX_W = 25000
EXT_IMPORT_LIMIT_STEP_W = 100

# External charging_enable OFF
OPT_EXTERNAL_OFF_LATCHED = "external_off_latched"
OPT_EXTERNAL_LAST_OFF_TS = "external_last_off_ts"
OPT_EXTERNAL_LAST_ON_TS = "external_last_on_ts"

# Phase switching (EU-only v1)
CONF_PHASE_SWITCH_SUPPORTED = "phase_switch_supported"
CONF_PHASE_MODE_FEEDBACK_SENSOR = "phase_mode_feedback_sensor"

# Persisted runtime state keys (unified store)
CONF_PHASE_SWITCH_AUTO_ENABLED = "phase_switch_auto_enabled"
CONF_PHASE_SWITCH_ACTIVE_PROFILE = "phase_switch_active_profile"  # reserved (future)
CONF_PHASE_SWITCH_FORCED_PROFILE = "phase_switch_forced_profile"  # "primary" or "alternate"

PHASE_PROFILE_PRIMARY = "primary"      # EU: 3P 400V
PHASE_PROFILE_ALTERNATE = "alternate"  # EU: 1P 230V

# Event-driven phase switch request
PHASE_SWITCH_REQUEST_EVENT = "evcm_phase_switch_request"
PHASE_SWITCH_SOURCE_FORCE = "force"
PHASE_SWITCH_SOURCE_AUTO = "auto"

# Timings
PHASE_SWITCH_CE_VETO_SECONDS_DEFAULT = 10
PHASE_SWITCH_WAIT_FOR_STOP_SECONDS_DEFAULT = 60
PHASE_SWITCH_STOPPED_POWER_W_DEFAULT = 50

# UI/status: if no valid feedback after this during a request -> Unknown + notify
PHASE_SWITCH_REQUEST_FEEDBACK_TIMEOUT_S = 300

# Phase switching UI mode select (for select.py)
PHASE_SWITCH_MODE_AUTO = "Auto"
PHASE_SWITCH_MODE_FORCE_1P = "Force 1p"
PHASE_SWITCH_MODE_FORCE_3P = "Force 3p"

PHASE_SWITCH_MODE_OPTIONS = [
    PHASE_SWITCH_MODE_AUTO,
    PHASE_SWITCH_MODE_FORCE_1P,
    PHASE_SWITCH_MODE_FORCE_3P,
]

# Phase switching request throttling (no-queue)
PHASE_SWITCH_COOLDOWN_SECONDS = 300

# Persisted keys in unified store
OPT_PHASE_SWITCH_COOLDOWN_UNTIL_ISO = "phase_switch_cooldown_until_iso"
OPT_PHASE_SWITCH_COOLDOWN_TARGET = "phase_switch_cooldown_target"

# Auto phase switching (v1: stopped-based)
CONF_AUTO_PHASE_SWITCH_DELAY_MIN = "auto_phase_switch_delay_min"
AUTO_PHASE_SWITCH_DELAY_MIN_MIN = 15
AUTO_PHASE_SWITCH_DELAY_MIN_MAX = 60
DEFAULT_AUTO_PHASE_SWITCH_DELAY_MIN = 15

# Phase switching control mode
CONF_PHASE_SWITCH_CONTROL_MODE = "phase_switch_control_mode"
PHASE_CONTROL_INTEGRATION = "integration"
PHASE_CONTROL_WALLBOX = "wallbox"
DEFAULT_PHASE_SWITCH_CONTROL_MODE = PHASE_CONTROL_INTEGRATION

# Controller timing constants
CONNECT_DEBOUNCE_SECONDS = 1
EXPORT_SUSTAIN_SECONDS = 5
PLANNER_MONITOR_INTERVAL_S = 1.0
RELOCK_AFTER_CHARGING_SECONDS = 5

# Current limits
MIN_CURRENT_A = 6

# Unknown state handling
UNKNOWN_DEBOUNCE_SECONDS = 30.0
UNKNOWN_STARTUP_GRACE_SECONDS = 15.0

# Upper debounce defaults
DEFAULT_UPPER_DEBOUNCE_SECONDS = 3
UPPER_DEBOUNCE_MIN_SECONDS = 0
UPPER_DEBOUNCE_MAX_SECONDS = 60

# charging_enable toggle timing
CE_MIN_TOGGLE_INTERVAL_S = 0.5

# Auto phase switching timing
AUTO_RESET_DEBOUNCE_SECONDS = 180.0
AUTO_1P_TO_3P_MARGIN_W = 1000

# Charging detection thresholds
CHARGING_POWER_THRESHOLD_W = 100
CHARGING_WAIT_TIMEOUT_S = 5.0
CHARGING_DETECTION_TIMEOUT_S = 120.0

# State persistence
STATE_STORAGE_VERSION = 1
STATE_STORAGE_KEY_PREFIX = "evcm_state"
STATE_SAVE_DEBOUNCE_DELAY_S = 0.5

# Startup timing
POST_START_LOCK_DELAY_S = 5.0
LATE_START_INITIAL_DELAY_S = 5
MQTT_READY_TIMEOUT_S = 180.0
MQTT_READY_POLL_INTERVAL_S = 1.0

# Lock timing
UNLOCK_TIMEOUT_S = 5.0
LOCK_WAIT_POLL_INTERVAL_S = 0.2

# Regulation timing
REGULATION_MIN_POWER_CHECK_DELAY_S = 1.0

# Priority polling
PRIORITY_REFRESH_POLL_INTERVAL_S = 0.25
PRIORITY_REFRESH_RETRIES = 4
OTHER_CHARGING_CHECK_RETRIES = 8
OTHER_CHARGING_CHECK_INTERVAL_S = 0.25

# Verify delays
CE_VERIFY_DELAY_S = 1.0


# EOF
