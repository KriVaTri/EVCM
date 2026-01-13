from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Optional

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .const import (
    DOMAIN,
    PLANNER_START_ENTITY_NAME,
    PLANNER_STOP_ENTITY_NAME,
    CONF_NAME,
    PLANNER_DATETIME_UPDATED_EVENT,
)
from .controller import EVLoadController


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
    start_object_id = slugify(f"evcm {base} {PLANNER_START_ENTITY_NAME}")
    stop_object_id = slugify(f"evcm {base} {PLANNER_STOP_ENTITY_NAME}")

    entities: list[DateTimeEntity] = [
        _PlannerDateTime(controller, entry.entry_id, True, f"{base} {PLANNER_START_ENTITY_NAME}", start_object_id),
        _PlannerDateTime(controller, entry.entry_id, False, f"{base} {PLANNER_STOP_ENTITY_NAME}", stop_object_id),
    ]
    async_add_entities(entities)


class _PlannerDateTime(DateTimeEntity):
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        controller: EVLoadController,
        entry_id: str,
        is_start: bool,
        friendly_name: str,
        object_id: str
    ) -> None:
        self._controller = controller
        self._entry_id = entry_id
        self._is_start = is_start
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_planner_{'start' if is_start else 'stop'}"
        self._attr_name = friendly_name
        self.entity_id = f"datetime.{object_id}"
        self._unsub_bus = None

    async def async_added_to_hass(self) -> None:
        @callback
        def _handle_update(event):
            if event.data.get("entry_id") == self._entry_id:
                self.async_write_ha_state()

        self._unsub_bus = self.hass.bus.async_listen(
            PLANNER_DATETIME_UPDATED_EVENT,
            _handle_update
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_bus:
            with contextlib.suppress(Exception):
                self._unsub_bus()
            self._unsub_bus = None

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
    def native_value(self) -> Optional[datetime]:
        return (
            self._controller.planner_start_dt
            if self._is_start
            else self._controller.planner_stop_dt
        )

    async def async_set_value(self, value: datetime) -> None:
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        else:
            value = dt_util.as_local(value)

        if self._is_start:
            await self._controller.async_set_planner_start_dt_persist(value)
        else:
            await self._controller.async_set_planner_stop_dt_persist(value)

        self.async_write_ha_state()

# EOF
