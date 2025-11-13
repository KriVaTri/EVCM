# EVCM — Smart EV Charging Manager for Home Assistant

[![GitHub release (latest SemVer including pre-releases)](https://img.shields.io/github/v/release/KriVaTri/evcm?include_prereleases)](https://github.com/KriVaTri/evcm/releases)

EVCM is a Home Assistant custom integration to intelligently control one or more EV wallboxes based on:
- Net power at the grid connection (export/import)
- Hysteresis thresholds (ECO ON vs ECO OFF profiles)
- EV battery state-of-charge (SoC) limit
- Planner window (start/stop datetimes)
- Priority order across multiple charging points
- Automatic pausing on insufficient surplus or missing data
- Dynamic current regulation (Amps up/down) driven by export/import
- One-phase vs three-phase specific behavior
- Upper start debounce (start delay on the upper threshold)
- Auto unlock switch (allow/prevent automatic unlocking before starting charge)

This document explains how EVCM works, how to configure it, and which entities it provides.

---

## Table of contents

- [1. Concepts and terminology](#1-concepts-and-terminology)  
- [2. Key features](#2-key-features)  
- [3. Installation](#3-installation)  
- [4. Configuration flow](#4-configuration-flow)  
- [Compatibility and required entities](#compatibility-and-required-entities)
- [Supply Profiles and Net Power Target](#supply-profiles-and-net-power-target)
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
- [18. Use Case Example](#18-use-case-example)
- [19. Troubleshooting](#19-troubleshooting)

---

## 1) Concepts and terminology

- Net power: grid export minus import (positive = exporting, negative = importing). In “single sensor” mode a single sensor may report positive and negative values; otherwise separate export/impor[...]
- ECO ON thresholds: “upper” and “lower” thresholds used when ECO mode is ON.
- ECO OFF thresholds: an alternate band used when ECO mode is OFF.
- Start/Stop mode: main automation controlling auto start/pause based on thresholds, planner window, SoC and priority.
- Manual mode: manual override; no dynamic hysteresis regulation, but planner/SoC/priority still gate starting.
- Priority Charging: when ON, only the “current priority” entry is allowed to regulate.
- Order: global order of entries; used to pick the next/first candidate in priority mode.
- Preferred: internal pointer to the top-of-order entry; avoids race conditions on reconnect.
- Regulation loop: periodic task that adjusts current (Amps) up or down based on net export/import.
- Sustain: delay in seconds before pausing when conditions remain below lower threshold or data is missing.
- Planner window: local datetimes (start/stop) defining when charging is allowed if planner mode is enabled.
- SoC limit: maximum EV battery % at which charging should pause.
- Upper start debounce: seconds that net power must stay at/above the upper threshold before (re)starting.
- Auto unlock: per-entry switch to allow or prevent automatic unlocking of the wallbox lock to start charging.

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
- Upper start debounce for clean starts on the upper threshold.
- Auto unlock (switch): ON = default behaviour (auto-unlock when all start conditions are met); OFF = user must manually unlock before charging can start. Automatic re-locking remains unchanged.

---

## 3) Installation

- Use HACS and add a custom repository, copy [https://github.com/KriVaTri/EVCM](https://github.com/KriVaTri/EVCM) into the repository field and choose integration as type.

- Or Copy the folder `custom_components/evcm/` into your Home Assistant configuration directory.
Ensure `manifest.json` contains `"domain": "evcm"`.
Restart Home Assistant.
Add the integration via Settings → Devices & Services → “EVCM”.

---

## 4) Configuration flow

The configuration flow has three steps:

1. Basic setup
   - Name
   - Grid mode (single net power sensor vs. separate export/import)
   - Wallbox phases (1 vs 3)

2. Device (optional)
   - Select a wallbox device to pre-populate the entities in the next step (optional)
   - When a wallbox device was selected, please check the pre-populated entities in step 3 and adjust if needed

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
   - ECO ON / ECO OFF threshold bands (upper/lower for each)
   - Scan interval (regulation tick seconds)
   - Upper start debounce (s): seconds that net ≥ upper must persist before (re)start. Set 0 to start immediately.
   - Sustain seconds for below-lower and missing-data pauses
   - Max current limit (A)

Validation includes:
- Minimum band width (phase-dependent)
- ECO ON upper > ECO OFF upper; ECO ON lower > ECO OFF lower
- Each band’s lower < upper
- Scan interval ≥ minimum

All numeric inputs use integer steps and input boxes.

---

## Compatibility and required entities

Originally designed for Wallbox chargers (e.g. Copper SB and the Pulsar series), EVCM can also work with other EV chargers as long as the following entities are available:

Required charger entities (must be provided by the charger integration):
- Charge power: sensor (W/kW)
- Charger status: sensor (e.g. enum/text state)
- Cable connected: binary_sensor
- Charging enable: switch
- Lock: lock

Required grid input:
- Grid power sensor: either a single net power sensor (export positive, import negative) or separate Import and Export sensors (both positive-only, net = Export − Import).

Optional:
- EV SoC sensor (percentage)

When these entities are present and correctly mapped during setup, EVCM’s automation, gating, and regulation features work across a broad range of EVSE brands.

---

## Supply Profiles and Net Power Target

EVCM now offers selectable supply/voltage profiles and an optional Net Power Target for finer current regulation.

Supply profiles (select during setup/options):
- 1‑phase 230V/240V (`eu_1ph_230`/`na_1ph_240`)
  - Phases: 1, phase voltage ≈ 235 V
  - Min power at 6 A ≈ 1.41 kW
  - Regulation thresholds: export_inc=240 W, import_dec=70 W
- 3‑phase 400V (`eu_3ph_400`)
  - Phases: 3, phase voltage ≈ 230 V (400 V line-to-line)
  - Min power at 6 A ≈ 4.14 kW
  - Regulation thresholds: export_inc=700 W, import_dec=200 W
- 3‑phase 208V (`na_3ph_208`)
  - Phases: 3, phase voltage ≈ 120 V (208 V line-to-line)
  - Min power at 6 A ≈ 2.16 kW
  - Regulation thresholds: export_inc=370 W, import_dec=105 W
- 1‑phase 200V (`jp_1ph_200`)
  - Phases: 1, phase voltage ≈ 200 V
  - Min power at 6 A ≈ 1.20 kW
  - Regulation thresholds: export_inc=205 W, import_dec=60 W
- 1‑phase 120V (Level 1) (`na_1ph_120`)
  - Phases: 1, phase voltage ≈ 120 V
  - Min power at 6 A ≈ 0.72 kW
  - Regulation thresholds: export_inc=122 W, import_dec=35 W

Net Power Target (fine regulation center):
- What it is: a configurable grid balance target (in W) that biases the +/−1 A current adjustments. Default is 0 W.
- How it works:
  - Deviation = measured_net_power − net_power_target.
  - Increase current (+1 A) when deviation ≥ export_inc_threshold (profile-dependent).
  - Decrease current (−1 A) when deviation ≤ −import_dec_threshold.
- Hysteresis (ECO ON/OFF upper/lower) is unchanged and remains absolute; it still governs start/pause decisions. The target only affects fine‑grain current steps while charging.
- Practical examples:
  - Target = +1000 W: the charger will try to keep exporting ~1 kW; current increases only when net export exceeds target by the “export_inc” threshold.
  - Target = −500 W: tolerates ~500 W import before stepping current down.
- Availability: exposed as a Number entity per entry (“net power target”) and persisted; can be changed live without restarting.

---

## 5) Mode switches (per entry)

EVCM creates a set of switches per configured entry:

- Priority Charging (global proxy per entry)
- ECO
- Manual
- Charge Planner
- Start/Stop
- Start/Stop Reset
- Auto unlock

Notes:
- Priority Charging is a global flag; each entry exposes a proxy switch that reads/writes the same global value and stays in sync via events.
- Auto unlock controls if EVCM is allowed to automatically unlock the wallbox lock to start charging:
  - ON: default behaviour (unchanged from previous versions). When all start conditions are met (thresholds/planner/SoC/priority/data), EVCM may unlock and start charging. Automatic re‑lock after charging start remains active.
  - OFF: EVCM will not unlock automatically. The user must manually unlock before charging can start. All other logic (including automatic re‑lock on cable removal etc.) remains unchanged.
- Start/Stop Reset controls whether Start/Stop should be reset to ON or OFF after cable disconnect and on integration reload (persisted). In those moments the Start/Stop switch mirrors the Reset state[...]

---

## 6) Priority charging behavior

When Priority Charging is ON:
- Only the “current priority” entry is allowed to regulate and auto-start.
- On disconnect or SoC gating of the current entry, EVCM advances to the next eligible entry by order.
- On cable connect:
  - If the preferred entry (top-of-order) connects, preemptive restore applies when appropriate.
  - “Top-of-order takeover”: if an entry is order 1 and connects, it becomes current priority (subject to the latest logic and preferred).
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
- Name: “{Entry Name} priority order”
- Type: box input, 1‑based integer
- Changing this value moves the entry within the global order
- All Priority Order numbers update immediately (no duplicate numbers)
- A global event is fired on each order change so the UI and entities refresh instantly, even with Priority Charging OFF

Uniqueness is guaranteed by treating the order array as the single source of truth: each entry appears exactly once.

---

## 8) Hysteresis thresholds (ECO vs OFF)

Two bands are defined:
- ECO ON band (used when ECO = ON): ECO ON upper and ECO ON lower (Delta depending on supply voltage / phase profile)
- ECO OFF band (used when ECO = OFF): ECO OFF upper and ECO OFF lower (Delta depending on supply voltage / phase profile)

Behavior outline:
- If not charging and net ≥ upper → start (subject to planner/SoC/priority and upper start debounce)
- If charging and net < lower → start the below-lower sustain timer; pause when the timer elapses
- Otherwise, keep/reset timers accordingly

Upper start debounce:
- A separate setting (“Upper start debounce (s)”) defines how long net power must remain at/above the upper threshold before (re)starting.
- Set to 0 to start immediately when net ≥ upper.
- Applies to automatic starts in Start/Stop mode; Manual mode ignores threshold gating for starting.

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

Number entity: “{Entry Name} SoC limit” (0–100 %, integer, unit “%”).

- When an SoC sensor is configured and the SoC is ≥ limit, charging is paused and (if Priority Charging is ON and this entry is current) EVCM advances to the next by order.
- If there is no SoC sensor or the limit is unset, SoC gating is effectively disabled.

### Temporarily disabling SoC gating

You have two simple ways to effectively disable SoC-based pausing without changing any internal configuration:

1. Set the SoC limit to 100%  
   Charging will never pause due to SoC (unless your sensor reports >100%).

2. Disable (or remove) the EV SoC sensor entity in Home Assistant  
   When the sensor is unavailable or removed, EVCM treats SoC gating as inactive and will not pause based on SoC until the sensor is available again.

---

## 11) Planner window (start/stop datetimes)

DateTime entities:
- “{Entry Name} planner start”
- “{Entry Name} planner stop”

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

| Aspect                | Start/Stop (ON)                   | Manual (ON)                                                 |
|-----------------------|-----------------------------------|-------------------------------------------------------------|
| Threshold gating      | Yes                               | No (upper/eco thresholds ignored for starting)              |
| Regulation loop       | Yes                               | No                                                          |
| Sustain timers        | Yes                               | No                                                          |
| Auto-start            | Yes (when conditions allow)       | One-shot checks only (enable may be turned on/off)          |
| Priority gating       | Yes (if Priority Charging is ON)  | Yes (for initial start allowance)                           |

Manual is intended for “force charging” scenarios but still respects planner/SoC for starting and priority gating for allowance.

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
  - `{Name} Priority Charging` (global proxy)
  - `{Name} ECO`
  - `{Name} Start/Stop`
  - `{Name} Manual`
  - `{Name} Charge Planner`
  - `{Name} Start/Stop Reset`
  - `{Name} Auto unlock`
- Numbers
  - `{Name} priority order` (integer, 1‑based)
  - `{Name} SoC limit` (integer, unit “%”)
- DateTime
  - `{Name} planner start`
  - `{Name} planner stop`

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

6. Restart of integration or cable disconnect  
   Start/Stop is synchronized to the persisted Start/Stop Reset state (only the user can change the Reset switch).

7. Auto unlock OFF and cable just connected  
   Conditions may allow charging to start, but EVCM will not unlock the lock automatically. Manually unlock the lock to allow charging to start. Automatic re‑lock behavior (after charging starts or on cable removal) remains unchanged.

---

## 18) Use Case Example

Use Case Example with ECO mode ON:

When the upper threshold is set to 4000W, charging will start when grid export is 4000W or above.
If the power supply profile is set to 3-phase 400V (minimum charging power = 4150W), grid export will decrease by approximately 4150W (when charging @ 6A), resulting in 150W of grid consumption.
The regulation loop will then wait for the conditions to either increase or decrease the charging current:
For 3-phase 400V, the charging power must rise by +700W above the net target to increase by 1A, or drop by -200W below the net target to decrease by 1A.
These conditions will be checked at every scan interval.

If grid consumption exceeds the lower threshold (maximum allowed consumption) for the duration specified in the "sustain time" setting, charging will pause.
Charging will only resume once the upper threshold is reached for the duration specified in the "debounce upper" setting.

The "sustain" and "debounce upper" timers are designed to account for fluctuations, such as cloud cover (e.g., in solar energy systems), and to prevent the charging process from toggling too frequently.

When ECO mode is turned on, the "ECO on" upper and lower thresholds will be used, while the "ECO off" thresholds will be ignored (and vice versa).

---

## 19) Troubleshooting

| Symptom | Likely cause | Fix |
|--------|--------------|-----|
| After reorder, the old current stays active | Alignment/preferred not updated | Ensure you’re on a version that updates preferred to top and aligns to first eligible on order change |
| No UI refresh after order change | Missing event fire | EVCM fires `evcm_priority_refresh` after each order update; ensure automations do not bypass order helpers |
| Charging never starts | Below upper threshold / invalid planner / missing data / priority gating | Check thresholds, planner window, sensor availability, and Priority Charging state |
| SoC limit ignored | No SoC sensor configured or limit unset | Configure EV SoC sensor and set a limit |
| Pauses too quickly | Sustain = 0 | Increase `sustain_seconds` |
| Charging doesn’t start with a locked cable | Auto unlock is OFF | Manually unlock the wallbox lock or turn Auto unlock ON |

Enable debug logs for `custom_components.evcm` if you need deeper insight.

---

Happy smart charging with EVCM!
