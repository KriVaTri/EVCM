# EVCM – Smart EV Charging for Home Assistant (Simple Overview)

[![Latest Release](https://img.shields.io/github/v/release/KriVaTri/evcm?include_prereleases&label=release)]

> This custom integration is all about plugging your EV into your wallbox and forget about it, you don't have to worry about consuming excessive grid energy or pause charging when conditions are not good. (e.g. low solar surplus)
> EVCM helps your Home Assistant system charge one or more electric cars only when it makes sense and is very versatile and flexible in its setup.

---

## What does it actually do?

- Starts charging when there is enough excess power (like solar export).
- Pauses charging when you start importing too much from the grid.
- Slowly turns the charging amps up or down to match what you have available. (you can also set a max charging current limit)
- Can stop at a chosen battery percentage (SoC limit).
- Can restrict charging to a time window (planner).
- Can handle more than one wallbox with (or without) a priority order (who gets to charge first).
- Lets you force charging manually if you just want to plug in and go.

You set a few numbers and switches; it does the boring part.

---

## Example of a typical EVCM entry:

<img width="256" height="381" alt="EVCM smaller" src="https://github.com/user-attachments/assets/34dd9297-f24f-4bc7-8f33-7748016332c3" />

---

## Minimum required entities

From your charger integration (examples: Wallbox, etc.) you need:
- Charge power sensor
- Charging status / state sensor
- Cable connected (binary_sensor)
- Charging enable (switch)
- Lock (lock entity)
- Current setting (number entity to set amps)

From your energy setup:
- Either a single “net power” sensor (positive = export, negative = import)  
  OR separate export and import sensors.

Optional:
- EV battery SoC (%) for use with the EV SoC limit function

If you have these, you can use EVCM.

---

## Installation (short version)

1. Via HACS: add custom repository `https://github.com/KriVaTri/EVCM` (type: Integration), install, then restart Home Assistant.
2. Or manual: copy `custom_components/evcm/` into your HA `config` directory and restart.
3. Add integration: Home Assistant → Settings → Devices & Services → Add Integration → search “EVCM”.

---

## First setup (what you’ll click)

During the config flow:
1. Pick name and how you provide net power (single vs export+import).
2. Choose 1‑phase or 3‑phase (affects minimum power math).
3. Map the charger and grid sensors.
4. Enter two threshold bands:
   - ECO ON (used when ECO switch ON)
   - ECO OFF (used when ECO switch OFF)
5. (Optional) Set SoC limit or planner window.
6. Save—entities (switches & number inputs) appear.

Turn the `Start/Stop` switch ON to let it work.

---

## Everyday use

- Plug in EV.
- Make sure `Start/Stop` is ON.
- ECO ON uses ECO thresholds; ECO OFF uses the other band. (handy for different seasons e.g. summer/winter)
- Watch it adjust amps up/down as sun/clouds change.
- Need to force charging? Turn `Manual` ON (ignores threshold gating and automatic current regulation).
- Want it to stop at 80%? Set the SoC limit number to 80.

---

## Multiple chargers?

- Each charger (“entry”) has its own switches.
- Turn `Priority Charging` ON (any entry’s proxy switch) to let only one charge at a time.
- Set order numbers (1, 2, 3…). Order 1 is “first in line.”
- When the first finishes or reaches SoC limit, the next starts if conditions allow.


## Where to go next

- Full deep-dive (all concepts, events, edge cases): [docs/README.md](docs/README.md)
- Releases / changelog: [Releases](https://github.com/KriVaTri/EVCM/releases)
- Issues / feedback: [GitHub Issues](https://github.com/KriVaTri/EVCM/issues)

---

## License

See the repository for license details.

---

Happy smart charging!
