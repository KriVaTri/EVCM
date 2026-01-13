from __future__ import annotations

import voluptuous as vol
from typing import Optional, Dict, List, Tuple
import logging

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.helpers.selector import selector
from homeassistant.helpers import entity_registry as er

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
    # Profile-specific min band
    SUPPLY_PROFILE_MIN_BAND,
    MIN_BAND_230,
    MIN_BAND_400,
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

CONF_UPPER_DEBOUNCE_SECONDS = "upper_debounce_seconds"
DEFAULT_UPPER_DEBOUNCE_SECONDS = 3
UPPER_DEBOUNCE_MIN_SECONDS = 0
UPPER_DEBOUNCE_MAX_SECONDS = 60


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


def _validate_thresholds(data: dict, band_min: float) -> dict[str, str]:
    errors: dict[str, str] = {}
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


# Keys we will filter/prefill by the selected device (wallbox-related)
KEY_DOMAIN_MAP: Dict[str, str] = {
    CONF_CHARGE_POWER: "sensor",
    CONF_WALLBOX_STATUS: "sensor",
    CONF_CABLE_CONNECTED: "binary_sensor",
    CONF_CHARGING_ENABLE: "switch",
    CONF_LOCK_SENSOR: "lock",
    CONF_CURRENT_SETTING: "number",
}
FILTERABLE_KEYS = set(KEY_DOMAIN_MAP.keys())


def _build_sensors_schema(
    hass,
    grid_single: bool,
    defaults: dict,
    selected_device: Optional[str] = None,
    filter_keys: Optional[set[str]] = None,
) -> vol.Schema:
    # Defensive: callers may pass None for defaults; ensure we have a dict here.
    if not isinstance(defaults, dict):
        defaults = {}

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
            "min": SUSTAIN_MIN_SECONDS,
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
    num_sel_upper_debounce = {
        "number": {
            "min": UPPER_DEBOUNCE_MIN_SECONDS,
            "max": UPPER_DEBOUNCE_MAX_SECONDS,
            "step": 1,
            "mode": "box",
            "unit_of_measurement": "s",
        }
    }

    fields: dict = {}

    # Grid sensors
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

    def add_ent(key: str, domain: str, filterable: bool = True):
        ent_selector: Dict = {"entity": {}}
        if selected_device and filterable and (filter_keys is None or key in filter_keys):
            candidates = _find_device_candidates(hass, selected_device, domain)
            if candidates:
                ent_selector["entity"]["include_entities"] = candidates
            else:
                ent_selector["entity"]["domain"] = domain
        else:
            ent_selector["entity"]["domain"] = domain
        fields[vol.Required(key, default=defaults.get(key, ""))] = selector(ent_selector)

    # Wallbox-related entities
    add_ent(CONF_CHARGE_POWER, "sensor", filterable=True)
    add_ent(CONF_WALLBOX_STATUS, "sensor", filterable=True)
    add_ent(CONF_CABLE_CONNECTED, "binary_sensor", filterable=True)
    add_ent(CONF_CHARGING_ENABLE, "switch", filterable=True)
    add_ent(CONF_LOCK_SENSOR, "lock", filterable=True)
    add_ent(CONF_CURRENT_SETTING, "number", filterable=True)

    # EV SOC
    evsoc_default = defaults.get(CONF_EV_BATTERY_LEVEL, "")
    if evsoc_default:
        fields[vol.Optional(CONF_EV_BATTERY_LEVEL, default=evsoc_default)] = selector(
            {"entity": {"domain": "sensor"}}
        )
    else:
        fields[vol.Optional(CONF_EV_BATTERY_LEVEL)] = selector({"entity": {"domain": "sensor"}})

    # Other controls
    fields[vol.Required(CONF_MAX_CURRENT_LIMIT_A, default=defaults.get(CONF_MAX_CURRENT_LIMIT_A, 16))] = selector(num_sel_a)

    # Thresholds
    fields[vol.Required(CONF_ECO_ON_UPPER, default=defaults.get(CONF_ECO_ON_UPPER, DEFAULT_ECO_ON_UPPER))] = selector(num_sel_w)
    fields[vol.Required(CONF_ECO_ON_LOWER, default=defaults.get(CONF_ECO_ON_LOWER, DEFAULT_ECO_ON_LOWER))] = selector(num_sel_w)
    fields[vol.Required(CONF_ECO_OFF_UPPER, default=defaults.get(CONF_ECO_OFF_UPPER, DEFAULT_ECO_OFF_UPPER))] = selector(num_sel_w)
    fields[vol.Required(CONF_ECO_OFF_LOWER, default=defaults.get(CONF_ECO_OFF_LOWER, DEFAULT_ECO_OFF_LOWER))] = selector(num_sel_w)

    # Timers and intervals
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
    fields[vol.Required(CONF_UPPER_DEBOUNCE_SECONDS, default=defaults.get(CONF_UPPER_DEBOUNCE_SECONDS, DEFAULT_UPPER_DEBOUNCE_SECONDS))] = selector(num_sel_upper_debounce)
    fields[vol.Required(CONF_SUSTAIN_SECONDS, default=defaults.get(CONF_SUSTAIN_SECONDS, DEFAULT_SUSTAIN_SECONDS))] = selector(num_sel_s)

    return vol.Schema(fields)


def _get_reg_entry(hass, entity_id: str):
    try:
        ent_reg = er.async_get(hass)
        return ent_reg.async_get(entity_id)
    except Exception:
        return None


def _get_registry_name(hass, entity_id: str) -> str:
    try:
        e = _get_reg_entry(hass, entity_id)
        if e:
            return (e.original_name or e.original_device_class or e.unique_id or e.entity_id) or entity_id
    except Exception:
        pass
    return entity_id


def _find_device_candidates(hass, device_id: str, domain: str) -> list[str]:
    """Return entity_ids for a device filtered by domain, only enabled entries."""
    if not device_id:
        return []
    ent_reg = er.async_get(hass)
    out: list[str] = []
    for entry in ent_reg.entities.values():
        try:
            if entry.device_id != device_id:
                continue
            if getattr(entry, "disabled_by", None) is not None:
                continue
            edomain = getattr(entry, "domain", None) or entry.entity_id.split(".", 1)[0]
            if edomain != domain:
                continue
            out.append(entry.entity_id)
        except Exception:
            continue
    return out


def _prefer_by_keywords(hass, candidates: List[str], include_any: List[str], bonus_any: Optional[List[str]] = None,
                        exclude_any: Optional[List[str]] = None) -> Tuple[List[str], Dict[str, int]]:
    if not candidates:
        return [], {}
    bonus_any = bonus_any or []
    exclude_any = exclude_any or []
    score_map: Dict[str, int] = {}
    for eid in candidates:
        name = f"{eid}|{_get_registry_name(hass, eid)}".lower()
        score = 0
        for kw in include_any:
            if kw in name:
                score += 3
        for kw in bonus_any:
            if kw in name:
                score += 1
        for kw in exclude_any:
            if kw in name:
                score -= 3
        score_map[eid] = score
    max_score = max(score_map.values()) if score_map else 0
    best = [eid for eid, sc in score_map.items() if sc == max_score]
    return (best if max_score > 0 else candidates), score_map


def _refine_candidates_for_key(hass, candidates: List[str], key: str) -> List[str]:
    if not candidates:
        return []
    refined = list(candidates)
    if key == CONF_CHARGE_POWER:
        # 1) device_class power or unit W/kW
        power_like = []
        for eid in refined:
            st = hass.states.get(eid)
            if not st:
                continue
            unit = st.attributes.get("unit_of_measurement")
            dc = st.attributes.get("device_class")
            if (dc == "power") or (unit in ("W", "kW")):
                power_like.append(eid)
        if len(power_like) == 1:
            return power_like
        if len(power_like) > 1:
            refined = power_like
        # 2) preferences by keywords
        refined, _ = _prefer_by_keywords(
            hass,
            refined,
            include_any=["charge_power", "charging_power", "charger_power", "evse_power", "ev_power", "wallbox_power", "power"],
            bonus_any=["charge", "charging", "ev", "wallbox", "charger"],
            exclude_any=["grid", "import", "export", "solar", "pv", "home", "house", "total", "sum", "accumulated", "energy", "session_energy", "l1", "l2", "l3", "phase"],
        )
        return refined

    if key == CONF_WALLBOX_STATUS:
        enum_like = []
        for eid in refined:
            st = hass.states.get(eid)
            if not st:
                continue
            if st.attributes.get("device_class") in ("enum", "timestamp"):
                enum_like.append(eid)
        if len(enum_like) == 1:
            return enum_like
        if len(enum_like) > 1:
            refined = enum_like
        refined, _ = _prefer_by_keywords(
            hass,
            refined,
            include_any=["status", "charging_status", "ev_status", "wallbox_status", "state"],
            bonus_any=["charge", "charging", "ev", "wallbox"],
        )
        return refined

    return refined


def _autofill_from_device(hass, defaults: dict, device_id: Optional[str]) -> None:
    if not device_id:
        return
    for key, domain in KEY_DOMAIN_MAP.items():
        if defaults.get(key):
            continue
        candidates = _find_device_candidates(hass, device_id, domain)
        if not candidates:
            continue
        refined = _refine_candidates_for_key(hass, candidates, key)
        if len(refined) == 1:
            defaults[key] = refined[0]
            _LOGGER.debug("Auto-filled %s with %s (from %d candidates)", key, refined[0], len(candidates))
        else:
            _LOGGER.debug(
                "Did not auto-fill %s: %d candidates on device, %d after refine (ambiguous)",
                key, len(candidates), len(refined)
            )


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
            CONF_UPPER_DEBOUNCE_SECONDS: DEFAULT_UPPER_DEBOUNCE_SECONDS,
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

        # Autofill from selected device (first rendering)
        if user_input is None and self._selected_device:
            _autofill_from_device(self.hass, self._s_defaults, self._selected_device)

        if user_input is None:
            try:
                schema = _build_sensors_schema(self.hass, grid_single, self._s_defaults, self._selected_device, FILTERABLE_KEYS)
                return self.async_show_form(
                    step_id="sensors",
                    data_schema=schema,
                    description_placeholders={"name": self._step1.get(CONF_NAME, "")},
                )
            except Exception as exc:
                _LOGGER.warning("Device-filtered entity selector failed (%s); falling back to unfiltered.", exc)
                schema = _build_sensors_schema(self.hass, grid_single, self._s_defaults, None, FILTERABLE_KEYS)
                return self.async_show_form(
                    step_id="sensors",
                    data_schema=schema,
                    description_placeholders={"name": self._step1.get(CONF_NAME, "")},
                )

        for k, v in (user_input or {}).items():
            self._s_defaults[k] = v

        # Select band minimum by supply profile (fallback by phases)
        band_min = SUPPLY_PROFILE_MIN_BAND.get(profile_key)
        if band_min is None:
            band_min = MIN_BAND_400 if three_phase else MIN_BAND_230

        # Validate thresholds
        thresh_data = {
            CONF_ECO_ON_UPPER: self._s_defaults.get(CONF_ECO_ON_UPPER, DEFAULT_ECO_ON_UPPER),
            CONF_ECO_ON_LOWER: self._s_defaults.get(CONF_ECO_ON_LOWER, DEFAULT_ECO_ON_LOWER),
            CONF_ECO_OFF_UPPER: self._s_defaults.get(CONF_ECO_OFF_UPPER, DEFAULT_ECO_OFF_UPPER),
            CONF_ECO_OFF_LOWER: self._s_defaults.get(CONF_ECO_OFF_LOWER, DEFAULT_ECO_OFF_LOWER),
        }
        errors = _validate_thresholds(thresh_data, band_min)

        # Scan interval
        try:
            si = int(self._s_defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
            if si < MIN_SCAN_INTERVAL:
                raise ValueError
        except Exception:
            errors[CONF_SCAN_INTERVAL] = "value_out_of_range"

        # Sustain
        try:
            st = int(self._s_defaults.get(CONF_SUSTAIN_SECONDS, DEFAULT_SUSTAIN_SECONDS))
            if st < SUSTAIN_MIN_SECONDS or st > SUSTAIN_MAX_SECONDS:
                raise ValueError
        except Exception:
            errors[CONF_SUSTAIN_SECONDS] = "value_out_of_range"

        # Upper debounce
        try:
            ud = int(self._s_defaults.get(CONF_UPPER_DEBOUNCE_SECONDS, DEFAULT_UPPER_DEBOUNCE_SECONDS))
            if ud < UPPER_DEBOUNCE_MIN_SECONDS or ud > UPPER_DEBOUNCE_MAX_SECONDS:
                raise ValueError
        except Exception:
            errors[CONF_UPPER_DEBOUNCE_SECONDS] = "value_out_of_range"

        # Max current
        try:
            max_a = int(self._s_defaults.get(CONF_MAX_CURRENT_LIMIT_A, 16))
            if max_a < ABS_MIN_CURRENT_A or max_a > ABS_MAX_CURRENT_A:
                raise ValueError
        except Exception:
            errors[CONF_MAX_CURRENT_LIMIT_A] = "value_out_of_range"

        if errors:
            try:
                schema = _build_sensors_schema(self.hass, grid_single, self._s_defaults, self._selected_device, FILTERABLE_KEYS)
            except Exception as exc:
                _LOGGER.warning("Device-filtered entity selector failed (%s); falling back to unfiltered.", exc)
                schema = _build_sensors_schema(self.hass, grid_single, self._s_defaults, None, FILTERABLE_KEYS)
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
                CONF_UPPER_DEBOUNCE_SECONDS: eff.get(CONF_UPPER_DEBOUNCE_SECONDS, DEFAULT_UPPER_DEBOUNCE_SECONDS),
                CONF_MAX_CURRENT_LIMIT_A: eff.get(CONF_MAX_CURRENT_LIMIT_A, 16),
                CONF_ECO_ON_UPPER: eff.get(CONF_ECO_ON_UPPER, DEFAULT_ECO_ON_UPPER),
                CONF_ECO_ON_LOWER: eff.get(CONF_ECO_ON_LOWER, DEFAULT_ECO_ON_LOWER),
                CONF_ECO_OFF_UPPER: eff.get(CONF_ECO_OFF_UPPER, DEFAULT_ECO_OFF_UPPER),
                CONF_ECO_OFF_LOWER: eff.get(CONF_ECO_OFF_LOWER, DEFAULT_ECO_OFF_LOWER),
                CONF_SCAN_INTERVAL: eff.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                CONF_SUSTAIN_SECONDS: eff.get(CONF_SUSTAIN_SECONDS, DEFAULT_SUSTAIN_SECONDS),
            }

        if user_input is None:
            if self._selected_device:
                _autofill_from_device(self.hass, self._values, self._selected_device)
            try:
                schema = _build_sensors_schema(self.hass, grid_single, self._values, self._selected_device, FILTERABLE_KEYS)
                name = eff.get(CONF_NAME) or self.config_entry.title or "EVCM"
                return self.async_show_form(step_id="sensors", data_schema=schema, description_placeholders={"name": name})
            except Exception as exc:
                _LOGGER.warning("Device-filtered entity selector failed (%s); falling back to unfiltered.", exc)
                schema = _build_sensors_schema(self.hass, grid_single, self._values, None, FILTERABLE_KEYS)
                name = eff.get(CONF_NAME) or self.config_entry.title or "EVCM"
                return self.async_show_form(step_id="sensors", data_schema=schema, description_placeholders={"name": name})

        for k, v in (user_input or {}).items():
            self._values[k] = v

        # Select band minimum by supply profile (fallback by phases)
        band_min = SUPPLY_PROFILE_MIN_BAND.get(profile_key)
        if band_min is None:
            band_min = MIN_BAND_400 if three_phase else MIN_BAND_230

        # Validate thresholds
        thresh_data = {
            CONF_ECO_ON_UPPER: self._values.get(CONF_ECO_ON_UPPER),
            CONF_ECO_ON_LOWER: self._values.get(CONF_ECO_ON_LOWER),
            CONF_ECO_OFF_UPPER: self._values.get(CONF_ECO_OFF_UPPER),
            CONF_ECO_OFF_LOWER: self._values.get(CONF_ECO_OFF_LOWER),
        }
        errors = _validate_thresholds(thresh_data, band_min)

        # Validate scan interval
        try:
            si = int(self._values.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
            if si < MIN_SCAN_INTERVAL:
                raise ValueError
        except Exception:
            errors[CONF_SCAN_INTERVAL] = "value_out_of_range"

        # Validate sustain
        try:
            st = int(self._values.get(CONF_SUSTAIN_SECONDS, DEFAULT_SUSTAIN_SECONDS))
            if st < SUSTAIN_MIN_SECONDS or st > SUSTAIN_MAX_SECONDS:
                raise ValueError
        except Exception:
            errors[CONF_SUSTAIN_SECONDS] = "value_out_of_range"

        # Validate upper debounce
        try:
            ud = int(self._values.get(CONF_UPPER_DEBOUNCE_SECONDS, DEFAULT_UPPER_DEBOUNCE_SECONDS))
            if ud < UPPER_DEBOUNCE_MIN_SECONDS or ud > UPPER_DEBOUNCE_MAX_SECONDS:
                raise ValueError
        except Exception:
            errors[CONF_UPPER_DEBOUNCE_SECONDS] = "value_out_of_range"

        # Max current
        try:
            max_a = int(self._values.get(CONF_MAX_CURRENT_LIMIT_A, 16))
            if max_a < ABS_MIN_CURRENT_A or max_a > ABS_MAX_CURRENT_A:
                raise ValueError
        except Exception:
            errors[CONF_MAX_CURRENT_LIMIT_A] = "value_out_of_range"

        if errors:
            if self._selected_device:
                _autofill_from_device(self.hass, self._values, self._selected_device)
            try:
                schema = _build_sensors_schema(self.hass, grid_single, self._values, self._selected_device, FILTERABLE_KEYS)
            except Exception as exc:
                _LOGGER.warning("Device-filtered entity selector failed (%s); falling back to unfiltered.", exc)
                schema = _build_sensors_schema(self.hass, grid_single, self._values, None, FILTERABLE_KEYS)
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

# EOF
