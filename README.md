# EVCM – EV Charging Manager for Home Assistant

[![Latest Release](https://img.shields.io/github/v/release/KriVaTri/evcm?include_prereleases&label=release)](https://github.com/KriVaTri/EVCM/releases)

### This custom integration is about plugging your EV into your wallbox and forgetting about it.
### You don’t have to worry about consuming excessive grid energy or pausing charging when conditions aren’t good (e.g. low solar surplus).  
### EVCM helps Home Assistant charge one or more electric vehicles only when it makes sense and is flexible in how you set it up.

---

## What does it actually do?

- Starts charging when there is enough excess power (solar export / surplus)
- Pauses charging when you start importing too much from the grid
- Slowly turns the charging amps up or down to match what you have available
- Can stop at a chosen battery percentage (SoC limit)
- Can restrict charging to a time window (planner)
- Can handle more than one wallbox with or without a priority order (who gets to charge first)
- Lets you force charging manually if you just want to plug in and go
- Supports phase switching for even better load balancing

You set a few numbers and switches; it does the boring part.

---

## Example of a typical EVCM entry

<img width="300" height="446" alt="EVCM image small" src="https://github.com/user-attachments/assets/e20bf7fc-0b55-41d8-8de0-4e236463c52f" />

---


## Minimum required entities

From your charger integration (e.g. Wallbox) you need:
- Charge power sensor (sensor)
- Charging status / state sensor (sensor)
- Cable connected (binary_sensor)
- Charging enable (switch)
- Lock (lock entity)
- Current setting (number entity to set amps)
- A phase feedback sensor (only required when using the phase switching feature)

From your energy setup:
- Either a single “net power” sensor (positive = export, negative = import)  
  OR separate export and import sensors

Optional:
- EV battery SoC (%) for use with the SoC limit function

If your setup does not expose these required entities directly (for example when using Modbus),
you can create **Template Helpers** in Home Assistant to bridge the gap.

---

## Communication method / latency note

EVCM is a feedback loop (measure → decide → command → observe).  
It was primarily developed and tested with **local, low‑latency control** (e.g. MQTT on the LAN, typically sub‑second end‑to‑end).

If your charger is controlled through a **high‑latency and/or rate‑limited path** (e.g. a cloud API), you may experience:
- slower response to changing conditions (export/import),
- less accurate regulation,
- repeated commands because state updates arrive late,

**Recommendation:** prefer local control when possible. If you must use a cloud integration,
instructions are available in: [docs/README.md](docs/README.md#compatibility-and-required-entities)
    
---

## Installation

1. Via HACS: search for "EVCM", download and restart Home Assistant
2. Or manual: copy `custom_components/evcm/` into your Home Assistant `config` directory and restart
3. Add integration: Home Assistant → Settings → Devices & Services → Add Integration → search “EVCM”

---

## First setup

During the config flow:
1. Pick a name and how you provide net power (single net sensor vs export + import)
2. Choose 1‑phase or 3‑phase (affects minimum power math)
3. Select your wallbox (optional) and phase switching support (optional)
4. Map the charger and grid sensors
5. Enter the threshold bands:  
   - ECO ON (used when the ECO switch is ON)  
   - ECO OFF (used when the ECO switch is OFF)
6. Set the sustain, debounce and scan interval timings
7. Submit

---

## Everyday use

- Plug in the EV
- Make sure `Start/Stop` is ON
- ECO ON uses the ECO ON thresholds; ECO OFF uses the other band (handy for different seasons like summer vs winter)
- Watch it adjust amps up/down as sun/clouds change
- Need to force charging? Turn `Manual` ON (ignores threshold gating and automatic current regulation)
- Want it to stop at 80%? Set the SoC limit number to 80
- Optionally: use the Max peak avg setting to override ECO thresholds if an easy adjustable or automated threshold is needed (e.g. prevent exceeding monthly max peak average)

---

## Multiple chargers

- Each charger (“entry”) has its own switches
- Turn `Priority Charging` ON (any entry’s proxy switch) to let only one charge at a time
- Set order numbers (1, 2, 3…). Order 1 is “first in line.”
- When the first finishes or reaches its SoC limit, the next starts if conditions allow

---

## Where to go next

- Full deep-dive (all concepts, events, edge cases): [docs/README.md](docs/README.md)
- Releases / changelog: [Releases](https://github.com/KriVaTri/EVCM/releases)
- Issues / feedback: [GitHub Issues](https://github.com/KriVaTri/EVCM/issues)

---

## License

MIT

---

Happy smart charging!
