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
- [5. Compatibility and required entities](#5-compatibility-and-required-entities)
- [6. Supply Profiles and Net Power Target](#6-supply-profiles-and-net-power-target)
- [7. Mode switches (per entry)](#7-mode-switches-per-entry)  
- [8. Priority charging behavior](#8-priority-charging-behavior)  
- [9. Priority order numbering](#9-priority-order-numbering)  
- [10. Hysteresis thresholds (ECO ON vs ECO OFF) and Max Peak avg](#10-hysteresis-thresholds-eco-on-vs-eco-off-and-max-peak-avg)
- [11. Phase switching](#11-phase-switching)  
- [12. Automatic regulation (regulation loop)](#12-automatic-regulation-regulation-loop)  
- [13. SoC limit](#13-soc-limit)  
- [14. Planner window (start/stop datetimes)](#14-planner-window-startstop-datetimes)  
- [15. Sustain timers (below-lower / no-data)](#15-sustain-timers-below-lower--no-data)  
- [16. Manual vs Auto modes](#16-manual-vs-auto-modes)  
- [17. Events and bus signals](#17-events-and-bus-signals)  
- [18. Entities overview](#18-entities-overview)  
- [19. Unknown/unavailable detection](#19-unknownunavailable-detection)
- [20. Safety: external charging_enable OFF detection](#20-safety-external-charging_enable-OFF-detection) 
- [21. Common scenarios](#21-common-scenarios)  
- [22. Use Case Example](#22-use-case-example)
- [23. Troubleshooting](#23-troubleshooting)

---

## 1) Concepts and terminology

- Net power: grid export minus import (positive = exporting, negative = importing). In “single sensor” mode a single sensor may report positive and negative values; otherwise separate export/import sensors may report only positive values.
- ECO ON thresholds: “upper” and “lower” thresholds are typically set for use with high grid export (summer).
- ECO OFF thresholds: “upper” and “lower” thresholds are typically set for use with low grid export (winter).
- Max Peak avg: this setting overrides the ECO threshold when it is stricter than the currently active lower threshold.
- Start/Stop mode: main automation controlling auto start/pause based on thresholds, planner window, SoC and priority.
- Manual mode: manual override; no dynamic hysteresis regulation, but planner/SoC/priority still gate starting and stopping.
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

- Use HACS: search for "EVCM", download and restart Home Assistant. Add the integration via Settings → Devices & Services → “EVCM”.

- Or Copy the folder `custom_components/evcm/` into your Home Assistant configuration directory. Restart Home Assistant. Add the integration via Settings → Devices & Services → “EVCM”.

---

## 4) Configuration flow

The configuration flow has three steps:

1. Basic setup
   - Name
   - Grid mode (single net power sensor vs. separate export/import)
   - Wallbox phases (1 vs 3)

2. Device and phase switching support (optional)
   - Select a wallbox device to pre-populate the entities in the next step (optional)
   - When a wallbox device was selected, please check the pre-populated entities in step 3 and adjust if needed
   - When phase switching is selected, additional settings must be set in step 3

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

## 5) Compatibility and required entities

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

## 6) Supply Profiles and Net Power Target

EVCM now offers selectable supply/voltage profiles and an optional Net Power Target for finer current regulation.

Supply profiles (select during setup/options):
- 1‑phase 230V/240V (`eu_1ph_230`/`na_1ph_240`)
  - Phases: 1, phase voltage ≈ 230 V
  - Min power at 6 A ≈ 1.4 kW
  - Regulation thresholds: export_inc=240 W, import_dec=70 W
- 3‑phase 400V (`eu_3ph_400`)
  - Phases: 3, phase voltage ≈ 230 V (400 V line-to-line)
  - Min power at 6 A ≈ 4 kW
  - Regulation thresholds: export_inc=700 W, import_dec=200 W
- 3‑phase 208V (`na_3ph_208`)
  - Phases: 3, phase voltage ≈ 120 V (208 V line-to-line)
  - Min power at 6 A ≈ 2.15 kW
  - Regulation thresholds: export_inc=370 W, import_dec=105 W
- 1‑phase 200V (`jp_1ph_200`)
  - Phases: 1, phase voltage ≈ 200 V
  - Min power at 6 A ≈ 1.2 kW
  - Regulation thresholds: export_inc=205 W, import_dec=60 W
- 1‑phase 120V (Level 1) (`na_1ph_120`)
  - Phases: 1, phase voltage ≈ 120 V
  - Min power at 6 A ≈ 0.7 kW
  - Regulation thresholds: export_inc=122 W, import_dec=35 W

Net Power Target (fine regulation center):
- What it is: a configurable grid balance target (in W) that biases the +/−1 A current adjustments. Default is 0 W.
- How it works:
  - Deviation = measured_net_power − net_power_target.
  - Increase current (+1 A) when deviation ≥ export_inc_threshold (profile-dependent).
  - Decrease current (−1 A) when deviation ≤ −import_dec_threshold.
- Hysteresis (ECO ON/OFF upper/lower) is unchanged and remains absolute; it still governs start/pause decisions. The target only affects fine‑grain current steps while charging.
- Practical examples:
  - Target = +1000 W: the charger will try to keep exporting ~1 kW; current increases only when net export exceeds target by the “export_inc” threshold. (e.g. 700W for 3p 400V profile = charge current will increase at +1700W export.
  - Target = −500 W: tolerates ~500 W import before stepping current down.
  - When charging in winter or when export is not available, but there is still headroom before reaching the lower threshold, the charge current will increase if you set the net power target closer to that threshold. This can be handy if faster charging is needed. Example: assume a 3-phase 400 V setup and you do not want to exceed −6000 W import. Set the lower threshold (Eco Off Lower) to −6000 W and the net power target to −5800 W. If the session starts with 500 W import, the charger will use the available headroom (4100 W) plus the existing 500 W, resulting in 4600 W import (−4600 W). Because −4600 W is still 1200 W above the net power target (−5800 W), EVCM increases the current to 7 A, which adds about 700 W extra import. That leaves a 500 W margin (1200 − 700 = 500), so the charge current remains at 7 A. If you want a higher charge current, either raise the net power target or the lower threshold, or reduce consumption from other devices in your home.
  - *Important*: leave a small margin between the lower threshold and the net power target. If these values are set too close together there is a greater risk that the lower threshold will pause charging due to measurement variability and control hysteresis. A practical margin (e.g. around 200–500 W) helps avoid unintended pauses.

- Availability: exposed as a Number entity per entry (“net power target”) and persisted; can be changed live without restarting.

---

## 7) Mode switches (per entry)

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
  - OFF: EVCM will not unlock automatically. The user must manually unlock before charging can start. All other logic remains unchanged.
- Start/Stop Reset controls whether Start/Stop should be reset to ON or OFF after cable disconnect and on integration reload (persisted). In those moments the Start/Stop switch mirrors the Start/Stop Reset state.

---

## 8) Priority charging behavior

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

## 9) Priority order numbering

For each entry EVCM provides a Number entity:
- Name: “{Entry Name} priority order”
- Type: box input, 1‑based integer
- Changing this value moves the entry within the global order
- All Priority Order numbers update immediately (no duplicate numbers)
- A global event is fired on each order change so the UI and entities refresh instantly, even with Priority Charging OFF

Uniqueness is guaranteed by treating the order array as the single source of truth: each entry appears exactly once.

---

## 10) Hysteresis thresholds (ECO ON vs ECO OFF) and Max Peak avg

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

### Max Peak avg:
- This is an optional lower threshold that can be set outside the config flow.
- This value is used to set an import limit.
- When set it overrides the ECO thresholds, but only applies when it is stricter than the currently active lower threshold; otherwise it has no effect.
- Threshold delta will be set to the default for the used power profile. (when charging with 3p 400V the delta is 4500W)
- This threshold can be used as the only threshold when setting the ECO lower thresholds to a lower value.
- The minimum value that can be used is 100W resulting a maximum upper threshold of 4400W when 3p 400V charging. (charging will start from 4400W or more grid export)
- To disable set the value to 0.

---

## 11) Phase switching

EVCM supports dynamic phase switching between 1-phase (1P) and 3-phase (3P) charging when your wallbox hardware supports this capability.

### Configuration

Phase switching is **optional** and can be configured during the integration setup/options flow.
(Only available when 3p 400V is the primary profile):

1. **Enable phase switching**: Choose whether you want to use this feature
2. **Alternate (1P) thresholds**: If enabled, you must provide additional ECO ON/OFF upper and lower thresholds specifically for 1-phase charging:
   - ECO ON Upper Alt (1P)
   - ECO ON Lower Alt (1P)
   - ECO OFF Upper Alt (1P)
   - ECO OFF Lower Alt (1P)

3. **Phase feedback sensor** (required): A sensor that reports the current active phase configuration of your wallbox
   - Expected values: `1p` (single-phase) or `3p` (three-phase)
   - This sensor is mandatory when phase switching is enabled

4. **Control mode**: Choose how phase switching is controlled:
   - **Integration-controlled**: EVCM manages phase switching decisions and requests
   - **Wallbox-controlled**: Your wallbox handles phase switching autonomously

---

### Wallbox-controlled mode

In this mode, the wallbox itself decides when to switch phases. EVCM adapts its behavior based on the current phase reported by the feedback sensor.

**Behavior:**
- EVCM continuously monitors the **phase feedback sensor**
- The integration uses the feedback value to select the appropriate power profile (1P or 3P) internally
- Power calculations, minimum thresholds, and current regulation adapt automatically to the active phase
- **Fallback**: If the feedback sensor reports `unknown` or `unavailable`, EVCM defaults to the **3P profile** (most conservative approach to prevent start/stop flapping)

**User responsibility:**
- Ensure your wallbox's internal phase switching logic is properly configured
- Verify the phase feedback sensor accurately reflects the wallbox's current state

---

### Integration-controlled mode

In this mode, EVCM actively controls when phase switching should occur, but **you must implement the physical switching** via automation.

#### Phase switch requests (events)

EVCM communicates phase switch requests via the Home Assistant event bus:

**Event**: `PHASE_SWITCH_REQUEST_EVENT`  
**Data payload**: `{"phase": "1p"}` or `{"phase": "3p"}`

**Your automation must:**
1. Listen for this event as a trigger
2. Execute the necessary commands to switch your wallbox between 1P and 3P modes
3. Ensure the phase feedback sensor updates to reflect the new state

**Example automation trigger:**
```yaml
trigger:
  - platform: event
    event_type: PHASE_SWITCH_REQUEST_EVENT
    event_data:
      phase: "1p"
action:
  - service: [your_wallbox.switch_to_single_phase]
    # ... your specific wallbox commands
```

#### Mode selector

When integration-controlled mode is active, EVCM provides a **phase mode selector** per entry with three options:

1. **Auto**: EVCM automatically determines when to switch phases based on grid conditions (see switching logic below)
2. **Force 3P**: Lock to 3-phase mode; no automatic switching occurs
3. **Force 1P**: Lock to 1-phase mode; no automatic switching occurs

*Note: Force modes override automatic phase switching decisions. The integration will still send events if you manually change the selector.*

#### Automatic phase switching logic (Auto mode)

When the selector is set to **Auto**, EVCM evaluates switching opportunities based on grid conditions:

##### Switching from 3P → 1P

**Conditions:**
- Current profile is 3P
- Charging is currently **stopped** (not actively charging)
- Net power is **between** the 1P upper threshold (Alt) and the 3P upper threshold:
  
  `upper_alt_1p ≤ net_power < upper_3p`

- This condition must remain stable for **at least** the configured minimum delay (default: 15 minutes, user-configurable)

**Reasoning**: There is sufficient surplus to start charging in 1P mode, but not enough to start in 3P mode.

##### Switching from 1P → 3P

**Conditions:**
- Current profile is 1P
- Charging is **active**
- Current is at the configured **maximum** (wallbox is charging at full 1P capacity)
- Net power + charge power exceeds the 3P upper threshold with margin:
  
  `(net_power + charge_power) ≥ (upper_3p + safety_margin)`

- This condition must remain stable for **at least** the configured minimum delay

**Reasoning**: There is significantly more surplus available; switching to 3P would utilize the excess solar/export power more efficiently.

#### Timing constraints

- Minimum delay: **15 minutes** (configurable during setup/options)
- The delay is enforced to prevent rapid switching (wear on contactors, grid instability)
- The timer **resets** if conditions no longer match before the delay elapses

#### Feedback handling and fallback

- EVCM continuously monitors the **phase feedback sensor** to confirm the active phase
- **Mismatch detection**: If the feedback does not match the last requested phase, EVCM assumes the switch failed or is pending
  - The integration will **fall back to the 3P profile** (primary/conservative profile) until feedback aligns
- **Unknown/unavailable feedback**: Always triggers fallback to **3P profile**

*This ensures safe operation even when communication with the wallbox is unreliable.*

---

### Example threshold settings for optimal use of phase switching 3p -> 1p

- When 3p charging stops because of below lower threshold @ 6A => import gain will be minimum 4000W (= default **delta**)
- The **delta** between 3p Lower and 1p Upper determines how quickly switching can happen (smaller delta = earlier switch, larger delta = later switch)
- The 3p upper threshold must be set to a higher value (less negative) than the 1p upper threshold to avoid 3p from resuming the charge session before phase switching can happen
- Recommended threshold settings for different switch timings:
  
 | Switch timing | 3p Lower | 1p Upper | Delta |
 | --------------|----------|----------|-------|
 | EARLY         |  -7000W  |  -4000W  | 3000W |
 | NORMAL        |  -7000W  |  -3000W  | 4000W |
 | LATE          |  -7000W  |  -2000W  | 5000W |

- When adjusting the 3p lower threshold, 1p upper must be adapted accordingly to keep the delta as preferred.
  
---

### Important notes

#### For integration-controlled users:

⚠️ **Disable wallbox-internal phase switching logic** to avoid conflicts between EVCM and your wallbox's autonomous decisions. Only one controller should manage phase switching at a time.

⚠️ **You are responsible for implementing the automation** that listens to `PHASE_SWITCH_REQUEST_EVENT` and executes the actual phase switch on your hardware.

#### Primary profile

When phase switching is enabled, the **3P profile is always the primary profile**:
- It is the most conservative (higher minimum power requirement reduces risk of frequent start/stop cycles)
- Used as the fallback in case of unknown feedback or mismatch
- Initial state on integration load defaults to 3P unless feedback indicates otherwise

---

### Summary table

| Aspect | Wallbox-controlled | Integration-controlled |
|--------|-------------------|----------------------|
| **Who decides when to switch** | Wallbox internal logic | EVCM (via Auto/Force modes) |
| **Event emission** | No | Yes (`PHASE_SWITCH_REQUEST_EVENT`) |
| **User automation required** | No | Yes (to execute physical switching) |
| **Feedback sensor** | Required (for profile selection) | Required (for confirmation & fallback) |
| **Mode selector** | Not available | Available (Auto / Force 3P / Force 1P) |
| **Fallback on unknown feedback** | 3P profile | 3P profile |
| **Configuration complexity** | Lower | Higher (requires automation setup) |

---

---

## 12) Automatic regulation (regulation loop)

Runs every `scan_interval` seconds when all of these are true:
- Start/Stop = ON
- Manual = OFF
- Cable connected
- Charging enable is ON
- Planner window allows start
- SoC is below limit (only when a EV SoC sensor was configured)
- If Priority Charging is ON: this entry is the current priority
- Essential data is available (net power, and when configured, wallbox status and charge power)

Regulation logic:
- Evaluate net power and charge power per scan interval
- If charging and charge power ≥ minimum threshold:
  - Increase current by +1A when export exceeds a phase-dependent threshold
  - Decrease current by −1A when import exceeds a phase-dependent threshold
- Current is clamped between 6A and the configured max current
- One-phase and three-phase have different minimum viable charging power and thresholds

---

## 13) SoC limit

Number entity: “{Entry Name} SoC limit” (0–100 %, integer, unit “%”).

- When an SoC sensor is configured and the EV SoC is ≥ SoC limit, charging is paused and (if Priority Charging is ON and this entry is current) EVCM advances to the next by order.
- If there is no SoC sensor or the limit is unset, SoC gating is effectively disabled.

### Temporarily disabling SoC gating

You have two simple ways to effectively disable SoC-based pausing without changing any internal configuration:

1. Set the SoC limit to 100%  
   Charging will never pause due to SoC (unless your sensor reports >100%).

2. Disable (or remove) the EV SoC sensor entity in Home Assistant  
   When the sensor is unavailable or removed, EVCM treats SoC gating as inactive and will not pause based on SoC until the sensor is available again.

---

## 14) Planner window (start/stop datetimes)

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

## 15) Sustain timers (below-lower / no-data)

If `sustain time` > 0:
- Below-lower: if net < lower continuously for ≥ sustain time → pause
- No-data: if essential data is missing continuously for ≥ sustain time → pause
- If set to 0, pausing happens immediately on these conditions

The timers are canceled/reset when conditions no longer apply.

---

## 16) Manual vs Auto modes

| Aspect            | Auto (Manual OFF) | Manual (Manual ON) |
|-------------------|-------------------|--------------------|
| Threshold gating  | Yes               | No                 |
| Regulation loop   | Yes               | No                 |
| Sustain timers    | Yes               | No                 | 
| Auto-start/stop   | Yes               | No                 |
| Priority gating   | Yes               | Yes                |

Manual is intended for “force charging” scenarios but still respects planner/SoC for starting and priority gating for allowance.

---

## 17) Events and bus signals

- `evcm_priority_refresh`: fired on any global priority/order/mode change and on each order update. UI and entities (numbers/switches) listen to this to refresh immediately.
- `evcm_unknown_state`: emitted when unknown/unavailable sensor states are encountered (with debouncing and startup grace).
- `evcm_priority_anchor_changed`: internal, used when entries are removed to re-anchor shared state.

You can observe these in Developer Tools → Events.

---

## 18) Entities overview

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

## 19) Unknown/unavailable detection

The controller reports unknown/unavailable transitions per sensor with:
- A startup grace period to reduce noise
- Debounce per entity/context
- Context-aware categories (transition, initial, enforcement, get)

Warnings include the entity ID and context and are also mirrored to the event bus as `evcm_unknown_state`.

---

## 20) Safety: external `charging_enable` OFF detection

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

*NOTE: external OFF detection notifications will be suppressed in wallbox-controlled phase switching mode to avoid false notification when switching.*

---

## 21) Common scenarios

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

## 22) Use Case Example

Use Case Example with ECO mode ON:

When the upper threshold is set to 4000W, charging will start when grid export is 4000W or above.
If the power supply profile is set to 3-phase 400V (minimum charging power ≈ 4000W), grid export will decrease by approximately 4000W (when charging @ 6A), resulting in 0W of grid consumption.
The regulation loop will then wait for the conditions to either increase or decrease the charging current:
For 3-phase 400V, the charging power must rise by +700W above the net target to increase by 1A, or drop by -200W below the net target to decrease by 1A.
These conditions will be checked at every scan interval.

If grid consumption exceeds the lower threshold (maximum allowed consumption) for the duration specified in the "sustain time" setting, charging will pause.
Charging will only resume once the upper threshold is reached for the duration specified in the "debounce upper" setting.

The "sustain" and "debounce upper" timers are designed to account for fluctuations, such as cloud cover (e.g., in solar energy systems), and to prevent the charging process from toggling too frequently.

When ECO mode is turned on, the "ECO ON" upper and lower thresholds will be used, while the "ECO OFF" thresholds will be ignored (and vice versa).

---

## 23) Troubleshooting

| Symptom | Likely cause | Fix |
|--------|--------------|-----|
| No UI refresh after order change | Missing event fire | EVCM fires `evcm_priority_refresh` after each order update; ensure automations do not bypass order helpers |
| Charging never starts | Below upper threshold / invalid planner / missing data / priority gating | Check thresholds, planner window, sensor availability, and Priority Charging state |
| SoC limit ignored | No SoC sensor configured or limit unset | Configure EV SoC sensor and set a limit |
| Pauses too quickly | Sustain = 0 | Increase `sustain time` |
| Charging doesn’t start with a locked cable | Auto unlock is OFF | Manually unlock the wallbox lock or turn Auto unlock ON |

Enable debug logs for `custom_components.evcm` if you need deeper insight.

---

Happy smart charging with EVCM!
