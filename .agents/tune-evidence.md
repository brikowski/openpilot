# Odyssey longitudinal tune — evidence archive

**This is a reference document, not an instruction file.** The rules that must survive a cold start
live in the repo-root [`AGENTS.md`](../AGENTS.md) (`CLAUDE.md` is a symlink to it), which both Codex
and Claude Code load automatically every session. This file holds the measurements, failed
experiments, and reasoning *behind* those rules, and is read on demand — it is deliberately not
auto-loaded, because at ~86 KB it would crowd out the work.

Read it when you need the receipts: why a threshold is the value it is, what was already tried and
failed, and which investigations are closed. Conclusions here that conflict with the root file are
stale — the root file wins, and the conflict is worth fixing in place.

(Historical note: this file predates the root `AGENTS.md` and once carried an agent persona header.
That was removed 2026-08-06 to stop it reading as directives to any tool doing nested agent-file
discovery.)

## Submodule & Branch Mechanics
- Honda production logic lives in the [`opendbc_repo`](../opendbc_repo) submodule. If publication is
  requested, publish the child commit before the parent gitlink; pushing never implies deployment.
- Rebase opendbc only onto the commit pinned by openpilot upstream. `.agents/sync_upstream.py` performs
  the compatible local pair rebase and never pushes; inspect source conflicts and the final Honda diff.
- Keep the recovery/shared-tooling parent and submodule paired on `ody-op`. Temporary mechanism
  children are deleted after promotion or rejection; `ody-op-test` and `ody-op-test2` are historical
  snapshots, not active deployment targets. The VS Code tasks are intentionally limited to
  all-retained private log pull, Jotpluggler, Cabana, and explicit guarded deployments for openpilot and
  sunnypilot. There are no implicit sync, publish-only, maneuver, or generic validation tasks.

## Layered Verification Workflow
No one tool establishes that a tune is good. Use these layers in order, and keep an experimental production change isolated until both controlled and ordinary-road evidence agree.

1. **Static, unit, interface, and panda-safety gates** (the old "Run Checks" task was removed from tasks.json 2026-08-05; run the commands directly): `lefthook run pre-commit` covers ruff over `.agents` + the Honda tune plus the pure custom-metric tests; `.venv/bin/python -m pytest .agents/test_odyssey_long_rails.py` covers the active-longitudinal rail/lifecycle invariants; `opendbc_repo/test.sh` covers car-interface tests and upstream Odyssey `test_models`. These establish software correctness and legal CAN output; they do **not** grade ride quality.
2. **Official controlled maneuvers**: for a longitudinal change, record the official longitudinal suite in a safe empty area and run `uv run openpilot/tools/longitudinal_maneuvers/generate_report.py` on the route (the VSCode report tasks were removed 2026-08-05). These are the primary repeatable step-response characterization. Do not enable either maneuver mode automatically: the driver must make the safe-site decision.
3. **Ordinary-road validation**: the "Pull and Validate New Logs" task (or `.agents/pull_logs.py`) SSH-pulls every retained full-rate rlog not already in the validation ledger and runs the custom validator; `.agents/validate_log.py <route>` re-validates one already-local route. The custom tool is authoritative for branch-specific invariants (wire/request fidelity, lifecycle leaks, gas handoff, physical CAN transitions, crashes, interventions, thermal) and useful for trends. A threshold flag identifies an event to inspect; by itself it is not permission to tune.
4. **Raw attribution**: inspect flagged timestamps in the standard Jotpluggler layout; use Cabana when the question is raw CAN/DBC semantics. Decide whether the planner, car port, or Honda actuator owns the symptom before changing code.
5. **Evidence rule**: change tuning only when controlled maneuvers and real-road evidence point the same way. Check provenance, compare the same `opendbc_commit`, require adequate exposure, and repeat the conclusion after dropping the most influential route.

## Stock-radar command reverse-engineering tool

Use `.agents/analyze_radar_commands.py` for command-shape analysis before proposing a gas-map or
transition change. Supply at least two stock-radar routes for route-held-out validation and any
OpenPilot routes to score against the pooled radar shadow:

```bash
uv run python .agents/analyze_radar_commands.py \
  --stock-radar 0000002b--4882f84449 \
  --stock-radar 0000003b--08f77bc5c3 \
  --openpilot 00000038--5b6729c780 \
  --openpilot 00000039--ae57d5ce6e \
  --out /private/tmp/ody-radar-command-analysis.json \
  --events /private/tmp/ody-radar-command-events.csv
```

The report keeps the raw 50 Hz `ACC_CONTROL` stream, integrity status, counter/checksum results,
payload bit-change counts, domain transition timing, speed/acceleration cells, and a held-out
model. This is not a calibration oracle: `GAS_COMMAND` is unitless/opaque, the fitted model is a
shadow estimator, and replay/log fitting does not establish closed-loop ride quality. Preserve the
`-30000` inactive sentinel and Honda safety rails; report first-live gas handoffs diagnostically
rather than treating an uncalibrated slew limit as known-good behavior.

- **Private log retention**: `pull_logs.py` retains full-rate local rlogs by default. Pruning is deliberately opt-in with `--prune-hours`; once both the device and local archive delete a route, new metrics cannot be backfilled. Interrupted rsyncs may leave empty segment directories; the validator, extractor, following inspector, and replay now select only directories containing `rlog.zst`. Official maneuver report generators accept these bare local route IDs, so comma connect publication is not required.
- **Counterfactual replay boundary**: `replay_carcontroller.py` compares command shape on frozen recorded inputs. It can catch command-fidelity regressions without driving, but cannot predict closed-loop vehicle response or on-road BRAKE_REQUEST counts. Never promote a tuning change from replay alone.
- **Upstream workflow**: "Inspect Upstream Delta" is read-only apart from fetching refs. "Sync Upstream Locally" rewrites local history but never pushes. Run checks and inspect the net Honda-only diff before the separate explicit publish or deploy task.

## Current Validation Arm (raw split failed 2026-08-15; three-domain candidate)
- **Latest mixed-mode drive attribution and baseline decision (2026-08-24).** Routes
  `00000035--cdd11a0ea4`, `00000037--0c6fc80a62`, and `00000038--c43a0ecf6c` ran the final
  `ody-op-test2` source at parent `b7980254d7` with nested `opendbc` `41aaf59ee6`; route
  `00000039--39fdbea04c` is thin context. In the same-drive uphill windows, route 38 requested
  `+0.174 m/s2` outside Experimental versus `+0.009 m/s2` in Experimental, while achieved
  acceleration was `+0.086` versus `-0.079`; route 37 showed the same direction (`+0.105` versus
  approximately `0.000` request). `carControl` to `ACCEL_COMMAND` was effectively passthrough, so
  the large Experimental slowdown begins in the model/planner/lead path, with additional Honda
  powertrain grade under-response downstream of an otherwise faithful command. All new software lead
  tracks reported `radar=false`; the current Honda Bosch path still disables the radar ECU, so radar
  integration is a separate reverse-engineering and AEB-safety project, not a tune toggle.
  Lateral used the 3840 range without broad saturation (new-route CAN p95 1535-1918, saturation
  0-.39%); keep 3840 and reopen only for a repeatable lateral symptom. The device was returned to
  official `sunnypilot/staging`; the private `ody-sp` overlay is no longer a deployment target.
- **Retained radar and Alpha-Long review (2026-08-23).** The newly pulled routes were all
  `staging` at parent `b2ee22854616` with no resolved `opendbc_commit`; they are not road evidence
  for the current `ody-op-test2` nested candidate `46468be936`. Stock-radar route
  `00000029--b43171dfe1` provided 113.0 minutes of Honda `ACC_CONTROL` at 50.1 Hz. Its command
  stream showed no discrete command or lead-continuity change at 43 mph, so these logs do not
  support a radar target cutoff there. The OEM target identity is not exposed as a validated
  `radarState` track, and the 43.5 mph value remains the stock-ACC `minSteerSpeed` configuration,
  not a proven radar limit. Alpha-Long route `00000025--2db306153b` provided 11.217 engaged
  minutes and reproduced 60 gas-to-brake and 57 brake-to-gas transitions, 120 physical brake
  edges, and a 24-per-10-second peak. Planner-to-`carControl` RMS was 0.0078 m/s2 and
  brake-domain wire-request RMS was 0.0103 m/s2 with no sign-disagreement interval; the first
  divergence is therefore the Honda domain decision as the raw request crosses approximately
  `-0.20`, not planner tracking. This confirms the minimal three-domain candidate remains the
  correct next road arm, but does not validate it. Route `00000026--8d38fff2db` was initially
  incomplete during the interrupted transfer and was recovered after the device returned.
- **Route-25 frozen-input replay of the current candidate (command evidence only).** Feeding the
  staging route's recorded `carControl` and `carState` through nested `46468be936` reduced
  request-to-returned-command RMS from `0.00815` to `0.00492 m/s2` over 67,328 engaged frames.
  The candidate produced 36 brake-bit flips, 17 with a forceful `ACCEL_COMMAND` (absolute value
  above `0.3`), and 15,020 coast-domain frames. The replayed and recorded wire-jerk summaries were
  effectively identical because the vehicle response and planner inputs are frozen; this supports
  the candidate as the next command-shape arm but is not road evidence for comfort, stopping, or
  closed-loop transition frequency.
- **Recovered route-26 Alpha-Long attribution (2026-08-23).** The complete route supplied 43.1
  engaged minutes on `staging` with `radarUnavailable=True`, so it is not road evidence for
  `46468be936`. It measured 323 physical brake-domain edges, a peak of 36 in 10 seconds, 39
  downhill edges/min, and 158 direct gas-to-brake plus 158 brake-to-gas handoffs. In the peak
  10-second window at approximately 70 mph, the request stayed near `-0.20` while
  `ACCEL_COMMAND` followed within the measured `0.006` m/s2 planner/carControl and `0.007`
  m/s2 brake-domain wire RMS; `inspect_following` found no sign-disagreement interval. Honda's
  inactive gas sentinel alternated with small live gas values as `BRAKE_REQUEST` followed each
  crossing. This is the same first divergence as route 25, now with substantially more exposure.
  Replaying the current candidate over the frozen route produced request RMS `0.00316` versus
  recorded `0.00629`, wire-command peak jerk `1.29` versus `1.46` m/s3, and 72 open-loop domain
  flips. Those figures select the candidate for an exact-source road arm; they do not claim a
  closed-loop 323-to-72 improvement.
- **Lateral decision after the retained-route review.** The staging routes used the 2560 range,
  while the current candidate carries the isolated 3840 Odyssey range. Because no new route ran
  the current nested commit, the staging lateral numbers cannot justify changing that arm. Keep
  lateral at 3840 and require a current-candidate logged symptom before reopening it.

- **Route 4f uphill Experimental attribution and lateral arm (2026-08-17).** On
  `0000004f--2cf5bde88e`, positive-pitch Experimental windows contained 15.5 engaged minutes.
  `longitudinalPlan.aTarget` to `carControl.actuators.accel` to `ACCEL_COMMAND` remained aligned
  (request-to-wire RMS 0.006 m/s2), while achieved `aEgo` was commonly 0.4-0.7 m/s2 lower when the
  request was near zero on the uphill grade. The E2E desired acceleration followed the same
  request and gas remained active for positive requests, so this route does not justify a
  car-port gas compensation; the first unresolved question is the upstream Experimental grade
  command versus Honda powertrain response. The route also establishes the lateral telemetry
  baseline: 23.4 active minutes, CAN torque abs p95/max 1617/2560, 0.5% torque-controller
  saturation, one steer-fault event, and 69 steering-override events. The Odyssey 3840 range is
  now an isolated arm; command/output, lateral model error, steering response, overrides, and
  faults are logged for the comparison, but the arm requires road validation and is not lane-
  tracking proof.
- **Route 4e is the adjacent full-route non-Experimental comparison (2026-08-17).** On
  `0000004e--b155cb69cc`, Experimental was off for the entire 27.1 engaged minutes. Above 20 m/s
  on positive-pitch sections it held the set-speed error near zero (median +0.07 mph over 18.5
  minutes), while the following Experimental route `0000004f--2cf5bde88e` spent 13.1 minutes in
  the same speed/grade mask at a median 7.94 mph below its set speed. The difference is not a
  car-port translation: route 4e had planner-to-`carControl` RMS 0.008 and passthrough RMS 0.007;
  route 4f measured 0.006 and 0.005. In route 4f, the E2E plan source supplied 10.3 of those
  uphill minutes; its median request was +0.037 m/s2 while achieved `aEgo` averaged -0.121 m/s2.
  The model therefore asked for the low acceleration that reached the wire. This is adjacent-drive
  evidence rather than a controlled A/B—the set speeds and traffic differ—but it strengthens the
  upstream Experimental/model attribution and does not justify adding Honda gas force or changing
  the gas map. Current routes also no longer expose internal gasfactor/windfactor state through
  `carOutput`; the validator must not grade actual gas/brake actuator outputs as learner values.
- **Road-speed `-0.50` brake-entry arm (2026-08-17, software only).** Nested opendbc commit
  `b472c9afe` changes only the Odyssey road-speed brake-entry constant from `-0.30` to `-0.50`.
  It preserves raw clipped `ACCEL_COMMAND`, low-speed brake authority, the upstream `-0.20` active
  gas hold, positive-request brake release, and all gasfactor behavior. The nested opendbc suite
  passed 4,011 tests with 703 skips; the Odyssey rails and validator tests passed 45 tests and 43
  subtests. Frozen-input replay of routes 4e/4f is retained only as command-shape evidence (the
  replayed request-error RMS was 0.0042/0.0036 m/s2); it cannot predict closed-loop domain edges.
  Routes 4e/4f ran the predecessor `f453a51e0081`, so neither is road evidence for `b472c9afe`.
  The arm requires the official longitudinal maneuvers and a terrain-matched ordinary-road drive;
  reject it for late onset, overspeed, renewed tapping or gas pulsing, incomplete stops, or driver
  takeovers.
- **Route 4e gas-pulse attribution (2026-08-17).** The non-Experimental full route contained 76
  moving gas episodes; 13 lasted under one second (one under 0.5 s). The short episodes began at
  tiny positive cruise requests (`+0.001` to `+0.014 m/s2`) and ended when the same request fell
  through the active-gas `-0.20` release boundary, usually on a descent. Planner-to-`carControl`
  and `carControl`-to-wire fidelity remained intact, so this is a request/domain re-entry symptom,
  not evidence to raise gasfactor or add grade force. Route 4f had no sub-second moving gas episode
  under the same predecessor arm. The `-0.50` brake arm deliberately leaves gas re-entry unchanged;
  a separate gas-domain arm needs its own controlled/ordinary-road comparison.
- **Gas re-entry deadband sizing (2026-08-17, frozen-input projection only).** Applying a candidate
  `+0.02 m/s2` minimum only when re-entering gas after coast projects route 4e from 76 to 69 gas
  entries and from 15 to 12 sub-second episodes, while leaving projected brake-domain time and
  route 4f's sub-second count unchanged. This leaves the raw `ACCEL_COMMAND` intact but withholds
  opaque gas for tiny positive requests that immediately reverse. The projection cannot predict
  closed-loop speed, domain edges, or overspeed, so it selects no production value and is not yet a
  code change.
- **Gas re-entry pulse diagnostic (2026-08-17, frozen full-rate extraction).** The validator now
  reports only moving, engaged gas starts whose preceding frame was coast rather than brake, then
  separates short episodes from entries whose first 20 ms request is at most `+0.02 m/s2`. On the
  same predecessor extracts, route 4e contained 37 coast re-entries, 4 under one second and 4
  tiny-request short pulses; route 4f contained 36 re-entries and no sub-second pulse. This is a
  narrower symptom measure than the 13 short gas episodes above because it excludes brake-to-gas
  handoffs. It is diagnostic only and does not authorize a deadband or any wire-command change.
- **Three post-`b472c9afe` uploads (2026-08-17).** Route
  `00000051--f714a28f5f` is a 21-second disabled/offroad log with zero vehicle speed and no
  longitudinal or lateral evidence; it is useful only as a thermal record (75C at start, 84C peak).
  Routes `00000052--5550e053e9` and `00000053--360703793d` are thin ordinary-road samples with
  5.7 and 5.5 engaged minutes, respectively. Neither contains moving Experimental driving, so
  neither tests the uphill Experimental behavior.
  Route 52 had 7 coast re-entries and no sub-second in-control pulse under the corrected diagnostic.
  Its three raw gas intervals under two seconds were around 50 mph, began at requests from
  `+0.001` to `+0.011 m/s2`, and remained faithful at the wire (`0.006 m/s2` gas RMS); a frozen
  `+0.02` re-entry threshold removes the one 0.69-second interval without changing projected
  brake edges. Route 53 had 3 true coast re-entries, including one 0.75-second tiny-request pulse
  at about 427 seconds; its request-to-wire RMS was `0.007 m/s2`. A separate apparent 0.83-second
  burst at 268 seconds ended with longitudinal disengagement and is excluded from the pulse count.
  The `+0.02` projection removes the tiny-request classification but leaves a strong-request
  transient, so it is not a complete fix for every short gas event.
  Both routes carried raw commands correctly and had zero direct gas-to-brake handoffs. Route 52
  measured 17 brake edges (peak 4/10s, 12/min on a very short downhill window); route 53 measured
  3 edges (peak 2/10s). Their port-owned stop-lurch portions were `+0.07` and `+0.03 m/s2`, below
  the current action bound, while the remaining response was Honda actuator behavior. Lateral
  telemetry reached the restored 3840 range without controller saturation or steer faults on either
  route. These are attribution and candidate-screening results, not enough exposure to promote a
  production gas threshold.
- **Road-speed `+0.02 m/s2` gas re-entry arm (2026-08-17, software only).** Nested opendbc commit
  `46468be93` adds the isolated Odyssey candidate. It keeps a fresh road-speed request at or below
  `+0.02 m/s2` in coast after gas has
  already ended, while preserving active gas through Honda's existing `-0.20` release split and
  all low-speed start behavior. This is the smallest source delta that addresses the observed
  coast-to-gas pulse without reshaping `ACCEL_COMMAND`, changing gasfactor, or adding Honda force.
  The latest frozen routes project removal of route 52's lone sub-second in-control interval and
  route 53's tiny-request pulse, but route 53 retains a separate strong-request transient. The arm
  therefore requires an official controlled screen and an ordinary-road drive; reject it for
  under-acceleration, overspeed, renewed gas pulsing, or any low-speed start/stop regression.
- **First exact-arm road routes and timestamp attribution (2026-08-23).** Routes
  `00000030--d288c988eb`, `00000031--781e1d39f2`, and `00000032--3526ec7811` ran parent
  `62ca2b5745a7` with nested opendbc `41aaf59ee6f2`, the current `-0.50` brake-entry plus
  `+0.02` gas-re-entry arm. They are thin context, not promotion evidence: 9.7, 4.5, and 4.9
  engaged minutes. Their combined 36 physical brake edges were 1.9/min with peaks of 3, 4, and
  2 per 10 s; there were no direct gas-to-brake handoffs and no tiny-request short gas pulses.
  Request-to-wire RMS stayed 0.005-0.009 m/s2 and sustained sign disagreement was zero. This is
  a narrow improvement over unmodified master routes 22/24 (9.6/18.3 brake edges/min, peak
  25/10 s) and the failed raw split routes 41/42 (11.2/30.3 edges/min, peak 26/28 s), but the
  routes are not terrain-matched and remain too thin to claim overall smoothness.
  At 11:57 on route 30, the lead was vision-only (`leadOne.radar=false`, model probability
  0.98-1.00); its dRel/vRel moved through 51-82 m and -2.6/+3.1 m/s while the planner selected
  a lead source. `aTarget`-to-`carControl` RMS was 0.004 m/s2 and the wire carried the request,
  so the speed-down/speed-up sequence first diverges upstream in the vision lead/planner path,
  not in the Honda port. The 12:02 uphill window likewise had a vision-only lead at 20-40 m,
  lead-source planning, and 0.004 m/s2 planner-to-carControl RMS; gas was available and no rail or
  driver gas override occurred, so its weak climb is consistent with lead following rather than
  withheld Honda gas. At 12:00-12:01, driver braking dominated portions of the downhill and
  stopped-lead approach; when the planner requested the stop, `ACCEL_COMMAND` followed it and
  low-speed domain conflict stayed zero. At 12:59 on route 31, a vision-only lead closed from
  about 74 to 39 m at -12.6 to -7.3 m/s relative speed; the planner/carControl request reached
  -1.76 to -1.16 m/s2 and the wire matched it while the driver braked. That is a lead
  perception/planner timing and/or Honda achieved-response event, not evidence for more port brake
  force. Route 31 still had four brake takeovers and a felt-jerk flag, so these routes do not yet
  promote the arm or establish radar-quality following. Experimental exposure was zero on routes
  30 and 32 and only about 0.03 engaged minutes on route 31; the historical route-33 planner A/B
  therefore cannot substitute for a current-arm Experimental screen.
- **Exact-arm gas versus held-out stock-radar command shape (2026-08-23).** A pooled model fit on
  stock-radar routes `0000002b--4882f84449` and `0000003b--aeccafe9e4` predicted each held-out
  route with `R2=0.824/0.904`. Current exact-arm routes 30/31/32 scored `MAE=103/130/63` raw
  `GAS_COMMAND` counts, with model-minus-OpenPilot bias `-28/+20/-22`; the signs are mixed and
  do not show a consistent under-command that would explain the uphill report. This is an opaque
  command-shape shadow, not a gas calibration or closed-loop ride result, so it does not justify
  changing the retained gasfactor arm.
- **Route 48 first divergence and gas-pulse attribution (2026-08-17).** On
  `00000048--766dc7107b`, planner-to-`carControl` RMS was 0.0097 m/s2 and
  `carControl`-to-`ACCEL_COMMAND` RMS was 0.0082 m/s2, while achieved tracking RMS was 0.4176
  m/s2. The wire carried the request; the first material divergence was Honda's achieved response.
  The route had 168 inactive-to-live gas episodes in 10.13 engaged minutes (16.6/min); 163 began
  at requests no greater than 0.05 m/s2 and 83 lasted under one second. The prior -0.02 release
  hysteresis reduced the route-46 reference's 29.4/min rate but left positive-only re-entry exposed
  to near-zero request cycling.
- **Route 48 closes another car-port brake-shaping hypothesis.** Its 12 complete road-speed brake
  episodes in 10.13 engaged minutes (1.18/min) are close in frequency to stock-radar routes 2b and
  3b (0.79 and 0.98/min). The remaining shape difference begins in the requested command: route 48
  reached 80% `ACCEL_COMMAND` depth in 0.33 s and lasted 1.03 s median, versus 0.90/1.12 s and
  5.92/5.27 s on radar. Achieved 80% times were 0.66 s versus 1.77/1.36 s, while median achieved
  onset jerk (-1.56 m/s3) remained in the same range as radar (-1.23/-1.39 m/s3). Ten of the 12
  OpenPilot episodes were cruise-plan requests without a lead; they crossed -0.30 and returned
  positive quickly, and the port held brake until that positive release while preserving the raw
  request. Do not add a Honda brake shaper for this aggregate difference. The next isolated brake
  comparison is the built-in Experimental planner mode, which earlier within-drive evidence showed
  reduces hill overspeed braking without car-port code.
- **Stock radar defines the gas-domain continuity target.** On stock-radar route
  `0000002b--4882f84449`, gas was active for 85.6% of samples with `ACCEL_COMMAND` from -0.20
  through 0, and entered only 1.59 times/min. Its active `GAS_COMMAND` in that interval had median
  154 and p90 310 counts. Holding an already-active Odyssey gas domain down to the existing Honda
  Bosch -0.20 split therefore follows both upstream semantics and measured OEM command shape; it
  does not infer a new `GAS_COMMAND` calibration.
- **Current isolated gas-pulse arm.** At road speed, an active gas command now remains active down
  to Honda's upstream -0.20 gas split. After a true coast or brake state, gas still requires a
  positive request to re-enter; below 5 m/s, non-positive requests retain brake authority. Frozen
  route-48 inputs project 168->23 gas entries and 83->2 sub-second gas episodes, with zero direct
  gas-to-brake handoffs. This is command-shape evidence only and requires an isolated road screen.
- **Route 48 also exposes a separate highway request/gear interaction.** Around 59-71 mph,
  repeated requests near +0.6 to +0.8 m/s2 were followed by several seconds of undertracking while
  the 10-speed shifted down through multiple gears, then by positive achieved-acceleration surges.
  The online gas trim spent 59.0% of engaged frames at its 3.0 rail and did not converge away from
  the mismatch. Stock radar requested materially less acceleration in comparable high-speed/grade
  cells and tracked it more closely. Do not raise gas force or combine a cruise-acceleration limit
  with the gas-domain road arm. A limit must be its own upstream-style experiment; Ford/Honda
  Nidec's near-cruise limit shape does not directly cover most route-48 events and must not be
  copied without controlled evidence.
- **Highway-limit candidate sizing is not yet a tune.** Applying Ford's exact upstream
  `get_pid_accel_limits` shape (`+2.0` to `+0.2` m/s2 over cruise-speed deltas of 2.0 to 0.4 m/s)
  to route 48 would clip 44.5 of 111.3 seconds with high-grade, high-request exposure, leaving
  52.3 seconds in gears 7-10 unchanged. A separate widened shape that reaches +0.3 m/s2 by a
  2.0 m/s cruise delta would clip 82.8 seconds in those gears, but its breakpoint and +0.3 value
  are Odyssey-specific calibration, not current commaai/opendbc master behavior. Both are
  command-shape projections only. If the gas arm road screen passes, the next controlled arm must
  compare one such pre-`carControl` limit against the unmodified f53d878a1 controller on the same
  uphill set-speed sequence, measuring downshifts, achieved acceleration, overspeed/underspeed,
  and post-shift surge before any ordinary-road promotion.
- **Next road-screen contract keeps the mechanisms isolated.** The first post-`f53d878a1` route
  must assess only the gas-domain hold: report inactive-to-live gas entries/minute, sub-second gas
  episodes, first-live command values, direct gas/brake handoffs, command-to-wire RMS, speed/grade
  exposure, takeovers, and complete stops. Compare ordinary-road exposure with route 48 and use a
  controlled set-speed/coast sequence; do not change the brake threshold or gasfactor in that arm.
  The braking question is a separate matched A/B with Experimental mode off/on and no car-port
  change. Its acceptance evidence is brake episode frequency and duration, request/wire/achieved
  80%-depth timing, jerk, overspeed, interventions, and stop completion. A planner-mode result can
  justify using the built-in mode; it cannot justify a new Honda brake shaper.
- **Route 43 gas attribution (2026-08-16).** The thin full-rate drive `00000043--87b375be62`
  followed `carControl.actuators.accel` and the Honda CAN/domain bits (gas RMS 0.0098 m/s2,
  brake RMS 0.0176 m/s2, no command/domain divergence), so its excessive gas is not a planner-to-
  wire mismatch. Against held-out stock-radar routes `0000002b` and `0000003b`, the pooled gas
  shadow scored the openpilot wire at MAE 817.9 counts with bias -817.7; at small positive
  requests the current custom path reached roughly 750-1,700 counts where the stock-radar shadow
  was typically 180-400. This is command-shape evidence, not a closed-loop ride result. The
  smallest isolated arm therefore keeps the road-supported speed-scheduled gasfactor and the
  existing brake/domain path, but removes wind/grade feedforward from the actual gas wire. The
  windfactor learner remains diagnostic-only so this arm does not silently change its evidence
  stream; the arm is not road-proven until a controlled and ordinary-road comparison is run.

- **Routes 49/4a are deployment-failure evidence, not tune evidence (2026-08-17).** The first
  post-switch route records had zero engaged minutes and qlog-only control coverage. Their
  `errorLogMessage` traces show manager retries failing to import compiled runtime modules
  (`rednose.helpers.ekf_sym_pyx` and `msgq.visionipc.visionipc_pyx`) after a live branch switch
  removed build artifacts; the Odyssey controller was never reached. The device was repaired with
  the standard AGNOS build using its `/usr/local/venv` environment, then rebooted. Read-only
  imports of those modules and `controlsd` pass on the repaired checkout. Do not pool these routes
  with behavioral evidence or call their crash rows a tune regression; a fresh on-road route after
  the repair is required.

- **Fresh source-matched baseline route 4c failed the pulsing-brake screen (2026-08-17).** Route
  `0000004c--9430801c67` ran on parent `1195e247c5b8` with nested `3169fd4cc3fa`, after the
  parent was rebased onto `openpilot/upstream/master` and the exact pair was deployed and verified
  on the device. It recorded 50 physical brake-domain edges, a peak of 6 in 10 seconds, and
  29 downhill edges/min over 10.8 engaged minutes; the shortest edge gap was 0.56 s. There were
  four driver brake takeovers among 29 brake presses and felt-jerk RMS was 0.408 m/s3 versus
  0.189 m/s3 commanded (2.2x), with brake jerk RMS 0.73 versus gas 0.37. Route `0000004b` is
  only 6.3 engaged minutes and is retained as context, not pooled evidence.
- **Route-4c attribution identifies the request/domain interaction, not CAN fidelity.** In the
  repeated approximately 44 mph set-speed window, `longitudinalPlan.aTarget` and
  `carControl.actuators.accel` agreed (RMS 0.0085 m/s2); requests repeatedly moved from about
  `-0.31` to `0.00..+0.02` and back. `ACCEL_COMMAND` followed `carControl`, the gas/brake bits
  followed the selected domain, and Honda `COMPUTER_BRAKING` followed `BRAKE_REQUEST`. The
  first actionable divergence is therefore the closed-loop interaction between mild negative
  speed-regulation requests and Honda's binary friction-brake domain, not a numeric CAN encoding
  error. The four driver takeovers, including one near a request of `-0.24` and another near
  `-0.16`, remain a counter-risk: lowering brake entry could under-brake those situations and
  must be rejected if controlled or ordinary-road overspeed/stop screens worsen.
- **Next isolated brake arm: change one constant, `-0.30` to `-0.50`.** Keep raw
  `ACCEL_COMMAND`, the low-speed brake authority, the existing negative-request brake hold, and
  all gasfactor/windfactor behavior unchanged. The only change is that a road-speed request must
  be below `-0.50` to newly select friction brake; mild negative requests coast, while stronger
  requests retain brake authority and positive requests release immediately. Frozen route-4c
  inputs project 50 to 6 brake-domain edges and retain three stronger-request episodes, but this
  is command-shape evidence only. It does not establish closed-loop edge counts, onset, comfort,
  overspeed, or stop completion. The arm requires the official controlled maneuvers and an
  ordinary-road drive before any promotion.
- **Low-speed stopped-lead concern is a separate open safety finding (2026-08-17).** In the
  route-4b approach at approximately 2.3 to 1.1 mph, the lead remained about 4 m ahead and its
  filtered speed was approximately 0.1--0.2 m/s. OpenPilot's `shouldStop` stayed false, but its
  request moved from about `-0.88` to `-0.17 m/s2`; `carControl`, `ACCEL_COMMAND`,
  `BRAKE_REQUEST`, and Honda `COMPUTER_BRAKING` agreed, with no gas-domain release. The driver
  brake takeover at about 1.1 mph ended `longActive`; it was not caused by the Odyssey port
  releasing brake. This is not closed as safe merely because the recorded gap remained about 4 m:
  the driver reported that the lead was stopped and that an override was necessary.
- **Do not use the `-0.50` road threshold or Ford creep compensation as this fix.** The threshold
  is inactive below 5 m/s, and Honda Bosch `ACCEL_COMMAND` is already the raw OpenPilot request
  with Honda closing the acceleration loop. The upstream generic stop state does not assert until
  below approximately 0.3 m/s. A low-speed stopped-lead arm must first establish whether the
  planner/lead estimate, the generic stop transition, or Honda's response owns the risk; it then
  requires a controlled stopped-lead approach and ordinary-road confirmation of gap, complete
  stop, takeover, onset, and no renewed pulsing. Keep the `-0.50` arm unpublished until that
  screen is complete.

- **MVL-inspired low-speed brake-tracking arm (2026-08-17, nested `f453a51e0`).** MVL's Honda
  Bosch branch provides a directly relevant precedent: a one-sided integral correction below
  3 m/s when the recorded acceleration is weaker than the negative request. The literal branch
  gate uses its road-speed gas threshold (`accel < min_gas`) and `KI=1.0`; that would reset on
  this Odyssey as the low-speed request relaxed from about `-0.20` to `-0.17`, even though our
  three-domain low-speed policy deliberately kept the brake domain selected. The isolated arm
  therefore makes the smallest semantic adaptation: `kP=0`, `KI=0.5`, the prior Odyssey seed,
  and the already-selected low-speed brake domain as the gate. It changes only clipped
  `ACCEL_COMMAND`; gas selection, brake selection, planner inputs, and positive re-engagement are
  unchanged, and the integrator resets whenever control is inactive or the brake domain is not
  selected. The focused rail test covers persistent under-deceleration, the relaxed `-0.17`
  request, Panda limits, and inactive reset.
- **Frozen-input result for the arm is command evidence only.** On route `0000004b`, the arm keeps
  brake authority through the reported 1.2--1.1 mph crawl and continues correcting the relaxed
  negative request; the replayed final approach was approximately `-0.50 m/s2` versus a raw
  request near `-0.17 m/s2`. This is materially closer to the stock-radar low-speed command
  magnitude than the recorded raw command, but the recorded `aEgo` is held fixed, so replay does
  not prove stopping distance, comfort, or collision avoidance. Road validation must reject the
  arm for excess onset, a stop lurch, renewed pulsing, a positive-request hold, late stop, or any
  driver takeover; do not promote it from this replay.

- **Minimal upstream port (2026-08-17, software evidence only).** The deployed `f53d878a1` child
  was based on the older `b0685818f` Honda architecture. The active behavior was ported onto the
  exact Honda commit pinned by the then-current upstream parent, `c536b211b762`, in nested commit
  `3169fd4cc3fa`. The four-file delta is 103 insertions and 11 deletions: Odyssey-only gasfactor/
  domain selection, explicit CAN-domain inputs, the stock-LKA range correction, and an instance-
  scoped gas ceiling. Retired supplemental brake PID, compensated input, onset shaping, and gas
  ramp code are not present. The nested opendbc suite (4,011 tests, 703 skipped) and Odyssey rail
  suite (14 tests, 43 subtests) pass. The parent has since been rebased onto
  `openpilot/upstream/master` at `03e6c81821ed`; that upstream tree still pins `c536b211b762`,
  and parent `1195e247c5b8` records the exact `3169fd4cc3fa` gitlink. This corrected pair is
  force-published on `origin/ody-op-test2` and deployed on the device. Its manager, UI, Panda,
  hardwared, and native imports passed after reboot; route 4c is the first fresh behavioral
  screen and fails the current `-0.30` brake-entry setting as documented above. The port also restores
  `CarOutput.actuatorsOutput` gas/brake semantics to actual actuator output; learned factors are
  no longer written into those fields as fork-only telemetry.

- **The fresh brake-source reset failed its first road screen.** It removed the supplemental brake
  PID, compensated input, release hysteresis, and onset shaping, then used upstream's raw `-0.20`
  split. Routes `00000042--990be22fe1` and `00000041--91a6b6745b` immediately reproduced the
  symptom: 167/69 physical brake edges, peaks of 28/26 per 10 s, and 119.4/121.0 downhill edges/min.
  `ACCEL_COMMAND` followed `carControl` within 0.006-0.008 m/s2, and Honda
  `COMPUTER_BRAKING` followed the brake bit. The source reset was useful attribution, not usable
  behavior.
- **Route-42 39 mph pulse (about 18:12:44 local).** The request cycled roughly `-0.14` to `-0.23`;
  crossing `-0.20` changed `GAS_COMMAND` from a small live value to `-30000`, asserted
  `BRAKE_REQUEST`, and made Honda assert `COMPUTER_BRAKING`. The 28 s inspected window contained
  36 physical brake edges. That is the first divergence for the pulse report.
- **Both reported incomplete lead stops are present.** Route 41 stayed in brake while the request
  relaxed to `-0.22`, reached about 1.1 mph, and the driver took over before `shouldStop` asserted.
  Route 42 relaxed from `-0.21` to `-0.18` at about 1.4 mph with the stopped lead about 5.8 m away;
  the raw split released brake and sent live gas, speed rose to about 2.3 mph as the gap closed, and
  the driver took over. In both routes the planner kept `shouldStop=false` while moving and only
  asserted it near zero after takeover. The upstream stop decision and the low-speed domain error
  are separate findings.
- **Deployed source-matched command-domain baseline.** `ACCEL_COMMAND` remains the raw clipped request. At road
  speed, brake enters below -0.30 and remains selected while the request is negative; positive gas
  releases it immediately. An active gas command remains live down to the stock -0.20 split, but
  after coast it re-enters only for a positive request. Below 5 m/s, every non-positive request
  selects brake and a positive request selects gas immediately. There is no brake PID, onset
  shaper, or compensated brake input. The -0.30 brake entry remains an unvalidated calibration;
  the gas-domain hold is the isolated route-48 arm.
- **Frozen-input replay result, not road proof.** Route-wide brake-bit edges changed 69->2 on route
  41 and 167->14 on route 42. The exact route-42 39 mph window changed 36->0, and both stop windows
  remained continuously in brake with zero gas. Replay freezes the old response and planner input,
  so it cannot prove set-speed control, brake timing, comfort, or full stopping. Reject on road for
  late onset, excess overspeed, renewed tapping, or another incomplete stop.
- **The two-state threshold/width arm is CLOSED without promotion.** Entry=-0.30,width=0.50 sharply
  reduced descent transitions versus master but held the brake domain through positive requests
  and produced sustained underspeed. The split width=0.20 retest on routes
  `00000027--fc0ab6fafa` and `00000028--06e3430ffc` returned driver-felt tapping: 12 physical
  descent edges over 0.734 min, or 16.4/min. That is far below master route
  `00000024--5c888c605c` (108.2/min) but a regression from width=0.50 route
  `00000026--bfe3fd933b` (about 1.9/min), and it fails the predefined recurrence rule. Do not keep
  moving `BRAKE_DOMAIN_ENTRY` or `DOMAIN_HYST_EXIT` as the next arm.
- **Attribution points to the binary actuator transition, not request fidelity.** Across the split
  routes, planner-to-carControl RMS was about 0.007 m/s2 and carControl-to-wire about 0.006. Most
  brake entries used the cruise plan source, and the supplemental brake-PID term was near zero at
  entry. Yet Honda `COMPUTER_BRAKING` was active in 84-90% of the following 0.5 s and engine torque
  changed from positive to negative. A representative route-28 entry at 187.70 s carried request
  +0.05 and wire +0.04 on a -0.041-rad descent while aEgo changed +0.42 to -0.27 m/s2. Smooth
  numeric targets therefore do not make repeated gas-to-brake state changes smooth at the vehicle.
- **The first `ody-op-test` three-state candidate FAILED its road screen.** Route
  `00000029--4c9b612e7c` carried 9.718 engaged minutes and 163 state transitions: 24 gas-to-brake,
  23 brake-to-gas, 53 coast-to-gas, 48 gas-to-coast, 8 coast-to-brake, and 7 brake-to-coast. The
  driver-reported 08:33 pulsing coincided with repeated raw-request crossings near -0.30, typically
  producing 0.6-1.0 s brake pulses with `COMPUTER_BRAKING` on every entry. Route-wide achieved jerk
  RMS was 0.376 m/s3 (0.749 in brake versus 0.323 outside brake), and the validator measured 20.3
  downhill brake edges/min. Request-to-wire fidelity remained good. The coast state was reachable
  for 42.33 s over 60 events, but compensated force could reactivate gas throughout the old
  brake-release band, so coast did not separate gas from brake.
- **The one-command gas-to-brake coast interlock is CLOSED without promotion.** It removed the
  direct gas-to-brake edges it targeted, but current routes `0000003f--cf7b94c588` and
  `00000040--ff2868cffe` still produced driver-felt downhill pulses. A mechanism passing its own
  invariant is not evidence that it fixed the symptom.
- **Matched stock radar is the smoothness reference, not the target-selection oracle.** Route
  `0000002b--4882f84449` had 41 transitions over 11.4 Honda-ACC-active minutes and zero direct
  gas/brake handoffs. Its route-wide achieved jerk RMS was 0.305 m/s3 (0.511 in brake versus 0.280 outside
  brake). Around 08:37:49 Honda ramped brake over roughly 2.8 s while passing a lead; another short
  brake command occurred around 08:38:43 without an openpilot vision lead. The received Honda CAN
  proves the brake commands, but the proprietary radar target choice is not logged. Keep phantom
  braking separate from the smooth actuator-transition evidence.
- **The 2026-08-13 conclusion that only episode timing remained is RETRACTED.** It was based on
  route-wide/windowed jerk summaries from routes `38`/`39` and radar route `2b`; those aggregates
  hid how quickly the shallow downhill commands reached their depth. On the completed direct-release
  arm, route `3f` had 9 physical downhill edges over 0.272 min (33.1/min) and route `40` had 16 over
  1.223 min (13.1/min), versus 4 over 1.316 min (3.0/min) on stock-radar route `3b`. Typical
  OpenPilot downhill brake applications lasted 1.0-1.1 s; the wire reached 80% command depth in
  0.19-0.20 s and achieved acceleration reached 80% in 0.64-0.66 s. Radar's two downhill
  applications had a median duration of 10.86 s and median achieved-accel 80% time of 8.08 s.
  The gap is both WHEN and HOW.
- **Upstream stock is a measured control, not the recovery candidate.** Master route
  `00000024--5c888c605c` (opendbc `44f2987cb6ed`) produced 98 downhill edges in 0.906 min
  (108.2/min, peak 25/10 s), versus 2 in 1.057 min on `ody-op` route
  `00000026--bfe3fd933b` (1.9/min, peak 3/10 s). The current upstream pin `c536b211b762` retains
  the same relevant raw-accel, fixed -0.20 Honda Bosch split. Resetting the driving candidate to
  upstream stock would therefore restore the worst logged version of this symptom.
- **Attribution on routes `3f`/`40`:** the pulse clusters were cruise-plan requests crossing the
  raw -0.40 entry. Planner-to-carControl RMS was 0.0067/0.0101 m/s2. The car port converted those
  small crossings into `BRAKE_REQUEST`; its shaper started at -0.20 and reached the shallow
  -0.45..-0.54 episode depth in about 0.2 s. Honda then asserted `COMPUTER_BRAKING`, dropped engine
  torque, and amplified achieved jerk. The first discontinuity was the domain state; the shaper was
  also much faster than radar. `BRAKE_PID_KI=0` cannot explain the pulses and has no isolated matched
  road benefit, so neither it nor the raw -0.40/direct-release stack carries into `ody-op-test2`.
- **The onset-only `ody-op-test2` design was withdrawn before road validation.** It would have
  started `ACCEL_COMMAND` at -0.10 and progressed at 0.60 m/s3, with -1.5 m/s2, stopping, and
  10 m/s bypasses. Those values were bracketed by only two matched-radar downhill entries and were
  never proven on this vehicle. They remain historical command-shape rationale, not live behavior.
- **Archived stock-radar evidence establishes semantics, not calibration.** OEM-long routes
  `00000012--36525474db` and `00000013--dd070c2142` contain repeated 0.66-1.73 s coast runs at mild
  `ACCEL_COMMAND` (roughly -0.1 to -0.3), usually gas-to-coast-to-gas and once
  gas-to-coast-to-brake near -0.35. Their downhill exposure and brake sample are too small to choose
  thresholds or predict ride quality. Promotion requires terrain-matched road comparisons against
  stock Honda radar and `ody-op`.
- **Historical fixed-input coast replay established reachability only.** Replaying master route 24 and ody-op
  routes 26-28 through `ody-op-test` produced coast in 2.1-5.8% of engaged frames, with 18-37 coast
  entries per route, while preserving `ACCEL_COMMAND` through the coast state. The recorded aEgo
  still belongs to the old controller, and replay/request error changed materially on three routes;
  do not use these counts or jerk values as a road prediction.
- **No custom brake PID is retained.** The earlier `BRAKE_PID_KI=0` replay ablation was not road
  proof; the fresh reset instead follows the independently verified upstream Bosch constraint that
  Honda closes the acceleration loop and the port should not stack another controller. Windfactor
  identification remains parked because its learner is coupled to gasfactor.
- **Historical pooling note:** entry=-0.30,width=0.50 hashes `c1ce76fa857a`, `14677d814cb2`, and
  `2cc9d0df854d` are behavior-equivalent. Their 19/20 interim gate and later route evidence describe
  the now-closed 0.50 arm and must not be pooled with the failed 0.20-width retest.
- **Late slow-lead braking — WATCH, mixed attribution (`0000001d--9be29ce71e`, 11:36:38-11:36:50):**
  the vision-only lead estimate was unstable (`~120 m -> absent -> 110 m -> 65 m`, with closing
  speed worsening to -8.5 m/s), and the planner did not select `lead0` until 0.9 s before the driver
  intervened. That is the first and dominant divergence. The numeric car-port output was faithful
  (route passthrough RMS 0.006 m/s2; immediately before intervention request -1.12, wire -1.18), so
  the controller did not withhold `ACCEL_COMMAND`. There was a smaller domain contribution: on
  frozen recorded inputs, compensated entry occurred at 11:36:49.55 with -0.20 and 11:36:49.76
  with -0.30; the driver braked at 11:36:50.02. Thus the prior entry candidate added ~0.21 s, while the
  compensated-force architecture as a whole entered ~2.0 s after a raw -0.20 request comparison.
  Do not tune against this one perception-confounded event. Reopen/revert the entry candidate if
  late onset repeats with a stable lead trajectory; keep inspecting lead, request, wire, gas/domain,
  and `aEgo` separately.
- **Gas-command ramp — MECHANISM VERIFIED, CALIBRATION RETIRED**: after its precharge defect was
  fixed, seven ordinary drives produced 72 first-live commands at `<=60` counts and official route
  `00000056--9c1708dfa7` added 101 more with clean lifecycle behavior. That proved the limiter worked
  as coded and could complete the maneuver suite; it did not compare driver feel, achieved response,
  or launch delay against upstream direct gas, and therefore did not prove the ramp or its 60-count
  value helped. The route-42 resume audit further showed the limiter consumed about 0.45 s while the
  larger response deficit continued for several seconds. `ody-op-test2` now applies calculated gas
  immediately and retains the first-live command metric as a diagnostic. Reintroduce a limiter only
  after an isolated direct-versus-limited road comparison identifies a repeatable transition defect.
- **Lateral tune — RETIRED TO STOCK 2026-08-11.** The planned cold-start fallback confirmation was
  never executed: route `00000055--b6c9bb3917` completed all 24 lateral runs but `liveDelay` stayed
  cached at 0.444 s. The GPS-matched stock/ody routes showed essentially equal lateral tracking
  (0.0670/0.0649 RMS), residual lag (0.11/0.12 s), and live delay (0.372/0.374 s), with no lane
  departure warnings. With no isolated benefit, `steerActuatorDelay` returned from 0.20 to stock
  0.15. Reopen only for a logged lateral symptom; `validate_log` deliberately has no lateral checks.
- **Windfactor identification — PARKED, not part of this arm**: logs show windfactor can move while gas is not commanded. It is not known-good behavior; it remains unchanged only to isolate the brake-source reset. Any removal or replacement must be an independent gas-side experiment so attribution stays possible.
  - **Offline shadow added 2026-08-01:** the validator now replays the same sign-only learner only
    on live gas commands with neither pedal pressed, away from actuator rails, above 15 m/s, and
    at steady speed/grade. Four substantial current-logic routes (`0000003c`, `0000003e`,
    `00000044`, `00000049`) provided 110 eligible minutes; every shadow moved from 0.50 to
    0.10-0.14 while observed mean error remained negative (-0.007 to -0.033 m/s²). Tightening the
    identification gate does not keep the factor off its lower rail; treat this as evidence of
    base-drag/gasfactor coupling, not evidence to change production commands.
- **Domain hysteresis — CLOSED WIDTH TEST**: the 0.50 width's anti-tapping benefit and release cost
  remain historical evidence. The 0.20 retest returned tapping and failed its early rejection rule.
  Preserve both results; do not resume width tuning without a new mechanism-specific symptom.

## Ordered Longitudinal Evidence Queue (agreed 2026-07-31)
Apply this order as new logs arrive; do not skip ahead because a later idea is easy to code. Lateral
is stock unless a logged symptom reopens it. The onset-shape and custom brake-PID questions are
closed by removal; do not couple the remaining gasfactor and windfactor work to a new brake arm.

1. **Keep the raw-split `ody-op-test2` reference failed and the promoted three-domain behavior
   bounded to its measured road-screen result.** Before making another longitudinal change, run
   controlled start, set-speed, moderate brake, and lead-free descent maneuvers in a safe empty area.
   Then compare new children against `ody-op` using physical `BRAKE_REQUEST` edges, coast exposure,
   set-speed error, onset timing, interventions, and complete stops. Replay establishes only that the
   intended CAN shape changed.
2. **Evaluate a gas-active-only shadow windfactor as a separate gas-side arm.** First calculate it without changing commands. Learn
   only while `GAS_COMMAND` is live in the gas domain, neither pedal is pressed, the command is away from
   saturation, and speed/grade are sufficiently steady. Compare stability and following error with the
   existing learner; promote, replace, or remove it only in its own isolated road arm.
3. **Consider Toyota-style predictive brake-integrator winddown only if overshoot repeats.** Require the
   brake-PID overshoot check to recur on at least 2 substantial, comparable recent routes and agree with a
   controlled brake maneuver. Adapt only future-error/integral winddown to the one-sided supplemental
   brake PID; do not port Toyota's full PID on top of Honda's internal loop.
4. **Leave the ruled-out cross-brand mechanisms alone without a new logged symptom.** Do not add generic
   jerk limiting, Ford-style creep subtraction, more brake gain, GM-style actuator blending, or
   Tesla/Hyundai/VW CAN features Honda does not expose. None can repair a planner `shouldStop=false`
   event or provide stop-line detection.

## Custom Tuning & Development Guidelines
- Start with current openpilot architecture, DBC semantics, and panda limits. Locate the first logged
  divergence before selecting a parameter or implementation pattern.
- Cross-brand code is a source of hypotheses, not a recommendation. Transfer a pattern only when the
  actuator semantics and a specific Odyssey symptom match.
- **Planner/Perception vs. Car-Port Boundary**: Late or hard braking on a lead approach, lead-tracking dropouts (`radarState/leadOne/dRel` jumping to max and back), and jumpy `aTarget` are **upstream of the car port** - they come from the model / `radard` / longitudinal planner, not `carcontroller`. Diagnose before tuning: if `aEgo` faithfully tracks `aTarget`, the control is fine and it's the planner/perception; only if the *output* diverges from the *command* is it ours. Don't chase planner behavior in the tune. The real lever is **driving personality** (Relaxed = longer follow distance, earlier and gentler braking). This has recurred many times in this project - verify the trace first.
  - **Measured instance (2026-07-27, "stopping too close / stops late at lights", routes `00000023`/`00000021`/`00000017`)**: attribution over every >5 m/s-to-stop approach came out the same on both branches - `mean(aEgo - aTarget)` within **±0.03 m/s²** (we track the request), `mean(wire - aTarget)` **negative** on every route (-0.036 to -0.046: our `brake_pid` only ever *adds* authority), and deepest achieved decel always *exceeded* deepest asked (-3.09 vs -2.89 asked; -3.74 vs -3.50). Structurally it could not be otherwise: `target_accel = min(accel, accel + brake_addon)` is one-directional, and `DOMAIN_HYST` widens the *exit* from the brake domain so it holds BRAKE_REQUEST longer, never shorter. The lateness lives in `aTarget`. Mechanism: `STOP_DISTANCE`=6.0 m and `COMFORT_BRAKE`=2.5 (`long_mpc.py`); when the plan commits late (route `00000023` #2: 24.7 m at 14.1 m/s needs ~5.3 m/s² to stop 6 m short, asked -2.83) it lands at ~4.5-5 m instead of the 7-8 m it reaches when it commits on time - and that late-commit signature appears on **baseline too**. Also note the car was in `experimentalMode=True`, so the model writes the longitudinal plan directly including stopping for lights; the car port has no concept of a stop line at all. **A permanent validate_log check for this was deliberately NOT added** - it returns "model" every time, so it carries no information; re-derive ad hoc if a specific stop ever looks wrong.
- **Document All Custom Changes**: Every single custom edit must include an inline comment explaining exactly *why* the change was made, written PR-lean from the start — the why and any revert trigger live in the code, while numbers and route history live in this file. (The `TODO: delete excessive comments before trying to submit a PR.` marker convention was retired 2026-08-08 after an audit brought every comment to PR standard; do not reintroduce the marker.)
- **Write Findings Into the Code, Not Just the Chat**: When a session spends real effort (WebFetch calls, DBC spelunking, log analysis) establishing *why* something is tuned a certain way, that reasoning belongs in a comment at the point of use, not just in conversation - it saves re-deriving the same investigation (and the tokens/PR fetches that cost) in a future session.
- **Comments Are a Starting Point, Not Ground Truth**: Custom-tune comments (including "CUSTOM TUNE" blocks and any journal-style writeups) reflect the reasoning *at the time they were written*. Treat them as a lead to verify, not a fact to cite - upstream PRs move, DBC signals get re-checked, and code gets reworked or reverted out from under a comment that still references it. If you find one that's stale, wrong, or points at code that no longer exists, correct or remove it as part of your change rather than leaving it to mislead the next session.
- **Jotpluggler Layout**: The `brikowski` layout (`openpilot/tools/jotpluggler/layouts/brikowski.json`, launched via the "Run Jotpluggler" task) is the standard layout for reviewing tuning drives. Keep the checked-in JSON minified. Its five tabs cover lateral reference, longitudinal tracking, learned factors, powertrain/CAN, and lead/feedforward attribution. The historical deployed child wrote effective gasfactor and windfactor telemetry into `actuatorsOutput.gas` and `.brake`; the upstream-rooted port restores those fields to actual actuator output, with raw commands remaining in `sendcan`. Any future learner telemetry must use deterministic offline reconstruction or a separately named diagnostic event approved with its schema.

## Known Upstream Constraints (Honda Bosch A/C - not cached locally, re-fetch if reasoning needs re-verifying)
- **opendbc PR #2165** (github.com/commaai/opendbc/pull/2165): wind drag + hill/pitch compensation for Bosch gas pedal force. Still draft upstream, parked pending a broader drivetrain-torque refactor.
- **opendbc PR #2347** (github.com/commaai/opendbc/pull/2347): documents that Honda Bosch's own ECU already runs an internal brake PID. Stock `kp=0, ki=0` (pure feedforward) in `interface.py` is deliberate - adding openpilot's own closed-loop kp/ki on top "doubles up... and causes oscillating braking/acceleration strength." Check this before adding closed-loop longitudinal gain on a Honda Bosch car.
- **opendbc PR #2767** (github.com/commaai/opendbc/pull/2767, closed): a comma engineer tried pitch-compensation on the gas pedal and hit "will need to switch the gas actuator from accel-based to torque-based first." Bosch A has no writable torque CAN signal (`ACC_CONTROL.ACCEL_COMMAND` is a real m/s2 value Honda's ECU closes its own loop on; `ACC_CONTROL.GAS_COMMAND` is opaque/unitless). A torque-based redesign would mean reverse-engineering a speed-dependent `GAS_COMMAND`-to-torque calibration using the car's own `GAS_PEDAL_2.ENGINE_TORQUE_ESTIMATE` telemetry as ground truth.
- **Current longitudinal design on this branch**: `ody-op` runs a speed-scheduled, live-trimmed gas feedforward plus one-sided supplemental integral braking. Filtered grade and learned drag feed gas and the compensated domain decision but never add brake authority. One stateful domain selects gas versus brake, gates supplemental braking and gasfactor learning, and is mirrored onto CAN. Below 5 m/s the raw controller request prevents grade compensation from releasing an engaged stop. Windfactor remains only partly identifiable; see the concise rationale and current code before using this historical archive.
- **Review-sized design record**: `.agents/odyssey-tune-rationale.md` is the concise durable rationale removed from production comments; use the longer history here only when investigating a regression.
- **Tune status (validated 2026-07-20, lateral returned fully to stock 2026-08-11; longitudinal has one isolated road candidate)**: after the master rebase + domain-decision cleanup, on-road drives (routes `00000009`, `0000000b`, `0000000c` under `805f87f5e96d128c`) show: zero `controlsd` crashes; planner->carcontroller passthrough near-perfect (`|aTarget-cmd|` ~0.0005-0.06); brake_pid gentle, no windup. **At that historical point, lateral followed OpenPilot's stock-LKA baseline: 2560 maximum command, `latAccelFactor 0.9`, and `steerActuatorDelay=0.15`; the former linear 3840 RDM-range command, 1.1 override, and unproven 0.20 delay are historical, while the current isolated 3840 arm and lateral diagnostics are recorded above.** **The older "windfactor confirmed NOT dead" conclusion is retracted.** Current production and gas-active-only shadow evidence cannot identify windfactor independently from gasfactor and grade; its value remains parked and unproven. Before proposing a tune change, look for a specific logged symptom first. **Lead-approach braking that feels abrupt is upstream, not ours**: radar is disabled so every lead is vision-only (`radarState/leadOne/radar`=0, 0% radar-matched on real routes), and vision range-rate noise at 100m+ (worse in rain) makes the planner brake ~-0.5 to -0.8 m/s2 - gentle in magnitude, abrupt in onset. The only lever is Relaxed personality (settings, not code); comma's own radarless model work targets this.
- **Historical brake-onset experiment (`DOMAIN_HYST` 0.06 + symmetric 2.0 m/s³ jerk limit): CLOSED 2026-07-27, both branches DELETED.** Do not recreate that combined architecture: its functional change and failed isolation remain useful history. The current `ody-op-test2` candidate does not shape `ACCEL_COMMAND`; it adds a stateless coast domain and low-speed brake selection only. Retired tips in case the historical commits are still reachable: `ody-brake-onset` = parent `cb03c32b4` / opendbc `1b6048e98`; `ody-op-long2` = parent `9f73e6205` / opendbc `57fe3a908`.
    ```python
    DOMAIN_HYST = 0.06                     # module scope
    self.in_brake_domain = False           # __init__
    base_min_gas_accel = float(np.interp(CS.out.vEgo, [5.0, 10.0], [0.01, min_gas]))
    min_gas_accel = base_min_gas_accel + (DOMAIN_HYST if self.in_brake_domain else -DOMAIN_HYST)
    self.in_brake_domain = in_brake_domain
    ```
  - **The honest verdict on the hysteresis half is UNTESTED, not "no benefit".** Replay predicted 62 -> 32 toggles; four road drives (48.7 engaged min against 46.7 baseline, flip totals 127 vs 126) showed nothing. But that A/B graded a whole-drive forceful-flip fraction while the defect concentrates on descents, which are 2-5% of engaged time - diluting any grade-local effect ~10x before the test saw it. Re-run on descent toggles it reads 2.2x, which then fails our own leave-one-out rule (drop route `2f` and it falls to 1.48x, z 3.93 -> 1.62). The one apparently-significant pooled result (forceful share 33.0% vs 45.1%, p=0.048) was carried entirely by route `00000005` and collapses to p=0.61 without it - see "Ledger Comparability Rules" for why that route is excluded from every pooled comparison. Power was ~127 flips per arm, enough to rule out a *large* city benefit and not a modest one, and the experiment arm had zero highway minutes. Say "untested", not "no effect".
  - **The jerk-limit half genuinely does nothing, for a structural reason.** `SOFT_BRAKE_FLOOR=-1.2` bypasses the ramp on firm brakes, and every large-jerk event on the test drive was firm (command reached -2.0), so commanded wire jerk was unchanged to nine significant figures. **Raising the cap makes it act LESS, not more** - do not "fix" it that way. The one number it moved is a trap: forceful toggles read 25 / 22 / 18 across the arms while the toggle *count* stayed 32, i.e. the ramp was holding the command shallower at the instant of the toggle so it fell under the 0.3 m/s^2 "forceful" threshold. That is the metric being gamed by delayed brake depth, which is the very behaviour suspected of adding release jerk.
  - **Two measurement traps this exposed, both still worth knowing.** `validate_log`'s original brake-onset jerk check differentiated `carControl.actuators.accel` - the planner's command, an INPUT to the car controller - so it read identically on every branch and could never measure a carcontroller change; `wire_jerk_*` (added 2026-07-26) measures `ACCEL_COMMAND` and is the real A/B readout. And the replay's `BRAKE_REQUEST` toggle counts are fiction, for the reason in "What the replay can and cannot predict" below. The replay itself is sound for command shape - replaying the baseline branch gives `replay_vs_recorded_rms` = 0.0069 m/s^2.
  - **Still-valid finding from route `00000013`**: the one recurring highway deviation is uphill accel undershoot until the 10-speed kicks down - a transmission trait, **NOT a tune fault**. Do not raise gasfactor; it worsens the post-downshift surge. That route also re-confirmed the converged tune is healthy (RMS `|aEgo-aTarget|` 0.22, passthrough RMS 0.11).
- **openpilot PR #38394** (github.com/commaai/openpilot/pull/38394): Adeeb removed per-car `stoppingDecelRate` and `vEgoStopping` from `CarParams`, hardcoding universal values in `longcontrol.py` (decel rate → 1.0 m/s²/s, vEgoStopping → 0.25 m/s via new `should_stop()` helper). Both fields deprecated in `car.capnp`. Zero direct impact on our branch (we don't set either). Minor behavioral change: stopping state engages at 0.25 m/s instead of 0.5 m/s (slightly later, arguably better). Validates the "shared logic, learning handles car differences" direction - comma is actively removing per-car longitudinal differentiation.

## Per-Log Validation Workflow (added 2026-07-22)
- **Run `.agents/validate_log.py <route>` on every pulled log** (the pull task does this automatically). It computes coverage, convergence/safety, driver interventions, model-following and lifecycle diagnostics, ride-quality indicators, and device thermal health. It prints a PASS/FLAG verdict and appends one idempotent row to the evidence ledger.
- **Ledger**: `.agents/log-validation-ledger.jsonl` (authoritative, one JSON row per log) + `.agents/log-validation-ledger.md` (human table). The script reads accumulated Odyssey rows and **suggests status transitions** (a symptom flagged in ≥2 of the last 5 logs → promote watch→CANDIDATE; any flag against a check whose status is PARKED → revisit it). It never edits this file — a human applies suggestions to the statuses below, so the prose stays curated.
- **Metric integrity note (learned 2026-07-22)**: the brake-onset jerk metric MUST differentiate the command over a ~0.1s window with heavy pre-smoothing, NOT frame-to-frame. The command updates at 50Hz (`carcontroller` frame%2) but `carControl` logs at 100Hz; a naive `np.gradient` aliases that into phantom jerk. First real run (route `0000000e`) showed **15 phantom binds** with frame-diff vs **1 marginal bind (peak 2.1 m/s²/s, cap 2.0)** with the windowed metric — the same aliasing that faked the earlier "clipped live" claims. If you touch the jerk check, preserve the windowed differentiation.
- **How the gasfactor seed was derived (2026-07-24, the first tuning change the ledger produced)**: the cross-drive "GASFACTOR vs SEED" report over 4 drives, confirmed by a narrow ±1.5 m/s per-breakpoint check, showed the low-cruise dip in `GAS_FACTOR_SPEED_V` was over-fit to the single original drive (00000088). Converged effective gasfactor is **0.54 at 8 m/s** (tight spread 0.52-0.56, implied trim ~1.55) and 0.57 at 15 m/s — the seed under-gassed low cruise so the trim re-clawed it 1.55x from 1.0 every cold start (persistence dropped) = the low-cruise sluggishness the baseline is meant to kill. Raised **8→0.54, 15→0.56** (opendbc `ec2e5a1b1`); 22 m/s (0.60, trim 0.94) confirmed good and left as-is. The 0 m/s seed was 0.90 at the time and was **later lowered to 0.72** (the "0 m/s gasfactor seed change" referenced under Ledger Comparability Rules); the shipping table is now `GAS_FACTOR_SPEED_V = [0.72, 0.54, 0.56, 0.60]`. **Read the constant, not this paragraph** — the individual seed commits were squashed into opendbc `ed78a3f1b`, so this history is not recoverable from the log. **This only changes cold-start ramp — converged steady-state is identical** (the trim compensated either way), so it's low-risk and doesn't reopen the converged tune. (Three checks added alongside it — domain chatter, stop-approach quality, post-kickdown surge — were all removed again 2026-07-29; see "Model Following" for why.)
- **Gasfactor report correction (2026-08-09):** the later `8 m/s: seed 0.54 learned 0.63 (n=46)` suggestion is invalid. That report averaged a 4.0-11.5 m/s midpoint bin, compared it to the single 8 m/s point, accepted ~0.21 s of exposure, mixed code versions, and weighted every drive equally. The validator now uses ±1.5 m/s live-gas frames, compares learned and interpolated seed on identical frames, requires 30 s per route plus 300 s/3 routes, excludes thin/qlog/route 5 data, exposure-weights, and groups by exact `opendbc_commit`. Keep the 8 m/s seed at 0.54 until the corrected report earns new evidence.
- **Test-suite audit (2026-07-26, routes `00000015`/`00000016`)**: audited every check against the 8 accumulated rows and cut what could never fire or could never *stop* firing, then added what was missing.
  - **Added — coverage** (`engaged_min`, `engaged_mi`, `engaged_frac`, `vego_max`; never flags). The ledger previously could not distinguish a clean row earned over 45 engaged minutes from one earned over 30 seconds, yet every cross-drive aggregate weighted them equally. It now also gates `suggest_status`, so a thin drive can't cast a vote in a "2 of the last 5" promotion.
  - **Added — driver interventions** (gas overrides, brake takeovers, per 10 engaged min). The only checks graded by what the *driver* did rather than by telemetry we chose how to interpret. Note the Honda-specific trap: the brake switch drops `longActive` on the same frame, so `active & brakePressed` reads ~0 on every drive — attribute a press to OP if it was engaged within the preceding 0.5 s. Reported as "N of M brake presses" so a 0 with a healthy M means the driver never braked out, while 0 of 0 means the signal never arrived and the metric proved nothing.
  - **Added — accel rail saturation**: the wire is clipped to `BOSCH_ACCEL_MIN/MAX`, and sitting on the upper rail both reads as sluggish and freezes the learner (the carcontroller's own "at accel max the signal is saturated" guard). Tracking error can look perfect while pinned, because `aTarget` was never deliverable — no other check would surface it. 0.0% on both new routes.
  - **Removed — charging diagnostics**: route logs do not replace a mechanic's battery/alternator test, so `validate_log` no longer extracts, grades, or reports `pandaState.voltage`. Historical ledger rows keep their old fields for provenance, but future validation is limited to driving behavior and comma-device thermal health.
  - **Result**: `00000015` (47.3 min / 54.8 mi engaged) all-green. `00000016` (43.0 min / 47.7 mi) flagged brake_pid overshoot 7.3%, 4 jerk binds (peak 3.8 m/s³), and forceful domain chatter — **with zero driver interventions**, which is exactly the contrast coverage + intervention tracking was added to expose. Those three flags are telemetry symptoms on a drive the driver never once overruled; treat them as evidence to accumulate, not a mandate to change the converged tune.

## Live-learn or constant? (decided 2026-07-29)
Two things are live-learned today: `gasfactor` trim has direct supporting evidence, while
`windfactor` is not independently identified and remains an architecture question. The test for
retaining or adding a learner is:
1. **Is it a physical property of the plant, with an unambiguous per-frame error signal?** `gas_error = self.accel - aEgo` gives the gas/drag learners a signed error every frame. A crossing RATE or a chatter statistic is not that - it is a measurement over minutes.
2. **Is a wrong value merely degraded, or unstable?** Wrong `gasfactor` = sluggish or eager, self-correcting. Wrong hysteresis width = a behavioral failure mode, and the degenerate direction is dangerous.
3. **Can it converge inside one drive?** **Persistence is deliberately dropped** (no openpilot `Params` from opendbc, see the carcontroller note), so every learned value resets at each ignition. Anything that cannot converge in minutes must be a constant, because it will never be right when it is needed.
- **`DOMAIN_HYST_EXIT` must stay a constant.** It is a state-selection parameter, not a plant
  estimate, and descents are only 2-5% of driving (0.17-2.09 min per drive measured), so a learner
  would spend every drive re-converging. Size it offline from road evidence rather than adapting it
  from transition counts.
- **`hill_brake`'s gravity gain was the one remaining genuine candidate, and it is NOT worth learning.** It is physical and has a clean error signal, so it passes tests 1 and 2. But measured over 328k learner-eligible gas-domain frames across 5 drives, the residual `gas_error` regressed on the hill term gives slope +0.092, r = +0.145, implying a correction of only **0.91x** - about 9%, or 0.02 m/s^2 on a typical -0.22 hill term. The residual is dominated by a **pitch-independent** intercept (-0.069) that the existing learners already absorb. Note the trap: run this regression over ALL frames rather than gas-domain-only and the slope inflates, because `brake_pid` makes the wire more negative exactly on descents where the hill term is also negative - manufacturing a correlation that has nothing to do with gravity.
- **Never learn**: `BRAKE_PID_KI` (adapting a gain against Honda's own brake loop is the #2347 instability by construction), `min_gas_accel` or any domain threshold, and the learn divisors themselves.

## Where the constants belong (audited 2026-07-29)
`tune-evidence.md`'s own Bosch A generalization target is "shared Bosch A logic in `carcontroller.py`, per-car seed tables in `values.py`". **We are not there yet**, and it matters because module-level constants in `carcontroller.py` would silently apply to every Bosch Honda the moment the `CAR.HONDA_ODYSSEY_5G_MMR` gate is widened.
- **Per-car, should move to `values.py`**: `GAS_FACTOR_SPEED_BP/V` (powertrain), the `wind_brake_ms2` curve (aerodynamics - frontal area x Cd, currently an inline `np.interp` at the point of use), and any evidence-derived fixed drag factor. Naming and relocating the curve is behavior-neutral; changing its factor or learning rule is a separate road arm.
- **Shared Bosch A, correctly module-level**: `DOMAIN_HYST_EXIT`, `BRAKE_PID_KI`,
  `BRAKE_DOMAIN_ENTRY` and its `min_gas_accel` speed ramp (PR #2342 behavior), and the learn divisors
  (convergence rates, not plant properties). The Odyssey fingerprint gate currently limits their use.
- **Already correct**: `BOSCH_GAS_LOOKUP_V = [0, 2000]` is an INSTANCE attribute in `values.py`, not a class mutation. Upstream still mutates the class for `ACURA_RDX_3G_MMR`; ours does not, which is why it does not leak across cars in `test_car_interfaces`.

## What the replay can and cannot predict (learned the hard way, three times)
`replay_carcontroller.py` feeds the controller **recorded** `aTarget` and `aEgo`. Those are inputs, frozen. So the replay can answer "given this exact input trajectory, what would the new code command?" and nothing more.
- **VALID**: the shape of the command on a fixed input - wire jerk, command magnitude, how much `brake_pid` adds at a given error. Anything that is a pure function of the recorded inputs.
- **INVALID: any count of domain transitions - `BRAKE_REQUEST` toggles, domain flips.** Toggling is a **closed-loop** property. `switch_accel = aTarget + drag + sin(pitch)*g`, and `aTarget` is the planner responding to the car's state. Brake harder or longer and the car slows more, so the planner asks for less decel, so `switch_accel` climbs back across `min_gas_accel` and the limit cycle simply re-forms at a new period. That feedback path **does not exist in the replay**, so its toggle counts are fiction.
- **The evidence**: `DOMAIN_HYST` replayed 62 -> 32 flips and showed nothing on-road. `BRAKE_RELEASE_HOLD` replayed 80 -> 42 flips and came back worse on-road, with the driver reporting no felt difference. `DOMAIN_HYST_EXIT = 0.20` swept to 8-9 crossings/min and measured **15.1 corrected physical edges/min** on route `00000033`; 0.50 later measured 3.6-4.8. Earlier 27.4/25.0 figures used the broken compacted-descent counter and are retired. Three confident replay predictions still failed to predict the road ordering or magnitude. If quoting an open-loop count, label it command-shape evidence rather than scaling it into a road prediction.
- **What to size against instead.** For a hysteresis band the closed-loop-independent quantity is the *plan's own ripple* (p-p `aTarget` at set speed, 0.51-0.81 m/s^2). A band smaller than the ripple cannot suppress it, whatever the sweep says. Both failed bands were smaller. Size to the physics of the signal, not to a knee in a curve the replay drew.
- **Rule**: if a proposed change alters *when* we brake, only a road drive can measure it. Use the replay to check the change does what you think to the command, then road-test the effect. Never let a replay delta close the question.

## Model Following: the one question the car port answers (added 2026-07-29)
**"Did we put on the wire what CarController was asked for?" is the whole job.** The exact input is `carControl.actuators.accel`, set by `controlsd` after `longcontrol`; `longitudinalPlan.aTarget` is one stage upstream. `validate_log` used to substitute the latter even while calling it the car-port boundary. Routes `00000034`/`00000035` showed that the two happen to be close here (0.0056/0.0080 m/s^2 RMS), so prior conclusions did not reverse, but the metric was still conceptually wrong and now compares `carControl.actuators.accel` to sent `ACCEL_COMMAND`. Anything upstream of the CarController input belongs to openpilot's control/planning stack; anything downstream of `ACCEL_COMMAND` belongs to Honda's ECU.
- **The blind spot this replaced.** `passthrough_rms` computed `gas_dom = active & ~brake_added`, deliberately excluding brake-domain frames because `brake_pid` "intentionally diverges the wire". Intentional divergence is still divergence, and that exclusion removed from measurement **the only place we ever leave the model**. It hid a real defect indefinitely - no number of drives would have surfaced it.
- **Checks removed 2026-07-29, all for the same reason - they graded the CAR's response or the MODEL's plan, not our fidelity**: `stop-approach quality` (aEgo jerk; stopping is the planner's, established 2026-07-27), `post-kickdown surge` (documented here as a transmission trait, "NOT a tune fault"), `pitch-transition lag` (aEgo vs aTarget with Honda's ECU in the loop; 0 of 5 flagged and structurally unable to catch the real grade defect, which is command-side), and `domain chatter` (whole-drive average - see the CORRECTION above for what averaging cost us).
- **A metric tied to a proposed FIX dies with that fix; a metric tied to a SYMPTOM survives.** `domain chatter` was demoted 2026-07-27 because `DOMAIN_HYST` closed - reasoning from the lever instead of the symptom. The symptom was real and the driver felt it two days later. Name checks after what is wrong, not after what you plan to change.
- **Downhill brake tapping (found 2026-07-29, driver-flagged route `0000002f` @ 07:50:57 and 08:18:53)**: `braking = switch_accel < min_gas_accel` in `hondacan.create_acc_commands` is a bare per-frame compare. On a descent `switch_accel = aTarget + drag + sin(pitch)*g` settles at the threshold while the plan's own ripple is +/-0.1 m/s^2, so it crosses repeatedly - 13 toggles in 20 s against a smooth plan. Each toggle re-engages the friction brake, **flickers `BRAKE_LIGHTS` at following traffic**, and resets `brake_pid` so the next entry ramps from zero. First fix attempted (opendbc `BRAKE_RELEASE_HOLD`, time-debounce the release only): replayed 80 -> 42 toggles, came back **worse** on-road, **REVERTED**. Superseded by `DOMAIN_HYST_EXIT`, which debounces on the same quantity the decision is made from rather than on time. The original 9.5/14.3, 27.4, and 25.0 comparisons were produced by the broken compacted-descent counter. Corrected physical-edge results are in the table below: 15.1/min at 0.20 and 3.6/4.8 at 0.50. Driver interventions stayed low (0.65/0.83 brake takeovers per 10 engaged min).
  - **CALIBRATE AGAINST NO HYSTERESIS, not against the two regressed configs.** `00000032` ran `BRAKE_RELEASE_HOLD` and `00000033` ran 0.20; both came back worse than the bare per-frame compare, so beating them is not a benefit over stock behavior. Group every route by the `DOMAIN_HYST_EXIT`/`BRAKE_RELEASE_HOLD` value actually on the wire (resolve each row's `git_commit` to its `opendbc_repo` pointer - the ledger records the parent commit, not the submodule). A first pass at this table was computed with the broken `np.diff(BR[down])` counter (see "Trusting the instrument"), which added about one phantom toggle per extra descent window and so punished the routes with the most fragmented terrain; those numbers are deleted rather than kept beside the good ones. Every affected route was re-validated with the fixed counter. Corrected, restricted to routes with >=0.5 descent minutes so a 10-second sample cannot dominate:

| config | opendbc | routes | descent toggles/min (corrected) |
|---|---|---|---|
| none | `7962b8b`/`1b6048e`/`ec82317` | 21, 23, 29, 2f | 7.1, 6.7, 10.0, 45.9 |
| `BRAKE_RELEASE_HOLD` | `6d2f79e` | 30, 32 | 27.5, 19.0 |
| 0.20 | `12daafe` | 33 | 15.1 |
| 0.50 | `b21cb2c` | 34, 35 | **3.6, 4.8** |
| 0.50 + low-speed release | `d8f962b` | 3b | **4.8** |

  - **Corrected conclusion: 0.50 does reduce descent toggling, roughly 2x below the best no-hysteresis routes** (3.6-4.8 vs 6.7-10.0), and the two regressed configs sit clearly above baseline where they belong. The morning's "0.50 only recovered baseline" reading was an artifact of the counter, not a property of the tune. **Both the original claim and its retraction were wrong for the same reason: nobody had checked the instrument.**
  - **What is still NOT settled.** n is 2-3 routes per config, descent exposure is 0.84-1.26 min each, and within-config spread remains enormous - route `2f` at 45.9/min sits on the same commit as `29` at 10.0. The corrected numbers make the hypothesis much more likely, not proven.
  - **GATE RESTATED 2026-08-06 - the old ">=3 descent minutes in one drive" gate was unreachable and is retired.** It was written without checking the ledger. Measured over 46 validated routes / 643 engaged minutes: **zero** routes have ever reached 3.0 descent minutes, the maximum ever recorded is **2.10** (`00000049`, over 69 engaged min), and the median is 0.32. Worse, the two routes the gate itself named as the terrain match are `0000002f` = **0.57** and `00000030` = **1.42** descent minutes - together **1.99**, so the gate demanded more descent from a single drive than both of its own reference routes produced combined. Descent is a stable ~4% of engaged time on this terrain, so 3 minutes in one drive needs ~118 engaged minutes of continuous highway; a 129-minute drive (`0000000d`) returned 1.66. The gate also contradicted the pooling rule that governs every other comparison here.
    **The gate is now: >=20 descent hold-episodes pooled across routes at one behavior-equivalent `opendbc_commit` arm, terrain-matched, measured at both the incumbent and candidate setting.** Episodes, not wall-clock, because episodes are what the change is supposed to move; minutes were only a proxy for sample size. A hold-episode is >=0.5 s of `longActive & request > 0.02 & BRAKE_REQUEST & pitch < -0.7 deg`. **The incumbent is satisfied** at `d1d5eb5c7255`: 26 episodes / 74.1 s over 2.93 descent min. The candidate equivalent-hash arm has 19 episodes / 35.7 s over 1.23 descent min through 2026-08-09; one more terrain-matched episode closes sample size but does not predetermine the decision.
  - **Priced cost of a wider band: sign disagreement scales with it.** 0.04-0.72% of engaged frames with no hysteresis, 2.18% at 0.20, 2.39%/2.74% at 0.50 - the two highest in the ledger. Magnitude stayed small (worst -0.12 m/s^2 on `00000035`); the -2.04 m/s^2 on `00000034` belongs to the re-engagement bug below, not to the band.
- **Route `00000034` found a separate state-lifecycle regression in that implementation.** At re-engagement (route t=794.78 s), the CarController input was +0.09..+0.27 m/s^2 while the wire stayed -1.95..-1.76 for 0.20 s. Cause: while `longActive=False`, the hysteresis latch remained in the brake domain and `brake_pid` continued integrating against the driver's acceleration even though `create_acc_commands` correctly sent no brake; it reached about -2.0 and leaked into re-engagement. Fixed by clearing the domain latch whenever longitudinal control is inactive, which also routes the existing `else` through `brake_pid.reset()`. A regression test recreates active-brake -> inactive/manual +2 m/s^2 -> positive re-engagement and asserts ACCEL_COMMAND=+0.10, live gas, BRAKE_REQUEST=0. Open-loop route replay reduces request-error RMS 0.0468 -> 0.0071 and worst positive-request disagreement -2.07 -> -0.58; only a road drive can close the remaining closed-loop question.
  - **CORRECTION 2026-07-30: that test's `BRAKE_REQUEST=0` assertion was vacuous until today.** `_decode_acc_control` read `(dat[4] >> 3) & 0x1`, which is **`STANDSTILL`** (Motorola start bit 35), not `BRAKE_REQUEST` (bit 34 = byte 4, bit 2). `STANDSTILL` is driven by `stopping_counter`, which is 0 throughout these tests, so the assertion read a constant 0 and could never fail. Verified by re-running the sweep with the old index: the new `any(brake_requests)` guard fails 25 of 31 subtests. The *other* two assertions (ACCEL_COMMAND, live gas) were real and are what actually caught the route-34 bug, so the fix itself stands - but do not cite this test as BRAKE_REQUEST coverage for anything dated before 2026-07-30.
  - **Closed-loop validation 2026-07-30:** routes `37`/`3a`/`3b` contain six longitudinal engagements. After allowing one 20 ms CAN command period, none contains a single positive-request frame with stale BRAKE_REQUEST and gas disabled. `validate_log` now records this lifecycle check directly instead of inferring it from the route-wide sign-disagreement statistic.
- **The same 0.50 band had an independent low-speed lifecycle defect (found by code audit 2026-07-30).** At or below 5 m/s, `min_gas_accel` is +0.01 and the switch input is the raw controller request. Carrying the full 0.50 band across an engaged stop therefore required `accel > +0.51` to leave the brake domain. Synthetic CAN output confirmed +0.03..+0.51 requests kept BRAKE_REQUEST=1 and GAS_COMMAND inactive; current-code replay over stop-heavy routes `17`/`21`/`23` found 4/7/6 episodes, 4.0/5.7/4.9 total seconds, with the longest 1.2-1.3 s. The exact on-road duration is a closed-loop question, but the contradictory wire state is not. Fixed by speed-scheduling the exit band from 0 below 5 m/s to 0.50 at 10 m/s, where the switch input also transitions to grade compensation. The parent safety test now decodes the real BRAKE_REQUEST bit (Motorola bit 34 = byte 4 bit 2; it previously read bit 3) and carries an engaged stop -> +0.10 start regression.

## Upstream test coverage of this tune (audited 2026-07-29 by running them)
**Answer: none of upstream's CI executes our longitudinal code, and no upstream test can grade tuning.** Measured, not inferred. Do not re-derive this.
- **`opendbc test_models.py` covers the platform but not the tune.** `opendbc/car/tests/routes.py:113` really does have `CarTestRoute("d7233a428eb7d0b5/00000001--9b99b04d43", HONDA.HONDA_ODYSSEY_5G_MMR)`, and it runs in the `test_models` CI job. But that route predates openpilot longitudinal on this car, so `alpha_long` resolves **False** -> `openpilotLongitudinalControl=False` -> `create_acc_commands` is never called. Measured: **0 ACC_CONTROL (0x1DF) frames emitted.** The domain decision, `brake_pid`, and the gas lookup never run. Even forcing `alpha_long=True`, `test_panda_safety_tx_cases` drives the controller with `structs.CarControl()` defaults (`longActive=False`) plus cancel/resume, which pins ACCEL_COMMAND at 0 and GAS_COMMAND at the -30000 inactive constant for all 3000 frames.
- **The panda safety hook bounds magnitude only.** `honda_tx_hook` on 0x1DF (`opendbc/safety/modes/honda.h`) runs `longitudinal_accel_checks` (accel in [-350, 200] counts = [-3.5, +2.0] m/s^2) and `longitudinal_gas_checks` (gas in [-30000 inactive, 2000]). **There is no BRAKE_REQUEST check and no gas/brake mutual-exclusion check**, so no safety test can ever validate the gas/brake domain *decision* - including the queued `min_gas_accel` change. It is caught if out of range, never if wrong.
- **`opendbc car diff` is a parser test.** `Ref = tuple[int, structs.CarState]` - it diffs decoded **CarState** across segments and never compares `sendcan`. Structurally blind to the tune.
- **openpilot `process replay` has the right signal and the wrong car.** The `card` config subs `sendcan`/`carState`/`carOutput` and `controlsd` subs `carControl`, which is exactly what we would want compared. But its Honda segments are `HONDA` = Civic (Nidec) and `HONDA2` = Accord (Bosch); there is no Odyssey. Our code is gated on `carFingerprint == HONDA_ODYSSEY_5G_MMR`, so it takes the stock `else` branch. **Read green there as proof we cannot regress other Bosch Hondas - that direction only.**
- **Access is fine.** Workflows use `runs-on: ${{ (github.repository == 'commaai/openpilot') && 'namespace-profile-...' || 'ubuntu-latest' }}`, so on `brikowski/openpilot` they fall back to free runners, and comma-only steps (pushing refs, submodule check) are gated on repo name. The exception is `jenkins-pr-trigger.yaml` - comma's Jenkins driving real hardware, not available to us.
- **None of them help with tuning, structurally.** They are regression and legality tests over frozen recorded inputs. `process_replay` in particular has the **identical blind spot** documented above for our own replay harness: frozen `aTarget` means no feedback path, so it could never have told us whether `DOMAIN_HYST_EXIT` reduces toggling. Same trap, three times already.

**What we added instead (2026-07-29):**
- **`.agents/test_odyssey_long_rails.py`** - parent-repository coverage for the custom tune; keeping it outside the opendbc submodule leaves that worktree scoped to production edits. It drives the *active* path (`longActive=True`) over the full accel authority and across grade and speed, and asserts every emitted 0x1DF passes the real panda TX hook. Fills exactly the gap above. Runs in under 2 s, needs no route download. **Mutation-verified**: deleting the `np.clip(target_accel, BOSCH_ACCEL_MIN, BOSCH_ACCEL_MAX)` in `carcontroller.py` fails 26 of 28 sweep cases. It also carries a `test_sweep_actually_reaches_both_rails` guard so the assertions cannot go vacuous if the sweep range drifts, plus the route-34 inactive-state/re-engagement and engaged stop/start regressions above. This matters most for the coming `min_gas_accel` change: an out-of-range ACCEL_COMMAND is dropped by the panda **silently, while driving**.
- **`.agents/preflash.py`** - runs both (`test_models` for the Odyssey + the rail test) in ~4 s. `test_models`' concrete classes only exist under `DIRECTLY_CALLED`, hence the hand-built runner. Run it before flashing; it says nothing about ride quality, which still needs a drive plus `validate_log.py`.

## PARKED NEXT: decouple the domain threshold from the gas-lookup floor (queued 2026-07-29)
`BRAKE_DOMAIN_ENTRY=-0.20` is now named separately from the gas lookup with no behavior change.
Do not combine a future entry experiment with a release-band change: entry at -0.10 addresses
delayed brake entry, while route `00000002--412e40c6a0` exposed an excessive release hold. Moving
entry alone to -0.10 increased frozen-replay brake exposure from 13.7% to 18.0%; it is not the fix
for the reported underspeed. A combined -0.10 entry / 0.15 band released that event 1.12 s earlier
on frozen inputs, but 0.15 is narrower than the 0.20 band that already failed on road and the pair
changes both sides of the state machine. Keep it experimental until a clean baseline drive exists.

**The next drive should be the `0000002f`/`00000030` descent route carrying a CANDIDATE value, not
another baseline.** The 0.50 baseline arm is closed (26 pooled hold-episodes, see the restated gate
above); do not spend another drive re-measuring it. Drive the same roads with ordinary
disengage/re-engage and stop/start cycles until the candidate arm also reaches 20 pooled episodes.
Compare physical `BRAKE_REQUEST` bursts, compensated-force release holds, interventions, sign
disagreement, and whether set-speed recovery still undershoots. Known felt-tapping route `2f`
produced **18 physical edges/10s**, failed `BRAKE_RELEASE_HOLD` route `30` produced **10**, and 0.50
routes `34`/`35` produced **3/4**.

`min_gas_accel` is derived from `BOSCH_GAS_LOOKUP_BP[0]` (= `min_gas` = -0.2), so the domain threshold asserts *the gas domain can deliver -0.2 m/s^2 of deceleration*. It cannot. At the crossing we command **23 of 2000 counts** of gas (1.2% throttle) and achieve ~0.0 m/s^2 while the plan asks -0.15. The whole -0.2..0 span of "gas authority" is under 9% throttle, which produces no braking at all. **The gas-signal scaling floor and the can-we-still-follow boundary are two different numbers sharing one constant.**

Measured following error inside `-0.2 < aTarget < -0.02`, gas domain, above 10 m/s, over routes `0000002f`-`00000033` (positive = decelerating LESS than asked):

| grade | sec | mean err | p90 | frac > 0.15 |
|---|---|---|---|---|
| mild down | 45 | +0.153 | +0.311 | 58% |
| flat | 120 | +0.146 | +0.272 | 52% |
| up | 842 | +0.072 | +0.203 | 22% |

Not a downhill-only defect - flat is just as bad. Upgrades are fine because gravity does the decelerating. Exposure is ~165 s of 45 engaged min, so it is real but second-order next to the toggling. It is also *sustained*, not a transient: for the full 3 s before a brake onset the plan asks -0.08..-0.20 and aEgo sits at ~0.0, then the correction arrives over ~0.5 s. That step is the lurch.

Cost of the fix, open-loop and therefore indicative: moving entry from -0.20 to -0.10 takes overall brake duty 15% -> 36%. Prefer a separate named constant over reusing `min_gas`; a grade gate is **not** justified by the table above.

### The EXIT side of the same conflation: withheld gas is engine braking, not coasting (measured 2026-08-06)

Driver-reported, routes `0000000d` and `00000006` (2026-08-06): *"going downhill we keep slowing coming out of the hill while the car in front pulls away - there's no reason for us to continue to slow down."* The report is correct and the cause is ours. This is the **release** side of the `min_gas_accel` conflation documented above, and it is a **separate defect from the toggling** the `DOMAIN_HYST_EXIT` work was aimed at.

Measured over descent hold-episodes (`longActive & request > 0.02 & BRAKE_REQUEST & pitch < -0.7 deg`), pooled at `opendbc d1d5eb5c7255`:

| route | held | request mean | aEgo mean | shortfall | COMPUTER_BRAKING | brake_pid addon | engine torque |
|---|---|---|---|---|---|---|---|
| `0000000d` | 39.7 s | +0.192 | -0.065 | **-0.257** | 5% | -0.006 | **-103** |
| `00000003` | 34.6 s | +0.134 | -0.009 | **-0.143** | 19% | -0.009 | **-164** |

**It is not the friction brakes and it is not `brake_pid`.** `COMPUTER_BRAKING` is asserted on only 5-19% of those frames and the brake PID addon averages -0.006 m/s^2. **It is not a downshift either** - `TRANS_TARGET_GEAR` is unchanged across descent brake-domain entries (10.00 -> 10.00 on `0000000d`, 6.00 -> 6.00 on `00000003`, RPM +/-40). It is the closed throttle. On the *same descents* with the same positive request, the gas domain runs engine torque **+311** and achieves aEgo +0.502 against +0.552 asked; the brake domain runs **-103** and achieves -0.065 against +0.192 asked. Withholding `GAS_COMMAND` swings engine torque ~414 units. A 4500 lb van is not decelerating by coasting here - it is being engine-braked by a throttle we shut.

**Why the release band is the wrong shape.** During those holds the required powertrain force `gas_pedal_force = accel + wind*windfactor + hill_brake` sits at **~0** (mean -0.001 on `0000000d`, -0.111 on `00000003`; 47%/16% of frames outright positive), while release requires `> +0.30`. So the exit band spans exactly the region where the physics wants roughly neutral torque, and in that region the action taken is "shut the throttle". Because the decision input carries `hill_brake`, both thresholds slide with grade *in request terms* (wind term +0.024 at 65 mph with the rail-pinned windfactor):

| grade | hill_brake | enter brake if req < | exit brake if req > |
|---|---|---|---|
| +2.0 deg | +0.34 | -0.57 | -0.07 |
| 0.0 deg | +0.00 | -0.22 | +0.28 |
| -1.5 deg | -0.26 | **+0.03** | **+0.53** |
| -3.0 deg | -0.51 | +0.29 | +0.79 |

On a -1.5 deg descent we **enter** the brake domain while the planner still wants +0.03 and do not release until it asks +0.53. That is the whole of *"this behavior isn't seen on flat ground"*, and it is why the flat/uphill control route `00000006` (set 65, 100% lead-following, 7.4 engaged min) recorded **0.00 s of brake domain** - at its +1.31 deg mean pitch `hill_brake` = +0.22 lifted even a -0.71 request clear of entry.

**RETRACTED CANDIDATE (proposed and killed the same day, 2026-08-06).** The first idea was "keep `BRAKE_REQUEST` latched but command the neutral gas value (~81 of 2000 counts) instead of the inactive constant, so the release threshold never has to move." **It is not implementable.** `hondacan.create_acc_commands` defines `gas_dom = (not brake_domain)` and `gas_command = gas if active and gas_dom else -30000` - gas and brake are **mutually exclusive by construction**, and `BRAKE_REQUEST` is the *same bit* as `BRAKE_LIGHTS`. Commanding both would put throttle against brake with **no panda check** (`honda_tx_hook` bounds magnitude only, see "Upstream test coverage") and would flash the brake lights at following traffic while accelerating. Do not resurrect it. Recorded because the reasoning is the useful part: the defect is real, but the domain flag is not a knob with an independent gas side.

**What that leaves, and why nothing was written at the time.** Keeping the mutual exclusion means the only lever is *when* we switch - i.e. exactly the `DOMAIN_HYST_EXIT` territory with the fidelity/chatter trade and three on-road failures. Corrected evidence showed **15.1 toggles/min at 0.20**, versus 3.6-4.8 at 0.50 and 6.7-10.0 on the typical no-hysteresis routes; the old 27.4/25.0 comparison was a broken-counter artifact. Moving entry up from -0.20 to -0.10 takes brake duty **15% -> 36%**, which makes the release defect more frequent. Moving entry down helps that defect but can worsen brake onset by the same mechanism. **There is no free setting**; the 2026-08-11 -0.30/0.20 retest is explicitly an attempt to see whether changed band position alters the prior width trade, not a claim that 0.20 is good.

**WHAT SHIPPED AS THE ROAD CANDIDATE (2026-08-06): `BRAKE_DOMAIN_ENTRY` -0.20 -> -0.30.** The
insight that unblocked this is that **band position and band width are different axes.** Every prior
sweep - `DOMAIN_HYST`, `BRAKE_RELEASE_HOLD`, `DOMAIN_HYST_EXIT` 0.20 - moved the *width*, which is
what trades ~1:1 against chatter and failed three times. Nobody had moved the band's *position*.
Method: re-run the domain state machine over the cached signals and **validate it against the logged
`BRAKE_REQUEST` first** - 99.8% (`0000000d`) / 98.9% (`00000003`) agreement at the shipped -0.20, so
the counterfactual is credible. Then sweep:

| entry | descent hold vs +req | brake duty | descent toggles/min | x2.7 scaled |
|---|---|---|---|---|
| **-0.20** (was) | 74.3 s | 7.2% | 6.1 | 16.5 |
| -0.25 | 45.6 s (-39%) | 5.6% | 6.5 | 17.5 |
| **-0.30** (now) | 29.8 s (-60%) | 4.5% | 6.5 | 17.5 |
| -0.35 | 17.1 s (-77%) | 3.5% | 5.8 | 15.6 |
| -0.40 | 10.3 s (-86%) | 3.0% | 4.3 | 11.7 |

Toggling is **flat to better** across the whole sweep, because shifting the band down means entering
the brake domain less often - fewer entries, fewer edges. That is why this is not the 1:1 trade.
-0.30 was chosen over -0.35/-0.40 as the smallest step that removes most of the defect.
**The cost is real and is what to watch on road:** 132.5 s, 2.74% of engaged time, moves brake->gas
domain. Mean request on those frames is ~0 (+0.030 / -0.048), so most of it is genuinely near-neutral
where the gas domain belongs - but **p10 is -0.37**, and per the table above gas has no braking
authority below ~-0.2. **Failure mode is late brake onset / longer stops, not chatter.** Revert to
-0.20 if the driver reports either. Per habit #1 this is open-loop and therefore NOT validated;
crossing rates underpredict ~2.7x and the sim freezes the feedback path.

**The one genuinely untested state.** `GAS_COMMAND` has never been sent as **0** on this car: measured over `0000000d`/`00000003`, GAS_COMMAND is the -30000 inactive constant 4%/21% of engaged frames and positive 96%/79%, and **exactly 0 on 0.0%**. The +43 vs -139 torque contrast above is *low gas in the gas domain* vs *inactive in the brake domain*, so it conflates the domain flag with the gas value and cannot answer whether `GAS_COMMAND = 0` alone avoids the overrun fuel-cut. Per `comma-standards`, this signal is opaque/unitless in the DBC and must not be extrapolated. Answering it needs a deliberate probe, not a log query - and no existing route can substitute, because the state has never been on the wire.

**Attribution note.** The 16:02/16:08 dips on `0000000d` that first looked like this defect are **upstream** - request was negative throughout and the wire tracked it to RMS 0.020, `plan_source = lead0`. On `00000006` the driver-reported event is upstream in full: **0.00 s brake domain, 0.00 s withheld gas**, wire-request RMS 0.0055, and the felt "holding the brake" is a **6.3 s lag** between the lead re-accelerating (t=374.0) and the MPC's request turning positive (t=380.3) while the gap opened 23 m -> 36 m. Do not attribute lead-following lag to the domain logic; check `brake_request` first.

## Standing pitch bias (measured 2026-08-08, settles the old "+0.03 rad" open item)

`carControl.orientationNED[1]` carries a constant positive offset. Median driving pitch
(`vEgo > 5`) across every route with usable data: +0.019 to +0.033 rad over 7 routes spanning
2026-07-29 -> 2026-08-08 (`00000031` +0.0255, `00000037` +0.0329, `00000003` +0.0236, `00000004`
+0.0240, `00000006` +0.0232, `0000000d` +0.0219, `0000000e` +0.0193). It is **speed-invariant**
(`0000000d` steady-state medians +0.021/+0.019/+0.022 at 5-10 / 15-22 / >25 m/s) and
**accel-invariant** (+0.023 at aEgo > +0.5 vs +0.021 at aEgo < -0.5, where body squat/dive would
split these far wider) - so it is a mount/calibration offset, not aero or load transfer. The lone
pre-tune log (`00000018`, 2026-06-05) has no usable speed data, so "always" is bounded at 2026-07-29.
Magnitude: sin(0.02)*g ~= **+0.21 m/s² of phantom hill_brake** (the old note's ~+0.34 was an
overestimate from the +0.03 guess).

**Do not "fix" it.** Every empirical number in this file - band entry/exit behavior, descent masks,
learner trims - was measured against the biased signal, and the domain decision and the validator
read the same signal, so arms compare like-for-like. Zeroing the offset would shift effective band
position by ~0.2 m/s² and invalidate the road evidence. Consequences to remember instead:
`DOWNHILL_PITCH = -0.012` measured is ~-0.032 true (~-1.8% grade), i.e. our "descent" metrics
under-count shallow true descents, identically in both arms; and true grade ~= pitch - 0.02.

## ALT_RADAR steering enablement (measured 2026-08-08 - no change warranted, do not re-investigate)

Upstream carries two TODOs our platform can speak to: `carstate.py:121` "better handle delayed
steering enablement on ALT_RADAR cars" and `carstate.py:102` "See if this logic works for all
other Honda". Scanned raw `STEER_STATUS` (bus 1) + `carState` + alerts over 4 routes / ~92 engaged
minutes (`0000000c`/`00000006`/`00000003`/`0000000d`):

- **`low_speed_lockout`: 15 episodes, all at standstill** (entry vEgo <= 0.16 m/s, release by
  0.26 m/s, up to 54 s parked). The `expected_low_speed_lockout` suppression caught every one -
  `steerFaultTemporary` frame counts equal the `no_torque_alert_1` counts exactly on all 4 routes,
  so lockout contributed zero fault frames.
- **`no_torque_alert_1`: 230 episodes, and it is NOT a crawl-band phenomenon** - entry vEgo p50
  3.6-8.0 m/s (max 26.5), duration p50 0.03-0.04 s (max 0.99). Every single episode began while
  `latActive` was false, during manual/override steering (routes log 361-1290 steerOverride
  events). Zero fault frames overlapped `latActive`; zero `steerTempUnavailable`(`Silent`) alerts
  fired anywhere. (A first-25-transitions eyeball of `0000000c` had suggested a 0-1.2 m/s crawl
  band; the full scan corrects that - biased sample.)
- **Consequence chain if it ever did overlap**: `controlsd` drops `latActive` on any
  `steerFaultTemporary` frame, and at 0.5+ m/s a persisting fault escalates to SOFT_DISABLE. On
  this platform with openpilot long it simply never overlaps.

**Verdict: the existing ALT_RADAR logic works as intended here - n=1 upstream confirmation for
`carstate.py:102`, and no observed delayed-enablement gap for `carstate.py:121` (lockout releases
at first motion; openpilot never wanted torque the EPS refused).** No code change is warranted;
changing fault reporting with zero logged symptom is exactly what the tuning rules prohibit.
Scanner: session scratchpad `steer_enable_scan.py` pattern - raw bus 1 `STEER_STATUS` against
`carState`/`carControl`/`onroadEvents`.

### The 43.5 mph boundary is openpilot's config, not the EPS (stock-ACC routes, 2026-08-08)

The gap above ("stock-ACC config NOT covered") is now closed. Driver-reported: *"it doesn't seem
like a direct cut-off at 43 mph - sometimes it wouldn't kick on until 45+, sometimes steering
doesn't drop off until under 43."* Measured on `00000012--36525474db` and `00000013--dd070c2142`
(stock ACC + openpilot lateral, `minSteerSpeed` = 70 km/h = 43.50 mph), and both routes agree
exactly:

| quantity | route 12 | route 13 |
|---|---|---|
| EPS `low_speed_lockout` episodes | 2, both at **0.0 mph** | 2, both at **0.0 mph** |
| EPS `no_torque_alert_1` | 32 eps, 19-31 mph, all cruise-off | 85 eps, 16-26 mph, all cruise-off |
| `latActive` engage / disengage | **43.5 / 43.5** | **43.5 / 43.5** |
| `lowSpeedAlert` SET | **44.6** | **44.6** |
| `lowSpeedAlert` CLEAR | **45.7** | **45.7** |

**There is no EPS speed lockout to find.** `low_speed_lockout` fires only at standstill; the EPS
reports `normal` continuously through the whole 43-46 mph band. The boundary is entirely
`ret.minSteerSpeed = 70. * CV.KPH_TO_MS` (`interface.py`, stock-ACC path) acting through
`controlsd`'s `standstill = vEgo <= minSteerSpeed` gate - exact, no hysteresis, both directions.
`no_torque_alert_1` is a driver-steering artifact at half that speed and is unrelated.

**The felt inconsistency is the ALERT disagreeing with the CONTROL, in opposite directions.**
`latActive` uses bare `minSteerSpeed` while `low_speed_alert` uses `+0.5` set / `+1.0` clear
(`carstate.py`, the block carrying the `carstate.py:121` TODO):
- accelerating: steering resumes at **43.5** but the alert holds to **45.7** -> 2.2 mph where it
  steers while the UI says unavailable. This is the "wouldn't kick on until 45+" report.
- decelerating: alert re-arms at **44.6** but steering runs to **43.5** -> 1.1 mph where the UI
  warns while it still steers. This is the "doesn't drop off until under 43" report.

**Not answerable from these logs:** whether 70 km/h is the *right* value. openpilot never commands
torque below it (`vEgo` min while `latActive` = 43.5 on both routes), so nothing here tests the
`interface.py` claim that the radar filters steering commands below that speed. Note 43.5 mph is
approximately where Honda's own stock LKAS begins, so the value looks deliberate. Lowering it is a
road experiment, not a code cleanup, and lateral is otherwise closed.

## Ruled out on route 00000033 - do not re-investigate (2026-07-29)
Three plausible causes of the harsh brake onset, all measured dead. Two were my own hypotheses.
- **Gas cut at domain entry.** `GAS_COMMAND` in the frame *before* `BRAKE_REQUEST` goes 1 is **3 of 2000**, 41/41 onsets. There is no gas/brake double step. An earlier pass reported 38-62 counts; that was an artifact of taking `max` over the preceding 0.6 s instead of the frame before. **When measuring the size of a step, sample the frame adjacent to it.**
- **`brake_pid` windup during an ordinary active brake onset.** Peaks at **-0.074 m/s^2** after entry and unwinds to -0.016 by +2.0 s. It is not accumulating against the actuator's 0.35 s dead time. This result is scoped to active control; route `00000034` later found the distinct inactive-state accumulation bug above.
- **Honda ECU overshoot.** Wire reaches -0.38, aEgo reaches -0.49 - **1.3x**, i.e. the Bosch tracks a light brake application acceptably. Comparing *changes from t=0* instead of absolutes yields a bogus "5-7x" because aEgo starts offset (accelerating, on a descent) while `aTarget` is already negative. **Attribute with absolute values; deltas from an arbitrary origin inherit that origin's error.**

**`experimentalMode` is the largest available lever on hills and costs no code.** Within-drive A/B, routes `00000030`/`00000033`: overspeed brake onsets **1.1-2.1/min with it on vs 5.4-5.8/min off**; on `00000033` brake duty 5.0% vs 20.1% and felt-jerk RMS 0.381 vs 0.466. The e2e planner treats the set speed as a cap, the MPC tracks it as a setpoint and brakes at every overshoot. That is upstream of `aTarget`, so per the model-following rule above it is **not ours to fix** - but it is ours to recommend the driver use.

## What openpilot does NOT do at a stop light (verified 2026-07-30, do not re-investigate)
**There is no traffic-light or stop-sign detection anywhere in openpilot.** Grepped: the only `stopSign` in the tree is `cereal/deprecated.capnp:429`. This is ACC - it decelerates for a *lead vehicle* and for nothing else. A red light with clear road ahead produces no braking at all, at set speed, forever. When the driver reports "it rarely stops at stop lights," that is the product boundary, not a tune defect and not a model defect. Do not go looking for it in the car port.

## Lead following distance is the planner's, measured not assumed (2026-07-30)
Driver reported "we get real close to the car in front." Measured on route `0000003b`, 10322 engaged samples with a lead present above 2 m/s: **time headway p1 1.53 s, p5 1.68 s, p25 1.93 s, median 2.17 s, and ZERO frames under 1.2 s.** Closest absolute approach 5.5 m, but at 2.0 m/s = 2.7 s headway. The gap does not actually get short.
- **What the driver is feeling is the approach shape, not the distance.** Both clean engaged approaches to a standstill had the planner asking up to **-2.16 m/s^2** - it coasts, then brakes firmly and late. That reads as "we got close" while headway never drops below 1.5 s.
- **It is not us.** Over those approaches RMS(wire - request) was 0.068/0.095 m/s^2 and mean(aEgo - request) was +0.020/-0.045 - the wire carried the request and the car achieved it. Headway is `T_FOLLOW` in the planner, entirely upstream of `carControl.actuators.accel`. A bigger gap is a follow-distance/planner change, never a car-port change.

## Stop lurch is Honda's actuator, not our command and not the plan (attributed 2026-07-30)
`stop lurch (felt)` had blamed longcontrol's stopping ramp by assertion. Measured at the worst frame of both routes that reached a standstill:

| route | aEgo | request | wire | wire-request | aEgo-request | state |
|---|---|---|---|---|---|---|
| `0000003b` | -1.68 | -1.497 | -1.500 | **-0.003** | -0.179 | pid |
| `0000003a` | -1.49 | -1.083 | -1.080 | **+0.003** | -0.410 | pid |

RMS(wire - request) over +/-0.6 s around each was 0.011 and 0.018 m/s^2. **We put what we were asked on the wire to within 3 mm/s^2, and the car then decelerated 0.18-0.41 m/s^2 HARDER than commanded.** The lurch is Honda's brake actuator overshooting a modest command in the final crawl - downstream of `ACCEL_COMMAND`, the same actuator-bite behaviour already documented under `brake_pid overshoot`. Neither `longcontrol`'s stopping ramp (it was in `pid` both times) nor the planner (the request is smooth) nor the car port explains it. **Do not tune against this metric.** If it is ever worth chasing, the lever is the brake command shape into a lagging actuator, not the magnitude.

## Trusting the instrument (added 2026-07-30)
**Every expensive mistake on this project so far has been the measurement being wrong, not the tune.** The tune gets road-tested; the thing that grades it does not. Fourteen instances, all of which produced a confident, plausible, passing answer:
- `passthrough_rms` excluded brake-domain frames, hiding the only place we leave the model - "it hid a real defect indefinitely; no number of drives would have surfaced it."
- The replay harness freezes `aTarget`, so it structurally cannot see a feedback effect. Cost three failed fixes before it was named.
- `_decode_acc_control` read `STANDSTILL` while calling it `BRAKE_REQUEST`. The assertion could not fail, so it never did.
- `low_speed_conflict` gated at `FOLLOW_MIN_VEGO` (3.0) while the defect lived below 5.0, blinding it to the 3-5 m/s band.
- The 0.50 comparison pooled against two regressed configs because the ledger's `git_commit` is the parent, not the submodule.
- **`downhill_toggles_per_min` computed `np.diff(BR[down])` - compacting to descent frames BEFORE differencing.** That splices non-adjacent descents together, so the brake state ending window N diffs against the start of window N+1 and invents a toggle that never physically happened. Measured 2026-07-30: route `3b` scored 12 across 11 windows where 6 were real; route `37` scored 7 where 3 were real. **This was the headline metric of the entire `DOMAIN_HYST_EXIT` investigation**, and its error scales with how broken-up the terrain is - so it penalised exactly the routes that carried the most descent evidence. Fixed by counting edges on the full timeline and masking (`edges & down[1:] & down[:-1]`); `downhill_toggles` and `downhill_windows` are now recorded so the inflation is visible. Every affected row was re-validated.
- **`stop lurch (felt)` asserted its own cause.** The status string blamed longcontrol's stopping ramp unconditionally, but that ramp only runs in `longControlState == "stopping"` and below `CREEP_VEGO` the controller is frequently still in `pid`. Measured: the worst lurch on BOTH routes `3a` and `3b` was in `pid`. The code had already extracted `cc_stopping` and never used it. Now recorded as `stop_lurch_in_stopping` and the status says which state it was in.
- **`low_speed_conflict_worst` compared a 100 Hz request with a 50 Hz held CAN command.** Depending on phase, a request can wait up to one complete 20 ms `ACC_CONTROL` period before the next command is emitted. Three measured standstill starts released in 12-21 ms; the old defect persisted for 1.2-1.3 s. The validator now uses zero-order hold for discrete CAN commands and tolerates one command period via `LOW_SPEED_SKEW_S`.
- **“Uncommanded brake toggles” asserted the wrong domain model.** Raw requested acceleration does not solely choose gas versus brake: above 5 m/s the Odyssey deliberately adds drag and pitch before the decision. A BRAKE_REQUEST edge without a raw request sign change can therefore be exactly what grade compensation requires. The durable symptom is rapid physical cycling, so the validator now reports the largest number of adjacent-sample BRAKE_REQUEST edges in any 10-second window. It also requires both samples to remain inside the active mask, avoiding the same window-splice error as the old downhill counter.
- **`sign disagreement` graded a signal that is near-zero by construction (found 2026-08-05).** Its magnitude field was `min(wire - requested)` - the ACCEL_COMMAND error - but in exactly the frames it selects, the wire carries the request faithfully (measured -0.06 and -0.11 m/s^2 on routes `00000002`/`00000003`). GAS_COMMAND is at its inactive constant throughout, so a positive ACCEL_COMMAND cannot produce acceleration; the real severity was **1.82 and 7.62 m/s of withheld speed**. `SIGN_DISAGREE_MAG_FLAG` at 0.50 therefore could not fire on a domain hold at any severity - it guards the route-34 stale-state leak, a different failure. Now reports both, and the withheld-request integral is the number to compare tunes on. **A near-zero error is not evidence of fidelity when the other half of the command makes the request undeliverable.**
- **`track RMS` still referenced the planner after the 2026-07-29 boundary correction.** It compared `aEgo` to `longitudinalPlan.aTarget` while `passthrough_rms` and the following checks had been moved to `carControl.actuators.accel`. Re-anchored 2026-08-05; the number barely moved (0.208 -> 0.205) because `plan_override_rms` - now recorded per drive rather than asserted once - measures 0.007-0.009 on `pid` frames. **The 0.325 "divergence" first reported that day was an artifact of computing it over all engaged frames instead of `pid`, i.e. of including the stopping/starting overrides longcontrol makes by design. Check the mask before believing a metric moved.**
- **`stop lurch (felt)` graded the total, not our share.** It fired on 17 of 24 drives against a symptom this file attributes to Honda's actuator and says not to tune against - noise that also fed `suggest_status`. The car-port contribution was already separated (`stop_lurch_wire_extra`): measured max **0.057** m/s^2 over 9 drives with a stop while the actuator reached **2.744**. Now flags on our share at 0.15 and reports the rest, which keeps a real `brake_pid` regression guard instead of a permanent red light.
- **A proposed new check turned out to be a duplicate, and testing that was the whole value.** A standalone "GAS withheld against a positive request" metric was written, then compared frame-by-frame against `sign disagreement`: **100% overlap**, because `brake_request` and gas-inactive are exact complements in `create_acc_commands` (0 disagreeing frames across both routes). It was deleted and the one genuinely missing part - the withheld-request magnitude - folded into the existing check. **Before adding a check, measure its overlap with the checks you already have.**
- **`creep at stop` has never fired in 79 drives, and that is the car, not a dead check.** Driving the predicate with a synthetic creep trips it, so it is a healthy symptom guard; the Bosch ECU handling creep internally is why it stays quiet. Verified rather than assumed on 2026-08-05, and the synthetic case is now a test so a future edit cannot silently disable it.

Four habits that would have caught all fourteen. Apply them when writing the check, not when the result surprises you:
1. **A check you have never seen fail is not evidence.** Mutation-verify at write time: break the thing it guards and watch it go red. `test_sweep_actually_reaches_both_rails` was this instinct applied to one assertion; it belongs on all of them. If a check cannot be made to fail, that is the finding.
2. **A constant that mirrors one in the controller must say so and name it.** Two numbers that must move together, written in two files with no link between them, will drift - `3.0` vs `5.0` did. Import it, or comment `MUST track <the other one>` (see `LOW_SPEED_DOMAIN_VEGO`).
3. **Resolve an identifier before using it as a key.** Re-validating with a bare log-id prefix (`00000017` rather than `00000017--4bde00dfda`) missed `_base_route`'s regex, so 22 drives were APPENDED as new ledger rows instead of updating the existing ones - silently double-counting them in every cross-drive aggregate, on the same afternoon this section was written. `validate_log` now resolves a local prefix to the full id before the ledger sees it and refuses an ambiguous prefix.
4. **Prefer making a bad state impossible to detecting it.** The deploy guards in `tasks.json` are the model: `git_dirty` had been *recorded* in the ledger for weeks, and that never once stopped a mismatched flash. Refusing to deploy a dirty tree, a mismatched submodule branch, or an unpinned pointer converts a field nobody reads into a state that cannot occur. When you find yourself adding a field to notice a problem, ask what would make the problem unrepresentable instead.

## Ledger Comparability Rules (added 2026-07-27)
- **`track_rms` changed reference on 2026-08-05 and the ledger is mixed.** Rows before that date hold `RMS(aEgo - aTarget)`; rows validated after hold `RMS(aEgo - carControl.actuators.accel)`, with the old value preserved as `track_rms_plan`. The two differ by `plan_override_rms`, measured 0.007-0.009 on `pid` frames, so pooling across the boundary is safe for this metric - but read `track_rms_plan` if you want a strictly like-for-like column. Most historical routes are no longer on the device, so a full backfill is not possible.
Cross-drive aggregates are only as good as the pooling. Two boundaries are known to invalidate a pool, and both are already recorded per row by `_provenance` - **that is what `git_branch`/`git_commit` are for; use them before pooling anything.**
- **The driving-model boundary (openpilot `93f5aa469a`, "Rebellious Hope model" #38475, 2026-07-27).** A new `driving_supercombo.onnx` rewrites what the planner asks for, and it landed **without an `op_version` bump** - every drive before and after reads `0.11.2`, so version cannot separate them and `git_commit` must. Split the ledger on it for anything keyed on `aTarget`: **brake_pid overshoot, pitch-transition lag, stop-approach quality, domain chatter, both jerk metrics, and track RMS**. Do NOT split for metrics that measure the car's response to a command rather than the plan - **gasfactor/windfactor learning (`gas_error = self.accel - CS.out.aEgo`), passthrough RMS, rail saturation, thermal, crashes** are model-independent and pool across the whole ledger. (The 0 m/s gasfactor seed change rests entirely on that second group, which is why it was safe to make immediately after the model landed.)
- **Route `00000005` is excluded from every pooled comparison**, per the brake-onset writeup above: it is the only drive running opendbc `618dc5995f`, before `cb7b2a1f1` unified the gas/brake domain decision. It has now skewed two separate analyses - the domain-chatter A/B (it alone carried a p=0.048 result that collapsed to p=0.61 without it) and the gasfactor aggregate (its 1.032 was the sole outlier above 0.86; excluding it moved the estimate 0.765 -> 0.738). Both times it was the single most influential row. **Assume any pooled result that hinges on one drive is this one until proven otherwise.**
- **General rule**: before acting on a cross-drive aggregate, check whether dropping the single most influential drive changes the conclusion. Both real findings in the 2026-07-27 session came down to that test, with opposite outcomes - the gasfactor signal survived it, the domain-hysteresis signal did not.
- **`git_commit` is the PARENT commit; the tune lives in the submodule. Pool on `opendbc_commit`, not on branch or parent commit.** Grouping by the parent is what made the 0.50 analysis wrong on 2026-07-30: routes `32`/`33` were treated as "baseline" when their pointers were `BRAKE_RELEASE_HOLD` and 0.20, two configurations already known worse than no hysteresis. `_provenance` now resolves `git ls-tree <git_commit> opendbc_repo` and stores `opendbc_commit` per row (35 of 39 historical rows backfilled; the 4 blanks predate provenance tracking). It is deliberately blank for a dirty tree - the pointer then describes what was committed, not necessarily what was flashed. `suggest_status` enforces the same boundary, so an old tune cannot vote to promote a warning against the current one.
  - Found while adding that column: the MD table had been emitting **16 cells against 15 headers** since `windf mean` was added without a header, so every column from `follow gas` rightward was labelled one to the left - the "follow gas" column was showing `windf_mean`. The `.jsonl` was always correct and all analysis to date read from it, so no conclusion moved. Header and row are now generated from the same 17-column list and a cell-count check is cheap: `awk -F'|' 'NF!=19'` over the table.

## Device Thermal (added 2026-07-26)
- **This car's device is a `tizi` (comma 3X)** — read from `initData.deviceType`, not assumed. It matters: `hardwared.py` branches its thermal numbers on device type, and the `mici` branch is different (bands 96/100, offroad danger 85). For tizi: **ok < 96 °C, overheated 88–107, critical > 94, `OFFROAD_DANGER_TEMP` = 75**. `validate_log` mirrors these as constants rather than importing them — `hardwared` calls `HARDWARE.get_device_type()` at import time and pulls the alert stack, so it isn't safe to import off-device. **If the device is ever replaced, re-check those constants.**
- **Measured baseline (routes `00000015`/`00000016`, mild weather)**: `maxTempC` median **74 °C**, peak **76–77 °C**, memory 67–69 °C. So driving sits ~17-18 °C below the 94 °C critical line — no onroad concern at all. Cold-start temp was 49 °C.
- **openpilot does NOT protect a parked device.** `should_shutdown()` has no temperature term (voltage / 30 Wh budget / time only). At thermal critical it just refuses to go onroad and runs the fan at 100 %. Any hardware thermal trip is separate and below openpilot.
- **Units trap — every °C on this page is SILICON, not ambient air.** `maxTempC` is the max of the CPU/GPU/memory/PMIC die temperatures; silicon idles well above ambient, so a **49 °C** cold start corresponds to only ~15-25 °C outside. Do not compare these numbers to weather-report temperatures or to rules of thumb stated in ambient (e.g. "pull the device above 35 °C ambient"). The chain is: ambient → cabin (far hotter in sun) → device soaks toward *cabin*, because a parked device is powered off and generates no heat of its own. Rough mapping: ~15-25 °C ambient ⇒ ~49 °C silicon (measured); ~30-35 °C ambient in sun ⇒ ~55-70 °C cabin and silicon, i.e. at the 75 °C line.
- **The soak is invisible in logs, so we proxy it.** `loggerd` is onroad-only (`process_config` `logging` = `started and run`), so a parked device logs *nothing* — there is no offroad tail to analyse even with constant power. `validate_log` therefore records **`temp_start`**, the first `deviceState` sample of a drive: the temperature the device came up at, before load or fan, i.e. how hot the car left it. Above 75 °C ⇒ it started with zero headroom, which is the actionable "sunshade / shade parking / pull it" signal.
- **Interaction with constant power (matters seasonally)**: with the OBD power cable the device stays *on* while parked, adding its own heat in a closed car, with no thermal shutdown to save it and the fan at 100 % draining the 30 Wh offroad budget faster. Constant power is a clear win in cool months (free home-Wi-Fi uploads + `updated`) and materially worse in summer heat. Treat it as a seasonal choice, not a permanent one.
- **Standing advisory (`report_thermal_advisory`)**: prints after the ledger and answers "should the device come out of the car while parked?". It only counts **cold-start** drives — ones beginning ≥2 h after the previous drive ended — because a hot start otherwise just means the device never cooled down. Above 70 °C on a cold start it says to pull the device / sunshade until the weather passes; below, it says leaving it in is fine; with no cold-start drive yet it explicitly refuses to advise rather than guess.
- **Clock trap — do NOT use `initData.wallTimeNanos`.** The device boots with an unsynced RTC, so routes `00000015` and `00000016`, genuinely an hour apart, both report `2026-06-05 10:37:02` there, 0.7 s apart. The `clocks` stream publishes the same field and keeps going after NTP corrects it, so anchor on its **last** sample and back-compute from elapsed monotonic time (`_wall_start`). Getting this wrong silently destroys the cold-start logic above.
- **Worked example of why the confound matters**: route `00000016` came up at **73 °C**, which looks like a hot soak. It isn't — real times are route 15 ≈ 08:44-09:43 and route 16 starting ≈ 09:45, so it is leftover heat from a drive that ended two minutes earlier. Route `00000015`'s **49 °C** cold start is the true mild-weather baseline for this car.
- The thermal section **survives a qlog route** — `deviceState` is 2 Hz with qlog decimation 1, so unlike the control metrics it is never decimated away.

## Cross-Brand Longitudinal Patterns (surveyed 2026-07-22, re-verified 2026-07-22)
All carcontroller.py files across opendbc were reviewed, then re-verified against live code. The following patterns from other brands are relevant to our Honda Bosch A tune. These are **watchlist items** — when analyzing logs, check for these symptoms before implementing. **The tune is converged: none of these is a change to make now — each maps to a specific logged symptom, and you only implement it if that symptom shows up in a drive.**

- **Toyota's predictive-error / jerk-based integral winddown** (`toyota/carcontroller.py` L214-238): Toyota computes `j_ego` (jerk) from filtered `aEgo`, projects `a_ego_future = aEgo + j_ego * future_t`, and feeds `error_future = cmd - a_ego_future` into the PID instead of raw error. This reduces overshoot when aEgo is trending toward target. **Watch for**: if logs show our `brake_pid` overshooting (contributing more braking than needed as `aEgo` catches up to `aTarget`), Toyota's future-error pattern is the fix. Current routes show no overshoot — this is "watch for" only.
- **Toyota's high-pass pitch compensation** (`toyota/carcontroller.py` L229-233): a `HighPassFilter` on pitch that transiently amplifies the accel command on sudden grade changes, compensating for the PCM's slow pitch response. Capped at ±1.5 m/s². **Watch for**: sluggish response on sudden grade transitions (flat→steep hill). If seen, apply high-pass pitch on the **brake side only** (`self.accel` / `ACCEL_COMMAND`). The gas side (`GAS_COMMAND`) is blocked because it's opaque/unitless (PR #2767 confirmed).
- **Ford's creep compensation** (`ford/carcontroller.py` L28-32): subtracts engine creep torque at 0-3 m/s, and crucially *accel-gates* it — `creep_accel = interp(v_ego, [1,3], [0.6,0])` then `interp(accel, [0,0.2], [creep,0])`, so it only fires when the car is nearly coasting and tapers to zero as commanded accel rises. **Do NOT port this to Bosch as-is.** Honda Bosch's `ACCEL_COMMAND` is a real m/s² the ECU closes its own loop on — it already accounts for its own creep — so subtracting creep openpilot-side would **double-count**. (Ford applies it on their brake/ABS path, which does *not* self-compensate; Honda Nidec has its own creep comp; Bosch's ECU handles it internally.) **Watch for**: the Odyssey physically creeping forward when the planner wants to hold position in the 0-5 m/s gas-domain hold-at-stop window. Only if that symptom is *seen in logs* consider creep subtraction. Current low-speed switch (planner accel holds brake through a stop) likely already covers it.
- **Rate-limited / jerk-limited ACCEL_COMMAND** (Toyota does `rate_limit(pcm_accel_cmd, prev, ±0.12/frame)`; **Ford** does a brake-jerk limit `accel = max(accel, self.accel - 3.5*step*DT)` = 3.5 m/s³ on the ACCEL/brake side, `ford/carcontroller.py` L124-126): we rate-limit gas (60 units/frame) but not `self.accel`. The old symmetric 2.0 m/s³ experiment and the later onset-only candidate are both closed without road proof. The current three-domain candidate changes only gas/brake/coast selection and leaves `ACCEL_COMMAND` unshaped.
- **`longitudinalActuatorDelay = 0.5s` (Bosch, interface.py L86) is conventional, NOT a lever**: checked because it's a tempting knob. GM/Hyundai/VW all use 0.5; Toyota's 0.05 (`toyota/interface.py` L121) is **hybrid-only** ("Hybrids have much quicker longitudinal actuator response") — a physical-response fact, not a byproduct of their future-error winddown. 0.5 is correct for a Bosch ECU that closes its own accel loop. Do not lower it hoping for snappier braking; that just makes the planner less anticipatory (later braking). Noted here so a future session doesn't re-derive it as a "tweak."
- **Patterns we correctly avoid**: full closed-loop PID on ACCEL_COMMAND (Toyota pattern - their PCM is dumb, Honda's isn't, stacking causes #2347 oscillation); GM's direct lookup with no learning (they have direct brake/regen actuators, we don't); Hyundai's explicit jerk signal (Honda has no writable jerk field in ACC_CONTROL).

## Bosch A Generalization Strategy (decided 2026-07-22)
- **Architecture is Bosch A universal; seed values are Odyssey-specific.** The learning loop, brake_pid, pitch comp, and gas/brake domain decision all operate on the shared `ACC_CONTROL` protocol (opaque `GAS_COMMAND` + real `ACCEL_COMMAND`) that every Honda Bosch A car uses identically. What differs per car is the gasfactor speed shape (powertrain-dependent: engine size, transmission, torque converter), gas lookup range (weight-dependent: `[0, 2000]` for heavy vehicles like Odyssey/Pilot, `[0, 1600]` stock for lighter Civics), and wind drag curve (aerodynamics: frontal area × Cd).
- **Target structure**: shared Bosch A logic in `carcontroller.py` (gated on `HONDA_BOSCH` + `openpilotLongitudinalControl`), per-car seed tables in `values.py` (e.g., `BOSCH_LONG_PARAMS[CAR.HONDA_ODYSSEY_5G_MMR]`). The learner adapts from the seed — wrong seeds just mean longer cold-start warmup, not unsafe behavior (gas ramps are hardware-limited by panda safety).
- **Current gate**: code is gated on `CAR.HONDA_ODYSSEY_5G_MMR` because we can only road-test the Odyssey. Do NOT widen the gate to all Bosch A without per-car seed tables and a volunteer to road-test. If submitting upstream, refactor to the shared + per-car-seed design with Odyssey as the only populated seed; comma or other contributors fill in theirs.
- **Comma is moving this direction**: PR #38394 (removing per-car stopping tunes) confirms comma is actively removing per-car longitudinal differentiation. Our "shared logic + learning handles car-specific differences" approach aligns with upstream trajectory.

## Bosch MMR radar-track feasibility (measured 2026-08-24)

`inventory_radar_can.py` scanned all 138 full-rate segments from stock-radar routes
`0000002b--4882f84449` / `0000003b--08f77bc5c3` and OpenPilot-longitudinal routes
`00000037--0c6fc80a62` / `00000038--5b6729c780`. It inventories received CAN by physical source
bus and excludes Panda returned/rejected copies (`src >= 0x80`). The comparison found **zero CAN
messages present in both stock-radar routes and absent from either OpenPilot-longitudinal route**.

The Honda harness topology settles the direction of the interesting traffic: bus 0 is the radar
side of ACC-CAN, bus 2 is the camera side, and bus 1 is F-CAN B/powertrain. The dense 80-address
bank at `0x280-0x297` and `0x2C8-0x2FF` runs at about 14.88 Hz on **bus 2**, with grouped sentinel
payloads and rolling integrity fields. It is structured camera-originated traffic toward the radar,
not radar measurements. It may be a camera object/fusion input, but that semantic hypothesis is not
needed for the boundary and must not be presented as decoded.

Only three messages run continuously from the radar side on bus 0 in every cohort:

- `0x400` (4 bytes) at about 50 Hz, with only 8-20 complete payload variants per route;
- `0x420` (8 bytes) at about 10 Hz, with four counter/checksum variants;
- `0x410` (6 bytes) at about 1 Hz, with four counter/checksum variants and the stable `THRA0`
  payload body.

That is status/heartbeat-shaped traffic, not a multi-object feed. The stock-only high-rate changes
are instead known controller outputs on bus 1: steering `0xE4`, `ACC_CONTROL` `0x1DF`, supplemental
ACC `0x1EF`, and HUD/control messages `0x30C`/`0x33D`/`0x39F`. Their near-disappearance after the
radar communication-control request confirms that the logs expose the radar's **commands**, not
its selected lead or tracks.

**Verdict:** a normal `RadarInterface` implementation cannot recover Bosch MMR tracks from the CAN
available at this harness. Stock `ACC_CONTROL` remains valuable as an offline smoothness benchmark,
but it cannot provide a live radar lead after the radar is disabled for OpenPilot longitudinal.
Keeping the radar active while independently intercepting its powertrain commands would be a
hardware/safety architecture experiment, not a minimal opendbc parser change, and is out of scope
until an intercept path is proved. No vehicle or tuning change is justified by this feasibility
scan.
