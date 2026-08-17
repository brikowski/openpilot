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
- The active gas arm keeps the speed-scheduled gasfactor calibration but sends `GAS_COMMAND` from
  the controller request only. Pitch and learned aerodynamic-drag data remain available for
  diagnostic analysis; the controller does not use them to select the brake domain, change
  `ACCEL_COMMAND`, or add wire force. Command domains use only the raw request and speed.
- Honda Bosch treats `ACCEL_COMMAND` as acceleration and closes its own brake loop. The fresh
  `ody-op-test2` brake path therefore adds no second controller.
- `ody-op` retains `BRAKE_DOMAIN_ENTRY=-0.30`, `DOMAIN_HYST_EXIT=0.20`, compensated road-speed
  switching, and its one-sided brake integral. `ody-op-test` is frozen after its stacked coast,
  threshold, integral, onset, and release experiments failed the reported downhill symptom.
- The raw upstream-split `ody-op-test2` reference failed its first road screen. The current
  `-0.50` arm still removes the custom brake PID, compensated threshold, release hysteresis, and
  onset shaping. It keeps raw clipped `ACCEL_COMMAND`, coasts for road-speed requests from `0`
  through `-0.50`, brakes below `-0.50`, and retains brake for non-positive requests below 5 m/s.
  This is a software-validated, road-unvalidated arm.
- Eligible gas receives the calculated `GAS_COMMAND` immediately. The former 60-count handoff ramp
  was mechanically verified but retired because no isolated comparison established a road benefit.
- The Odyssey gas lookup ceiling is an instance attribute so constructing it cannot contaminate
  other Honda interfaces in the same process.
- `.agents/analyze_radar_commands.py` is the offline stock-radar reverse-engineering tool. It
  preserves native `ACC_CONTROL` timing and raw bytes, reports checksum/counter validity and
  payload-bit changes, reconstructs inactive/coast/gas/brake transitions, exports an event CSV,
  and fits a route-held-out gas-command shadow model from speed, `ACCEL_COMMAND`, and pitch. It
  intentionally treats `GAS_COMMAND` as opaque and never produces a live command. Its pure metric
  helpers and mutation tests live in `radar_command_metrics.py` and
  `test_radar_command_metrics.py`.
- `actuatorsOutput.gas` and `.brake` carry actual actuator outputs, while raw commands remain in
  `sendcan`. Learner visibility is recovered through deterministic offline reconstruction; the
  validator and Jotpluggler layout must not treat these actuator fields as gasfactor/windfactor
  telemetry.

## Evidence that fixed the design

- The retired gas ramp reliably limited first-live commands after its precharge defect was fixed,
  but those observations proved implementation rather than benefit versus upstream direct gas.
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
- Raw-split routes `00000042--990be22fe1` and `00000041--91a6b6745b` produced 167/69 brake edges,
  including the reported 39 mph cycling. Route 42 also released brake and sent gas at about
  `-0.18 m/s2` below 2 mph during a lead stop. The current three-domain candidate changes the
  frozen-input edge counts to 14/2, removes all 36 edges from the exact pulse window, and keeps
  both recorded stop windows in brake. Those results establish command shape only.
- Late lead approaches and traffic-light non-commitment have first diverged in `aTarget`/`shouldStop`,
  upstream of the Honda port. Low-speed excess decel has primarily appeared after correct CAN output,
  in Honda's actuator response. Neither symptom justifies more port brake authority.
- Windfactor is speed-adaptive but not independently identifiable from gasfactor and grade in ordinary
  logs. Its value is therefore unproven, not "confirmed not dead" and not part of the known-good set.
  Route 43 also showed the candidate's GAS_COMMAND far above the pooled stock-radar shadow model at
  small positive requests. The smallest isolated arm removes wind/grade feedforward from the wire
  while retaining the road-supported gasfactor calibration; windfactor remains diagnostic-only so a
  later identification can be compared without changing the brake path. Freeze or partition
  gasfactor during any drag identification because the current learners use the same error.
- The bounded onset shaper was withdrawn before road validation when the calibration audit found
  that every numeric brake value in that stack was still provisional. Its `-0.10`, `0.60 m/s3`,
  `10 m/s`, and `-1.5 m/s2` values remain historical hypotheses, not retained behavior.

## Validation and reopening criteria

- `ody-op` remains the recovery and shared-tooling branch; stock Honda radar remains the road
  fallback. `ody-op-test` is a frozen failed snapshot. The raw-split `ody-op-test2` reference is
  road-failed, and its three-domain successor is a software-only candidate rather than a presumed
  improvement. Compare future evidence on the same terrain against radar and `ody-op`, grouped by
  resolved `opendbc_commit`.
- Keep the official lateral and longitudinal maneuver routes plus ordinary-road full-rate rlogs
  private and retained. `.agents/log-validation-ledger.jsonl` is the compact evidence index.
- Reopen the layer containing a repeatable symptom's first divergence: model/planner,
  `longcontrol`, Honda CAN/domain translation, or achieved Honda actuator response. A correct
  numeric `ACCEL_COMMAND` without the correct active domain is not command fidelity. Preserve the
  downstream Honda ECU loop and gas-command safety rails; never reshape a model command to hide an
  upstream defect.
- Before promotion, require controlled maneuvers and comparable ordinary-road evidence. Measure
  gas/coast/brake exposure, direct gas/brake handoffs, physical brake transitions, achieved jerk,
  set-speed error, and driver report. Software, replay, and preflash tests establish correctness and
  safety rails, not ride quality.
