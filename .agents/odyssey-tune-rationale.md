# Odyssey tune rationale

This note preserves the evidence behind `ody-op` without carrying route history and failed
experiments in production comments. Treat it as context to re-verify, not a substitute for current
code, DBC semantics, or full-rate logs.

## Current design

- Lateral follows the stock LKA envelope: 2560 maximum command and the stock-derived torque tune.
  `steerActuatorDelay` is the stock 0.15 s. The former 0.20 s fallback had no isolated evidence of
  benefit and was retired on 2026-08-11; lateral stays stock until a logged symptom reopens it.
- Longitudinal is scoped to `HONDA_ODYSSEY_5G_MMR`. Other Bosch Hondas retain upstream behavior.
- `GAS_COMMAND` uses a speed-scheduled baseline `[0.72, 0.54, 0.56, 0.60]` at
  `[0, 8, 15, 22] m/s`, with a per-drive residual learner.
- Filtered pitch and learned aerodynamic drag feed gas forward and participate in the compensated
  domain decision; they never add brake authority to `ACCEL_COMMAND`.
- Honda Bosch treats `ACCEL_COMMAND` as acceleration and closes its own brake loop. Our supplemental
  controller is integral-only and one-sided: it may add braking but cannot reduce Honda's request.
- One stateful gas/brake-domain decision gates learning, supplemental braking, and the CAN command.
  Its named entry threshold `BRAKE_DOMAIN_ENTRY` is separate from the gas lookup's scaling floor;
  it is -0.30 m/s2 as of 2026-08-06 (moving the band's *position*; the original decoupled value was
  -0.20). The active 2026-08-11 candidate narrows exit hysteresis (band *width*) from 0.50 to 0.20
  m/s2, ramped from zero at 5 m/s to full width at 10 m/s. Below 5 m/s, the raw controller request
  prevents grade compensation from releasing an engaged
  stop; at road speed both entry and release use compensated force.
- Domain and brake-PID state reset while longitudinal control is inactive. Gas ramp state resets
  while inactive or braking, keeping every inactive-to-live `GAS_COMMAND` handoff at <=60 counts.
- The Odyssey gas lookup ceiling is an instance attribute so constructing it cannot contaminate
  other Honda interfaces in the same process.
- `actuatorsOutput.gas` and `.brake` currently carry effective gasfactor and windfactor for log
  telemetry, while raw commands remain in `sendcan`. This is fork-only instrumentation: those
  fields are defined as actuator outputs and must regain actuator semantics before an upstream PR.
  Preserve learner visibility through deterministic offline reconstruction or a separately named,
  schema-reviewed diagnostic event before removing this dependency from the validator and layout.

## Evidence that fixed the design

- Precharging the gas ramp while its command was ineligible produced first live commands of
  192-255 counts. Resetting inactive state has since held all validated handoffs to <=60.
- A latched brake domain once integrated while disengaged and leaked braking on re-engagement.
  Resetting domain and PID state with `longActive == false` eliminated that lifecycle failure.
- Grade compensation can sit near the gas/brake threshold on descents. Small symmetric hysteresis,
  time-based release holds, and replay-selected values failed road A/Bs. A 0.50 release width sharply
  reduced tapping but the latest GPS-matched road comparison exposed long positive-request brake-domain
  holds and underspeed. The 0.20 width is therefore being retested only with the lower -0.30 entry;
  its earlier -0.20-entry road result was worse for tapping, so recurrence is an immediate rejection.
- Sunnypilot route `00000002--412e40c6a0` reproduced 26.9 s of compensated-force release hold.
  Exact replay showed the reported event remained latched for 2.24 s; a raw-request release bypass
  changed only its final 0.38 s and weakened the descent-stability mechanism, so it was rejected.
  The validator retains the hold-time diagnosis independently of production release logic.
- Replay is useful for fixed-input command shape but repeatedly underpredicted closed-loop domain
  transitions. Do not promote another transition change without a terrain-matched road comparison.
- Late lead approaches and traffic-light non-commitment have first diverged in `aTarget`/`shouldStop`,
  upstream of the Honda port. Low-speed excess decel has primarily appeared after correct CAN output,
  in Honda's actuator response. Neither symptom justifies more port brake authority.
- Windfactor is speed-adaptive but not independently identifiable from gasfactor and grade in ordinary
  logs. Its value is therefore unproven, not "confirmed not dead." Finish the release-width arm
  before comparing an evidence-derived fixed drag factor with a gas-active-only shadow learner.
  Since gasfactor and windfactor currently learn from the same error, freeze or partition gasfactor
  learning during drag identification; tighter windfactor gates alone do not make two coupled
  parameters identifiable. Treat further wind learning as a separate architecture experiment.

## Validation and reopening criteria

- The tune is in maintenance mode with one active road candidate: `BRAKE_DOMAIN_ENTRY = -0.30` and
  `DOMAIN_HYST_EXIT = 0.20` (since 2026-08-11). The entry=-0.30,width=0.50 arm is closed without
  promotion: it controlled tapping but held the brake domain too long. Reject the new combination
  for renewed downhill tapping, stable-lead late onset, or longer stops. Compare by resolved
  `opendbc_commit`, not only the parent OpenPilot commit.
- Keep the official lateral and longitudinal maneuver routes plus ordinary-road full-rate rlogs
  private and retained. `.agents/log-validation-ledger.jsonl` is the compact evidence index.
- Reopen tuning only for a repeatable symptom whose first divergence is inside the Honda controller
  or between controller output and CAN. Preserve the downstream Honda ECU loop and the <=60 gas
  handoff invariant.
- Before a behavior change, require controlled maneuvers and comparable ordinary-road evidence.
  Software, replay, and preflash tests establish correctness and safety rails, not ride quality.
