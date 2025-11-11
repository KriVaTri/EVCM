# EVCM QA Test Checklist

Fill this checklist during testing. Tick each item when verified. Use the “Notes” fields to record observations, entity IDs, and logs.

Metadata
- Date: 11/11/2025
- Tester: KriVaTri
- Home Assistant version: 16.3 / 2025.11.1
- EVCM version: 0.3.6
- Entries under test: A = “wallbox 1”, B = “wallbox 2”

Environment
- [x] Net power sensor(s) present or simulated
- [x] Cable connected sensor present/simulated
- [x] Charging enable switch present/simulated
- [x] Current setting number present/simulated
- [x] Wallbox status and charge power sensors present/simulated
- [x] EV SoC sensor present/simulated
Notes:

## A. UI sanity and device info

- [x] Device shows “by KriVaTri” in Devices & Services
- [x] Each entry exposes 6 switches, 3 numbers, 2 datetime entities
- [x] Entity names have the “evcm …” object ID prefix and correct friendly names
Notes:

## B. Switches (per entry)

Perform for Entry A, then optionally repeat for Entry B unless stated otherwise.

1) Start/Stop
- [x] OFF → charging_enable turns OFF, regulation stops
- [x] ON → if net ≥ upper threshold → enable ON and regulation starts; else waits
- [x] Toggling Start/Stop triggers reset to 6A
Notes:

2) ECO
- [x] ECO ON uses ECO ON band; ECO OFF uses OFF band
- [x] Toggling ECO changes which band drives start/pause; no immediate current step unless hysteresis conditions change
Notes:

3) Manual
- [ ] Manual ON → no regulation; planner/SoC/priority still gate initial start
- [ ] Manual OFF → automation resumes as before
Notes:

4) Charge Planner (basic toggle)
- [ ] Planner ON → outside window: pause; inside window: normal hysteresis applies
- [ ] Planner OFF → planner no longer gates start/pause
Notes:

5) Start/Stop Reset
- [ ] Behavior after disconnect matches the configured reset policy (e.g., keeps Start/Stop ON)
Notes:

6) Priority Charging (global; test from either A or B)
- [ ] OFF → ON sets a current priority (top-of-order if none)
- [ ] ON → OFF lets both entries regulate independently
- [ ] State is synchronized across proxy switches
Notes:

## C. Numbers

1) Priority order (requires two entries)
- Setup: A=1, B=2
- [ ] Connect only B (A disconnected) → B starts (good)
- [ ] Connect A → B stops; A starts (good)
- [ ] Disconnect A → B resumes automatically (regression fixed)
- [ ] Setting order indices never produces duplicates; other entry’s number updates promptly
Notes:

2) SoC limit
- [ ] With SoC sensor: SoC ≥ limit → pause; SoC < limit → allowed to run
- [ ] When paused by SoC while Priority ON and entry is current → advances to next eligible
- [ ] With no SoC sensor or unset limit → SoC gating disabled
Notes:

3) Net power target
- [ ] Target = 0 W (baseline) behaves like previous default
- [ ] Target = +1000 W → aims to keep ~+1000 W export; +1A only if (net − 1000) ≥ export_inc_thr
- [ ] Target = −500 W → tolerates ~500 W import before −1A
- [ ] Target below lower threshold does not override hysteresis; charging pauses when net < lower
Notes:

## D. Hysteresis thresholds

ECO ON band:
- [ ] net just below upper → no start
- [ ] net ≥ upper → start
- [ ] net < lower continuously for sustain_seconds → pause
Notes:

ECO OFF band:
- [ ] OFF thresholds used when ECO is OFF; behavior mirrors ON-band structure
Notes:

Sustain:
- [ ] sustain_seconds = 0 → immediate pause on net < lower
- [ ] sustain_seconds > 0 → pause after timer elapses
Notes:

## E. Planner window

- [ ] Valid window: before start → no start; inside window → normal behavior; after stop → immediate pause
- [ ] Invalid window (start ≥ stop) → no start while Planner ON
- [ ] Timezone handling: local times are honored; no unexpected offsets
Notes:

## F. Regulation loop and supply profiles

- [ ] Steps only occur when charge_power ≥ profile’s regulation_min_w
- [ ] Export/import step thresholds match selected supply profile mapping
- [ ] +1A when deviation/export exceeds profile export_inc threshold; −1A when deviation/import exceeds import_dec threshold
Notes:

## G. Priority behavior (two entries)

- [ ] Connect B first (A disconnected) → B starts
- [ ] Connect A (A=1) → A becomes current, B stops
- [ ] Disconnect A → B resumes automatically
- [ ] Reorder while active: when Priority ON and order changes, alignment selects first eligible as current; UI updates and preferred updated to top-of-order
Notes:

## H. Unknown/unavailable handling

- [ ] Startup grace suppresses noisy warnings on initial unknown/unavailable states
- [ ] During operation: sustained unknown/no-data triggers pause after sustain_seconds
- [ ] Events `evcm_unknown_state` emitted with context; logs informative
Notes:

## I. Persistence and reload

- [x] ECO/Manual/Start-Stop toggles persist across integration reload / HA restart
- [x] SoC limit and net power target persist
- [x] Priority order and current/preferred persist; on reconnect, preferred/top-of-order logic behaves as expected
Notes:

## J. Config and options flow

- [ ] Config flow validates threshold ranges and minimum band sizes
- [ ] Options flow updates supply profile and device references; changes applied after reload
Notes:

## K. Edge cases

- [ ] Missing current setting number: start/pause works; no amp adjustments performed
- [ ] Lock “locked” → “unlocked”: if conditions allow, enable turns ON and charging may start
- [ ] Separate export/import sensors: negative readings clamped; net = export − import correct
Notes:

## L. Events and logging

- [ ] `evcm_priority_refresh` fired on priority/order/mode changes; UI refreshes
- [ ] Logs show “Pause: net < lower …”, planner end, and “Adjust current …” messages during steps
Notes:

## M. Performance and stability

- [ ] With scan_interval at minimum, rapid connect/disconnect and reorder cause no stuck tasks or exceptions
- [ ] Regulation/resume tasks cancel/restart cleanly (no leaks)
Notes:

---
Sign‑off
- [ ] All critical tests passed
- [ ] No unhandled exceptions observed
- [ ] Known issues documented (below)

Known issues:
- …
