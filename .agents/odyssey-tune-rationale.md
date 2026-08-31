# Odyssey tune rationale

This note preserves the evidence behind `ody-op` and its experimental children without carrying
route history and failed experiments in production comments. Treat it as context to re-verify, not
a substitute for current code, DBC semantics, or full-rate logs.

## Current design

- Lateral keeps the stock-derived torque tune, stock 2560 command map, and 0.15 s
  `steerActuatorDelay`. The nonlinear 3840 road arm is retired after routes `5d`, `61`, and `64`
  completed the bounded three-example screen without an attributable improvement over comparable
  2560 response. Route `64` was clean but matched the stock median under-response rather than
  improving it. Do not restore the nonlinear arm, former linear 3840 RDM map, or 0.20 s delay
  fallback without a repeatable logged symptom and an isolated matched-road comparison.
  `validate_log.py` continues to counter-match full-rate controller sends to the physical bus-1
  steering frame so stock-radar attenuation is not confused with the controller cap.
- Longitudinal is scoped to `HONDA_ODYSSEY_5G_MMR`. Other Bosch Hondas retain upstream behavior.
- `GAS_COMMAND` uses upstream's direct request mapping and upstream Odyssey ceiling:
  `[-0.2, 2.0] m/s2 -> [0, 2000]` counts. The former speed map and live residual multiplier are
  both retired: the map was an adaptive seed, and keeping it alone permanently attenuated upstream
  gas to 54-72% without an isolated road benefit. On frozen routes `61`, `64`, and `68`, however,
  direct mapping is usually lower than the final learned wire command. The road arm must therefore
  reject repeatable under-response or set-speed loss as well as excess gas or surge; replay proves
  command exposure only.
- The active gas arm sends `GAS_COMMAND` from the controller request only. Pitch and
  aerodynamic-drag estimates remain available in offline diagnostic analysis; the retired
  production windfactor state and wind/grade terms do not select the brake domain, change
  `ACCEL_COMMAND`, or add wire force. Command domains use only the raw request and speed.
- Honda Bosch treats `ACCEL_COMMAND` as acceleration and closes its own brake loop. At road speed,
  the current path leaves that request raw and only selects Honda's gas/coast/brake domain. The
  former one-sided integral correction below 3 m/s is retired for lack of an attributable road
  benefit; low-speed non-positive requests still retain Honda brake-domain authority.
- Longitudinal tune decisions compare achieved `aEgo` with `carControl.actuators.accel` separately in
  live gas and brake domains, using comparable speed, request, and terrain exposure. Request-to-wire
  RMS and `GAS_COMMAND`/`BRAKE_REQUEST` first establish whether any divergence belongs to the Honda
  translation. Each custom mechanism gets at most three independent exposed road examples; no
  attributable improvement after all three means removal, while a safety regression can end it sooner.
- `ody-op-test` is frozen after its stacked coast, threshold, integral, onset, and release
  experiments failed the reported downhill symptom.
- The raw upstream-split `ody-op-test2` reference failed its first road screen. The current
  three-domain path removes the compensated threshold, release hysteresis, and onset shaping. At
  road speed it keeps raw clipped `ACCEL_COMMAND`, coasts for requests from `0` through `-0.30`,
  brakes below `-0.30`, and retains brake for non-positive requests below 5 m/s. The isolated
  `-0.30` entry is retained after current-code route `68`: it kept every entry request-to-wire error
  within `0.005 m/s2` and eliminated direct gas-to-brake handoffs, while a fixed-input `-0.20`
  selector would increase 40 physical edges to 72 and add 36 direct handoffs. This is an
  attributable domain-separation benefit, not a comfort claim; the route's worst burst originated
  in an upstream no-lead `cruise` request oscillation and Honda amplified the achieved response.
- Eligible gas receives the calculated `GAS_COMMAND` immediately once the gas domain is selected.
  The former 60-count handoff ramp was mechanically verified but retired because no isolated
  comparison established a road benefit. The former `+0.02 m/s2` fresh-gas re-entry gate is also
  retired after three exact-arm routes showed no attributable command-following or comfort gain.
  Any fresh positive road-speed request now selects gas; active gas still follows Honda's upstream
  `-0.20` release split and low-speed positive starts remain immediate.
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
- Current-code route `00000068--bbbfad9947` supplied 8.71 engaged minutes and 0.90 downhill minutes.
  It produced 40 physical brake edges, peak 9/10 s, with 27 downhill edges. All 20 entries followed
  requests below `-0.30`, all 20 releases followed nonnegative requests, and the entry
  request-to-wire error was `0.003/0.005 m/s2` median/max. The worst five-entry window had no lead:
  upstream `cruise` repeatedly requested about `-0.31..-0.44 m/s2` and then `+0.00..+0.05`, while
  achieved acceleration swung roughly `+0.4..+0.5` to `-0.55..-0.73 m/s2`. Replaying only the
  state selector on the recorded inputs gives 72/40/6 edges at entries `-0.20/-0.30/-0.50`, with
  36/0/0 direct gas-to-brake handoffs and 0.01/47.78/88.06 s of coast. Route 44 already rejects the
  apparent `-0.50` edge reduction because it delayed real lead/downhill braking. Retain `-0.30` as
  the smallest supported separation from the upstream `-0.20` gas split; do not claim it fixes the
  upstream pulse or Honda's downstream amplification.
- Routes `00000052--5550e053e9` and `00000053--360703793d` exercised the preceding `b472c9afe`
  brake arm, not nested `46468be93`. They exposed tiny-positive coast-to-gas intervals, including
  one true sub-second pulse, which motivated the isolated `+0.02 m/s2` arm. At that time no retained
  road route had run the new gas re-entry behavior. Exact-arm routes `30`, `31`, and `32` later
  supplied 20/14/10 coast re-entries plus 13/8/9 intervals where the gate withheld a positive
  request, but route-wide gas jerk was mixed versus the pre-arm routes and total short re-entries
  did not improve consistently. Later routes repeated the implementation without establishing a
  benefit, so the threshold is retired rather than retained for its tautological zero-tiny count.
- Late lead approaches and traffic-light non-commitment have first diverged in `aTarget`/`shouldStop`,
  upstream of the Honda port. Low-speed excess decel has primarily appeared after correct CAN output,
  in Honda's actuator response. Neither symptom justifies more port brake authority.
- Windfactor was speed-adaptive but not independently identifiable from gasfactor and grade in
  ordinary logs. Its value was therefore unproven, not "confirmed not dead" and not part of the
  known-good set. Route 43 also showed the candidate's `GAS_COMMAND` far above the pooled stock-radar
  shadow model at small positive requests. The first isolated arm removed wind/grade feedforward
  while retaining the then-current gasfactor calibration; the later audit retired that calibration
  too. The read-only offline shadow remains available for later identification without changing the
  brake path. Hold upstream gas mapping fixed during any future drag identification.
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
