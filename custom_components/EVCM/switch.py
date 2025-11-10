from __future__ import annotations

import contextlib
from typing import Any, Optional, Callable

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import slugify

from .const import DOMAIN, MODES, MODE_LABELS, CONF_NAME
from .controller import EVLoadController
from .priority import (
    async_get_priority_mode_enabled,
    async_set_priority_mode_enabled,
    async_get_order,
    async_get_priority,
    async_set_priority,
)


def _base_name(entry: ConfigEntry) -> str:
    name = (entry.data.get(CONF_NAME) or entry.title or "EVCM").strip()
    return name or "EVCM"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}
    controller: Optional[EVLoadController] = data.get("controller")
    if controller is None:
        return

    new_entities: list[SwitchEntity] = []

    # Add a per-entry Priority Charging proxy switch (same global state, per-device placement)
    base = _base_name(entry)
    prio_obj_id = slugify(f"evcm {base} Priority Charging")
    new_entities.append(PriorityChargingSwitchPerEntry(hass, entry.entry_id, friendly_name=f"{base} Priority Charging", object_id=prio_obj_id))

    # Mode switches (per entry)
    for mode_key in MODES:
        label = MODE_LABELS.get(mode_key, mode_key)
        friendly_name = f"{base} {label}"
        object_id = slugify(f"evcm {base} {label}")
        new_entities.append(_ModeSwitch(controller, entry.entry_id, mode_key, friendly_name, object_id))

    async_add_entities(new_entities)


class PriorityChargingSwitchPerEntry(SwitchEntity):
    """
    Per-entry proxy for the global Priority Charging mode.
    All instances read/write the same global flag and stay in sync via 'evcm_priority_refresh' bus events.
    """
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:star-circle"

    def __init__(self, hass: HomeAssistant, entry_id: str, friendly_name: str, object_id: str) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_priority_charging"
        self._attr_name = friendly_name
        self.entity_id = f"switch.{object_id}"
        self._is_on: bool = False
        self._unsub_bus: Optional[Callable[[], None]] = None

    async def async_added_to_hass(self) -> None:
        await self._refresh()
        # Refresh when global priority mode or priority/order changes
        self._unsub_bus = self.hass.bus.async_listen("evcm_priority_refresh", self._handle_global_refresh)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_bus:
            with contextlib.suppress(Exception):
                self._unsub_bus()
            self._unsub_bus = None

    async def _handle_global_refresh(self, _event) -> None:
        await self._refresh()
        self.async_write_ha_state()

    async def _refresh(self):
        self._is_on = await async_get_priority_mode_enabled(self.hass)

    async def async_update(self):
        await self._refresh()

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        # Enable global mode
        await async_set_priority_mode_enabled(self.hass, True)
        await self._refresh()
        # Ensure current priority is set if missing (choose first in order)
        order = await async_get_order(self.hass)
        current = await async_get_priority(self.hass)
        if not current and order:
            await async_set_priority(self.hass, order[0])
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await async_set_priority_mode_enabled(self.hass, False)
        await self._refresh()
        self.async_write_ha_state()

    @property
    def device_info(self) -> dict[str, Any]:
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        base = _base_name(entry) if entry else "EVCM"
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": base,
            "manufacturer": "Custom",
            "model": "EVCM",
        }


class _ModeSwitch(SwitchEntity):
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, controller: EVLoadController, entry_id: str, mode_key: str, friendly_name: str, object_id: str) -> None:
        self._controller = controller
        self._entry_id = entry_id
        self._mode_key = mode_key
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_mode_{mode_key}"
        self._attr_name = friendly_name
        self.entity_id = f"switch.{object_id}"
        self._unsub_mode_listener: Optional[Callable[[], None]] = None

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_modes_changed() -> None:
            self.async_write_ha_state()
        self._unsub_mode_listener = self._controller.add_mode_listener(_on_modes_changed)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_mode_listener:
            with contextlib.suppress(Exception):
                self._unsub_mode_listener()
            self._unsub_mode_listener = None

    @property
    def is_on(self) -> bool:
        try:
            return bool(self._controller.get_mode(self._mode_key))
        except Exception:
            return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._controller.set_mode(self._mode_key, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._controller.set_mode(self._mode_key, False)
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return True

    @property
    def device_info(self) -> dict[str, Any]:
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        base = _base_name(entry) if entry else "EVCM"
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": base,
            "manufacturer": "Custom",
            "model": "EVCM",
        }
