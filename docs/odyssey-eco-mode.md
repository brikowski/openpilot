# Factory ECON and following preference

On the Bosch Odyssey, the car's ECON button selects Eco Mode while OpenPilot controls longitudinal
motion. There is no OpenPilot Eco setting. Eco stays off until a validated factory status is received.
Factory ECON adds no OpenPilot acceleration cap. Its effect on Honda hardware remains native.

Each ECON activation starts Relaxed, the farthest following distance. Turning ECON off selects
Standard, the middle following distance. Settings and the steering-wheel distance button can change
the selected profile until the next mode switch.

A validated ECON change clears the temporary Honda gas-feedback and coast-response history.
Gas feedback keeps its output slew while rebuilding from current response.
Steering, camera calibration and vehicle-parameter learners keep their existing qualification rules
and stored calibration. No separate ECON gas map or permanent acceleration tune is learned.

Lead and model braking and stop requests, lateral control, CAN encoding and safety limits retain
their existing behavior. `carControl` remains authoritative at the Honda controller.

The selected mode is published as `selfdriveState.ecoMode` for replay, settings and attribution.
With Eco disabled, the existing planner calculations are unchanged.

A fresh, checksum-validated factory ECON status selects the mode. ECON on selects Eco; ECON off
selects normal mode. Missing or corrupt mode messages leave the last validated selection alone
and do not affect CAN health. The old software-selection parameter is ignored. Vehicles without
qualified factory status retain normal mode. No factory commands are transmitted.

This is a software-validated candidate. Fuel savings and closed-loop Honda response remain
unmeasured.
