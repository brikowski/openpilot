# Odyssey tune rationale

This note preserves the evidence behind `ody-op` and its experimental children without carrying
route history and failed experiments in production comments. Treat it as context to re-verify, not
a substitute for current code, DBC semantics, or full-rate logs.

## Current design

- Lateral follows the stock LKA envelope: 2560 maximum command and the stock-derived torque tune.
  `steerActuatorDelay` is the stock 0.15 s. The former 0.20 s fallback had no isolated evidence of
  benefit and was retired on 2026-08-11; lateral stays stock until a logged symptom reopens it.
- Longitudinal is scoped to `HONDA_ODYSSEY_5G_MMR`. Other Bosch Hondas retain upstream behavior.
- `GAS_COMMAND` uses a speed-scheduled baseline `[0.72, 0.54, 0.56, 0.60]` at
  `[0, 8, 15, 22] m/s`, with a per-drive residual learner.
- Filtered pitch and learned aerodynamic drag feed gas forward and, above 5 m/s on `ody-op`,
  participate in the compensated domain decision. They never add brake authority to
  `ACCEL_COMMAND`. The controller and validator share `odyssey_domain_switch_accel`, so a future
  experiment cannot silently change one model without the other.
- Honda Bosch treats `ACCEL_COMMAND` as acceleration and closes its own brake loop. Our supplemental
  controller is integral-only and one-sided: it may add braking but cannot reduce Honda's request.
- `ody-op` retains `BRAKE_DOMAIN_ENTRY=-0.30`, `DOMAIN_HYST_EXIT=0.20`, compensated road-speed
  switching, and its one-sided brake integral. `ody-op-test` is frozen after its stacked coast,
  threshold, integral, onset, and release experiments failed the reported downhill symptom.
- `ody-op-test2` changes only ordinary road-speed brake onset: -0.10 m/s2 first command, then no
  faster than 0.60 m/s3 toward the request. Matched radar route `3b` entered its two downhill
  episodes at -0.08 and 0.00; its first reached -0.40 after 0.5 s. Requests at or below -1.5 m/s2,
  stopping, and control below 10 m/s retain immediate authority.
- Brake-PID and gas-ramp state reset while longitudinal control is inactive. Gas ramp state also
  resets while braking, keeping every inactive-to-live `GAS_COMMAND` handoff at <=60.
- The Odyssey gas lookup ceiling is an instance attribute so constructing it cannot contaminate
  other Honda interfaces in the same process.
- `.agents/analyze_radar_commands.py` is the offline stock-radar reverse-engineering tool. It
  preserves native `ACC_CONTROL` timing and raw bytes, reports checksum/counter validity and
  payload-bit changes, reconstructs inactive/coast/gas/brake transitions, exports an event CSV,
  and fits a route-held-out gas-command shadow model from speed, `ACCEL_COMMAND`, and pitch. It
  intentionally treats `GAS_COMMAND` as opaque and never produces a live command. Its pure metric
  helpers and mutation tests live in `radar_command_metrics.py` and
  `test_radar_command_metrics.py`.
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
  reduced tapping but exposed long positive-request brake holds and underspeed. Retesting 0.20 with
  the lower -0.30 entry on split routes `00000027`/`00000028` returned 12 physical descent edges in
  0.734 min (16.4/min) and driver-felt tapping. That closes threshold/width tuning without promotion.
- Stock-radar routes `00000012`/`00000013` repeatedly used inactive gas with no brake for 0.66-1.73 s,
  usually gas-to-coast-to-gas and once gas-to-coast-to-brake. They prove the state semantics, not a
  production calibration: their downhill exposure and braking sample are insufficient.
- The first three-state road candidate allowed direct gas/brake changes whenever the compensated
  force and brake latch selected opposing domains. Route `00000029--4c9b612e7c` then produced 47
  direct gas/brake handoffs in 9.7 engaged minutes and matched the driver's pulsing report. The matched stock-radar route
  `0000002b--4882f84449` produced none, while also reproducing radar's separate phantom-braking
  drawback. A later one-command interlock removed direct gas-to-brake handoffs but did not remove
  the symptom: routes `0000003f--cf7b94c588` and `00000040--ff2868cffe` still measured 33.1 and
  13.1 downhill brake edges/min. The interlock is therefore not retained in `ody-op-test2`.
- On those same routes, typical downhill brake applications lasted about 1.0-1.1 s; the wire
  reached 80% command depth in 0.19-0.20 s and achieved acceleration reached 80% in 0.64-0.66 s.
  Stock-radar route `0000003b--08f77bc5c3` measured 3.0 downhill edges/min; its two downhill
  applications had a median duration of 10.86 s and median achieved-accel 80% time of 8.08 s.
  This retracts the earlier claim that only episode frequency remained: onset shape also differs.
- Sunnypilot route `00000002--412e40c6a0` reproduced 26.9 s of compensated-force release hold.
  Exact replay showed the reported event remained latched for 2.24 s; a raw-request release bypass
  changed only its final 0.38 s and weakened the descent-stability mechanism, so it was rejected.
  The validator retains the hold-time diagnosis through the production domain-input helper rather
  than a copied grade model.
- Replay is useful for fixed-input command shape but repeatedly underpredicted closed-loop domain
  transitions. Do not promote another transition change without a terrain-matched road comparison.
- Late lead approaches and traffic-light non-commitment have first diverged in `aTarget`/`shouldStop`,
  upstream of the Honda port. Low-speed excess decel has primarily appeared after correct CAN output,
  in Honda's actuator response. Neither symptom justifies more port brake authority.
- Windfactor is speed-adaptive but not independently identifiable from gasfactor and grade in ordinary
  logs. Its value is therefore unproven, not "confirmed not dead." Finish the onset-shape arm
  before comparing an evidence-derived fixed drag factor with a gas-active-only shadow learner.
  Since gasfactor and windfactor currently learn from the same error, freeze or partition gasfactor
  learning during drag identification; tighter windfactor gates alone do not make two coupled
  parameters identifiable. Treat further wind learning as a separate architecture experiment.

## Validation and reopening criteria

- `ody-op` remains the recovery and shared-tooling branch; stock Honda radar remains the road
  fallback. `ody-op-test` is a frozen failed snapshot. `ody-op-test2` is the unvalidated onset-only
  candidate. Compare it on the same terrain against radar and `ody-op`, and group openpilot
  evidence by resolved `opendbc_commit`.
- Keep the official lateral and longitudinal maneuver routes plus ordinary-road full-rate rlogs
  private and retained. `.agents/log-validation-ledger.jsonl` is the compact evidence index.
- Reopen tuning only for a repeatable symptom whose first divergence is inside the Honda controller
  or between controller output and CAN. Preserve the downstream Honda ECU loop and the <=60 gas
  handoff invariant.
- Before promotion, require controlled maneuvers and comparable ordinary-road evidence. Measure
  gas/coast/brake exposure, direct gas/brake handoffs, physical brake transitions, achieved jerk,
  set-speed error, and driver report. Software, replay, and preflash tests establish correctness and
  safety rails, not ride quality.
