# Optional Eco mode

On the Bosch Odyssey, the car's ECON button selects Eco Mode while OpenPilot controls longitudinal
motion. There is no OpenPilot Eco setting. Eco stays off until a validated factory status is received.
It uses the existing speed-dependent cruise acceleration envelope for speed recovery, including
model-based driving. It introduces no new tuning constants.

Eco defaults to Relaxed, the farthest following distance. Its driving personality is saved separately
from normal mode and can be changed in settings or with the steering-wheel distance button.
Turning Eco off restores the normal-mode preference.

The planner still considers lead and model braking and stop requests. Stopping control,
lateral control, Honda CAN translation and safety limits retain their existing
behavior. `carControl` remains authoritative at the Honda controller. Mode changes use the existing
cruise acceleration slew; turning Eco off restores the normal envelope.

The selected mode is published as `selfdriveState.ecoMode` for replay, settings and attribution.
With Eco disabled, the existing planner calculations are unchanged.

A fresh, checksum-validated factory ECON status selects the mode. ECON on selects Eco; ECON off
selects normal mode. Missing or corrupt mode messages leave the last validated selection alone
and do not affect CAN health. The old software-selection parameter is ignored. Vehicles without
qualified factory status retain normal mode. No factory commands are transmitted.

This is a software-validated candidate. Fuel savings and closed-loop Honda response remain
unmeasured.
