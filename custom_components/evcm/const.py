from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "evcm"

PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.DATETIME, Platform.NUMBER]

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
        "phase_voltage_v": 235,
        "min_power_6a_w": int(235 * 6),
        "regulation_min_w": 1300,
    },
    "eu_3ph_400": {
        "label": "3-phase 400V",
        "phases": 3,
        "phase_voltage_v": 230,
        "min_power_6a_w": int(230 * 6 * 3),
        "regulation_min_w": 4000,
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

# Default SoC limit on setup
DEFAULT_SOC_LIMIT_PERCENT = 80

# Wallbox current limit
CONF_MAX_CURRENT_LIMIT_A = "max_current_limit_a"
ABS_MIN_CURRENT_A = 6
ABS_MAX_CURRENT_A = 32

# Net power target
CONF_NET_POWER_TARGET_W = "net_power_target_w"
DEFAULT_NET_POWER_TARGET_W = 0
NET_POWER_TARGET_MIN_W = -5000
NET_POWER_TARGET_MAX_W = 5000
NET_POWER_TARGET_STEP_W = 50

# Profile-specific band minimum constants
MIN_BAND_230 = 1700
MIN_BAND_400 = 4500
MIN_BAND_208 = 2600
MIN_BAND_200 = 1500
MIN_BAND_120 = 1000

# Map supply profiles to their minimum band
SUPPLY_PROFILE_MIN_BAND = {
    "eu_1ph_230": MIN_BAND_230,
    "eu_3ph_400": MIN_BAND_400,
    "na_3ph_208": MIN_BAND_208,
    "jp_1ph_200": MIN_BAND_200,
    "na_1ph_120": MIN_BAND_120,
}

# Event name for planner datetime updates
PLANNER_DATETIME_UPDATED_EVENT = "evcm_planner_datetime_updated"
