# Optional Eco mode

Eco Mode is off by default and can be changed live in Settings → Toggles when OpenPilot controls
longitudinal motion. It uses the existing speed-dependent cruise acceleration envelope for speed
recovery, including model-based driving. It introduces no new tuning constants.

Eco defaults to Relaxed, the farthest following distance. Its driving personality is saved separately
from normal mode and can be changed in settings or with the steering-wheel distance button.
Turning Eco off restores the normal-mode preference.

The planner still considers lead and model braking and stop requests. Stopping control,
lateral control, Honda CAN translation and safety limits retain their existing
behavior. `carControl` remains authoritative at the Honda controller. Mode changes use the existing
cruise acceleration slew; turning Eco off restores the normal envelope.

The persistent `EcoModeEnabled` setting is published as `selfdriveState.ecoMode` for replay and
attribution. With Eco disabled, the existing planner calculations are unchanged.

On the Bosch Odyssey, a fresh, checksum-validated factory ECON status selects the same setting at
startup and whenever the factory selection changes. ECON on selects Eco; ECON off selects normal
mode. The software toggle can override that selection until the next factory change or startup.
Missing or corrupt mode messages leave the current selection alone and do not affect CAN health.
Other vehicles retain software-only selection. No factory commands are transmitted.

This is a software-validated candidate. Fuel savings and closed-loop Honda response remain
unmeasured.
