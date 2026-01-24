from __future__ import annotations

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
)
from .controller import EVLoadController


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

        data = hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}
        controller: Optional[EVLoadController] = data.get("controller")
        if controller is not None:
            entities.append(
                _PhaseModeSensor(
                    controller=controller,
                    entry=entry,
                    name=f"{base} Phase mode",
                    entity_id=f"sensor.{base_id}_phase_mode",
                )
            )

    async_add_entities(entities)


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
