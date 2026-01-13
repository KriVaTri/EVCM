from __future__ import annotations

import logging
import time
from typing import Optional, List, Dict

from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_NAME

_LOGGER = logging.getLogger(__name__)

PRIORITY_STORE_VERSION = 1
PRIORITY_STORE_KEY = f"{DOMAIN}_global"

# Runtime (non-persistent) pauses
_PAUSES_KEY = "priority_pauses"
VALID_PAUSE_REASONS = {"below_lower", "no_data"}


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


def _name_for(hass: HomeAssistant, entry_id: Optional[str]) -> Optional[str]:
    if not entry_id:
        return None
    e = hass.config_entries.async_get_entry(entry_id)
    if not e:
        return entry_id
    nm = (e.data.get(CONF_NAME) or e.title or e.entry_id).strip() or e.entry_id
    return nm


def _sorted_by_name(hass: HomeAssistant, entry_ids: List[str]) -> List[str]:
    return sorted(entry_ids, key=lambda eid: _name_for(hass, eid).lower())


def _runtime(hass: HomeAssistant) -> Dict:
    rh = hass.data.setdefault(DOMAIN, {})
    rh.setdefault(_PAUSES_KEY, {})
    return rh


def _pauses(hass: HomeAssistant) -> Dict[str, Dict[str, float]]:
    return _runtime(hass)[_PAUSES_KEY]


def _notify_all_priority_change(hass: HomeAssistant) -> None:
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


# ---------- Priority mode ----------
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


# ---------- Current / Preferred ----------
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
    _LOGGER.info("Global priority (current) set to: %s", _name_for(hass, valid))
    if notify:
        _notify_all_priority_change(hass)


async def async_set_priority(hass: HomeAssistant, entry_id: Optional[str]) -> None:
    data = await _load_raw(hass)
    exist = _existing_entry_ids(hass)
    valid = entry_id if isinstance(entry_id, str) and entry_id in exist else None
    data["priority_entry_id"] = valid
    if valid:
        data["preferred_priority_entry_id"] = valid
    await _save_raw(hass, data)
    _LOGGER.info("Priority set (current=%s, preferred=%s)",
                _name_for(hass, data.get("priority_entry_id")),
                _name_for(hass, data.get("preferred_priority_entry_id")))
    _notify_all_priority_change(hass)


# ---------- Pause reasons ----------
async def async_mark_priority_pause(hass: HomeAssistant, entry_id: str, reason: str, notify: bool = True) -> None:
    if reason not in VALID_PAUSE_REASONS:
        return
    pauses = _pauses(hass)
    rec = pauses.get(entry_id, {})
    rec[reason] = time.monotonic()
    pauses[entry_id] = rec
    _LOGGER.info("Priority pause marked: entry=%s reason=%s", _name_for(hass, entry_id), reason)
    if notify:
        _notify_all_priority_change(hass)


async def async_clear_priority_pause(hass: HomeAssistant, entry_id: str, reason: str, notify: bool = True) -> None:
    pauses = _pauses(hass)
    rec = pauses.get(entry_id)
    if not rec:
        return
    if reason in rec:
        rec.pop(reason, None)
        if not rec:
            pauses.pop(entry_id, None)
        _LOGGER.info("Priority pause cleared: entry=%s reason=%s", _name_for(hass, entry_id), reason)
        if notify:
            _notify_all_priority_change(hass)


async def async_clear_all_priority_pauses(hass: HomeAssistant, entry_id: str, notify: bool = True) -> None:
    pauses = _pauses(hass)
    if pauses.pop(entry_id, None) is not None:
        _LOGGER.info("Priority pauses cleared: entry=%s ALL", _name_for(hass, entry_id))
        if notify:
            _notify_all_priority_change(hass)


def _is_paused(hass: HomeAssistant, entry_id: str) -> bool:
    return bool(_pauses(hass).get(entry_id))


# ---------- Eligibility ----------
def _controller_for(hass: HomeAssistant, entry_id: str):
    data = (hass.data.get(DOMAIN, {}) or {}).get(entry_id) or {}
    return data.get("controller")


def _eligibility_reasons(hass: HomeAssistant, entry_id: str) -> Dict[str, bool]:
    ctl = _controller_for(hass, entry_id)
    if not ctl:
        return {"exists": False, "cable": False, "start_stop": False, "planner": False, "soc": False, "paused": _is_paused(hass, entry_id)}
    try:
        return {
            "exists": True,
            "cable": bool(ctl.is_cable_connected()),
            "start_stop": bool(ctl.get_mode("start_stop")),
            "planner": bool(getattr(ctl, "_planner_window_allows_start")()),
            "soc": bool(getattr(ctl, "_soc_allows_start")()),
            "paused": _is_paused(hass, entry_id),
        }
    except Exception:
        return {"exists": True, "cable": False, "start_stop": False, "planner": False, "soc": False, "paused": _is_paused(hass, entry_id)}


def _is_entry_eligible(hass: HomeAssistant, entry_id: str) -> bool:
    r = _eligibility_reasons(hass, entry_id)
    return r["exists"] and r["cable"] and r["start_stop"] and r["planner"] and r["soc"] and not r["paused"]


def _first_eligible_by_order(hass: HomeAssistant, order: List[str]) -> Optional[str]:
    for eid in order:
        if _is_entry_eligible(hass, eid):
            return eid
    return None


def _first_unpaused_excluding(hass: HomeAssistant, order: List[str], exclude: Optional[str] = None) -> Optional[str]:
    for eid in order:
        if exclude and eid == exclude:
            continue
        if not _is_paused(hass, eid):
            return eid
    return None


# ---------- Order ----------
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
    _LOGGER.debug("Priority order updated: %s (preferred=%s)",
                [_name_for(hass, e) for e in order],
                _name_for(hass, top) if top else None)
    try:
        hass.bus.async_fire("evcm_priority_refresh")
    except Exception:
        _LOGGER.debug("Failed to fire evcm_priority_refresh after order update", exc_info=True)
    await async_align_current_with_order(hass)


async def async_set_entry_order_index(hass: HomeAssistant, entry_id: str, index_one_based: int) -> None:
    if entry_id not in _existing_entry_ids(hass):
        return
    order = await async_get_order(hass)
    order = [e for e in order if e != entry_id]
    index = max(1, min(len(order) + 1, int(index_one_based)))
    order.insert(index - 1, entry_id)
    await async_set_order(hass, order)


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


# ---------- Align ----------
async def async_align_current_with_order(hass: HomeAssistant) -> None:
    if not await async_get_priority_mode_enabled(hass):
        return
    order = await async_get_order(hass)
    current = await async_get_priority(hass)
    eligible = _first_eligible_by_order(hass, order)
    if eligible:
        if eligible != current:
            _LOGGER.info("Align set current to %s (eligible)", _name_for(hass, eligible))
            await _set_priority_value(hass, eligible)
        return
    if current and _is_paused(hass, current):
        candidate = _first_unpaused_excluding(hass, order, exclude=current)
    else:
        candidate = _first_unpaused_excluding(hass, order, exclude=None)
    if candidate and candidate != current:
        _LOGGER.info("Align fallback set current to %s (unpaused)", _name_for(hass, candidate))
        await _set_priority_value(hass, candidate)
        return
    if current and not _is_paused(hass, current):
        _LOGGER.debug("Align leaves current %s (no better fallback)", _name_for(hass, current))
        return
    _LOGGER.info("Align sets current to None (all paused or no entries)")
    await _set_priority_value(hass, None)


# ---------- Advance ----------
async def async_advance_priority_to_next(hass: HomeAssistant, current_entry_id: str) -> None:
    entries = _existing_entry_ids(hass)
    if not entries or current_entry_id not in entries:
        preferred = await async_get_preferred_priority(hass)
        if preferred and _is_entry_eligible(hass, preferred):
            await _set_priority_value(hass, preferred)
        else:
            await async_align_current_with_order(hass)
        return
    order = await async_get_order(hass)
    try:
        idx = order.index(current_entry_id)
    except ValueError:
        await async_align_current_with_order(hass)
        return
    n = len(order)
    for step in range(1, n):
        cand_id = order[(idx + step) % n]
        if _is_entry_eligible(hass, cand_id):
            _LOGGER.info("Priority advanced from %s to %s",
                        _name_for(hass, current_entry_id),
                        _name_for(hass, cand_id))
            await _set_priority_value(hass, cand_id)
            return
    exclude = current_entry_id if _is_paused(hass, current_entry_id) else None
    fallback = _first_unpaused_excluding(hass, order, exclude=exclude)
    if fallback and fallback != current_entry_id:
        _LOGGER.info("No eligible next; fallback to unpaused %s", _name_for(hass, fallback))
        await _set_priority_value(hass, fallback)
        return
    if not _is_paused(hass, current_entry_id):
        _LOGGER.info("No eligible next; retain current %s (not paused)",
                    _name_for(hass, current_entry_id))
        return
    _LOGGER.info("No eligible/unpaused next; clearing priority")
    await _set_priority_value(hass, None)


# ---------- Handover helper ----------
async def async_handover_after_pause(hass: HomeAssistant, paused_entry_id: str) -> None:
    if not await async_get_priority_mode_enabled(hass):
        return
    try:
        current = await async_get_priority(hass)
        if current == paused_entry_id:
            await async_advance_priority_to_next(hass, paused_entry_id)
        else:
            await async_align_current_with_order(hass)
    except Exception:
        _LOGGER.debug("handover_after_pause failed for %s", _name_for(hass, paused_entry_id), exc_info=True)

# EOF
