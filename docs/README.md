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
- One-phase vs three-phase specific behavior (supply voltage / phase profiles)
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
- [8. Hysteresis thresholds (ECO ON vs ECO OFF) and Max Peak avg](#8-hysteresis-thresholds-eco-on-vs-eco-off-and-max-peak-avg)
- [9. Phase switching](#9-phase-switching)  
- [10. Automatic regulation (regulation loop)](#10-automatic-regulation-regulation-loop)  
- [11. SoC limit](#11-soc-limit)  
- [12. Planner window (start/stop datetimes)](#12-planner-window-startstop-datetimes)  
- [13. Sustain timers (below-lower / no-data)](#13-sustain-timers-below-lower--no-data)  
- [14. Manual vs Start/Stop modes](#14-manual-vs-startstop-modes)  
- [15. Events and bus signals](#15-events-and-bus-signals)  
- [16. Entities overview](#16-entities-overview)  
- [17. Unknown/unavailable detection](#17-unknownunavailable-detection)
- [18. Safety: external charging_enable OFF detection](#18-safety-external-charging_enable-OFF-detection) 
- [19. Common scenarios](#19-common-scenarios)  
- [20. Use Case Example](#20-use-case-example)
- [21. Troubleshooting](#21-troubleshooting)

---

## 1) Concepts and terminology

- Net power: grid export minus import (positive = exporting, negative = importing). In “single sensor” mode a single sensor may report positive and negative values; otherwise separate export/impor[...]
- ECO ON thresholds: “upper” and “lower” thresholds used when ECO mode is ON.
- ECO OFF thresholds: an alternate band used when ECO mode is OFF.
- Max Peak avg: this setting overrides the ECO threshold when it is stricter than the currently active lower threshold.
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
- Lock: in addition to its security aspect, lock is also used to postpone initial start of the charging session.

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
- Start/stop acts like a killswitch and will stop / prevent starting the charging process.

---

## 3) Installation

- Use HACS: search for "EVCM", download and restart Home Assistant.

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
     - This current limit does not replace the current limition set in your wallbox preventing your circuit breaker from tripping.
     - Use this current setting as an additional current limitation when charging in auto current regulation mode.

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
  
  **If your charger/wallbox does not provide a lock entity:**  
  EVCM still requires one to be configured. In that case you can work around this by creating a **dummy lock** in Home Assistant and selecting that lock entity during EVCM setup/options.
  The dummy lock does not need to control real hardware; it only exists to satisfy the required entity mapping.

Required grid input:
- Grid power sensor: either a single net power sensor (export positive, import negative) or separate Import and Export sensors (both positive-only, net = Export − Import).

Optional:
- EV SoC sensor (percentage)

When these entities are present and correctly mapped during setup, EVCM’s automation, gating, and regulation features work across a broad range of EVSE brands.

EVCM was primarily developed and tested with **local, low‑latency control** (e.g. MQTT on the LAN, typically sub‑second end‑to‑end).

If your charger is controlled through a **high‑latency and/or rate‑limited path** (e.g. a cloud API), you may experience:
- slower response to changing conditions (export/import),
- less accurate regulation,
- repeated commands because state updates arrive late,

**Recommendation:** prefer local control when possible. If you must use a cloud integration, manually increase debounce/cooldown timings in the code to match your setup’s typical end‑to‑end delay.

If your charger integration has 5s end‑to‑end delay (command → effect/state visible), consider using more conservative timings when experiencing issues.

- Adjustable in the integration options (UI):
  - Upper start debounce (s): 6s (instead of the default 3s)
- Currently only adjustable in code (custom_components/evcm/controller.py):
  - CONNECT_DEBOUNCE_SECONDS: 5s
  - EXPORT_SUSTAIN_SECONDS: 10s
  - PLANNER_MONITOR_INTERVAL: 3s
  - CE_MIN_TOGGLE_INTERVAL_S: 10s

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
- Planner
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

## 8) Hysteresis thresholds (ECO ON vs ECO OFF) and Max Peak avg

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

Max Peak avg:
- This is an optional threshold that can be set outside the config flow.
- When set it overrides the ECO thresholds, but only applies when it is stricter than the currently active lower threshold; otherwise it has no effect.
- Threshold delta will be set to the default for the used power profile.
- To disable set the value to 0.

---

## 9) Phase switching

EVCM can control single-phase (1p) vs three-phase (3p) charging if your wallbox/setup supports phase switching.

### Modes

- **Auto**: EVCM may switch phases automatically based on grid conditions (see below).
- **Force 3p**: Always request/assume 3-phase charging.
- **Force 1p**: Always request/assume 1-phase charging.

> Note: The actual phase change is performed by your own automation/listener reacting to the integration event: `PHASE_SWITCH_REQUEST_EVENT`.

### Auto phase switching (event-driven)

Auto phase switching is **event-driven**: it is evaluated only when relevant sensor updates/events occur (e.g. grid/net power, charge power/status, phase feedback).
This means the configured delay is a **minimum**; the switch will happen on the **first evaluation after the delay has elapsed**.

Auto switching is only considered when charging is allowed (same “may I charge?” gating as the controller):
Start/Stop enabled, cable connected, planner window allowed, SoC allowed, priority allowed, and essential data available.
If any of these become false, pending auto-switch candidates are cleared.

#### 3p → 1p (stopped-based)

EVCM considers switching from 3p to 1p only when:
- charging was previously stopped due to `below_lower` (latched stop reason),
- charging is currently OFF,
- grid/net power is in the **switch window**:

  `upper_alt ≤ net < current_upper`

Where:
- `upper_alt` = configured ALT upper threshold (Eco On/Off Upper Alt),
- `current_upper` = the currently effective upper threshold used for resuming (may include Max Peak Avg override).

The condition must remain continuously true for the configured delay (timer resets when it becomes false).
If `net ≥ current_upper`, resuming in the current phase has priority and no phase switch is requested.

#### 1p → 3p

EVCM considers switching from 1p to 3p only when:
- currently in 1p,
- current is at maximum,
- available headroom is sufficient: `(net + charge_power) ≥ (3p_upper + margin)`,
- delay has elapsed.

### Sensor update frequency

Because Auto switching is event-driven, a stalled or very slow-updating grid/net sensor can delay (or prevent) automatic phase switching.
Use a grid/net sensor with a reasonable update frequency (multiple updates per minute recommended).

---

## 10) Automatic regulation (regulation loop)

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

## 11) SoC limit

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

## 12) Planner window (start/stop datetimes)

DateTime entities:
- “{Entry Name} planner start”
- “{Entry Name} planner stop”

When Planner is ON:
- If the window is invalid (missing or start ≥ stop), charging is not allowed to start.
- Outside the window, charging is paused (enable OFF and regulation loop stopped).
- Upon entering the window, with thresholds/SoC/priority satisfied, charging starts automatically.

All times are treated as local.

Date rollover:
- At midnight local time or when toggling the planner switch, if date in planner start or stop is a past date, the date will be set to today, hours and minutes will not change.
- Future dates will never be reset to today.

---

## 13) Sustain timers (below-lower / no-data)

If `sustain time` > 0:
- Below-lower: if net < lower continuously for ≥ sustain time → pause
- No-data: if essential data is missing continuously for ≥ sustain time → pause
- If set to 0, pausing happens immediately on these conditions

The timers are canceled/reset when conditions no longer apply.

---

## 14) Manual vs Start/Stop modes

| Aspect                | Start/Stop (ON)                   | Manual (ON)                                                 |
|-----------------------|-----------------------------------|-------------------------------------------------------------|
| Threshold gating      | Yes                               | No (upper/eco thresholds ignored for starting)              |
| Regulation loop       | Yes                               | No                                                          |
| Sustain timers        | Yes                               | No                                                          |
| Auto-start            | Yes (when conditions allow)       | One-shot checks only (enable may be turned on/off)          |
| Priority gating       | Yes (if Priority Charging is ON)  | Yes (for initial start allowance)                           |

Manual is intended for “force charging” scenarios but still respects planner/SoC for starting and priority gating for allowance.

---

## 15) Events and bus signals

- `evcm_priority_refresh`: fired on any global priority/order/mode change and on each order update. UI and entities (numbers/switches) listen to this to refresh immediately.
- `evcm_unknown_state`: emitted when unknown/unavailable sensor states are encountered (with debouncing and startup grace).
- `evcm_priority_anchor_changed`: internal, used when entries are removed to re-anchor shared state.

You can observe these in Developer Tools → Events.

---

## 16) Entities overview

Per entry:

- Switches
  - `{Name} Priority Charging` (global proxy)
  - `{Name} ECO`
  - `{Name} Start/Stop`
  - `{Name} Manual`
  - `{Name} Planner`
  - `{Name} Start/Stop Reset`
  - `{Name} Auto unlock`
- Numbers
  - `{Name} priority order` (integer, 1‑based)
  - `{Name} SoC limit` (integer, unit “%”)
  - `{Name} Net tower target` (integer, unit “W”)
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

## 17) Unknown/unavailable detection

The controller reports unknown/unavailable transitions per sensor with:
- A startup grace period to reduce noise
- Debounce per entity/context
- Context-aware categories (transition, initial, enforcement, get)

Warnings include the entity ID and context and are also mirrored to the event bus as `evcm_unknown_state`.

---

## 18) Safety: external `charging_enable` OFF detection

EVCM detects when the configured `charging_enable` switch is turned **OFF externally** (by the wallbox itself, the vendor app, another integration, or an automation) while the EV cable is connected.
(If you have an automation that toggles the same `charging_enable` entity, consider using the EVCM **Start/Stop** switch instead).

When this happens, EVCM will:
- create a **persistent notification** (`EVCM: External OFF detected`) including a timestamp,
- **latch** the OFF state and **block automatic re-enabling** of charging,
- log a warning indicating that charging is blocked due to the external OFF latch.

### Clearing the latch
The external OFF latch is cleared when:
- the EV is unplugged, or
- `charging_enable` is turned ON externally by the same mechanisme that turned it OFF, or
- turned ON manually (**Warning:** this is not advised if charging was stopped by the wallbox due to an internal safety condition.  
   If you did not intentionally turn charging OFF yourself, investigate the wallbox first before forcing charging back ON.

EVCM also recreates the relevant notification(s) after a Home Assistant restart/reload if needed, so the user always understands why charging is blocked.

---

## 19) Common scenarios

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

## 20) Use Case Example

Use Case Example with ECO mode ON:

When the upper threshold is set to 4000W, charging will start when grid export is 4000W or above.
If the power supply profile is set to 3-phase 400V (minimum charging power = 4150W), grid export will decrease by approximately 4150W (when charging @ 6A), resulting in 150W of grid consumption.
The regulation loop will then wait for the conditions to either increase or decrease the charging current:
For 3-phase 400V, the charging power must rise by +700W above the net target to increase by 1A, or drop by -200W below the net target to decrease by 1A.
These conditions will be checked at every scan interval.

If grid consumption exceeds the lower threshold (maximum allowed consumption) for the duration specified in the "sustain time" setting, charging will pause.
Charging will only resume once the upper threshold is reached for the duration specified in the "debounce upper" setting.

The "sustain" and "debounce upper" timers are designed to account for fluctuations, such as cloud cover (e.g., in solar energy systems), and to prevent the charging process from toggling too frequently.

When ECO mode is turned on, the "ECO ON" upper and lower thresholds will be used, while the "ECO OFF" thresholds will be ignored (and vice versa).

---

## 21) Troubleshooting

| Symptom | Likely cause | Fix |
|--------|--------------|-----|
| After reorder, the old current stays active | Alignment/preferred not updated | Ensure you’re on a version that updates preferred to top and aligns to first eligible on order change |
| No UI refresh after order change | Missing event fire | EVCM fires `evcm_priority_refresh` after each order update; ensure automations do not bypass order helpers |
| Charging never starts | Below upper threshold / invalid planner / missing data / priority gating | Check thresholds, planner window, sensor availability, and Priority Charging state |
| SoC limit ignored | No SoC sensor configured or limit unset | Configure EV SoC sensor and set a limit |
| Pauses too quickly | Sustain = 0 | Increase `sustain time` |
| Charging doesn’t start with a locked cable | Auto unlock is OFF | Manually unlock the wallbox lock or turn Auto unlock ON |

Enable debug logs for `custom_components.evcm` if you need deeper insight.

---

Happy smart charging with EVCM!
