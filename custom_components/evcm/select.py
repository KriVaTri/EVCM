from __future__ import annotations

import contextlib
import asyncio
from typing import Any, Optional, Callable

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import slugify

from .const import (
    DOMAIN,
    CONF_NAME,
    CONF_PHASE_SWITCH_SUPPORTED,
    PHASE_SWITCH_MODE_OPTIONS,
    PHASE_SWITCH_MODE_AUTO,
    PHASE_SWITCH_MODE_FORCE_1P,
    PHASE_SWITCH_MODE_FORCE_3P,
    PHASE_SWITCH_SOURCE_FORCE,
    CONF_PHASE_SWITCH_CONTROL_MODE,
    PHASE_CONTROL_INTEGRATION,
    PHASE_CONTROL_WALLBOX,
    DEFAULT_PHASE_SWITCH_CONTROL_MODE,
)
from .controller import EVLoadController

import logging
_LOGGER = logging.getLogger(__name__)


def _base_name(entry: ConfigEntry) -> str:
    name = (entry.data.get(CONF_NAME) or entry.title or "EVCM").strip()
    return name or "EVCM"


def _effective_config(entry: ConfigEntry) -> dict:
    return {**entry.data, **entry.options}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}
    controller: Optional[EVLoadController] = data.get("controller")
    if controller is None:
        return

    eff = _effective_config(entry)
    if not bool(eff.get(CONF_PHASE_SWITCH_SUPPORTED, False)):
        return

    base = _base_name(entry)
    object_id = slugify(f"evcm {base} Phase switching mode")
    async_add_entities([
        _PhaseSwitchModeSelect(controller, entry, friendly_name=f"{base} Phase switching mode", object_id=object_id)
    ])


class _PhaseSwitchModeSelect(SelectEntity):
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:sine-wave"
    _attr_options = PHASE_SWITCH_MODE_OPTIONS

    def __init__(self, controller: EVLoadController, entry: ConfigEntry, friendly_name: str, object_id: str) -> None:
        self._controller = controller
        self._entry = entry
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_phase_switch_mode"
        self._attr_name = friendly_name
        self.entity_id = f"select.{object_id}"
        self._unsub_mode_listener: Optional[Callable[[], None]] = None
        self._forced_ui_option: Optional[str] = None

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

    def _is_wallbox_controlled(self) -> bool:
        """Check if phase switching is wallbox-controlled."""
        eff = _effective_config(self._entry)
        control_mode = eff.get(CONF_PHASE_SWITCH_CONTROL_MODE, DEFAULT_PHASE_SWITCH_CONTROL_MODE)
        return control_mode == PHASE_CONTROL_WALLBOX

    @property
    def available(self) -> bool:
        """Entity is unavailable when wallbox-controlled mode is active."""
        return not self._is_wallbox_controlled()

    @property
    def current_option(self) -> str | None:
        # If wallbox controlled, show a descriptive state (even though unavailable)
        if self._is_wallbox_controlled():
            return PHASE_SWITCH_MODE_AUTO  # or could return None
        
        # Allow temporary UI override
        if self._forced_ui_option is not None:
            return self._forced_ui_option
        return self._controller.get_phase_switch_mode()

    async def async_select_option(self, option: str) -> None:
        # Block selection when wallbox controlled
        if self._is_wallbox_controlled():
            _LOGGER.debug("Phase switch mode selection blocked: wallbox-controlled mode active")
            return

        if option not in PHASE_SWITCH_MODE_OPTIONS:
            return

        if option == PHASE_SWITCH_MODE_AUTO:
            self._controller.set_phase_switch_auto_enabled(True)
            self._controller._notify_mode_listeners()
            self.async_write_ha_state()
            return

        accepted: bool = False

        if option == PHASE_SWITCH_MODE_FORCE_1P:
            accepted = await self._controller.async_request_phase_switch(target="1p", source=PHASE_SWITCH_SOURCE_FORCE)
            if accepted:
                self._controller.set_phase_switch_auto_enabled(False)
                await self._controller.async_force_phase_profile(alternate=True)

        elif option == PHASE_SWITCH_MODE_FORCE_3P:
            accepted = await self._controller.async_request_phase_switch(target="3p", source=PHASE_SWITCH_SOURCE_FORCE)
            if accepted:
                self._controller.set_phase_switch_auto_enabled(False)
                await self._controller.async_force_phase_profile(alternate=False)

        self._controller._notify_mode_listeners()

        if accepted:
            # Normal refresh
            self.async_write_ha_state()
            return

        # REJECT PATH: keep user's choice visible for 1s, then snap back with near-invisible intermediate
        real = self._controller.get_phase_switch_mode()
        
        # Wait 1s so the user sees what they clicked
        await asyncio.sleep(1.0)

        # Choose an intermediate option different from both clicked and real
        intermediate = PHASE_SWITCH_MODE_AUTO
        if intermediate in (option, real):
            intermediate = (
                PHASE_SWITCH_MODE_FORCE_3P
                if real != PHASE_SWITCH_MODE_FORCE_3P
                else PHASE_SWITCH_MODE_FORCE_1P
            )

        # Publish intermediate then immediately publish real (same tick / near-invisible)
        self._forced_ui_option = intermediate
        self.async_write_ha_state()
        await asyncio.sleep(0)  # yield only; usually not visible

        self._forced_ui_option = real
        self.async_write_ha_state()
        await asyncio.sleep(0)  # yield only

        # Back to controller-driven
        self._forced_ui_option = None
        self.async_write_ha_state()

    @property
    def device_info(self) -> dict[str, Any]:
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        base = _base_name(entry) if entry else "EVCM"
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": base,
            "manufacturer": "KriVaTri",
            "model": "EVCM",
        }

# EOF
