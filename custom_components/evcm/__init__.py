from __future__ import annotations

import logging
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_OPT_MODE_ECO,
    CONF_PLANNER_START_ISO,
    CONF_PLANNER_STOP_ISO,
    CONF_SOC_LIMIT_PERCENT,
)
from .priority import async_cleanup_priority_if_removed

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

IGNORED_OPTION_KEYS = {
    CONF_OPT_MODE_ECO,
    CONF_PLANNER_START_ISO,
    CONF_PLANNER_STOP_ISO,
    CONF_SOC_LIMIT_PERCENT,
}


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .controller import EVLoadController

    try:
        controller = EVLoadController(hass, entry)
        await controller.async_initialize()
    except Exception as exc:
        _LOGGER.error("Controller initialization failed for %s: %s", DOMAIN, exc)
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][entry.entry_id] = {
            "controller": None,
            "last_options": dict(entry.options),
        }
        return False

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "controller": controller,
        "last_options": dict(entry.options),
    }

    # Post-start hook: must schedule in a thread-safe way.
    # hass.add_job is safe from any context; @callback ensures listener runs in loop.
    if hass.is_running:
        hass.add_job(controller.async_post_start)
    else:
        @callback
        def _on_started(_event):
            hass.add_job(controller.async_post_start)
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_started)

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception as exc:
        _LOGGER.error("Platform forward failed: %s", exc)
        try:
            await controller.async_shutdown()
        except Exception:
            pass
        return False

    entry.async_on_unload(entry.add_update_listener(_update_listener))

    await async_cleanup_priority_if_removed(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    controller = data.get("controller") if data else None

    unload_ok = True
    try:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    except Exception as exc:
        _LOGGER.warning("Platform unload failed: %s", exc)
        unload_ok = False

    if controller:
        try:
            await controller.async_shutdown()
        except Exception as exc:
            _LOGGER.debug("Controller shutdown raised: %s", exc)

    root = hass.data.get(DOMAIN, {})
    if entry.entry_id in root:
        root.pop(entry.entry_id, None)

    def _is_entry_dict(v):
        return isinstance(v, dict) and "controller" in v

    remaining_entry_dicts = [k for k, v in root.items() if _is_entry_dict(v)]

    anchor_removed = root.get("_priority_anchor_entry_id") == entry.entry_id

    if anchor_removed and remaining_entry_dicts:
        new_anchor = sorted(remaining_entry_dicts)[0]
        root["_priority_anchor_entry_id"] = new_anchor
        hass.bus.async_fire("evcm_priority_anchor_changed", {"new_anchor_entry_id": new_anchor})
        _LOGGER.debug("Priority anchor migrated to %s", new_anchor)
    elif anchor_removed and not remaining_entry_dicts:
        root.pop("_priority_anchor_entry_id", None)

    if not remaining_entry_dicts:
        for internal_key in list(root.keys()):
            if internal_key.startswith("_"):
                root.pop(internal_key, None)

    if not root:
        hass.data.pop(DOMAIN, None)

    await async_cleanup_priority_if_removed(hass)
    return unload_ok


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    domain_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not domain_data:
        await hass.config_entries.async_reload(entry.entry_id)
        return

    prev_opts = dict(domain_data.get("last_options", {}))
    curr_opts = dict(entry.options)

    def strip_ignored(d: dict) -> dict:
        return {k: v for k, v in d.items() if k not in IGNORED_OPTION_KEYS}

    if strip_ignored(prev_opts) == strip_ignored(curr_opts):
        domain_data["last_options"] = curr_opts
        return

    domain_data["last_options"] = curr_opts
    await hass.config_entries.async_reload(entry.entry_id)
