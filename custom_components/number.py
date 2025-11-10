from __future__ import annotations

from typing import Optional

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import slugify

from .const import DOMAIN, CONF_NAME
from .controller import EVLoadController
from .priority import async_get_order, async_set_entry_order_index


def _base_name(entry: ConfigEntry) -> str:
    name = (entry.data.get(CONF_NAME) or entry.title or "EVCM").strip()
    return name or "EVCM"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}
    controller: Optional[EVLoadController] = data.get("controller")
    if controller is None:
        return

    base = _base_name(entry)

    # UI namen
    friendly_name_soc = f"{base} SOC limit"
    object_id_soc = slugify(f"evcm {base} SOC limit")

    friendly_name_order = f"{base} priority order"
    object_id_order = slugify(f"evcm {base} priority order")

    entities: list[NumberEntity] = [
        _SocLimitNumber(controller, entry.entry_id, friendly_name_soc, object_id_soc),
        _PriorityOrderNumber(hass, entry, friendly_name_order, object_id_order),
    ]
    async_add_entities(entities)


class _SocLimitNumber(NumberEntity):
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = "%"
    _attr_suggested_display_precision = 0

    def __init__(self, controller: EVLoadController, entry_id: str, friendly_name: str, object_id: str) -> None:
        self._controller = controller
        self._entry_id = entry_id
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_soc_limit"
        self._attr_name = friendly_name  # UI name (no evcm)
        self.entity_id = f"number.{object_id}"  # enforce entity_id with evcm prefix

    @property
    def device_info(self):
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        base = _base_name(entry) if entry else "EVCM"
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": base,
            "manufacturer": "Custom",
            "model": "EVCM",
        }

    @property
    def native_value(self) -> Optional[float]:
        val = self._controller.soc_limit_percent
        return None if val is None else int(val)

    async def async_set_native_value(self, value: float) -> None:
        iv = max(0, min(100, int(round(float(value)))))
        self._controller.set_soc_limit_percent(iv)
        self.async_write_ha_state()


class _PriorityOrderNumber(NumberEntity):
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_suggested_display_precision = 0

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, friendly_name: str, object_id: str) -> None:
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_priority_order"
        self._attr_name = friendly_name
        self.entity_id = f"number.{object_id}"
        self._cached_index_1b: Optional[int] = None
        self._cached_max: int = 1

    async def async_added_to_hass(self) -> None:
        await self._refresh_cache()
        # Luister naar globale refresh (nieuwe/verwijderde entries, prioriteitswijziging, volgorde)
        self.async_on_remove(self.hass.bus.async_listen("evcm_priority_refresh", self._handle_refresh_event))

    @property
    def device_info(self):
        base = _base_name(self._entry)
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": base,
            "manufacturer": "Custom",
            "model": "EVCM",
        }

    @property
    def native_min_value(self) -> float:
        # HA verwacht float, maar int is ook toegestaan; 1 zonder decimalen
        return 1

    @property
    def native_max_value(self) -> float:
        # Geef integer terug om decimalen in UI te vermijden
        return self._cached_max

    @property
    def native_value(self) -> Optional[float]:
        # Geef integer terug i.p.v. float(…)
        return None if self._cached_index_1b is None else self._cached_index_1b

    async def async_set_native_value(self, value: float) -> None:
        # Forceer integer index
        idx = int(round(float(value)))
        if idx < 1:
            idx = 1
        await async_set_entry_order_index(self.hass, self._entry.entry_id, idx)
        await self._refresh_cache()
        self.async_write_ha_state()

    async def _refresh_cache(self) -> None:
        order = await async_get_order(self.hass)
        self._cached_max = max(1, len(order) or 1)
        try:
            self._cached_index_1b = order.index(self._entry.entry_id) + 1
        except ValueError:
            # Als niet gevonden, zet achteraan en sync
            order.append(self._entry.entry_id)
            await async_set_entry_order_index(self.hass, self._entry.entry_id, len(order))
            self._cached_index_1b = len(order)
            self._cached_max = len(order)

    async def _handle_refresh_event(self, _event) -> None:
        await self._refresh_cache()
        self.async_write_ha_state()