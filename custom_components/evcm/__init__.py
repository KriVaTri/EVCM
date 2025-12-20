from __future__ import annotations

import logging
import contextlib
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

    _LOGGER.debug("EVCM: async_setup_entry starting for entry_id=%s", entry.entry_id)

    # Instantiate controller and store immediately so platforms can find it
    hass.data.setdefault(DOMAIN, {})

    try:
        controller = EVLoadController(hass, entry)
    except Exception as exc:
        _LOGGER.error("Controller construction failed for %s: %s", DOMAIN, exc, exc_info=True)
        hass.data[DOMAIN][entry.entry_id] = {
            "controller": None,
            "last_options": dict(entry.options),
            "post_start_scheduled": False,
        }
        # Don't block HA startup on failure of one entry
        return False

    hass.data[DOMAIN][entry.entry_id] = {
        "controller": controller,
        "last_options": dict(entry.options),
        "post_start_scheduled": False,
    }

    # Initialize controller in the background to avoid blocking HA startup
    init_task = hass.async_create_task(controller.async_initialize())

    def _log_init_result(task):
        try:
            task.result()
            _LOGGER.debug("Controller initialization completed for entry_id=%s", entry.entry_id)
        except Exception as exc:
            _LOGGER.error("Controller initialization failed for %s: %s", DOMAIN, exc, exc_info=True)

    init_task.add_done_callback(_log_init_result)

    # Post-start hook: must schedule exactly once per entry in a thread-safe way.
    # hass.add_job is safe from any context; @callback ensures listener runs in loop.
    entry_data = hass.data[DOMAIN][entry.entry_id]
    if not entry_data.get("post_start_scheduled"):
        entry_data["post_start_scheduled"] = True
        if hass.is_running:
            _LOGGER.debug("Scheduling controller.async_post_start immediately (HA is running) for entry_id=%s", entry.entry_id)
            hass.add_job(controller.async_post_start)
        else:
            @callback
            def _on_started(_event):
                _LOGGER.debug("Scheduling controller.async_post_start on HA started for entry_id=%s", entry.entry_id)
                hass.add_job(controller.async_post_start)
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_started)
    else:
        _LOGGER.debug("Post-start already scheduled; skipping duplicate for entry_id=%s", entry.entry_id)

    try:
        _LOGGER.debug("Forwarding platforms for entry_id=%s: %s", entry.entry_id, PLATFORMS)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        _LOGGER.debug("Platform forward completed for entry_id=%s", entry.entry_id)
    except Exception as exc:
        _LOGGER.error("Platform forward failed: %s", exc, exc_info=True)
        try:
            await controller.async_shutdown()
        except Exception:
            pass
        return False

    entry.async_on_unload(entry.add_update_listener(_update_listener))

    await async_cleanup_priority_if_removed(hass)
    _LOGGER.debug("EVCM: async_setup_entry completed for entry_id=%s", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug("EVCM: async_unload_entry starting for entry_id=%s", entry.entry_id)
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    controller = data.get("controller") if data else None

    unload_ok = True
    try:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        _LOGGER.debug("Platform unload result for entry_id=%s: %s", entry.entry_id, unload_ok)
    except Exception as exc:
        _LOGGER.warning("Platform unload failed: %s", exc, exc_info=True)
        unload_ok = False

    if controller:
        try:
            await controller.async_shutdown()
        except Exception as exc:
            _LOGGER.debug("Controller shutdown raised: %s", exc, exc_info=True)

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
    _LOGGER.debug("EVCM: async_unload_entry completed for entry_id=%s", entry.entry_id)
    return unload_ok


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    _LOGGER.debug("EVCM: options updated for entry_id=%s", entry.entry_id)
    domain_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not domain_data:
        _LOGGER.debug("EVCM: domain_data missing, reloading entry_id=%s", entry.entry_id)
        await hass.config_entries.async_reload(entry.entry_id)
        return

    prev_opts = dict(domain_data.get("last_options", {}))
    curr_opts = dict(entry.options)

    def strip_ignored(d: dict) -> dict:
        return {k: v for k, v in d.items() if k not in IGNORED_OPTION_KEYS}

    if strip_ignored(prev_opts) == strip_ignored(curr_opts):
        domain_data["last_options"] = curr_opts
        _LOGGER.debug("EVCM: no effective option changes (ignored keys excluded) for entry_id=%s", entry.entry_id)
        return

    domain_data["last_options"] = curr_opts
    _LOGGER.debug("EVCM: effective option changes detected; reloading entry_id=%s", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)
