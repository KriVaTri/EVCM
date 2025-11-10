# EVCM — Smart EV Charging Manager for Home Assistant

EVCM is a Home Assistant custom integration to intelligently control one or more EV wallboxes based on:
- Net power at the grid connection (export/import)
- Hysteresis thresholds (ECO vs OFF profiles)
- EV battery state-of-charge (SoC) limit
- Planner window (start/stop datetimes)
- Priority order across multiple charging points
- Automatic pausing on insufficient surplus or missing data
- Dynamic current regulation (Amps up/down) driven by export/import
- One-phase vs three-phase specific behavior

This document explains how EVCM works, how to configure it, and which entities it provides.

---

## Table of contents

- [1. Concepts and terminology](#1-concepts-and-terminology)  
- [2. Key features](#2-key-features)  
- [3. Installation](#3-installation)  
- [4. Configuration flow](#4-configuration-flow)  
- [5. Mode switches (per entry)](#5-mode-switches-per-entry)  
- [6. Priority charging behavior](#6-priority-charging-behavior)  
- [7. Priority order numbering](#7-priority-order-numbering)  
- [8. Hysteresis thresholds (ECO vs OFF)](#8-hysteresis-thresholds-eco-vs-off)  
- [9. Automatic regulation (regulation loop)](#9-automatic-regulation-regulation-loop)  
- [10. SoC limit](#10-soc-limit)  
- [11. Planner window (start/stop datetimes)](#11-planner-window-startstop-datetimes)  
- [12. Sustain timers (below-lower / no-data)](#12-sustain-timers-below-lower--no-data)  
- [13. Manual vs Start/Stop modes](#13-manual-vs-startstop-modes)  
- [14. Events and bus signals](#14-events-and-bus-signals)  
- [15. Entities overview](#15-entities-overview)  
- [16. Unknown/unavailable detection](#16-unknownunavailable-detection)  
- [17. Common scenarios](#17-common-scenarios)  
- [18. Troubleshooting](#18-troubleshooting)  
- [19. Development](#19-development)

---

## 1) Concepts and terminology

- Net power: grid export minus import (positive = exporting, negative = importing). In “single sensor” mode a single sensor may report positive and negative values; otherwise separate export/import sensors are used.
- ECO thresholds: “upper” and “lower” thresholds used when ECO mode is ON.
- OFF thresholds: an alternate band used when ECO mode is OFF.
- Start/Stop mode: main automation controlling auto start/pause based on thresholds, planner window, SoC and priority.
- Manual mode: manual override; no dynamic hysteresis regulation, but planner/SOC/priority still gate starting.
- Priority Charging: when ON, only the “current priority” entry is allowed to regulate.
- Order: global order of entries; used to pick the next/first candidate in priority mode.
- Preferred: internal pointer to the top-of-order entry; avoids race conditions on reconnect.
- Regulation loop: periodic task that adjusts current (Amps) up or down based on net export/import.
- Sustain: delay in seconds before pausing when conditions remain below lower threshold or data is missing.
- Planner window: local datetimes (start/stop) defining when charging is allowed if planner mode is enabled.
- SoC limit: maximum EV battery % at which charging should pause.

---

## 2) Key features

- Multi-wallbox management with a clear priority order.
- Priority mode with current-preferred alignment and robust hand-over on connects/disconnects.
- SoC gating: pause charging at or above a configured SoC limit.
- Planner window gating: only allow charging within a time window.
- One-phase vs three-phase specific minimum power and tuning.
- Robust handling of unknown/unavailable sensor states (with debouncing and startup grace).
- Clear, integer-only configuration inputs:
  - Priority order (1‑based, Number entity, input box)
  - EV SoC limit (%) (Number entity, input box, unit “%”)
  - Planner start/stop (DateTime entities)
- No unintended reordering: setting current priority never mutates the global order.

---

## 3) Installation

1. Copy the folder `custom_components/evcm/` into your Home Assistant configuration directory.
2. Ensure `manifest.json` contains `"domain": "evcm"`.
3. Restart Home Assistant.
4. Add the integration via Settings → Devices & Services → “EVCM”.

---

## 4) Configuration flow

The configuration flow has three steps:

1. Basic setup
   - Name
   - Grid mode (single net power sensor vs. separate export/import)
   - Wallbox phases (1 vs 3)

2. Device (optional)
   - Select a device to group entities under (optional)

3. Sensors and thresholds
   - Net power sensor:
     - Either a single net sensor (export positive, import negative), or
     - Separate export/import sensors
   - Wallbox sensors and controls:
     - Charge power sensor
     - Wallbox status sensor
     - Cable connected (binary_sensor)
     - Charging enable (switch)
     - Lock (lock)
     - Current setting (number) — used to set amperage
   - Optional EV SoC sensor
   - ECO / OFF threshold bands (upper/lower for each)
   - Scan interval (regulation tick seconds)
   - Sustain seconds for below-lower and missing-data pauses
   - Max current limit (A)

Validation includes:
- Minimum band width (phase-dependent)
- ECO ON upper > ECO OFF upper; ECO ON lower > ECO OFF lower
- Each band’s lower < upper
- Scan interval ≥ minimum

All numeric inputs use integer steps and input boxes.

---

## 5) Mode switches (per entry)

EVCM creates a set of switches per configured entry:

- Priority Charging (global proxy per entry)
- ECO
- Start/Stop
- Manual
- Charge Planner
- Start/Stop Reset

Notes:
- Priority Charging is a global flag; each entry exposes a proxy switch that reads/writes the same global value and stays in sync via events.
- Start/Stop Reset controls whether Start/Stop should be reset to ON after cable disconnect (persisted).

---

## 6) Priority charging behavior

When Priority Charging is ON:
- Only the “current priority” entry is allowed to regulate and auto-start.
- On disconnect or SoC gating of the current entry, EVCM advances to the next eligible entry by order.
- On cable connect:
  - If the preferred entry (top-of-order) connects, preemptive restore applies when appropriate.
  - “Top-of-order takeover”: if an entry is order[0] and connects, it becomes current priority (subject to the latest logic and preferred).
- On order changes:
  - UI is refreshed immediately.
  - Preferred is updated to the top-of-order to prevent stale restores.
  - Current priority is aligned to the first eligible entry (connected + Start/Stop ON), falling back to the first in order.

When Priority Charging is OFF:
- All entries may regulate independently; “current priority” is effectively ignored for gating.

Design guarantee:
- Calling “set priority” never mutates the order. Order can only be changed via the Priority Order numbers.

---

## 7) Priority order numbering

For each entry EVCM provides a Number entity:
- Name: “<Entry Name> priority order”
- Type: box input (no slider), 1‑based integer
- Changing this value moves the entry within the global order
- All Priority Order numbers update immediately (no duplicate numbers)
- A global event is fired on each order change so the UI and entities refresh instantly, even with Priority Charging OFF

Uniqueness is guaranteed by treating the order array as the single source of truth: each entry appears exactly once.

---

## 8) Hysteresis thresholds (ECO vs OFF)

Two bands are defined:
- ECO band (used when ECO = ON): ECO upper and ECO lower
- OFF band (used when ECO = OFF): OFF upper and OFF lower

Behavior outline:
- If not charging and net ≥ upper → start (subject to planner/SOC/priority)
- If charging and net < lower → start the below-lower sustain timer; pause when the timer elapses
- Otherwise, keep/reset timers accordingly

Upper/lower values and minimum band sizes are validated in the config flow (phase-dependent).

---

## 9) Automatic regulation (regulation loop)

Runs every `scan_interval` seconds when all of these are true:
- Start/Stop = ON
- Manual = OFF
- Cable connected
- Charging enable is ON
- Planner window allows start
- SoC is below limit (or limit is not set)
- If Priority Charging is ON: this entry is the current priority
- Essential data is available (net power, and when configured, wallbox status and charge power)

Regulation logic:
- Evaluate net power and charge power
- If charging and charge power ≥ minimum threshold:
  - Increase current by +1A when export exceeds a phase-dependent threshold
  - Decrease current by −1A when import exceeds a phase-dependent threshold
- Current is clamped between 6A and the configured max current
- One-phase and three-phase have different minimum viable charging power and thresholds

---

## 10) SoC limit

Number entity: “<Entry Name> SOC limit” (0–100 %, integer, unit “%”).

- When an SoC sensor is configured and the SoC is ≥ limit, charging is paused and (if Priority Charging is ON and this entry is current) EVCM advances to the next by order.
- If there is no SoC sensor or the limit is unset, SoC gating is effectively disabled.

---

## 11) Planner window (start/stop datetimes)

DateTime entities:
- “<Entry Name> planner start”
- “<Entry Name> planner stop”

When Charge Planner is ON:
- If the window is invalid (missing or start ≥ stop), charging is not allowed to start.
- Outside the window, charging is paused (enable OFF and regulation loop stopped).
- Upon entering the window, with thresholds/SoC/priority satisfied, charging starts automatically.

All times are treated as local.

---

## 12) Sustain timers (below-lower / no-data)

If `sustain_seconds` > 0:
- Below-lower: if net < lower continuously for ≥ sustain_seconds → pause
- No-data: if essential data is missing continuously for ≥ sustain_seconds → pause
- If set to 0, pausing happens immediately on these conditions

The timers are canceled/reset when conditions no longer apply.

---

## 13) Manual vs Start/Stop modes

| Aspect                | Start/Stop (ON)                   | Manual (ON)                                         |
|-----------------------|-----------------------------------|-----------------------------------------------------|
| Threshold gating      | Yes                               | No (only initial start is checked)                  |
| Regulation loop       | Yes                               | No                                                  |
| Sustain timers        | Yes                               | No                                                  |
| Auto-start            | Yes (when conditions allow)       | One-shot checks only (enable may be turned on/off)  |
| Priority gating       | Yes (if Priority Charging is ON)  | Yes (for initial start allowance)                   |

Manual is intended for “force charging” scenarios but still respects planner/SOC for starting and priority gating for allowance.

---

## 14) Events and bus signals

- `evcm_priority_refresh`: fired on any global priority/order/mode change and on each order update. UI and entities (numbers/switches) listen to this to refresh immediately.
- `evcm_unknown_state`: emitted when unknown/unavailable sensor states are encountered (with debouncing and startup grace).
- `evcm_priority_anchor_changed`: internal, used when entries are removed to re-anchor shared state.

You can observe these in Developer Tools → Events.

---

## 15) Entities overview

Per entry:

- Switches
  - `<Name> Priority Charging` (global proxy)
  - `<Name> ECO`
  - `<Name> Start/Stop`
  - `<Name> Manual`
  - `<Name> Charge Planner`
  - `<Name> Start/Stop Reset`
- Numbers
  - `<Name> priority order` (integer, 1‑based)
  - `<Name> SOC limit` (integer, unit “%”)
- DateTime
  - `<Name> planner start`
  - `<Name> planner stop`

You will also configure references to:
- Net power sensor(s) (single or export/import)
- Wallbox status sensor
- Charge power sensor
- Cable connected sensor
- Charging enable switch
- Lock
- Current setting number
- Optional EV SoC sensor

---

## 16) Unknown/unavailable detection

The controller reports unknown/unavailable transitions per sensor with:
- A startup grace period to reduce noise
- Debounce per entity/context
- Context-aware categories (transition, initial, enforcement, get)

Warnings include the entity ID and context and are also mirrored to the event bus as `evcm_unknown_state`.

---

## 17) Common scenarios

1. Two wallboxes, Priority OFF  
   Both may regulate independently (no priority gating).

2. Turn Priority ON  
   Only current priority regulates (top-of-order typically becomes current). The second entry waits (enable OFF or no start).

3. Reorder A from 1 → 2 while priority is ON  
   - UI numbers update immediately.  
   - Preferred is set to top-of-order to avoid stale restore.  
   - Current is aligned to the first eligible entry (likely B).  
   - If A reconnects after B, A does not steal priority unless it is the new top-of-order and eligible.

4. SoC reaches limit for the current entry  
   Pause and advance to the next entry in order.

5. Export increases  
   Current increases by +1A steps (bounded by configured max).  
   Import increases  
   Current decreases by −1A steps (not below 6A).

---

## 18) Troubleshooting

| Symptom | Likely cause | Fix |
|--------|--------------|-----|
| After reorder, the old current stays active | Alignment/preferred not updated | Ensure you’re on a version that updates preferred to top and aligns to first eligible on order change |
| No UI refresh after order change | Missing event fire | EVCM fires `evcm_priority_refresh` after each order update; ensure automations do not bypass order helpers |
| Charging never starts | Below upper threshold / invalid planner / missing data / priority gating | Check thresholds, planner window, sensor availability, and Priority Charging state |
| SoC limit ignored | No SoC sensor configured or limit unset | Configure EV SoC sensor and set a limit |
| Pauses too quickly | Sustain = 0 | Increase `sustain_seconds` |

Enable debug logs for `custom_components.evcm` if you need deeper insight.

---

## 19) Development

Recommended tooling:
```bash
# Lint & format with Ruff
ruff check .
ruff format .

# Type-check with mypy
mypy custom_components/evcm

# Run tests (if present)
pytest
```

Contribution tips:
- Keep priority and order code free of unintended side-effects (do not mutate order when changing current).
- Add tests for priority advance, SoC gating, planner window gating, and hysteresis.
- Use the bus event `evcm_priority_refresh` for cross-entity refreshes.

---

Happy smart charging with EVCM!
