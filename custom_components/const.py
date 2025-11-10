from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "evcm"

# Platforms: SWITCH (modes + global priority charging), DATETIME (planner window), NUMBER (SoC limit + priority order)
# PRIORITY DROPDOWN (SELECT) VERWIJDERD
PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.DATETIME, Platform.NUMBER]

# Persistant ECO (legacy)
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

# Modes
MODE_ECO = "eco"
MODE_START_STOP = "start_stop"
MODE_MANUAL_AUTO = "manual"
MODE_CHARGE_PLANNER = "charge_planner"
MODE_STARTSTOP_RESET = "startstop_reset"  # persistent toggle to reset Start/Stop mode on cable disconnect

MODES = [MODE_ECO, MODE_START_STOP, MODE_MANUAL_AUTO, MODE_CHARGE_PLANNER, MODE_STARTSTOP_RESET]
MODE_LABELS = {
    MODE_ECO: "ECO",
    MODE_START_STOP: "Start/Stop",
    MODE_MANUAL_AUTO: "Manual",
    MODE_CHARGE_PLANNER: "Charge Planner",
    MODE_STARTSTOP_RESET: "Start/Stop Reset",
}

# Phases
CONF_WALLBOX_THREE_PHASE = "wallbox_three_phase"
DEFAULT_WALLBOX_THREE_PHASE = False

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

MIN_BAND_SINGLE_PHASE = 2000
MIN_BAND_THREE_PHASE = 5000

MIN_CHARGE_POWER_SINGLE_PHASE_W = 1400
MIN_CHARGE_POWER_THREE_PHASE_W = 4200

# Sustain timers
CONF_SUSTAIN_SECONDS = "sustain_seconds"
DEFAULT_SUSTAIN_SECONDS = 120
SUSTAIN_MAX_SECONDS = 1800

# Planner entity display names
PLANNER_START_ENTITY_NAME = "planner start"
PLANNER_STOP_ENTITY_NAME = "planner stop"

# Persist keys for planner + SoC limit (legacy options keys remain for compatibility)
CONF_PLANNER_START_ISO = "planner_start_iso"
CONF_PLANNER_STOP_ISO = "planner_stop_iso"
CONF_SOC_LIMIT_PERCENT = "soc_limit_percent"

# Wallbox current limit
CONF_MAX_CURRENT_LIMIT_A = "max_current_limit_a"
ABS_MIN_CURRENT_A = 6
ABS_MAX_CURRENT_A = 32