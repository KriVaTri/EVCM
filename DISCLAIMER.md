# DISCLAIMER

This Home Assistant custom integration (“EVCM”, domain: `evcm`) is provided “AS IS” and “AS AVAILABLE,” without any warranties of any kind, express or implied. Use of this software is entirely at your own risk.

EVCM influences EV charging behavior (e.g., start/stop and charge current adjustments) based on readings from Home Assistant entities. It does not replace certified electrical protections, load balancing, or safety systems.

By installing or using this software, you acknowledge and agree to the following:

## 1) No warranty
- The software is provided without warranties of any kind, including but not limited to merchantability, fitness for a particular purpose, accuracy, reliability, availability, or non‑infringement.
- The authors do not guarantee correct operation, continuous uptime, or that the software is free of defects.

## 2) Electrical safety
- EVCM is not a certified safety or protection system and must not be relied upon as such.
- You must ensure your electrical installation (mains, breakers, wiring, RCDs, EVSE/wallbox) is correctly designed, installed, and maintained by qualified professionals and complies with all applicable codes and standards (e.g., IEC, NEC, VDE, NEN, local regulations).
- Configuration values (e.g., maximum current limit) must never exceed the safe ratings of your installation, EVSE/wallbox, or vehicle. This software must not be used to bypass or defeat any safety limit or protection device.

## 3) Data quality and external dependencies
- EVCM’s decisions depend on external data (e.g., net power, wallbox status, cable connected, charge power, EV SoC, planner times).
- Sensors may be unavailable, delayed, noisy, misconfigured, or inaccurate. The integration performs limited validation and cannot guarantee correctness of any input.
- Any automated action taken based on such data is ultimately your responsibility.

## 4) Regulatory compliance
- You are solely responsible for compliance with all applicable laws, standards, and grid/operator rules (including but not limited to export limits, demand limits, time‑of‑use restrictions, charging codes, and local building/electrical regulations).
- EVCM does not perform legal, regulatory, or standards compliance checks.

## 5) No liability
- To the maximum extent permitted by law, the authors shall not be liable for any direct, indirect, incidental, special, exemplary, or consequential damages arising out of or in connection with the use or inability to use this software.
- This includes, without limitation, damage to equipment or property, fire, personal injury, battery degradation, unexpected energy costs, missed charge targets, loss of data, or business interruption.

## 6) Behavior changes and updates
- Features, algorithms (e.g., thresholds, hysteresis, priority handling), and defaults may change between versions.
- After any update, you are responsible for reviewing your configuration and verifying correct and safe operation.

## 7) No affiliation
- EVCM is not affiliated with, endorsed by, or officially supported by any vehicle manufacturer, wallbox/EVSE vendor, DSO/TSO, or energy provider. Product and brand names are used only for integration purposes within Home Assistant.

## 8) Privacy
- Logs and events may reveal information about charging behavior and energy usage. You are responsible for handling such data in compliance with applicable privacy laws and your own policies.

## 9) Intended use
- EVCM is intended as a convenience tool to orchestrate charging behavior in Home Assistant. It is not a substitute for certified load management or protection systems.
- Planner and SoC limit features are convenience aids only; they do not guarantee a specific state of charge at any time.

## 10) Acceptance
- If you do not accept all of the above terms, do not install or use this integration.
- Installing, enabling, or continuing to use EVCM constitutes your agreement to this disclaimer.

---
For licensing terms, see the project’s LICENSE file (e.g., MIT license). If any part of this disclaimer conflicts with mandatory local law, that part shall be interpreted to the minimum extent necessary while preserving the intent to disclaim warranties and limit liability.
