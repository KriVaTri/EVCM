from __future__ import annotations

from typing import Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
)


def _base_name(entry: ConfigEntry) -> str:
    """Same naming rule as switch.py/number.py/datetime.py."""
    name = (entry.data.get(CONF_NAME) or entry.title or "EVCM").strip()
    return name or "EVCM"


def _base_identifier(entry: ConfigEntry) -> str:
    """Return a short slug identifier from the user's configured name, or fall back to entry_id."""
    name = (entry.data.get(CONF_NAME) or entry.title).strip()
    if name:
        return slugify(name)
    return f"entry_{entry.entry_id}"


def _effective(entry: ConfigEntry) -> dict:
    """Return the effective merged data/options for the entry."""
    return {**entry.data, **entry.options}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Setup the threshold sensors as part of the config entry."""
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

    async_add_entities(entities)


class _ThresholdSensor(SensorEntity):
    """Sensor for a single ECO threshold."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:arrow-decision"
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
        """Return the device information for the sensor."""
        base = _base_name(self._entry)
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": base,
            "manufacturer": "KriVaTri",
            "model": "EVCM",
        }

    @property
    def native_value(self) -> Optional[float]:
        """Return the current value of the threshold."""
        eff = _effective(self._entry)
        raw = eff.get(self._key, self._default)
        try:
            return float(raw)
        except (ValueError, TypeError):
            return float(self._default)
