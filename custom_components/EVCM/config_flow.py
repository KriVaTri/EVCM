from __future__ import annotations

import voluptuous as vol
from typing import Optional, Dict, List, Tuple
import logging

from homeassistant import config_entries
from homeassistant.core import callback, State
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
    grid_single: bool,
    defaults: dict,
    selected_device: Optional[str] = None,
    filter_keys: Optional[set[str]] = None,
) -> vol.Schema:
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

    fields: dict = {}

    # Grid sensors should NOT be filtered by wallbox device (they often live on the energy meter)
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
        ent_selector: Dict = {"entity": {"domain": domain}}
        if selected_device and filterable and (filter_keys is None or key in filter_keys):
            ent_selector["entity"]["device"] = selected_device
        fields[vol.Required(key, default=defaults.get(key, ""))] = selector(ent_selector)

    # Wallbox-related (filtered if device selected)
    add_ent(CONF_CHARGE_POWER, "sensor", filterable=True)
    add_ent(CONF_WALLBOX_STATUS, "sensor", filterable=True)
    add_ent(CONF_CABLE_CONNECTED, "binary_sensor", filterable=True)
    add_ent(CONF_CHARGING_ENABLE, "switch", filterable=True)
    add_ent(CONF_LOCK_SENSOR, "lock", filterable=True)
    add_ent(CONF_CURRENT_SETTING, "number", filterable=True)

    # EV SOC may be from a different integration/device → do NOT filter by selected device
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
            # Skip disabled entities
            if getattr(entry, "disabled_by", None) is not None:
                continue
            # Match domain (RegistryEntry may or may not have .domain across HA versions)
            edomain = getattr(entry, "domain", None) or entry.entity_id.split(".", 1)[0]
            if edomain != domain:
                continue
            out.append(entry.entity_id)
        except Exception:
            continue
    return out


def _prefer_by_keywords(hass, candidates: List[str], include_any: List[str], bonus_any: Optional[List[str]] = None,
                        exclude_any: Optional[List[str]] = None) -> Tuple[List[str], Dict[str, int]]:
    """Rank candidates by keyword occurrence in entity_id or registry name.
    Return (best_ties, score_map)."""
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
    if not score_map:
        return candidates, {}
    max_score = max(score_map.values())
    best = [eid for eid, sc in score_map.items() if sc == max_score]
    return (best if max_score > 0 else candidates), score_map


def _score_charge_power(hass, eid: str) -> int:
    """Heuristic score for selecting the best 'charge power' sensor on a device."""
    score = 0
    st: Optional[State] = None
    try:
        st = hass.states.get(eid)
    except Exception:
        st = None

    # Registry hints
    reg = _get_reg_entry(hass, eid)
    reg_dc = getattr(reg, "original_device_class", None) if reg else None

    # Device class preference
    dc = st.attributes.get("device_class") if st else None
    if dc == "power" or reg_dc == "power":
        score += 8

    # Unit preference
    unit = st.attributes.get("unit_of_measurement") if st else None
    if unit in ("W", "kW"):
        score += 6
    if unit in ("kWh",):
        score -= 6  # energy, not power

    # State class: measurement vs totals
    sclass = st.attributes.get("state_class") if st else None
    if sclass == "measurement":
        score += 4
    if sclass and sclass.startswith("total"):
        score -= 6

    name = f"{eid}|{_get_registry_name(hass, eid)}".lower()

    # Positive keywords
    for kw, pts in [
        ("charge_power", 8),
        ("charging_power", 8),
        ("charger_power", 6),
        ("evse_power", 6),
        ("ev_power", 5),
        ("wallbox_power", 5),
        ("power", 2),
        ("charge", 2),
        ("charging", 2),
        ("ev", 1),
        ("wallbox", 1),
        ("charger", 1),
    ]:
        if kw in name:
            score += pts

    # Negative keywords (not the charger power)
    for kw, pts in [
        ("grid", -6),
        ("import", -6),
        ("export", -6),
        ("solar", -6),
        ("pv", -6),
        ("home", -4),
        ("house", -4),
        ("total", -4),
        ("sum", -4),
        ("accumulated", -4),
        ("energy", -6),
        ("session_energy", -8),
        ("l1", -3),
        ("l2", -3),
        ("l3", -3),
        ("phase", -3),
    ]:
        if kw in name:
            score += pts

    return score


def _select_single_charge_power(hass, candidates: List[str]) -> Optional[str]:
    """Return a single best candidate for charge power, or None if ambiguous."""
    if not candidates:
        return None
    scored = [(eid, _score_charge_power(hass, eid)) for eid in candidates]
    # Find unique highest
    scored.sort(key=lambda x: x[1], reverse=True)
    if not scored:
        return None
    top_eid, top_score = scored[0]
    # If multiple share top score, ambiguous
    ties = [eid for eid, sc in scored if sc == top_score]
    if top_score <= 0:
        return None
    if len(ties) == 1:
        return top_eid
    return None


def _refine_candidates_for_key(hass, candidates: List[str], key: str) -> List[str]:
    """Refine candidates using state attributes and keyword heuristics per key."""
    if not candidates:
        return []
    refined = list(candidates)

    if key == CONF_CHARGE_POWER:
        # If we can pick a unique best, return it directly
        pick = _select_single_charge_power(hass, refined)
        if pick:
            return [pick]

        # Otherwise narrow down:
        # 1) Prefer sensors with device_class power or unit W/kW
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

        # 2) Avoid totals/energy
        measurement_like = []
        for eid in refined:
            st = hass.states.get(eid)
            if not st:
                continue
            sclass = st.attributes.get("state_class")
            unit = st.attributes.get("unit_of_measurement")
            if sclass == "measurement" and unit in ("W", "kW"):
                measurement_like.append(eid)
        if len(measurement_like) == 1:
            return measurement_like
        if len(measurement_like) > 1:
            refined = measurement_like

        # 3) Prefer keywords; penalize grid/solar/pv/etc.
        refined, _ = _prefer_by_keywords(
            hass,
            refined,
            include_any=["charge_power", "charging_power", "charger_power", "evse_power", "ev_power", "wallbox_power", "power"],
            bonus_any=["charge", "charging", "ev", "wallbox", "charger"],
            exclude_any=["grid", "import", "export", "solar", "pv", "home", "house", "total", "sum", "accumulated", "energy", "session_energy", "l1", "l2", "l3", "phase"],
        )
        return refined

    if key == CONF_WALLBOX_STATUS:
        # Prefer enum-like sensors (device_class enum) if available
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
        # Keyword preference: 'status', 'charging_status', 'state'
        refined, _ = _prefer_by_keywords(
            hass,
            refined,
            include_any=["status", "charging_status", "ev_status", "wallbox_status", "state"],
            bonus_any=["charge", "charging", "ev", "wallbox"],
        )
        only_status = [eid for eid in refined if "status" in (eid.lower() + "|" + _get_registry_name(hass, eid).lower())]
        if len(only_status) == 1:
            return only_status
        return refined

    # Other keys: leave as-is
    return refined


def _autofill_from_device(hass, defaults: dict, device_id: Optional[str]) -> None:
    """Prefill defaults for filterable keys when a single best candidate is found on the selected device."""
    if not device_id:
        return
    for key, domain in KEY_DOMAIN_MAP.items():
        # Do not override if already provided/non-empty
        if defaults.get(key):
            continue
        candidates = _find_device_candidates(hass, device_id, domain)
        if not candidates:
            continue
        # Refine based on heuristics
        refined = _refine_candidates_for_key(hass, candidates, key)
        # If refinement yields a single candidate, use it
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

        # Before showing the form: apply auto-prefill from selected device (only once or when empty values)
        if user_input is None and self._selected_device:
            _autofill_from_device(self.hass, self._s_defaults, self._selected_device)

        if user_input is None:
            # Build schema with filtering; fallback to unfiltered if HA version doesn't support device filter
            try:
                schema = _build_sensors_schema(grid_single, self._s_defaults, self._selected_device, FILTERABLE_KEYS)
                return self.async_show_form(
                    step_id="sensors",
                    data_schema=schema,
                    description_placeholders={"name": self._step1.get(CONF_NAME, "")},
                )
            except Exception as exc:
                _LOGGER.warning("Device-filtered entity selector failed (%s); falling back to unfiltered.", exc)
                schema = _build_sensors_schema(grid_single, self._s_defaults, None, FILTERABLE_KEYS)
                return self.async_show_form(
                    step_id="sensors",
                    data_schema=schema,
                    description_placeholders={"name": self._step1.get(CONF_NAME, "")},
                )

        for k, v in (user_input or {}).items():
            self._s_defaults[k] = v

        # Validate thresholds
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
            # Re-apply auto-prefill for any still-empty fields (if device selected)
            if self._selected_device:
                _autofill_from_device(self.hass, self._s_defaults, self._selected_device)
            # Try filtered schema first, then fallback
            try:
                schema = _build_sensors_schema(grid_single, self._s_defaults, self._selected_device, FILTERABLE_KEYS)
            except Exception as exc:
                _LOGGER.warning("Device-filtered entity selector failed (%s); falling back to unfiltered.", exc)
                schema = _build_sensors_schema(grid_single, self._s_defaults, None, FILTERABLE_KEYS)
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

        # Before showing the form: apply auto-prefill from selected device for empty fields
        if user_input is None and self._selected_device:
            _autofill_from_device(self.hass, self._values, self._selected_device)

        if user_input is None:
            try:
                schema = _build_sensors_schema(grid_single, self._values, self._selected_device, FILTERABLE_KEYS)
                name = eff.get(CONF_NAME) or self.config_entry.title or "EVCM"
                return self.async_show_form(step_id="sensors", data_schema=schema, description_placeholders={"name": name})
            except Exception as exc:
                _LOGGER.warning("Device-filtered entity selector failed (%s); falling back to unfiltered.", exc)
                schema = _build_sensors_schema(grid_single, self._values, None, FILTERABLE_KEYS)
                name = eff.get(CONF_NAME) or self.config_entry.title or "EVCM"
                return self.async_show_form(step_id="sensors", data_schema=schema, description_placeholders={"name": name})

        for k, v in (user_input or {}).items():
            self._values[k] = v

        # Validate thresholds
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
            # Re-apply auto-prefill for any still-empty fields (if device selected)
            if self._selected_device:
                _autofill_from_device(self.hass, self._values, self._selected_device)
            try:
                schema = _build_sensors_schema(grid_single, self._values, self._selected_device, FILTERABLE_KEYS)
            except Exception as exc:
                _LOGGER.warning("Device-filtered entity selector failed (%s); falling back to unfiltered.", exc)
                schema = _build_sensors_schema(grid_single, self._values, None, FILTERABLE_KEYS)
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
