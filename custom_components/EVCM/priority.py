from __future__ import annotations

import logging
from typing import Optional, List

from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_NAME

_LOGGER = logging.getLogger(__name__)

PRIORITY_STORE_VERSION = 1
PRIORITY_STORE_KEY = f"{DOMAIN}_global"


def _store(hass: HomeAssistant):
    from homeassistant.helpers.storage import Store
    return Store(hass, PRIORITY_STORE_VERSION, PRIORITY_STORE_KEY)


async def _load_raw(hass: HomeAssistant) -> dict:
    data = await _store(hass).async_load()
    return data if isinstance(data, dict) else {}


async def _save_raw(hass: HomeAssistant, data: dict) -> None:
    await _store(hass).async_save({"version": PRIORITY_STORE_VERSION, **data})


def _existing_entry_ids(hass: HomeAssistant) -> List[str]:
    return [e.entry_id for e in hass.config_entries.async_entries(DOMAIN)]


def _name_for(hass: HomeAssistant, entry_id: str) -> str:
    e = hass.config_entries.async_get_entry(entry_id)
    if not e:
        return entry_id
    nm = (e.data.get(CONF_NAME) or e.title or e.entry_id).strip() or e.entry_id
    return nm


def _sorted_by_name(hass: HomeAssistant, entry_ids: List[str]) -> List[str]:
    return sorted(entry_ids, key=lambda eid: _name_for(hass, eid).lower())


def _notify_all_priority_change(hass: HomeAssistant) -> None:
    """Notify all controllers about global priority/order/mode changes."""
    updated = 0
    for key, data in (hass.data.get(DOMAIN, {}) or {}).items():
        if not isinstance(data, dict):
            continue
        ctl = data.get("controller")
        if ctl:
            try:
                ctl.on_global_priority_changed()
                updated += 1
            except Exception:
                _LOGGER.debug("Controller notify failed for %s", key, exc_info=True)
    hass.bus.async_fire("evcm_priority_refresh")
    _LOGGER.debug("Priority change notification dispatched (controllers updated=%d)", updated)


# ---------------- Priority Mode ----------------
async def async_get_priority_mode_enabled(hass: HomeAssistant) -> bool:
    data = await _load_raw(hass)
    return bool(data.get("priority_mode_enabled", False))


async def async_set_priority_mode_enabled(hass: HomeAssistant, enabled: bool) -> None:
    data = await _load_raw(hass)
    prev = bool(data.get("priority_mode_enabled", False))
    data["priority_mode_enabled"] = bool(enabled)
    await _save_raw(hass, data)
    if prev != enabled:
        _LOGGER.debug("Priority mode set to %s", enabled)
        _notify_all_priority_change(hass)


# ---------------- Current / Preferred ----------------
async def async_get_priority(hass: HomeAssistant) -> Optional[str]:
    data = await _load_raw(hass)
    pid = data.get("priority_entry_id")
    exist = _existing_entry_ids(hass)
    if isinstance(pid, str) and pid in exist:
        return pid
    return None


async def async_get_preferred_priority(hass: HomeAssistant) -> Optional[str]:
    data = await _load_raw(hass)
    pref = data.get("preferred_priority_entry_id")
    exist = _existing_entry_ids(hass)
    if isinstance(pref, str) and pref in exist:
        return pref
    return None


async def _set_priority_value(hass: HomeAssistant, entry_id: Optional[str], notify: bool = True) -> None:
    data = await _load_raw(hass)
    exist = _existing_entry_ids(hass)
    valid = entry_id if isinstance(entry_id, str) and entry_id in exist else None
    data["priority_entry_id"] = valid
    await _save_raw(hass, data)
    _LOGGER.debug("Global priority (current) set to: %s", valid)
    if notify:
        _notify_all_priority_change(hass)


async def async_set_priority(hass: HomeAssistant, entry_id: Optional[str]) -> None:
    """
    Set current priority (and preferred if valid) WITHOUT changing the order.
    Order is managed only by the dedicated 'order' UI.
    """
    data = await _load_raw(hass)
    exist = _existing_entry_ids(hass)
    valid = entry_id if isinstance(entry_id, str) and entry_id in exist else None
    data["priority_entry_id"] = valid
    if valid:
        data["preferred_priority_entry_id"] = valid
    await _save_raw(hass, data)
    _LOGGER.debug(
        "Priority set (current=%s, preferred=%s)",
        data.get("priority_entry_id"),
        data.get("preferred_priority_entry_id"),
    )
    _notify_all_priority_change(hass)


# ---------------- Eligibility helper ----------------
def _is_entry_eligible(hass: HomeAssistant, entry_id: str) -> bool:
    """
    Eligible voor priority als:
      - kabel verbonden
      - Start/Stop ON
      - planner venster laat start toe
      - SoC laat start toe
    """
    data = (hass.data.get(DOMAIN, {}) or {}).get(entry_id) or {}
    ctl = data.get("controller")
    if not ctl:
        return False
    try:
        if not ctl.is_cable_connected():
            return False
        if not ctl.get_mode("start_stop"):
            return False
        if hasattr(ctl, "_planner_window_allows_start") and not ctl._planner_window_allows_start():
            return False
        if hasattr(ctl, "_soc_allows_start") and not ctl._soc_allows_start():
            return False
        return True
    except Exception:
        return False


# ---------------- Order ----------------
async def async_get_order(hass: HomeAssistant) -> List[str]:
    data = await _load_raw(hass)
    order: List[str] = [e for e in data.get("order", []) if isinstance(e, str)]
    exist = _existing_entry_ids(hass)
    order = [e for e in order if e in exist]
    seen = set()
    order = [e for e in order if not (e in seen or seen.add(e))]
    missing = [e for e in exist if e not in order]
    order += _sorted_by_name(hass, missing)
    return order

async def async_get_priority_order(hass: HomeAssistant) -> List[str]:
    return await async_get_order(hass)


async def async_set_order(hass: HomeAssistant, order: List[str]) -> None:
    exist = _existing_entry_ids(hass)
    order = [e for e in order if e in exist]
    seen = set()
    order = [e for e in order if not (e in seen or seen.add(e))]
    order += [e for e in _sorted_by_name(hass, exist) if e not in order]
    data = await _load_raw(hass)
    data["order"] = order

    top = order[0] if order else None
    data["preferred_priority_entry_id"] = top if isinstance(top, str) else None

    await _save_raw(hass, data)
    _LOGGER.debug(
        "Priority order updated: %s (preferred set to %s)",
        [_name_for(hass, e) for e in order],
        _name_for(hass, top) if top else None,
    )

    try:
        hass.bus.async_fire("evcm_priority_refresh")
    except Exception:
        _LOGGER.debug("Failed to fire evcm_priority_refresh after order update", exc_info=True)

    await async_align_current_with_order(hass)


async def async_set_entry_order_index(hass: HomeAssistant, entry_id: str, index_one_based: int) -> None:
    """
    Verplaats entry naar een index (1-based) in de orderlijst.
    Behoud alle bestaande entries en normaliseer de lijst.
    """
    if entry_id not in _existing_entry_ids(hass):
        return
    order = await async_get_order(hass)
    order = [e for e in order if e != entry_id]
    # clamp index to [1, len(order)+1]
    index = max(1, min(len(order) + 1, int(index_one_based)))
    order.insert(index - 1, entry_id)
    await async_set_order(hass, order)


# ---------------- Cleanup ----------------
async def async_cleanup_priority_if_removed(hass: HomeAssistant) -> None:
    data = await _load_raw(hass)
    exist = _existing_entry_ids(hass)
    changed = False

    pid = data.get("priority_entry_id")
    if pid and pid not in exist:
        data["priority_entry_id"] = None
        changed = True

    pref = data.get("preferred_priority_entry_id")
    if pref and pref not in exist:
        data["preferred_priority_entry_id"] = None
        changed = True

    old_order: List[str] = [e for e in data.get("order", []) if isinstance(e, str)]
    new_order = [e for e in old_order if e in exist]
    for e in _sorted_by_name(hass, exist):
        if e not in new_order:
            new_order.append(e)
    if new_order != old_order:
        data["order"] = new_order
        changed = True

    if changed:
        await _save_raw(hass, data)
        _notify_all_priority_change(hass)


# ---------------- Advance / Align helpers ----------------
async def _first_eligible_by_order(hass: HomeAssistant) -> Optional[str]:
    """
    Kies eerste kandidaat in 'order' die geschikt is:
      kabel + Start/Stop + planner + SoC
    Valt terug op eerste in order als geen geschikte kandidaten gevonden.
    """
    order = await async_get_order(hass)
    for eid in order:
        if _is_entry_eligible(hass, eid):
            return eid
    return order[0] if order else None


async def async_align_current_with_order(hass: HomeAssistant) -> None:
    """Indien priority mode AAN: zet current naar 'first eligible' (fallback: eerste in order)."""
    if not await async_get_priority_mode_enabled(hass):
        return
    wanted = await _first_eligible_by_order(hass)
    current = await async_get_priority(hass)
    if wanted != current:
        await _set_priority_value(hass, wanted)


async def async_advance_priority_to_next(hass: HomeAssistant, current_entry_id: str) -> None:
    """
    Advance naar eerstvolgende geschikte entry:
      kabel + Start/Stop + planner + SoC
    Als geen geschikte kandidaat → restore preferred of None.
    """
    entries = _existing_entry_ids(hass)
    if not entries or current_entry_id not in entries:
        preferred = await async_get_preferred_priority(hass)
        await _set_priority_value(hass, preferred)
        return

    order = await async_get_order(hass)
    try:
        idx = order.index(current_entry_id)
    except ValueError:
        preferred = await async_get_preferred_priority(hass)
        await _set_priority_value(hass, preferred)
        return

    n = len(order)
    for step in range(1, n + 1):
        cand_id = order[(idx + step) % n]
        if cand_id == current_entry_id:
            continue
        if _is_entry_eligible(hass, cand_id):
            await _set_priority_value(hass, cand_id)
            _LOGGER.info("Priority advanced from %s to %s", current_entry_id, cand_id)
            return

    preferred = await async_get_preferred_priority(hass)
    await _set_priority_value(hass, preferred)
    if preferred:
        _LOGGER.info("No suitable next; priority restored to preferred %s", preferred)
    else:
        _LOGGER.info("Priority cleared (no suitable next and no preferred set)")
