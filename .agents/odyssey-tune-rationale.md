# Odyssey tune rationale

This note preserves the evidence behind `ody-op-long` without carrying route history and failed
experiments in production comments. Treat it as context to re-verify, not a substitute for current
code, DBC semantics, or full-rate logs.

## Current design

- Lateral follows the stock LKA envelope: 2560 maximum command and the stock-derived torque tune.
  `steerActuatorDelay` is 0.20 s; openpilot's lag estimator adds 0.20 s for a 0.40 s cold fallback.
- Longitudinal is scoped to `HONDA_ODYSSEY_5G_MMR`. Other Bosch Hondas retain upstream behavior.
- `GAS_COMMAND` uses a speed-scheduled baseline `[0.72, 0.54, 0.56, 0.60]` at
  `[0, 8, 15, 22] m/s`, with a per-drive residual learner.
- Filtered pitch and learned aerodynamic drag feed the gas side only. The supplemental brake PID
  never feeds the gas calculation.
- Honda Bosch treats `ACCEL_COMMAND` as acceleration and closes its own brake loop. Our supplemental
  controller is integral-only and one-sided: it may add braking but cannot reduce Honda's request.
- One stateful gas/brake-domain decision gates learning, supplemental braking, and the CAN command.
  Entry uses the base threshold; exit hysteresis ramps from zero at 5 m/s to 0.50 m/s2 at 10 m/s.
  Below 5 m/s, raw planner accel prevents grade compensation from releasing an engaged stop.
- Domain and brake-PID state reset while longitudinal control is inactive. Gas ramp state resets
  while inactive or braking, keeping every inactive-to-live `GAS_COMMAND` handoff at <=60 counts.
- The Odyssey gas lookup ceiling is an instance attribute so constructing it cannot contaminate
  other Honda interfaces in the same process.
- `actuatorsOutput.gas` and `.brake` carry effective gasfactor and windfactor for log telemetry;
  actual gas and brake commands remain available in `sendcan`.

## Evidence that fixed the design

- Precharging the gas ramp while its command was ineligible produced first live commands of
  192-255 counts. Resetting inactive state has since held all validated handoffs to <=60.
- A latched brake domain once integrated while disengaged and leaked braking on re-engagement.
  Resetting domain and PID state with `longActive == false` eliminated that lifecycle failure.
- Grade compensation can sit near the gas/brake threshold on descents. Small symmetric hysteresis,
  time-based release holds, and replay-selected values failed road A/Bs. The retained 0.50 value is
  release-only and speed-ramped so it does not delay brake entry or normal low-speed starts.
- Replay is useful for fixed-input command shape but repeatedly underpredicted closed-loop domain
  transitions. Do not promote another transition change without a terrain-matched road comparison.
- Late lead approaches and traffic-light non-commitment have first diverged in `aTarget`/`shouldStop`,
  upstream of the Honda port. Low-speed excess decel has primarily appeared after correct CAN output,
  in Honda's actuator response. Neither symptom justifies more port brake authority.
- Windfactor is speed-adaptive but not independently identifiable from gasfactor and grade in ordinary
  logs. Treat further wind learning as a separate architecture experiment, not routine tuning.

## Validation and reopening criteria

- The tune is feature-complete and in maintenance mode. Continue regression validation by resolved
  `opendbc_commit`; do not pool only by the parent OpenPilot commit.
- Keep the official lateral and longitudinal maneuver routes plus ordinary-road full-rate rlogs
  private and retained. `.agents/log-validation-ledger.jsonl` is the compact evidence index.
- Reopen tuning only for a repeatable symptom whose first divergence is inside the Honda controller
  or between controller output and CAN. Preserve the downstream Honda ECU loop and the <=60 gas
  handoff invariant.
- Before a behavior change, require controlled maneuvers and comparable ordinary-road evidence.
  Software, replay, and preflash tests establish correctness and safety rails, not ride quality.
