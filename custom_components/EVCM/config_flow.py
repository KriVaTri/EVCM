from __future__ import annotations

import voluptuous as vol
from typing import Optional, Dict
import logging

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.helpers.selector import selector

from .const import (
    DOMAIN,
    CONF_NAME,
    CONF_GRID_SINGLE,
    CONF_GRID_POWER,
    CONF_GRID_IMPORT,
    CONF_GRID_EXPORT,
    CONF_CHARGE_POWER,
    CONF_WALLBOX_STATUS,
    CONF_CABLE_CONNECTED,
    CONF_CHARGING_ENABLE,
    CONF_LOCK_SENSOR,
    CONF_CURRENT_SETTING,
    # Legacy compat flag
    CONF_WALLBOX_THREE_PHASE,
    # Supply profile
    CONF_SUPPLY_PROFILE,
    SUPPLY_PROFILES,
    # Thresholds
    CONF_ECO_ON_UPPER,
    CONF_ECO_ON_LOWER,
    CONF_ECO_OFF_UPPER,
    CONF_ECO_OFF_LOWER,
    DEFAULT_ECO_ON_UPPER,
    DEFAULT_ECO_ON_LOWER,
    DEFAULT_ECO_OFF_UPPER,
    DEFAULT_ECO_OFF_LOWER,
    MIN_THRESHOLD_VALUE,
    MAX_THRESHOLD_VALUE,
    MIN_BAND_SINGLE_PHASE,
    MIN_BAND_THREE_PHASE,
    # Timers and intervals
    DEFAULT_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    CONF_SUSTAIN_SECONDS,
    DEFAULT_SUSTAIN_SECONDS,
    SUSTAIN_MIN_SECONDS,
    SUSTAIN_MAX_SECONDS,
    # Device + optional
    CONF_DEVICE_ID,
    CONF_EV_BATTERY_LEVEL,
    # Current limit
    CONF_MAX_CURRENT_LIMIT_A,
    ABS_MIN_CURRENT_A,
    ABS_MAX_CURRENT_A,
)

_LOGGER = logging.getLogger(__name__)


def _merged(entry: config_entries.ConfigEntry) -> dict:
    return {**entry.data, **entry.options}


def _normalize_number(raw) -> float:
    if isinstance(raw, (int, float)):
        return float(raw)
    if raw is None or not isinstance(raw, str):
        raise ValueError("missing or non-string")
    s = raw.strip()
    if not s:
        raise ValueError("empty")
    s = s.replace("−", "-")
    tmp = s.replace(".", "").replace(",", "").replace(" ", "")
    if tmp and ((tmp.startswith("-") and tmp[1:].isdigit()) or tmp.isdigit()):
        s = tmp
    return float(s)


def _validate_thresholds(data: dict, three_phase: bool) -> dict[str, str]:
    errors: dict[str, str] = {}
    band_min = MIN_BAND_THREE_PHASE if three_phase else MIN_BAND_SINGLE_PHASE
    try:
        on_up = _normalize_number(data.get(CONF_ECO_ON_UPPER))
        on_lo = _normalize_number(data.get(CONF_ECO_ON_LOWER))
        off_up = _normalize_number(data.get(CONF_ECO_OFF_UPPER))
        off_lo = _normalize_number(data.get(CONF_ECO_OFF_LOWER))
    except Exception:
        for k in (CONF_ECO_ON_UPPER, CONF_ECO_ON_LOWER, CONF_ECO_OFF_UPPER, CONF_ECO_OFF_LOWER):
            errors[k] = "value_out_of_range"
        return errors

    def in_range(v: float) -> bool:
        return MIN_THRESHOLD_VALUE <= v <= MAX_THRESHOLD_VALUE

    for k, v in [
        (CONF_ECO_ON_UPPER, on_up),
        (CONF_ECO_ON_LOWER, on_lo),
        (CONF_ECO_OFF_UPPER, off_up),
        (CONF_ECO_OFF_LOWER, off_lo),
    ]:
        if not in_range(v):
            errors[k] = "value_out_of_range"

    if (on_up - on_lo) < band_min:
        errors[CONF_ECO_ON_UPPER] = "eco_on_band_small"
    if (off_up - off_lo) < band_min:
        errors[CONF_ECO_OFF_UPPER] = "eco_off_band_small"

    if on_up <= off_up:
        errors[CONF_ECO_ON_UPPER] = "must_exceed_off_upper"
    if on_lo <= off_lo:
        errors[CONF_ECO_ON_LOWER] = "must_exceed_off_lower"

    if on_lo >= on_up:
        errors[CONF_ECO_ON_LOWER] = "lower_above_upper"
    if off_lo >= off_up:
        errors[CONF_ECO_OFF_LOWER] = "lower_above_upper"
    return errors


def _build_sensors_schema(grid_single: bool, defaults: dict) -> vol.Schema:
    num_sel_w = {
        "number": {
            "min": MIN_THRESHOLD_VALUE,
            "max": MAX_THRESHOLD_VALUE,
            "step": 100,
            "mode": "box",
            "unit_of_measurement": "W",
        }
    }
    num_sel_s = {
        "number": {
            "min": SUSTAIN_MIN_SECONDS,   # min via constant
            "max": SUSTAIN_MAX_SECONDS,
            "step": 1,
            "mode": "box",
            "unit_of_measurement": "s",
        }
    }
    num_sel_a = {
        "number": {
            "min": ABS_MIN_CURRENT_A,
            "max": ABS_MAX_CURRENT_A,
            "step": 1,
            "mode": "box",
            "unit_of_measurement": "A",
        }
    }

    fields: dict = {}

    if grid_single:
        fields[vol.Required(CONF_GRID_POWER, default=defaults.get(CONF_GRID_POWER, ""))] = selector(
            {"entity": {"domain": "sensor"}}
        )
    else:
        fields[vol.Required(CONF_GRID_IMPORT, default=defaults.get(CONF_GRID_IMPORT, ""))] = selector(
            {"entity": {"domain": "sensor"}}
        )
        fields[vol.Required(CONF_GRID_EXPORT, default=defaults.get(CONF_GRID_EXPORT, ""))] = selector(
            {"entity": {"domain": "sensor"}}
        )

    def add_ent(key: str, domain: str):
        fields[vol.Required(key, default=defaults.get(key, ""))] = selector({"entity": {"domain": domain}})

    add_ent(CONF_CHARGE_POWER, "sensor")
    add_ent(CONF_WALLBOX_STATUS, "sensor")
    add_ent(CONF_CABLE_CONNECTED, "binary_sensor")
    add_ent(CONF_CHARGING_ENABLE, "switch")
    add_ent(CONF_LOCK_SENSOR, "lock")
    add_ent(CONF_CURRENT_SETTING, "number")

    evsoc_default = defaults.get(CONF_EV_BATTERY_LEVEL, "")
    if evsoc_default:
        fields[vol.Optional(CONF_EV_BATTERY_LEVEL, default=evsoc_default)] = selector(
            {"entity": {"domain": "sensor"}}
        )
    else:
        fields[vol.Optional(CONF_EV_BATTERY_LEVEL)] = selector({"entity": {"domain": "sensor"}})

    fields[vol.Required(CONF_MAX_CURRENT_LIMIT_A, default=defaults.get(CONF_MAX_CURRENT_LIMIT_A, 16))] = selector(num_sel_a)

    fields[vol.Required(CONF_ECO_ON_UPPER, default=defaults.get(CONF_ECO_ON_UPPER, DEFAULT_ECO_ON_UPPER))] = selector(num_sel_w)
    fields[vol.Required(CONF_ECO_ON_LOWER, default=defaults.get(CONF_ECO_ON_LOWER, DEFAULT_ECO_ON_LOWER))] = selector(num_sel_w)
    fields[vol.Required(CONF_ECO_OFF_UPPER, default=defaults.get(CONF_ECO_OFF_UPPER, DEFAULT_ECO_OFF_UPPER))] = selector(num_sel_w)
    fields[vol.Required(CONF_ECO_OFF_LOWER, default=defaults.get(CONF_ECO_OFF_LOWER, DEFAULT_ECO_OFF_LOWER))] = selector(num_sel_w)

    fields[vol.Required(CONF_SCAN_INTERVAL, default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))] = selector(
        {
            "number": {
                "min": MIN_SCAN_INTERVAL,
                "max": 3600,
                "step": 1,
                "mode": "box",
                "unit_of_measurement": "s",
            }
        }
    )
    fields[vol.Required(CONF_SUSTAIN_SECONDS, default=defaults.get(CONF_SUSTAIN_SECONDS, DEFAULT_SUSTAIN_SECONDS))] = selector(num_sel_s)

    return vol.Schema(fields)


class EVChargeManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._step1: dict | None = None
        self._s_defaults: dict | None = None
        self._selected_device: Optional[str] = None

    async def async_step_user(self, user_input=None):
        schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default=""): str,
                vol.Required(CONF_GRID_SINGLE, default=False): selector({"boolean": {}}),
                vol.Required(CONF_SUPPLY_PROFILE, default="eu_1ph_230"): selector({
                    "select": {
                        "options": [
                            {"value": key, "label": meta["label"]}
                            for key, meta in SUPPLY_PROFILES.items()
                        ]
                    }
                }),
            }
        )
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=schema)

        self._step1 = {
            CONF_NAME: (user_input.get(CONF_NAME) or "").strip(),
            CONF_GRID_SINGLE: bool(user_input.get(CONF_GRID_SINGLE, False)),
            CONF_SUPPLY_PROFILE: user_input.get(CONF_SUPPLY_PROFILE, "eu_1ph_230"),
        }
        self._s_defaults = {
            CONF_GRID_POWER: "",
            CONF_GRID_IMPORT: "",
            CONF_GRID_EXPORT: "",
            CONF_CHARGE_POWER: "",
            CONF_WALLBOX_STATUS: "",
            CONF_CABLE_CONNECTED: "",
            CONF_CHARGING_ENABLE: "",
            CONF_LOCK_SENSOR: "",
            CONF_CURRENT_SETTING: "",
            CONF_EV_BATTERY_LEVEL: "",
            CONF_MAX_CURRENT_LIMIT_A: 16,
            CONF_ECO_ON_UPPER: DEFAULT_ECO_ON_UPPER,
            CONF_ECO_ON_LOWER: DEFAULT_ECO_ON_LOWER,
            CONF_ECO_OFF_UPPER: DEFAULT_ECO_OFF_UPPER,
            CONF_ECO_OFF_LOWER: DEFAULT_ECO_OFF_LOWER,
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            CONF_SUSTAIN_SECONDS: DEFAULT_SUSTAIN_SECONDS,
        }
        return await self.async_step_device()

    async def async_step_device(self, user_input=None):
        schema = vol.Schema({vol.Optional(CONF_DEVICE_ID, default=""): selector({"device": {}})})
        if user_input is None:
            return self.async_show_form(step_id="device", data_schema=schema)
        device_id = (user_input.get(CONF_DEVICE_ID) or "").strip()
        self._selected_device = device_id if device_id else None
        return await self.async_step_sensors()

    async def async_step_sensors(self, user_input=None):
        assert self._step1 is not None
        grid_single = bool(self._step1.get(CONF_GRID_SINGLE, False))
        profile_key = self._step1.get(CONF_SUPPLY_PROFILE, "eu_1ph_230")
        profile_meta = SUPPLY_PROFILES.get(profile_key, SUPPLY_PROFILES["eu_1ph_230"])
        three_phase = bool(profile_meta.get("phases", 1) == 3)

        if self._s_defaults is None:
            self._s_defaults = {}

        if user_input is None:
            schema = _build_sensors_schema(grid_single, self._s_defaults)
            return self.async_show_form(
                step_id="sensors",
                data_schema=schema,
                description_placeholders={"name": self._step1.get(CONF_NAME, "")},
            )

        for k, v in (user_input or {}).items():
            self._s_defaults[k] = v

        # Validatie thresholds
        thresh_data = {
            CONF_ECO_ON_UPPER: self._s_defaults.get(CONF_ECO_ON_UPPER, DEFAULT_ECO_ON_UPPER),
            CONF_ECO_ON_LOWER: self._s_defaults.get(CONF_ECO_ON_LOWER, DEFAULT_ECO_ON_LOWER),
            CONF_ECO_OFF_UPPER: self._s_defaults.get(CONF_ECO_OFF_UPPER, DEFAULT_ECO_OFF_UPPER),
            CONF_ECO_OFF_LOWER: self._s_defaults.get(CONF_ECO_OFF_LOWER, DEFAULT_ECO_OFF_LOWER),
        }
        errors = _validate_thresholds(thresh_data, three_phase)

        # Scan interval
        try:
            si = int(self._s_defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
            if si < MIN_SCAN_INTERVAL:
                raise ValueError
        except Exception:
            errors[CONF_SCAN_INTERVAL] = "value_out_of_range"

        # Sustain (min via constant)
        try:
            st = int(self._s_defaults.get(CONF_SUSTAIN_SECONDS, DEFAULT_SUSTAIN_SECONDS))
            if st < SUSTAIN_MIN_SECONDS or st > SUSTAIN_MAX_SECONDS:
                raise ValueError
        except Exception:
            errors[CONF_SUSTAIN_SECONDS] = "value_out_of_range"

        # Max current
        try:
            max_a = int(self._s_defaults.get(CONF_MAX_CURRENT_LIMIT_A, 16))
            if max_a < ABS_MIN_CURRENT_A or max_a > ABS_MAX_CURRENT_A:
                raise ValueError
        except Exception:
            errors[CONF_MAX_CURRENT_LIMIT_A] = "value_out_of_range"

        if errors:
            schema = _build_sensors_schema(grid_single, self._s_defaults)
            return self.async_show_form(
                step_id="sensors",
                data_schema=schema,
                errors=errors,
                description_placeholders={"name": self._step1.get(CONF_NAME, "")},
            )

        data = {**self._step1, **self._s_defaults}

        if grid_single:
            data.pop(CONF_GRID_IMPORT, None)
            data.pop(CONF_GRID_EXPORT, None)
        else:
            data.pop(CONF_GRID_POWER, None)

        # Legacy compat
        data[CONF_WALLBOX_THREE_PHASE] = bool(profile_meta.get("phases", 1) == 3)

        if self._selected_device:
            data[CONF_DEVICE_ID] = self._selected_device

        title = self._step1.get(CONF_NAME) or "EVCM"
        return self.async_create_entry(title=title, data=data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return EVChargeManagerOptionsFlow(config_entry)


try:
    OptionsFlowBase = config_entries.OptionsFlowWithConfigEntry
except AttributeError:
    OptionsFlowBase = config_entries.OptionsFlow


class EVChargeManagerOptionsFlow(OptionsFlowBase):
    VERSION = 1

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        try:
            super().__init__(config_entry)
        except TypeError:
            super().__init__()
            self.config_entry = config_entry
        self._grid_single: bool | None = None
        self._supply_profile: str | None = None
        self._values: dict | None = None
        self._selected_device: Optional[str] = None

    async def async_step_init(self, user_input=None):
        eff = _merged(self.config_entry)
        current_single = bool(eff.get(CONF_GRID_SINGLE, False))
        current_profile = eff.get(CONF_SUPPLY_PROFILE, "eu_1ph_230")
        schema = vol.Schema(
            {
                vol.Required(CONF_GRID_SINGLE, default=current_single): selector({"boolean": {}}),
                vol.Required(CONF_SUPPLY_PROFILE, default=current_profile): selector({
                    "select": {
                        "options": [
                            {"value": key, "label": meta["label"]}
                            for key, meta in SUPPLY_PROFILES.items()
                        ]
                    }
                }),
            }
        )
        name = eff.get(CONF_NAME) or self.config_entry.title or "EVCM"
        if user_input is None:
            return self.async_show_form(step_id="init", data_schema=schema, description_placeholders={"name": name})
        self._grid_single = bool(user_input.get(CONF_GRID_SINGLE, current_single))
        self._supply_profile = user_input.get(CONF_SUPPLY_PROFILE, current_profile)
        return await self.async_step_device()

    async def async_step_device(self, user_input=None):
        eff = _merged(self.config_entry)
        existing_device = eff.get(CONF_DEVICE_ID, "")
        schema = vol.Schema(
            {vol.Optional(CONF_DEVICE_ID, default=existing_device): selector({"device": {}})}
        )
        name = eff.get(CONF_NAME) or self.config_entry.title or "EVCM"
        if user_input is None:
            return self.async_show_form(step_id="device", data_schema=schema, description_placeholders={"name": name})
        device_id = (user_input.get(CONF_DEVICE_ID) or "").strip()
        self._selected_device = device_id if device_id else None
        return await self.async_step_sensors()

    async def async_step_sensors(self, user_input=None):
        eff = _merged(self.config_entry)
        grid_single = self._grid_single if self._grid_single is not None else bool(eff.get(CONF_GRID_SINGLE, False))
        profile_key = self._supply_profile if self._supply_profile is not None else eff.get(CONF_SUPPLY_PROFILE, "eu_1ph_230")
        profile_meta = SUPPLY_PROFILES.get(profile_key, SUPPLY_PROFILES["eu_1ph_230"])
        three_phase = bool(profile_meta.get("phases", 1) == 3)

        if self._values is None:
            self._values = {
                CONF_GRID_POWER: eff.get(CONF_GRID_POWER, ""),
                CONF_GRID_IMPORT: eff.get(CONF_GRID_IMPORT, ""),
                CONF_GRID_EXPORT: eff.get(CONF_GRID_EXPORT, ""),
                CONF_CHARGE_POWER: eff.get(CONF_CHARGE_POWER, ""),
                CONF_WALLBOX_STATUS: eff.get(CONF_WALLBOX_STATUS, ""),
                CONF_CABLE_CONNECTED: eff.get(CONF_CABLE_CONNECTED, ""),
                CONF_CHARGING_ENABLE: eff.get(CONF_CHARGING_ENABLE, ""),
                CONF_LOCK_SENSOR: eff.get(CONF_LOCK_SENSOR, ""),
                CONF_CURRENT_SETTING: eff.get(CONF_CURRENT_SETTING, ""),
                CONF_EV_BATTERY_LEVEL: eff.get(CONF_EV_BATTERY_LEVEL, ""),
                CONF_MAX_CURRENT_LIMIT_A: eff.get(CONF_MAX_CURRENT_LIMIT_A, 16),
                CONF_ECO_ON_UPPER: eff.get(CONF_ECO_ON_UPPER, DEFAULT_ECO_ON_UPPER),
                CONF_ECO_ON_LOWER: eff.get(CONF_ECO_ON_LOWER, DEFAULT_ECO_ON_LOWER),
                CONF_ECO_OFF_UPPER: eff.get(CONF_ECO_OFF_UPPER, DEFAULT_ECO_OFF_UPPER),
                CONF_ECO_OFF_LOWER: eff.get(CONF_ECO_OFF_LOWER, DEFAULT_ECO_OFF_LOWER),
                CONF_SCAN_INTERVAL: eff.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                CONF_SUSTAIN_SECONDS: eff.get(CONF_SUSTAIN_SECONDS, DEFAULT_SUSTAIN_SECONDS),
            }

        if user_input is None:
            schema = _build_sensors_schema(grid_single, self._values)
            name = eff.get(CONF_NAME) or self.config_entry.title or "EVCM"
            return self.async_show_form(step_id="sensors", data_schema=schema, description_placeholders={"name": name})

        for k, v in (user_input or {}).items():
            self._values[k] = v

        # Validatie thresholds
        thresh_data = {
            CONF_ECO_ON_UPPER: self._values.get(CONF_ECO_ON_UPPER),
            CONF_ECO_ON_LOWER: self._values.get(CONF_ECO_ON_LOWER),
            CONF_ECO_OFF_UPPER: self._values.get(CONF_ECO_OFF_UPPER),
            CONF_ECO_OFF_LOWER: self._values.get(CONF_ECO_OFF_LOWER),
        }
        errors = _validate_thresholds(thresh_data, three_phase)

        # Validate scan interval
        try:
            si = int(self._values.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
            if si < MIN_SCAN_INTERVAL:
                raise ValueError
        except Exception:
            errors[CONF_SCAN_INTERVAL] = "value_out_of_range"

        # Validate sustain (min via constant)
        try:
            st = int(self._values.get(CONF_SUSTAIN_SECONDS, DEFAULT_SUSTAIN_SECONDS))
            if st < SUSTAIN_MIN_SECONDS or st > SUSTAIN_MAX_SECONDS:
                raise ValueError
        except Exception:
            errors[CONF_SUSTAIN_SECONDS] = "value_out_of_range"

        # Max current
        try:
            max_a = int(self._values.get(CONF_MAX_CURRENT_LIMIT_A, 16))
            if max_a < ABS_MIN_CURRENT_A or max_a > ABS_MAX_CURRENT_A:
                raise ValueError
        except Exception:
            errors[CONF_MAX_CURRENT_LIMIT_A] = "value_out_of_range"

        if errors:
            schema = _build_sensors_schema(grid_single, self._values)
            name = eff.get(CONF_NAME) or self.config_entry.title or "EVCM"
            return self.async_show_form(step_id="sensors", data_schema=schema, errors=errors, description_placeholders={"name": name})

        new_opts = dict(self.config_entry.options)
        new_opts[CONF_GRID_SINGLE] = bool(grid_single)

        new_opts[CONF_SUPPLY_PROFILE] = profile_key
        new_opts[CONF_WALLBOX_THREE_PHASE] = bool(profile_meta.get("phases", 1) == 3)

        if self._selected_device:
            new_opts[CONF_DEVICE_ID] = self._selected_device

        for k, v in self._values.items():
            new_opts[k] = v

        return self.async_create_entry(title="", data=new_opts)
