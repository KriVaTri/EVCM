from __future__ import annotations

import contextlib
from typing import Optional, Callable

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import slugify

from .const import (
    DOMAIN,
    CONF_NAME,
    NET_POWER_TARGET_MIN_W,
    NET_POWER_TARGET_MAX_W,
    NET_POWER_TARGET_STEP_W,
    DEFAULT_SOC_LIMIT_PERCENT,
    EXT_IMPORT_LIMIT_MIN_W,
    EXT_IMPORT_LIMIT_MAX_W,
    EXT_IMPORT_LIMIT_STEP_W,
)
from .controller import EVLoadController
from .priority import async_get_order, async_set_entry_order_index


def _base_name(entry: ConfigEntry) -> str:
    name = (entry.data.get(CONF_NAME) or entry.title or "EVCM").strip()
    return name or "EVCM"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
):
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}
    controller: Optional[EVLoadController] = data.get("controller")
    if controller is None:
        return

    base = _base_name(entry)

    friendly_name_soc = f"{base} SoC limit"
    object_id_soc = slugify(f"evcm {base} SoC limit")

    friendly_name_order = f"{base} priority order"
    object_id_order = slugify(f"evcm {base} priority order")

    friendly_name_target = f"{base} net power target"
    object_id_target = slugify(f"evcm {base} net power target")

    friendly_name_peak = f"{base} Max peak avg"
    object_id_peak = slugify(f"evcm {base} Max peak avg")

    entities: list[NumberEntity] = [
        _SocLimitNumber(controller, entry.entry_id, friendly_name_soc, object_id_soc),
        _PriorityOrderNumber(hass, entry, friendly_name_order, object_id_order),
        _NetPowerTargetNumber(controller, entry.entry_id, friendly_name_target, object_id_target),
        _MaxPeakAvgNumber(controller, entry.entry_id, friendly_name_peak, object_id_peak),
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
    _attr_icon = "mdi:battery-medium"

    def __init__(self, controller: EVLoadController, entry_id: str, friendly_name: str, object_id: str) -> None:
        self._controller = controller
        self._entry_id = entry_id
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_soc_limit"
        self._attr_name = friendly_name
        self.entity_id = f"number.{object_id}"

    @property
    def device_info(self):
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        base = _base_name(entry) if entry else "EVCM"
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": base,
            "manufacturer": "KriVaTri",
            "model": "EVCM",
        }

    @property
    def native_value(self) -> Optional[float]:
        val = self._controller.soc_limit_percent
        return int(val if val is not None else DEFAULT_SOC_LIMIT_PERCENT)

    async def async_added_to_hass(self) -> None:
        if self._controller.soc_limit_percent is None:
            with contextlib.suppress(Exception):
                self._controller.set_soc_limit_percent(DEFAULT_SOC_LIMIT_PERCENT)
        self.async_write_ha_state()

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
    _attr_icon = "mdi:numeric"

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
        self.async_on_remove(
            self.hass.bus.async_listen("evcm_priority_refresh", self._handle_refresh_event)
        )

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
    def native_min_value(self) -> float:
        return 1

    @property
    def native_max_value(self) -> float:
        return self._cached_max

    @property
    def native_value(self) -> Optional[float]:
        return None if self._cached_index_1b is None else self._cached_index_1b

    async def async_set_native_value(self, value: float) -> None:
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
            order.append(self._entry.entry_id)
            await async_set_entry_order_index(self.hass, self._entry.entry_id, len(order))
            self._cached_index_1b = len(order)
            self._cached_max = len(order)

    async def _handle_refresh_event(self, _event) -> None:
        await self._refresh_cache()
        self.async_write_ha_state()


class _NetPowerTargetNumber(NumberEntity):
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_step = NET_POWER_TARGET_STEP_W
    _attr_native_max_value = NET_POWER_TARGET_MAX_W
    _attr_native_unit_of_measurement = "W"
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:flash"

    def __init__(self, controller: EVLoadController, entry_id: str, friendly_name: str, object_id: str) -> None:
        self._controller = controller
        self._entry_id = entry_id
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_net_power_target"
        self._attr_name = friendly_name
        self.entity_id = f"number.{object_id}"
        self._unsub_mode_listener: Optional[Callable[[], None]] = None

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_update() -> None:
            self.async_write_ha_state()

        self._unsub_mode_listener = self._controller.add_mode_listener(_on_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_mode_listener:
            with contextlib.suppress(Exception):
                self._unsub_mode_listener()
            self._unsub_mode_listener = None

    @property
    def device_info(self):
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        base = _base_name(entry) if entry else "EVCM"
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": base,
            "manufacturer": "KriVaTri",
            "model": "EVCM",
        }

    @property
    def native_min_value(self) -> float:
        """Dynamic minimum based on current lower threshold + margin."""
        try:
            return float(self._controller._net_power_target_min_w())
        except Exception:
            return float(NET_POWER_TARGET_MIN_W)

    @property
    def native_value(self) -> Optional[float]:
        return int(self._controller.net_power_target_w)

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the dynamic minimum for debugging/UI."""
        attrs = {}
        try:
            attrs["dynamic_min_w"] = self._controller._net_power_target_min_w()
            attrs["current_lower_threshold_w"] = int(self._controller._current_lower())
            attrs["margin_w"] = 300
        except Exception:
            pass
        return attrs

    async def async_set_native_value(self, value: float) -> None:
        self._controller.set_net_power_target_w(value)
        self.async_write_ha_state()


class _MaxPeakAvgNumber(NumberEntity):
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_step = EXT_IMPORT_LIMIT_STEP_W
    _attr_native_min_value = EXT_IMPORT_LIMIT_MIN_W
    _attr_native_max_value = EXT_IMPORT_LIMIT_MAX_W
    _attr_native_unit_of_measurement = "W"
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:chart-bell-curve"

    def __init__(self, controller: EVLoadController, entry_id: str, friendly_name: str, object_id: str) -> None:
        self._controller = controller
        self._entry_id = entry_id
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_ext_import_limit"
        self._attr_name = friendly_name
        self.entity_id = f"number.{object_id}"

    @property
    def device_info(self):
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        base = _base_name(entry) if entry else "EVCM"
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": base,
            "manufacturer": "KriVaTri",
            "model": "EVCM",
        }

    @property
    def native_value(self) -> Optional[float]:
        val = self._controller.ext_import_limit_w
        return int(val or 0)

    async def async_set_native_value(self, value: float) -> None:
        self._controller.set_ext_import_limit_w(value)
        self.async_write_ha_state()

# EOF
