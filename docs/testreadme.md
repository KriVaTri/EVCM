# EVCM – Smart EV Charging for Home Assistant (Simple Overview)

[![Latest Release](https://img.shields.io/github/v/release/KriVaTri/evcm?include_prereleases&label=release)](https://github.com/KriVaTri/EVCM/releases)

## This custom integration is about plugging your EV into your wallbox and forgetting about it. You don’t have to worry about consuming excessive grid energy or pausing charging when conditions aren’t good (e.g. low solar surplus).  
## EVCM helps Home Assistant charge one or more electric vehicles only when it makes sense and is flexible in how you set it up.

---

## What does it actually do?

- Starts charging when there is enough excess power (solar export / surplus)
- Pauses charging when you start importing too much from the grid
- Slowly turns the charging amps up or down to match what you have available (you can also set a max charging current limit)
- Can stop at a chosen battery percentage (SoC limit)
- Can restrict charging to a time window (planner)
- Can handle more than one wallbox with or without a priority order (who gets to charge first)
- Lets you force charging manually if you just want to plug in and go

You set a few numbers and switches; it does the boring part.

---

## Example of a typical EVCM entry

<img width="300" height="446" alt="EVCM image small" src="https://github.com/user-attachments/assets/e8a1b83d-5c87-4a01-82fc-4c58daebbba8" />

---

## Minimum required entities

From your charger integration (e.g. Wallbox) you need:
- Charge power sensor
- Charging status / state sensor
- Cable connected (binary_sensor)
- Charging enable (switch)
- Lock (lock entity)
- Current setting (number entity to set amps)

From your energy setup:
- Either a single “net power” sensor (positive = export, negative = import)  
  OR separate export and import sensors

Optional:
- EV battery SoC (%) for use with the SoC limit function

If you have these, you can use EVCM.

---

## Installation (short version)

1. Via HACS: add custom repository `https://github.com/KriVaTri/EVCM` (type: Integration), install, then restart Home Assistant
2. Or manual: copy `custom_components/evcm/` into your Home Assistant `config` directory and restart
3. Add integration: Home Assistant → Settings → Devices & Services → Add Integration → search “EVCM”

---

## First setup (what you’ll click)

During the config flow:
1. Pick a name and how you provide net power (single net sensor vs export + import)
2. Choose 1‑phase or 3‑phase (affects minimum power math)
3. Map the charger and grid sensors
4. Enter two threshold bands:  
   - ECO ON (used when the ECO switch is ON)  
   - ECO OFF (used when the ECO switch is OFF)
5. (Optional) Set an SoC limit or a planner time window
6. Save—entities (switches & number inputs) appear

Turn the `Start/Stop` switch ON to let it work.

---

## Everyday use

- Plug in the EV
- Make sure `Start/Stop` is ON
- ECO ON uses the ECO ON thresholds; ECO OFF uses the other band (handy for different seasons like summer vs winter)
- Watch it adjust amps up/down as sun/clouds change
- Need to force charging? Turn `Manual` ON (ignores threshold gating and automatic current regulation)
- Want it to stop at 80%? Set the SoC limit number to 80

---

## Multiple chargers?

- Each charger (“entry”) has its own switches
- Turn `Priority Charging` ON (any entry’s proxy switch) to let only one charge at a time
- Set order numbers (1, 2, 3…). Order 1 is “first in line.”
- When the first finishes or reaches its SoC limit, the next starts if conditions allow

---

## Installation

- Use HACS and add a custom repository, copy [https://github.com/KriVaTri/EVCM](https://github.com/KriVaTri/EVCM) into the repository field and choose integration as type.

- Or Copy the folder `custom_components/evcm/` into your Home Assistant configuration directory.
Restart Home Assistant.
Add the integration via Settings → Devices & Services → “EVCM”.

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
