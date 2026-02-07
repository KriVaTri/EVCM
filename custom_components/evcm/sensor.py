from __future__ import annotations

import logging
import contextlib
from typing import Optional, Callable, Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.const import UnitOfPower
from homeassistant.util import slugify

from .const import (
    DOMAIN,
    CONF_NAME,
    CONF_ECO_ON_UPPER,
    CONF_ECO_ON_LOWER,
    CONF_ECO_OFF_UPPER,
    CONF_ECO_OFF_LOWER,
    DEFAULT_ECO_ON_UPPER,
    DEFAULT_ECO_ON_LOWER,
    DEFAULT_ECO_OFF_UPPER,
    DEFAULT_ECO_OFF_LOWER,
    # ALT thresholds
    CONF_ECO_ON_UPPER_ALT,
    CONF_ECO_ON_LOWER_ALT,
    CONF_ECO_OFF_UPPER_ALT,
    CONF_ECO_OFF_LOWER_ALT,
    DEFAULT_ECO_ON_UPPER_ALT,
    DEFAULT_ECO_ON_LOWER_ALT,
    DEFAULT_ECO_OFF_UPPER_ALT,
    DEFAULT_ECO_OFF_LOWER_ALT,
    CONF_PHASE_SWITCH_SUPPORTED,
    MODE_ECO,
    AUTO_1P_TO_3P_MARGIN_W,
    MIN_BAND_230,
    MIN_BAND_400,
)
from .controller import EVLoadController

_LOGGER = logging.getLogger(__name__)

def _base_name(entry: ConfigEntry) -> str:
    name = (entry.data.get(CONF_NAME) or entry.title or "EVCM").strip()
    return name or "EVCM"


def _base_identifier(entry: ConfigEntry) -> str:
    name = (entry.data.get(CONF_NAME) or entry.title).strip()
    if name:
        return slugify(name)
    return f"entry_{entry.entry_id}"


def _effective(entry: ConfigEntry) -> dict:
    return {**entry.data, **entry.options}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    base_id = _base_identifier(entry)
    base = _base_name(entry)

    # Get controller (may be None if not yet initialized)
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}
    controller: Optional[EVLoadController] = data.get("controller")

    entities: list[SensorEntity] = [
        _ThresholdSensor(
            entry=entry,
            key=CONF_ECO_ON_UPPER,
            default=DEFAULT_ECO_ON_UPPER,
            name=f"{base} ECO on upper",
            unique_suffix="eco_on_upper_w",
            entity_id=f"sensor.{base_id}_eco_on_upper",
        ),
        _ThresholdSensor(
            entry=entry,
            key=CONF_ECO_ON_LOWER,
            default=DEFAULT_ECO_ON_LOWER,
            name=f"{base} ECO on lower",
            unique_suffix="eco_on_lower_w",
            entity_id=f"sensor.{base_id}_eco_on_lower",
        ),
        _ThresholdSensor(
            entry=entry,
            key=CONF_ECO_OFF_UPPER,
            default=DEFAULT_ECO_OFF_UPPER,
            name=f"{base} ECO off upper",
            unique_suffix="eco_off_upper_w",
            entity_id=f"sensor.{base_id}_eco_off_upper",
        ),
        _ThresholdSensor(
            entry=entry,
            key=CONF_ECO_OFF_LOWER,
            default=DEFAULT_ECO_OFF_LOWER,
            name=f"{base} ECO off lower",
            unique_suffix="eco_off_lower_w",
            entity_id=f"sensor.{base_id}_eco_off_lower",
        ),
    ]

    # Add dynamic threshold sensors (require controller)
    if controller is not None:
        entities.extend([
            _StopThresholdSensor(
                controller=controller,
                entry=entry,
                name=f"{base} Stop threshold",
                entity_id=f"sensor.{base_id}_stop_threshold",
            ),
            _StartThresholdSensor(
                controller=controller,
                entry=entry,
                name=f"{base} Start threshold",
                entity_id=f"sensor.{base_id}_start_threshold",
            ),
        ])

    eff = _effective(entry)
    if bool(eff.get(CONF_PHASE_SWITCH_SUPPORTED, False)):
        # Expose ALT thresholds as sensors too (only when phase switching is supported)
        entities.extend(
            [
                _ThresholdSensor(
                    entry=entry,
                    key=CONF_ECO_ON_UPPER_ALT,
                    default=DEFAULT_ECO_ON_UPPER_ALT,
                    name=f"{base} ALT ECO on upper",
                    unique_suffix="eco_on_upper_alt_w",
                    entity_id=f"sensor.{base_id}_eco_on_upper_alt",
                ),
                _ThresholdSensor(
                    entry=entry,
                    key=CONF_ECO_ON_LOWER_ALT,
                    default=DEFAULT_ECO_ON_LOWER_ALT,
                    name=f"{base} ALT ECO on lower",
                    unique_suffix="eco_on_lower_alt_w",
                    entity_id=f"sensor.{base_id}_eco_on_lower_alt",
                ),
                _ThresholdSensor(
                    entry=entry,
                    key=CONF_ECO_OFF_UPPER_ALT,
                    default=DEFAULT_ECO_OFF_UPPER_ALT,
                    name=f"{base} ALT ECO off upper",
                    unique_suffix="eco_off_upper_alt_w",
                    entity_id=f"sensor.{base_id}_eco_off_upper_alt",
                ),
                _ThresholdSensor(
                    entry=entry,
                    key=CONF_ECO_OFF_LOWER_ALT,
                    default=DEFAULT_ECO_OFF_LOWER_ALT,
                    name=f"{base} ALT ECO off lower",
                    unique_suffix="eco_off_lower_alt_w",
                    entity_id=f"sensor.{base_id}_eco_off_lower_alt",
                ),
            ]
        )

        if controller is not None:
            entities.extend([
                _PhaseModeSensor(
                    controller=controller,
                    entry=entry,
                    name=f"{base} Phase mode",
                    entity_id=f"sensor.{base_id}_phase_mode",
                ),
                _PhaseSwitchThresholdSensor(
                    controller=controller,
                    entry=entry,
                    name=f"{base} Phase switch threshold",
                    entity_id=f"sensor.{base_id}_phase_switch_threshold",
                ),
            ])

    async_add_entities(entities)


# -----------------------------------------------------------------------------
# Helper: format watt value as human-readable string
# -----------------------------------------------------------------------------
def _format_threshold_w(value_w: float) -> str:
    """Format a threshold value as 'XW import' or 'XW export'.
    
    Convention: negative = import (grid to home), positive = export (home to grid)
    """
    val = int(round(value_w))
    if val > 0:
        return f"{val}W export"
    elif val < 0:
        return f"{-val}W import"
    else:
        return "0W"


# -----------------------------------------------------------------------------
# Dynamic threshold sensors (read from controller)
# -----------------------------------------------------------------------------
class _StopThresholdSensor(SensorEntity):
    """Sensor showing at what net power level charging will stop."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:pause"

    def __init__(
        self,
        *,
        controller: EVLoadController,
        entry: ConfigEntry,
        name: str,
        entity_id: str,
    ) -> None:
        self._controller = controller
        self._entry = entry
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_stop_threshold"
        self.entity_id = entity_id
        self._unsub: Optional[Callable[[], None]] = None

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_update() -> None:
            self.async_write_ha_state()

        self._unsub = self._controller.add_mode_listener(_on_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            with contextlib.suppress(Exception):
                self._unsub()
            self._unsub = None

    @property
    def device_info(self):
        base = _base_name(self._entry)
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": base,
            "manufacturer": "KriVaTri",
            "model": "EVCM",
        }

    def _get_stop_threshold(self) -> tuple[float, bool]:
        """Return (threshold_w, max_peak_active).
        
        Stop threshold:
        - If max_peak > 0: stop at max_peak import (convert to negative internally)
        - Else: use eco lower threshold
        """
        ext = self._controller._ext_import_limit_w
        
        # Max peak is set and > 0 (stored as positive, but means import = negative)
        if ext is not None and ext > 0:
            return (float(-ext), True)
        
        # No max peak: use eco lower
        lower = self._controller._current_lower()
        return (lower, False)

    @property
    def native_value(self) -> Optional[str]:
        try:
            threshold, _ = self._get_stop_threshold()
            return _format_threshold_w(threshold)
        except Exception:
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        try:
            threshold, max_peak_active = self._get_stop_threshold()
            attrs["mode"] = "eco_on" if self._controller.get_mode(MODE_ECO) else "eco_off"
            attrs["max_peak_active"] = max_peak_active
            attrs["current_phase"] = self._controller._phase_feedback_value
            attrs["raw_value_w"] = int(round(threshold))
        except Exception:
            pass
        return attrs


class _StartThresholdSensor(SensorEntity):
    """Sensor showing at what net power level charging will start/resume."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:play"

    def __init__(
        self,
        *,
        controller: EVLoadController,
        entry: ConfigEntry,
        name: str,
        entity_id: str,
    ) -> None:
        self._controller = controller
        self._entry = entry
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_start_threshold"
        self.entity_id = entity_id
        self._unsub: Optional[Callable[[], None]] = None

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_update() -> None:
            self.async_write_ha_state()

        self._unsub = self._controller.add_mode_listener(_on_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            with contextlib.suppress(Exception):
                self._unsub()
            self._unsub = None

    @property
    def device_info(self):
        base = _base_name(self._entry)
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": base,
            "manufacturer": "KriVaTri",
            "model": "EVCM",
        }

    def _get_min_band(self) -> int:
        """Get min_band based on current phase (1p=1700, 3p=4500)."""
        feedback = self._controller._phase_feedback_value
        if feedback == "1p":
            return MIN_BAND_230  # 1700
        else:
            # 3p or unknown -> use 3p band (conservative)
            return MIN_BAND_400  # 4500

    def _get_start_threshold(self) -> tuple[float, bool]:
        """Return (threshold_w, max_peak_active).
        
        Start threshold:
        - If max_peak > 0: start at -max_peak + min_band
            - 1p: -2000 + 1700 = -300 (300W import)
            - 3p: -2000 + 4500 = 2500 (2500W export)
        - Else: use eco upper threshold
        """
        ext = self._controller._ext_import_limit_w
        
        # Max peak is set and > 0 (stored as positive, but means import = negative)
        if ext is not None and ext > 0:
            min_band = self._get_min_band()
            # -max_peak + min_band
            threshold = float(-ext) + float(min_band)
            return (threshold, True)
        
        # No max peak: use eco upper
        upper = self._controller._current_upper()
        return (upper, False)

    @property
    def native_value(self) -> Optional[str]:
        try:
            threshold, _ = self._get_start_threshold()
            return _format_threshold_w(threshold)
        except Exception:
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        try:
            threshold, max_peak_active = self._get_start_threshold()
            attrs["mode"] = "eco_on" if self._controller.get_mode(MODE_ECO) else "eco_off"
            attrs["max_peak_active"] = max_peak_active
            attrs["current_phase"] = self._controller._phase_feedback_value
            attrs["raw_value_w"] = int(round(threshold))
        except Exception:
            pass
        return attrs


class _PhaseSwitchThresholdSensor(SensorEntity):
    """Sensor showing when a phase switch will occur."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:swap-horizontal"

    def __init__(
        self,
        *,
        controller: EVLoadController,
        entry: ConfigEntry,
        name: str,
        entity_id: str,
    ) -> None:
        self._controller = controller
        self._entry = entry
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_phase_switch_threshold"
        self.entity_id = entity_id
        self._unsub: Optional[Callable[[], None]] = None

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_update() -> None:
            self.async_write_ha_state()

        self._unsub = self._controller.add_mode_listener(_on_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            with contextlib.suppress(Exception):
                self._unsub()
            self._unsub = None

    @property
    def device_info(self):
        base = _base_name(self._entry)
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": base,
            "manufacturer": "KriVaTri",
            "model": "EVCM",
        }

    @property
    def native_value(self) -> Optional[str]:
        try:
            feedback = self._controller._phase_feedback_value
            auto_enabled = self._controller._phase_switch_auto_enabled

            # Unknown feedback - can't determine threshold
            if feedback not in ("1p", "3p"):
                return "Unknown phase"
                
            # 1p -> 3p scenario
            if feedback == "1p":
                if not auto_enabled:
                    return "Auto phase switch off"
                
                upper_3p = self._controller._auto_upper_3p()
                max_1p_power = float(self._controller._max_current_a()) * 230.0
                target = float(self._controller.net_power_target_w)
                
                threshold = upper_3p + float(AUTO_1P_TO_3P_MARGIN_W) + float(MIN_BAND_400) - max_1p_power + target
                
                return f"Switch to 3p at ±{_format_threshold_w(threshold)}"

            # 3p -> 1p scenario
            if feedback == "3p":
                if not auto_enabled:
                    return "Auto phase switch off"
                
                # Use effective 1p upper (respects max peak), without target
                threshold = self._controller._get_effective_1p_upper()
                
                return f"Switch to 1p at {_format_threshold_w(threshold)}"

        except Exception:
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        try:
            attrs["mode"] = "eco_on" if self._controller.get_mode(MODE_ECO) else "eco_off"
            attrs["max_peak_active"] = self._controller._max_peak_override_active()
            attrs["current_phase"] = self._controller._phase_feedback_value
            attrs["auto_enabled"] = self._controller._phase_switch_auto_enabled
            attrs["net_power_target_w"] = self._controller.net_power_target_w

            # Add raw threshold values
            feedback = self._controller._phase_feedback_value
            target = float(self._controller.net_power_target_w)
            
            if feedback == "1p":
                upper_3p = self._controller._auto_upper_3p()
                max_1p_power = float(self._controller._max_current_a()) * 230.0
                threshold = upper_3p + float(AUTO_1P_TO_3P_MARGIN_W) + float(MIN_BAND_400) - max_1p_power + target
                attrs["raw_value_w"] = int(round(threshold))
                attrs["target_phase"] = "3p"
                attrs["estimation_note"] = f"Based on {self._controller._max_current_a()}A × 230V + target {int(target)}W"
            elif feedback == "3p":
                threshold = self._controller._get_effective_1p_upper()
                attrs["raw_value_w"] = int(round(threshold))
                attrs["target_phase"] = "1p"
                attrs["max_peak_w"] = self._controller._ext_import_limit_w
                attrs["estimation_note"] = "effective 1p upper (respects max peak)"
            else:
                attrs["target_phase"] = None
        except Exception:
            pass
        return attrs


# -----------------------------------------------------------------------------
# Existing sensors
# -----------------------------------------------------------------------------
class _PhaseModeSensor(SensorEntity):
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:sine-wave"

    def __init__(self, *, controller: EVLoadController, entry: ConfigEntry, name: str, entity_id: str) -> None:
        self._controller = controller
        self._entry = entry
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_phase_mode"
        self.entity_id = entity_id
        self._unsub: Optional[Callable[[], None]] = None

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_update() -> None:
            self.async_write_ha_state()

        self._unsub = self._controller.add_mode_listener(_on_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            with contextlib.suppress(Exception):
                self._unsub()
            self._unsub = None

    @property
    def device_info(self):
        base = _base_name(self._entry)
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": base,
            "manufacturer": "KriVaTri",
            "model": "EVCM",
        }

    @property
    def native_value(self) -> Optional[str]:
        return self._controller.get_phase_status_value()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._controller.get_phase_status_attrs()


class _ThresholdSensor(SensorEntity):
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:arrow-expand-vertical"
    _attr_has_entity_name = False

    def __init__(
        self,
        *,
        entry: ConfigEntry,
        key: str,
        default: float | int,
        name: str,
        unique_suffix: str,
        entity_id: str,
    ) -> None:
        self._entry = entry
        self._key = key
        self._default = default
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{unique_suffix}"
        self.entity_id = entity_id

    @property
    def device_info(self):
        base = _base_name(self._entry)
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": base,
            "manufacturer": "KriVaTri",
            "model": "EVCM",
        }

    @property
    def native_value(self) -> Optional[float]:
        eff = _effective(self._entry)
        raw = eff.get(self._key, self._default)
        try:
            return float(raw)
        except (ValueError, TypeError):
            return float(self._default)


# EOF
