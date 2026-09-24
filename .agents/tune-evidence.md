# Odyssey command-following — evidence archive

**This is a reference document, not an instruction file.** Active rules live in the repo-root
[`AGENTS.md`](../AGENTS.md); Honda port invariants live in
[`car-port-standards.md`](car-port-standards.md). This file preserves dated measurements and
provenance for re-audit.

Imperative wording and labels such as "current," "required," "closed," "failed," or "retired"
record the decision made at that time. They do not direct future work, impose a route count, or
prohibit a new evidence-owned hypothesis. When this archive conflicts with current code, logs, or
the root rules, re-evaluate the underlying exposure rather than inheriting the conclusion.

(Historical note: this file predates the root `AGENTS.md` and once carried an agent persona header.
That was removed 2026-08-06 to stop it reading as directives to any tool doing nested agent-file
discovery.)

## Odyssey radar/Alpha Long live handoff candidate (2026-09-21)

The isolated `ody-op-swap` arm pairs the current `ody-op` parent baseline with nested `opendbc`
`df01ae3a79251bd3e80b156c1bd3f828fb41c708`. It adapts the mechanism investigated from
`mvl-boston/alphatoggle`, but does not copy that branch's broad Honda or unrelated source delta.
The source audit found that MVL's controller-originated extended-session and CommunicationControl
packets would be rejected by this branch's Honda Panda safety hook, which previously allowed only
tester-present at `0x18DAB0F1`. The candidate adds an Odyssey-long-only exact-payload exception for
the extended session plus enable/disable communication requests; nearby payload mutations remain
rejected.

The Alpha-on handoff defers radar disable to `CarController`, observes physical powertrain-bus
`ACC_CONTROL`, and suppresses every OpenPilot longitudinal and longitudinal-HUD transmission until
four consecutive 50 Hz radar frames are absent. Toggle-off stops OpenPilot longitudinal output
immediately and sends the matching session/enable pair. The outgoing Alpha-configured process does
not emit stock-mode supplemental or button traffic; the existing onroad process cycle reloads stock
`CarParams`, bus routing, and Panda safety. This avoids an ignition cycle, but it is not a seamless
single-process mode change in both directions.

Software gates passed before publication: both critical checks were mutation-verified; the focused
Odyssey suite passed 21 tests and 58 subtests; the Bosch-long safety selection passed 32 tests, four
skips, and seven subtests; `opendbc_repo/test.sh` passed 3,980 tests with 702 skips plus ruff, ty,
codespell, cpplint, and MISRA; `.agents/preflash.py` passed the seven Odyssey model/interface tests
and all focused command checks. These establish exact command ordering and Panda acceptance, not ECU
response, restored CMBS, clean on-device cycling, or road safety. First offroad validation must log
the stock `ACC_CONTROL` disappearance/reappearance, UDS requests, Panda safety state, faults, and
service health before any engagement or road test.

The first stationary ignition-on screen rejected that exact re-enable sequence. Routes
`0000000b--fde50f6ad2`, `0000000c--79b5cf8740`, `0000000d--cd249f0861`, and
`0000000e--c42733be6b` all resolve to parent `8635c394a8bb` and nested `df01ae3a7925`; the vehicle
stayed in Park at zero speed and OpenPilot was never engaged. Alpha operation itself established
clean ownership: the physical stock bus-1 `ACC_CONTROL` stream stopped, OpenPilot began 44.9 ms
later with no overlap, Panda used Honda Bosch parameter 35 without faults, and tester-present kept
the radar silent. The reverse transition exposed the failure. OpenPilot's final `ACC_CONTROL` was
sent at monotonic `2446.942 s`, CommunicationControl enable at `2447.014 s`, and the first restored
stock frame did not arrive until `2452.051 s`: a `5.109 s` command gap and `5.037 s` after enable.
At the next route start both `STANDSTILL.BRAKE_ERROR_1/2` bits had changed from zero to one; when the
radar resumed it published `ACC_HUD.ACC_PROBLEM=1` and `FCM_PROBLEM=1`, matching the driver's orange
warnings. The later OpenPilot Cruise Fault was those already-latched brake bits becoming visible
when Alpha was selected: it began at the end of the stock route before the next radar-disable UDS
request and before Panda entered Alpha safety. Ignition-off cleared the bits. The first divergence
is therefore the five-second radar return delay after enable, not CAN-author overlap, Panda rejection,
or the subsequent disable request.

The changed candidate adds one exact Odyssey-only UDS default-session request 50 ms after
enableRxAndTx. The five-second return delay matches waiting for the extended diagnostic session to
expire; explicitly returning to default session is intended to resume normal radar publication
before Honda latches the command-loss fault. The controller and Panda assertions for this payload
were each mutation-verified, then passed with 21 Odyssey tests/58 subtests, 32 Bosch-long tests/four
skips/nine subtests, ruff, diff checks, and preflash. This remains a hypothesis until another
stationary ignition-on cycle shows prompt stock `ACC_CONTROL` return, both VSA brake-error bits and
both radar problem bits remaining zero, no overlap, and no vehicle or OpenPilot warnings. Do not
engage or road-test this arm before that screen passes.

Routes `00000012--18d8134f31` and `00000013--e6f83e764c` resolve to the revised pair, parent
`4bd1548dd774` and nested `bef3e9148377`, but do not test radar return. Both initialized with
`AlphaLongitudinalEnabled=1` and `openpilotLongitudinalControl=true`, sent extended-session followed
by CommunicationControl disable, then maintained tester-present; neither sent CommunicationControl
enable or the new default-session request. Stock `ACC_CONTROL` disappeared after startup and the
OpenPilot stream remained the only longitudinal author. Both VSA brake-error bits, `ACC_PROBLEM`,
`FCM_PROBLEM`, and `carState.accFaulted` remained false. Route 12 was an ordinary drive reaching
`31.263 m/s`, not an authorized stationary return test. The report that radar never returned is
therefore expected Alpha-on behavior, not evidence for or against the revised return sequence. The
saved Alpha setting was restored to off with ignition off after this attribution.

On route 12, physical bus-1 radar `ACC_CONTROL` ended at route-relative `8.218 s`; the disable
request followed at `8.221 s`, and no physical radar command or HUD stream returned during the
remaining 23.5 minutes. An automatic policy cannot use live stock-radar lead or command state to
decide when to return after Alpha has disabled that ECU; such a policy needs a separate observable
trigger defined before implementation.

**RETIRE this arm.** The initial reverse handoff caused Honda VSA and radar faults, while the revised
default-session hypothesis never received the required stationary reverse-handoff test. The MVL
source contains a user-controlled runtime toggle, not an automatic radar-utilization policy, and no
safe observable trigger was defined for this experiment. Preserve these routes and timings as a
bounded failure record; restore the `ody-op` parent/nested baseline and delete both `ody-op-swap`
branch refs after device recovery is verified.

## Evidence reset and fresh-route re-audit (2026-09-18)

At the user's request, every historical keep/change/retire label in this archive is exposure-scoped
context, not a permanent tuning exclusion. A label means that the cited mechanism did not earn
retention in the cited comparison; it does not prove that every nearby mechanism is ineffective.
New exact-provenance full-rate logs may reopen any layer when they locate a repeatable first
divergence. Preserve raw logs, safety boundaries, and source provenance while rechecking old claims
against the new exposure.

The newly retained route `00000009--019ee79ffb` is exact `ody-op` parent `6eb188b60df1` with
nested `c16579385f56`, Alpha Long enabled, and the same small-model blob
`f030157ccd2bacbdc6d7b98358903cbacc0e0b34` as the current baseline. The other four new logs are
thin context on the same model/source pair. Route 09 supplied 12.3 engaged minutes; plan to
`carControl` RMS was `0.0026 m/s2`, gas-wire RMS was `0.0080`, and brake-wire RMS was `0.0172`.
It therefore does not identify a numeric Honda CAN translation failure. It did show 32 physical
brake-domain edges, a flagged downhill burst, achieved jerk RMS `0.372` versus commanded `0.242`,
and five brake takeovers. These are fresh response/domain symptoms to classify, not permission to
revive a prior arm automatically. The largest negative achieved-jerk peaks followed Honda
computer-braking activation, while the takeover samples ended control at the press boundary; no
production behavior change is selected from this route alone.

## Submodule & Branch Mechanics
- Honda production logic lives in the [`opendbc_repo`](../opendbc_repo) submodule. If publication is
  requested, publish the child commit before the parent gitlink; pushing never implies deployment.
- Rebase opendbc only onto the commit pinned by openpilot upstream. `.agents/sync_upstream.py` performs
  the compatible local pair rebase and never pushes; inspect source conflicts and the final Honda diff.
- Keep the recovery/shared-tooling parent and submodule paired on `ody-op`. Temporary mechanism
  children are deleted after promotion or rejection; `ody-op-test` and `ody-op-test2` are historical
  snapshots, not active deployment targets. The VS Code tasks cover all-retained private log pull,
  Jotpluggler, Cabana, the explicit Odyssey software checks, and guarded deployment/recovery for
  openpilot or Sunnypilot. There are no implicit sync, publish-only, or maneuver tasks; staging
  recovery is deliberately an explicit destructive action.

## Layered Verification Workflow
No one tool establishes that a tune is good. Use these layers in order, and keep an experimental production change isolated until both controlled and ordinary-road evidence agree.

1. **Static, unit, interface, and panda-safety gates**: the VS Code **Run Odyssey software checks** task (or the equivalent commands below) runs `lefthook run pre-commit`, the focused Odyssey rail/sync tests, and `opendbc_repo/test.sh`; use `UV_CACHE_DIR=/private/tmp/openpilot-uv-cache` when invoking `uv` in this workspace. These establish software correctness and legal CAN output; they do **not** grade ride quality.
2. **Official controlled maneuvers**: for a longitudinal change, record the official longitudinal suite in a safe empty area and run `uv run openpilot/tools/longitudinal_maneuvers/generate_report.py` on the route. No task enables maneuver mode or substitutes a route automatically: the driver must make the safe-site decision.
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
- **Upstream workflow**: "Inspect Upstream Delta" is read-only apart from fetching refs. "Sync Upstream Locally" rewrites local history but never pushes. Run **Odyssey software checks** and inspect the net Honda-only diff before the separate explicit publish or deploy task.

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
  0-.39%), but those unmatched diagnostics did not establish an improvement over 2560. The arm was
  later retired under the PR-minimal command-following objective; see the final lateral decision
  below. The device was returned to official `sunnypilot/staging`; the private `ody-sp` overlay is
  no longer a deployment target.
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
- **Final lateral range decision (2026-08-25): RETIRED TO STOCK 2560.** The earlier retained-route
  review temporarily kept the isolated 3840 arm because the available 2560 routes did not run its
  exact nested commit. That burden was backwards: a custom range must demonstrate an attributable
  improvement, not remain until a failure appears. The 2560 routes `4e`/`4f` supplied 50.6 active
  minutes with controller saturation of 0.74%/0.50% and actual-versus-desired lateral-acceleration
  RMS of `0.080/0.081 m/s2`; broader staging routes likewise had low saturation and no repeatable
  lateral symptom. Later 3840 routes accumulated about 99 active diagnostic minutes, sometimes used
  commands above 2560, and had low saturation, but no matched comparison showed better tracking,
  residual lag, lane keeping, interventions, or faults. Honda's 3840 RDM range also accompanies
  one-sided brake drag that OpenPilot does not command. Restore the stock LKA 2560 range, keep
  `latAccelFactor 0.9` and `steerActuatorDelay 0.15`, and reopen only for a repeatable symptom plus
  an isolated road comparison.

- **Stock-radar lateral authority question reopened (2026-08-28), baseline remains 2560.** All 13
  newly pulled `sunnypilot/staging` routes (`0000004b`, `4d`-`58`) used stock radar and had zero
  OpenPilot-longitudinal exposure; eight supplied 33.4 lateral-active minutes. After removing low
  speed, steering override/fault, tiny-demand, and fast-demand-change frames, the controller held
  2560 for 24.9 seconds. Twenty-seven sustained episodes remained, with median sign-corrected
  actual-versus-desired under-response of `+0.122 m/s2`; 18 of 27 episode medians under-responded.
  Retained unmatched 3840 routes had near-zero median error above 2560, so the old absence of a
  repeatable 2560-bound symptom is no longer true. That historical comparison remains observational:
  it primarily used OpenPilot longitudinal and a different steering path.

  Full-rate `sendcan` bus 0 to physical CAN bus 1 matching located an additional first divergence
  inside the stock radar. Nearest equal-counter matches had median `20-25 ms` latency and
  controller/radar torque correlation near `0.997` on transparent routes. Across all eight routes,
  21.7 seconds of clean sustained controller-side 2560 command remained. Six routes forwarded those
  sustained frames at 2560 essentially exactly. Routes `0000004d` and `00000051` instead contained
  clean sustained attenuation without steering override or reported fault: below-2400 forwarded
  frames had median output `695` and `1339` counts and median tracking under-response `+0.309` and
  `+0.109 m/s2`. The same two routes' exactly forwarded subsets slightly over-responded, so their
  first divergence is the radar filter, not the 2560 port cap. On the six transparent routes,
  exactly forwarded sustained-cap windows still had positive per-route median under-response on
  every route (`+0.010` to `+0.285 m/s2`), which is the evidence for a separate authority question.

  Keep 2560 as the road baseline. Do not restore the historical linear `[[0,3840],[0,3840]]` map:
  it changes gain throughout the range, Honda documents only a small nonlinear motor-torque increase
  above the 2560 LKA range, and the 3840 RDM behavior includes brake drag OpenPilot does not command.
  If tested, isolate the existing source-documented nonlinear candidate
  `torqueBP=[0,2560,3072]`, `torqueV=[0,2560,3840]`; run matched staging/radar curves, record actual
  bus-1 forwarded torque, model tracking, saturation, faults, and interventions, then keep or retire
  it. This is authorization for a controlled road arm, not promotion evidence.

  The validator now records that bus-1 forwarding diagnostic directly for full-rate Odyssey
  stock-radar routes: equal-counter bus-0 to bus-1 matches, transport delay, controller-to-radar
  error/correlation, clean cap exposure, and any source/output exposure above 2560. It also records
  whether `CarParams.openpilotLongitudinalControl` selected Alpha Long for Odyssey, without grading
  that mode. A smoke check
  reproduced transparent forwarding on route `0000004e--a1ef2eb048` (54,318 matches, 19.7 ms median
  delay, 0.9935 correlation, 2560/2560 clean max) and attenuation on route `00000051--a362f36904`
  (73,915 matches, 20.8 ms median delay, 0.9512 correlation, median cap gain 0.691). These are
  attribution diagnostics; neither route is evidence for the nonlinear arm.

  The isolated arm was implemented on `ody-op` at nested commit `17e1f614d8b3`. It changes only the
  Odyssey map to `torqueBP=[0,2560,3072]`, `torqueV=[0,2560,3840]`; `latAccelFactor=0.9`,
  `steerActuatorDelay=0.15`, and Alpha Long selection remain unchanged. Focused parameter assertions
  cover Alpha Long both off and on and were mutation-verified against the 2560 mapping. Preflash
  passed seven Odyssey model/interface/radar/safety checks plus 18 command/parameter tests and 43
  subtests. This is software/deployment eligibility only; the first road arm is stock radar with
  Alpha Long off.

  Route `0000005d--ed7df97035` is the first road exposure for that exact arm: parent
  `91bf0ddf3ac9`, nested `17e1f614d8b3`, stock radar, and Alpha Long off. It supplied 3.05
  lateral-active minutes. Controller-side CAN torque p95/max was `2698/3840`; clean source output
  exceeded 2560 for 8.08 s and the physical bus-1 output exceeded 2560 for 7.01 s. Counter-matched
  forwarding measured 26.4 ms median delay, 0.9705 correlation, and unity median gain during stable
  cap exposure. Request-to-controller-output RMS was `0.038`, actual-versus-desired lateral-
  acceleration RMS/mean was `0.070/-0.016 m/s2`, torque-controller saturation was 2.22%, and the
  route had three steering overrides and zero steering faults. The arm therefore reached the
  physical steering path without an obvious fault or radar clamp, but this short unmatched route
  does not establish better lane tracking than 2560. The initial decision held it only for a
  matched comparison; the later three-independent-example rule reopened the arm for a bounded screen.

  The retained same-day stock routes cannot supply that comparison. A conservative 10 Hz GPS
  screen compared 85 clean route-`5d` controller-output samples above 2560 against nine
  `sunnypilot/staging` stock-range routes. None had a stock-route point within 25 m in the same
  direction (15 degree bearing tolerance), before applying the additional speed, desired-lateral-
  acceleration, and stock-2560-command gates. Aggregate RMS differences between those routes are
  therefore unmatched observations, not arm evidence.

  **Nonlinear 3840 decision (2026-08-29): CONTINUE A BOUNDED THREE-EXAMPLE SCREEN.** Route `5d`
  had four independent sustained episodes above 2560. Their durations were `0.97`, `4.39`, `2.08`,
  and `0.59 s`; sign-corrected under-response medians were `+0.182`, `+0.207`, `-0.036`, and
  `-0.095 m/s2`, respectively. Two episodes under-delivered, one was near neutral, and one
  over-delivered, so this is not three examples of failure. A transparent but unmatched comparison
  conditioned to route `5d` speed `21.65..23.02 m/s` and desired-lateral-acceleration magnitude
  `0.218..1.919 m/s2` measured median under-response/RMS `+0.024/0.212 m/s2` over `5.78 s` on the
  nonlinear arm versus `+0.149/0.236 m/s2` over `2.16 s` across available stock samples. That points
  toward possible benefit but is too thin and unmatched to prove it. Count route `5d` as one
  inconclusive-to-promising road example, retain
  `torqueBP=[0,2560,3072]`, `torqueV=[0,2560,3840]`, and collect at most two more independently
  exposed routes. Compare actual versus desired lateral acceleration in comparable speed, demand,
  and authority bins; exact GPS matching strengthens the result but is not required. Retire after
  three road examples without attributable improvement, or sooner for a safety regression. The
  temporary stock restoration at nested `659b466e2511` is an audit point, not the active decision.

  Apply the same outcome standard to longitudinal tuning. In Alpha Long routes, compare achieved
  `aEgo` with `carControl.actuators.accel` separately during live gas and brake domains, conditioned
  on comparable speed, request, and terrain. Request-to-wire RMS and the Honda domain bits remain
  attribution checks: they establish whether divergence first appears before CAN or in Honda's
  achieved response. Do not average gas and brake into one route score, and do not treat a smooth
  wire as proof of a smooth vehicle response. Each longitudinal mechanism gets the same maximum of
  three independent, adequately exposed road examples before keep or retirement.

  **Alpha Long gas/brake split readout (2026-08-29).** The new diagnostics were re-run on two
  retained full-rate routes to establish the comparison shape. Custom `ody-op` route
  `00000044--1f70122a52` measured gas/brake wire RMS `0.0077/0.0108 m/s2` and achieved
  `aEgo-request` RMS `0.207/0.295 m/s2`; its median request magnitude/speed was `0.088/22.0` for
  gas and `0.560/15.8` for brake. Staging Alpha Long route `00000046--86d6f4b278` measured wire
  RMS `0.0055/0.0038 m/s2` and achieved RMS `0.144/0.134 m/s2`; its median request magnitude/speed
  was `0.068/30.9` for gas and `0.256/30.2` for brake. Both routes passed through the request-to-
  wire path without a meaningful wire mismatch, but their speed, demand, and terrain exposure are
  not matched. This is baseline instrumentation, not evidence that either tune is better. Future
  Alpha Long decisions must compare gas with gas and brake with brake in comparable exposure bins,
  then inspect first divergence before changing the Honda port.
  A direct speed/request-bin audit found no shared speed band with material gas or brake exposure:
  route `46` was concentrated at 25-35 m/s, while route `61` was concentrated at 15-25 m/s.
  Therefore route `46`'s lower achieved error cannot be treated as an A/B result against route `61`;
  the apparent gap remains exposure-confounded.

  **Second nonlinear 3840 exposure (2026-08-30).** Route `00000061--b8f07e1ca7` ran parent
  `19e658584ec9`, nested `17e1f614d8b3`, with Alpha Long enabled and supplied 5.9 engaged minutes
  at native rates. The nonlinear map reached 15.61 clean high-authority seconds; actual-versus-
  desired lateral RMS was `0.245 m/s2`, sign-corrected under-response median `+0.070 m/s2`, and
  74.4% of frames under-responded. The route had 3 steering-fault events, 14 steering overrides,
  and one brake takeover, so it is a mixed second example rather than a clean arm success or a
  mechanism-specific failure. Longitudinal command-to-wire RMS was `0.0071/0.0119 m/s2` for gas /
  brake; achieved `aEgo-request` RMS was `0.185/0.348 m/s2`, with material-command under-response
  medians `+0.089/-0.165 m/s2`. These are baseline rows with different exposure from route `44`,
  not an A/B result. The domain model is suppressed for nested `17e1f614d8b3`, but raw wire and
  achieved-response measurements remain attributable. Event-level inspection measured
  `carControl`-to-plan RMS `0.0076 m/s2`, brake-domain wire RMS `0.0119 m/s2`, and no sustained
  interval with `BRAKE_REQUEST` active while the controller requested acceleration. The takeover
  therefore does not identify a car-port command mismatch by itself; its stop/vehicle-response
  timestamps still require separate review. Count route `61` as example two; one more adequately
  exposed 3840 route is allowed before keep or retirement.

  The single brake takeover occurred at relative `272.39 s`. During the preceding `0.67 s`, speed
  was about `22.3 m/s`, the request ranged down to `-0.138 m/s2`, `GAS_COMMAND` remained live, and
  `BRAKE_REQUEST` remained off because active gas follows the upstream `-0.20` release split; the
  selected lead was roughly `105 m` away and `shouldStop` was false. The same live-gas/mild-negative
  condition is present in retained stock-radar routes `25` and `26` (`177.8`/`449.1 s`) and custom
  route `44` (`197.8 s`), so it is not unique to route `61` or the `-0.30` brake-entry arm. The
  takeover frame itself has already dropped `longActive`, so this event does not authorize changing
  the domain split; review future close-lead events separately from this high-speed intervention.

  Route `61` also contains the `+0.02 m/s2` road-speed gas re-entry behavior: its nested history
  includes the equivalent cherry-picked change `41aaf59ee6f2` (the relevant `carcontroller.py`
  blob matches `46468be93`). It recorded 7 coast re-entries, no sub-second re-entry pulses, and no
  tiny-request short pulses; median re-entry duration was 17.85 s and the largest entry request
  was `+0.042 m/s2`. This is one unpaired exposure, not evidence of improvement versus the prior
  behavior; retain it as a road readout and do not further tune the threshold from this route.
  The validator's full-route negative-request/live-gas diagnostic measured 94.57 s over 52
  episodes, with a 17.36 s longest episode and a minimum request of `-0.208 m/s2`. This is the
  expected upstream gas-domain split measured across the complete drive, not a comfort verdict or
  evidence to change the `-0.20` release boundary.

  **Additional new routes (2026-08-30).** Routes `0000005f--aaf45a0905` and
  `00000060--26ccab4b8f` ran the same parent `19e658584ec9` and nested `17e1f614d8b3` with Alpha
  Long disabled, so neither adds longitudinal command-following exposure. They exercised the
  lateral arm, but route `5f` supplied only 4.51 high-authority seconds and its counter-matched
  bus-1 output reached 3135 counts for only 0.06 seconds above 2560; route `60` supplied 2.75
  seconds and bus-1 output reached only 1455 counts. The corresponding forwarding attenuation
  makes these transport/arm diagnostics rather than clean independent 3840 road examples. Both
  had no steering faults, but each had seven steering overrides. They do not change the decision:
  route `61` remains example two and one adequately exposed route remains allowed before keep or
  retirement.

  **Route 64 command and alert attribution (2026-08-30).** Route `00000064--898a884741` ran
  `ody-op` at parent `7e3fb6fc6fd6`, nested `843b22ab0a74`, with Alpha Long enabled. At
  `11:46:58.574`, the vehicle was at `39.5 mph` against a `38.8 mph` set speed with no lead;
  `longitudinalPlan` selected `cruise`, `shouldStop` was false, and `aTarget` was `-0.314 m/s2`.
  `carControl.actuators.accel` was `-0.310`, `ACCEL_COMMAND` was `-0.310`, and the `-0.30`
  road-speed domain threshold selected `BRAKE_REQUEST`. The brief release at `11:47:00.482`
  occurred at the set speed, but a second no-lead cruise-braking episode began at `11:47:03.175`
  at `39.5 mph` with request `-0.303`; it remained active until the driver pressed the gas at
  `31.7 mph` at `11:47:11.467`. During that episode the request reached `-0.470 m/s2` and measured
  `aEgo` reached `-0.816 m/s2`. Route-wide carControl-to-plan, request-to-wire, and brake-domain
  wire RMS were `0.0078`, `0.0062`, and `0.0096 m/s2`; there was no meaningful port-added braking.
  The first unexpected decision is the upstream no-lead cruise candidate, and the exact mechanism is
  now resolved. `controlsState.forceDecel` and
  `driverMonitoringState.noResponseForceDecel` were false throughout the event, with selfdrived in
  `enabled`/`overriding`, so this was not driver-monitoring or soft-disable deceleration. Instead,
  model gas-press probability crossed below the upstream `0.4` threshold and published
  `allowThrottle=false`. `get_cruise_accel()` then capped maximum acceleration at
  `get_coast_accel(pitch)`: as pitch changed from about `-0.034` to `+0.030 rad`, that cap became
  increasingly negative, from about `-0.11` to `-0.47 m/s2`. Because the plan source was `cruise`,
  this negative coast estimate remained the requested acceleration even after speed fell below the
  set point. The driver restored throttle at `31.7 mph`.

  Routes `44`, `45`, `61`, `62`, `63`, and `64` all resolve to the same upstream longitudinal-
  planner blob (`cc1345a6ae20`). Under the matched diagnostic—active Alpha Long, no lead, source
  `cruise`, `allowThrottle=false`, more than `1 mph` below set, request below `-0.05 m/s2`, no gas
  override, and at least `0.5 s` duration—only route `64` had an episode: `4.08 s`, median
  speed error `-3.4 mph`, median pitch `+0.0108 rad`, minimum request `-0.459 m/s2`, and minimum
  achieved acceleration `-0.783 m/s2`. Honda domain selection and CAN carried the request while
  achieved response supplied the remaining amplification. This is an isolated upstream
  model/planner coast-limit event, not radar evidence or a Honda tune regression; do not compensate
  for it with gas/brake thresholds or command shaping. A port change is rejected unless a future
  route first diverges after `carControl` under a comparable request.

  The same route logged two large system alerts. At `12:08:04.550`, selfdrived raised `TAKE CONTROL
  IMMEDIATELY / System Lagging`, followed at the same instant by `TAKE CONTROL IMMEDIATELY /
  Communication Issue Between Processes`; the recorded comm issue listed invalid
  `driverMonitoringState` and missing/not-frequency-OK `alertDebug` and `lateralManeuverPlan`.
  At `12:10:59.027`, it raised `TAKE CONTROL IMMEDIATELY / System Lagging` without a comm issue.
  `carControl` and `longitudinalPlan` remained at normal local rates, manager state showed no missing
  required process, controlsd had no crash, and there was no active Panda CAN fault or bus-off. CPU
  reached 100% with 89-90% memory use while thermal status remained normal, so treat these as
  transient device scheduling/IPC load alerts rather than a radar, Honda command, or CAN-braking
  fault.

  **Final `+0.02 m/s2` fresh-gas re-entry decision (2026-08-30): RETIRE.** The candidate was
  introduced from frozen-input projection and then ran on exact-arm routes
  `00000030--d288c988eb`, `00000031--781e1d39f2`, and `00000032--3526ec7811` at nested
  `41aaf59ee6f2`. They supplied 20/14/10 coast re-entries and independently exposed 13/8/9
  sustained intervals where a positive request at or below `+0.02 m/s2` remained in coast for
  3.02/0.65/1.19 total seconds. Their gas-domain jerk RMS was `0.291/0.349/0.262 m/s3`, mixed
  against `0.299/0.349 m/s3` on pre-arm routes `52`/`53`, and they still produced 2/1/1 short
  coast-to-gas re-entries. No driver report or first-divergence trace attributed an improvement to
  the threshold.

  Routes `61`-`64` carried behavior-identical gas re-entry code and add current full-rate exposure.
  Across all seven retained arm routes, the threshold withheld 67 positive-request intervals for
  10.29 s; 55 were followed by gas entry within 0.25 s and 14 ended as the request reversed. The
  arm's zero tiny-request entries are therefore an expected consequence of forbidding the category,
  not evidence that achieved response became smoother or more accurate. Under the predeclared
  three-example and PR-minimal rules, remove only the `+0.02` fresh-entry gate. Fresh positive
  road-speed requests select gas again; active gas continuity to `-0.20`, the `-0.30` brake entry,
  low-speed domains, raw `ACCEL_COMMAND`, and gasfactor remain unchanged. Nested commit
  `929540bbc` contains only that production removal. The corrected 50 Hz rail assertion was
  mutation-verified against the old gate before the production change.

  **Final nonlinear 3840 decision (2026-08-30): RETIRE TO STOCK 2560.** Route `64` closes the
  predeclared three-independent-example screen. Its nested `843b22ab0a74` lateral production code
  is behavior-identical to routes `5d`/`61` at `17e1f614d8b3`; the only intervening lateral diff is
  the explanatory comment. Route `64` supplied 5.09 clean high-authority seconds at a median/max
  3840 command, actual-versus-desired RMS `0.084 m/s2`, median sign-corrected under-response
  `+0.009 m/s2`, 54.0% under-response, 33 steering overrides, and zero steering faults. Its two
  sustained episodes measured 3.80 s at `+0.045 m/s2` median under-response and 1.18 s at
  `-0.103 m/s2`; clean operation therefore proves exposure, not a consistent tracking gain.

  Across the three arm routes, the same high-authority readout measured RMS/median under-response
  `0.201/+0.122`, `0.245/+0.070`, and `0.084/+0.009 m/s2` for routes `5d`, `61`, and `64`.
  Resolved 2560 Alpha Long routes `44`, `45`, and `46` measured `0.036/+0.028`,
  `0.162/-0.037`, and `0.146/+0.008 m/s2`; their exposure is limited or fault-confounded, so this
  is not a matched superiority claim. A speed/demand nearest-slice check likewise produced no
  repeatable arm advantage, and route `64`'s full-route median is effectively identical to route
  `46`'s stock-2560 median. The first route's thin unmatched promising comparison, the second
  route's mixed response, and the third route's stock-like response do not meet the burden for a
  custom production range after the bounded screen. Nested commit `2dcbb30f5` restores only
  `torqueBP/torqueV=[[0,2560],[0,2560]]`; `latAccelFactor=0.9`,
  `steerActuatorDelay=0.15`, longitudinal behavior, and lateral diagnostics remain unchanged.
  Reopen authority only for a repeatable logged lateral symptom and an isolated matched road A/B.

  **Passive stock-camera confirmation (2026-08-30).** Route `00000069--eab494ffc4` logged 8.23
  minutes with zero engaged time and zero `sendcan` `0xE4` frames, so its camera-side bus-2
  `STEERING_CONTROL` is an OEM source rather than an OpenPilot command. Of 49,625 checksum-valid
  source frames, 18,922 carried a nonzero request in DBC `CONTROL_STATE=2` (`lka_active`). Their
  absolute maximum was exactly 2560; 216 frames (2.16 s at 100 Hz) were exactly at that cap and none
  exceeded it. The 1,362 request-bit frames labeled `CONTROL_STATE=5` (`rdm_active`) all carried zero
  torque and `HAPTIC_WARNING=1`; nonzero corrections surrounding those phases remained in state 2
  and within 2560. The labels are provisional signal semantics, but the raw command bound is not:
  this route directly confirms the stock camera's nonzero steering wire range as 2560 and supplies
  no evidence for a stock 3840 command. It supports retaining the restored 2560 map, while remaining
  a command-range observation rather than lane-tracking or matched-road proof.

- **Route 4f uphill Experimental attribution and lateral arm (2026-08-17).** On
  `0000004f--2cf5bde88e`, positive-pitch Experimental windows contained 15.5 engaged minutes.
  `longitudinalPlan.aTarget` to `carControl.actuators.accel` to `ACCEL_COMMAND` remained aligned
  (request-to-wire RMS 0.006 m/s2), while achieved `aEgo` was commonly 0.4-0.7 m/s2 lower when the
  request was near zero on the uphill grade. The E2E desired acceleration followed the same
  request and gas remained active for positive requests, so this route does not justify a
  car-port gas compensation; the first unresolved question is the upstream Experimental grade
  command versus Honda powertrain response. The route also establishes the lateral telemetry
  baseline: 23.4 active minutes, CAN torque abs p95/max 1617/2560, 0.5% torque-controller
  saturation, one steer-fault event, and 69 steering-override events. At that point the Odyssey
  3840 range became an isolated arm; command/output, lateral model error, steering response,
  overrides, and faults were logged for comparison. The bounded decision above now treats route
  `5d` as the first of at most three independent examples; these diagnostics alone remain
  insufficient lane-tracking proof.
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
  windfactor learner was initially left as diagnostic-only state so that arm did not silently
  change its evidence stream; it was later removed after a consumer audit proved it could not
  affect commands or telemetry. The gas-wire arm is not road-proven until a controlled and
  ordinary-road comparison is run.

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
- **Final low-speed PID decision (2026-08-25): RETIRED.** The original validator result of zero PID
  exposure on every exact-source route was invalid: the following analysis first restricted speed
  to above 3 m/s and then looked for frames below 3 m/s. A mutation-tested metric now runs before
  that road-speed gate and uses the physical brake domain. Corrected routes `30`/`31`/`32`/`38`
  contain 657/198/624/681 exposed frames; mean added command was
  `-0.043/-0.012/-0.052/-0.068 m/s2`, with most-negative samples
  `-0.174/-0.059/-0.117/-0.165 m/s2`. Direct frame inspection found both lagging and
  over-decelerating periods; on route 31, 54% of materially altered frames were already more than
  `0.10 m/s2` past the request. That observation cannot supply the frozen no-PID vehicle response,
  so it proves neither benefit nor net harm. The measured stop-lurch frames on routes 30/32/38 were
  instead almost entirely downstream of the wire: port contributions were only
  `+0.03/+0.02/~0.00 m/s2` versus Honda-response contributions of
  `+0.51/+0.30/+0.56 m/s2`. The official no-PID maneuver route 56 likewise carried request to wire
  at about `-1.79 m/s2` while the Odyssey achieved about `-4.53 m/s2` near 1.56 m/s. With no matched
  road A/B showing improvement, the custom loop's intentional command divergence does not meet the
  new command-fidelity or upstream-PR burden. Remove it while retaining low-speed brake-domain
  selection, positive start release, Honda safety rails, and historical source mapping in the
  validator.
- **Retired-PID tooling cleanup (2026-08-31).** The dedicated four-field low-speed PID reconstruction
  and its always-OK verdict are removed from current validation. They could not flag a symptom or
  influence status promotion after the production loop was retired, while the active source-matched
  request-to-wire, low-speed conflict, stop-lurch, and domain checks already preserve the actionable
  evidence. Existing JSONL rows remain historical records. `LOW_SPEED_BRAKE_PID_COMMITS` remains
  deliberately mapped because it still excludes those revisions' intentional low-speed additions
  from the general port-overshoot metric and selects their correct legacy brake-following threshold.
  The exact-source mapping test failed when `41aaf59ee6f2` was deliberately mistyped and passed after
  restoration. No-ledger validation then kept the current `f52c828fdf49` brake-following limit at
  `0.05 m/s2` on route 70 and the historical `41aaf59ee6f2` limit at `0.15 m/s2` on route 39, while
  neither output emitted the retired PID fields or verdict.

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
- **Windfactor production learner — RETIRED 2026-08-25.** Logs showed it could move while gas was
  not commanded, and the gas-active-only shadow below converged near its lower rail. After
  wind/grade feedforward was removed from `GAS_COMMAND`, the learner had no remaining consumer:
  it could not affect gas, brake, domain selection, `ACCEL_COMMAND`, or telemetry. Its fields and
  update loop were therefore removed as command-output-invariant dead state while gasfactor stayed
  unchanged. Any future replacement is a new gas-side arm, not restoration of the old learner.
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

## Historical tuning notes

The following notes preserve prior reasoning and examples. They are not active development rules;
use `AGENTS.md` and current evidence instead.
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

## Historical upstream context (re-verify before use)
- **opendbc PR #2165** (github.com/commaai/opendbc/pull/2165): wind drag + hill/pitch compensation for Bosch gas pedal force. Still draft upstream, parked pending a broader drivetrain-torque refactor.
- **opendbc PR #2347** (github.com/commaai/opendbc/pull/2347): documents that Honda Bosch's own ECU already runs an internal brake PID. Stock `kp=0, ki=0` (pure feedforward) in `interface.py` is deliberate - adding openpilot's own closed-loop kp/ki on top "doubles up... and causes oscillating braking/acceleration strength." Check this before adding closed-loop longitudinal gain on a Honda Bosch car.
- **opendbc PR #2767** (github.com/commaai/opendbc/pull/2767, closed): a comma engineer tried pitch-compensation on the gas pedal and hit "will need to switch the gas actuator from accel-based to torque-based first." Bosch A has no writable torque CAN signal (`ACC_CONTROL.ACCEL_COMMAND` is a real m/s2 value Honda's ECU closes its own loop on; `ACC_CONTROL.GAS_COMMAND` is opaque/unitless). A torque-based redesign would mean reverse-engineering a speed-dependent `GAS_COMMAND`-to-torque calibration using the car's own `GAS_PEDAL_2.ENGINE_TORQUE_ESTIMATE` telemetry as ground truth.
- **Current longitudinal design on this branch**: `ody-op` uses upstream's direct Odyssey gas
  mapping and a raw-request three-domain gas/coast/brake selector. `ACCEL_COMMAND` is the clipped
  controller request; the selector only chooses mutually exclusive Honda gas/coast/brake domains.
  The asymmetric road-speed onset limiter, supplemental low-speed PID, and production windfactor
  learner are retired. Wind and grade do not reshape the wire command or domain selection. See the
  concise rationale and current code before using this historical archive.
- **Review-sized design record**: `.agents/odyssey-tune-rationale.md` is the concise durable rationale removed from production comments; use the longer history here only when investigating a regression.
- **Current tune status:** lateral keeps the stock-LKA baseline: 2560 maximum command,
  `latAccelFactor 0.9`, and `steerActuatorDelay=0.15`; the nonlinear 3840 arm is retired. Longitudinal
  retains the road-screened three-domain selector and upstream direct gas mapping with raw
  `ACCEL_COMMAND`; the asymmetric onset arm is retired after its bounded road screen. The stopped-lead
  planner candidate remains an inactive supervised child, not production behavior. The production
  branch is software-validated and remains the rollback baseline until a separate candidate earns
  controlled and ordinary-road evidence.
- **Historical brake-onset experiment (`DOMAIN_HYST` 0.06 + symmetric 2.0 m/s³ jerk limit): CLOSED 2026-07-27, both branches DELETED.** Do not recreate that combined architecture: its functional change and failed isolation remain useful history. The retained three-domain selector itself does not shape `ACCEL_COMMAND`; the later asymmetric road arm was a separate mechanism and is also retired. Retired tips in case the historical commits are still reachable: `ody-brake-onset` = parent `cb03c32b4` / opendbc `1b6048e98`; `ody-op-long2` = parent `9f73e6205` / opendbc `57fe3a908`.
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
- **How the historical gasfactor seed was derived (2026-07-24):** the cross-drive "GASFACTOR vs SEED" report over 4 drives, confirmed by a narrow ±1.5 m/s per-breakpoint check, showed the low-cruise dip in `GAS_FACTOR_SPEED_V` was over-fit to the single original drive (00000088). Converged effective gasfactor was **0.54 at 8 m/s** (tight spread 0.52-0.56, implied trim ~1.55) and 0.57 at 15 m/s. The seed under-gassed low cruise so the trim re-clawed it 1.55x from 1.0 every cold start. The historical table became `[0.72, 0.54, 0.56, 0.60]`; its individual commits were squashed into opendbc `ed78a3f1b`. This history now exists only to interpret old telemetry: the later retention audit removed both the live trim and its seed table from production.
- **Gasfactor report correction (2026-08-09):** the later `8 m/s: seed 0.54 learned 0.63 (n=46)` suggestion is invalid. That report averaged a 4.0-11.5 m/s midpoint bin, compared it to the single 8 m/s point, accepted ~0.21 s of exposure, mixed code versions, and weighted every drive equally. The corrected historical analysis used ±1.5 m/s live-gas frames, compared learned and interpolated seed on identical frames, required 30 s per route plus 300 s/3 routes, excluded thin/qlog/route 5 data, exposure-weighted, and grouped by exact `opendbc_commit`. Its results remain historical route evidence. The active validator retired this report on 2026-08-31 after production removed both the learner and its seed table.
- **Test-suite audit (2026-07-26, routes `00000015`/`00000016`)**: audited every check against the 8 accumulated rows and cut what could never fire or could never *stop* firing, then added what was missing.
  - **Added — coverage** (`engaged_min`, `engaged_mi`, `engaged_frac`, `vego_max`; never flags). The ledger previously could not distinguish a clean row earned over 45 engaged minutes from one earned over 30 seconds, yet every cross-drive aggregate weighted them equally. It now also gates `suggest_status`, so a thin drive can't cast a vote in a "2 of the last 5" promotion.
  - **Added — driver interventions** (gas overrides, brake takeovers, per 10 engaged min). The only checks graded by what the *driver* did rather than by telemetry we chose how to interpret. Note the Honda-specific trap: the brake switch drops `longActive` on the same frame, so `active & brakePressed` reads ~0 on every drive — attribute a press to OP if it was engaged within the preceding 0.5 s. Reported as "N of M brake presses" so a 0 with a healthy M means the driver never braked out, while 0 of 0 means the signal never arrived and the metric proved nothing.
  - **Added — accel rail saturation**: the wire is clipped to `BOSCH_ACCEL_MIN/MAX`, and sitting on the upper rail both reads as sluggish and freezes the learner (the carcontroller's own "at accel max the signal is saturated" guard). Tracking error can look perfect while pinned, because `aTarget` was never deliverable — no other check would surface it. 0.0% on both new routes.
  - **Removed — charging diagnostics**: route logs do not replace a mechanic's battery/alternator test, so `validate_log` no longer extracts, grades, or reports `pandaState.voltage`. Historical ledger rows keep their old fields for provenance, but future validation is limited to driving behavior and comma-device thermal health.
  - **Result**: `00000015` (47.3 min / 54.8 mi engaged) all-green. `00000016` (43.0 min / 47.7 mi) flagged brake_pid overshoot 7.3%, 4 jerk binds (peak 3.8 m/s³), and forceful domain chatter — **with zero driver interventions**, which is exactly the contrast coverage + intervention tracking was added to expose. Those three flags are telemetry symptoms on a drive the driver never once overruled; treat them as evidence to accumulate, not a mandate to change the converged tune.

## Live-learn or constant? (closed 2026-08-30; upstream-direct road arm)
The earlier aggregate tuned adaptive seed values but did not isolate either the live multiplier or
the seed map against upstream direct gas. Both are now retired. The unidentified windfactor learner
remains retired. The test for retaining or adding a learner is:
1. **Is it a physical property of the plant, with an unambiguous per-frame error signal?** `gas_error = self.accel - aEgo` gives the gas/drag learners a signed error every frame. A crossing RATE or a chatter statistic is not that - it is a measurement over minutes.
2. **Is a wrong value merely degraded, or unstable?** Wrong `gasfactor` = sluggish or eager, self-correcting. Wrong hysteresis width = a behavioral failure mode, and the degenerate direction is dangerous.

3. **Can it converge inside one drive?** **Persistence is deliberately dropped** (no openpilot `Params` from opendbc, see the carcontroller note), so every learned value resets at each ignition. Anything that cannot converge in minutes must be a constant, because it will never be right when it is needed.

**Final live-learner audit.** A deterministic reconstruction over exact current-source routes
`00000045--6774d01fb4`, `61--b8f07e1ca7`, `62--e38819678c`, `63--fafa9ef1e1`,
`64--898a884741`, `66--a1ef887d10`, and `68--bbbfad9947` reproduced the recorded
`GAS_COMMAND` within 4-7 counts RMS. The residual multiplier ended at
`1.861/1.794/1.817/0.967/2.226/1.968/2.662`; relative to the static map it added a median
`122/84/99/52/133/119/105` command counts. It is active and material, not dead state.

That movement does not itself prove benefit because the same tracking error drives the update.
Positive-gas tracking split into route thirds was mixed: some routes improved late (`64`, `66`),
while others worsened or reversed (`45`, `61`, `62`, `63`, `68`). No retained full-rate route is
an isolated learner-on/off road comparison. A mutation check using identical request/speed with
opposite achieved-acceleration error failed under the learner (200/200 commands differed, maximum
245 counts) and passes without it. Fixed-input replays of routes `61`, `64`, and `68`
confirm raw `ACCEL_COMMAND`, brake/domain selection, and wire jerk are unchanged, but cannot prove
closed-loop gas response.

The intermediate static-seed arm was committed and deployed at parent `2ae03668e1` / nested
`5144f8b2f` but had no post-deployment route. Exact upstream inspection then showed that the
Odyssey 2000-count ceiling is already upstream behavior; the remaining custom map alone scaled
eligible gas to 54-72% of that direct request. Actual learner-on cold-start exposure supplied a
screen: over 24.6 s of stable requests with multiplier at or below 1.10, median under-response was
`+0.177 m/s2` and 82.4% of samples under-responded, versus `+0.084 m/s2` over 551.3 s above 1.50.
This is endogenous and not a matched A/B, but it disproves treating the seed as a proven standalone
calibration. A mutation-verified regression failed all 15 speed/request cases under the static map
and now requires the exact upstream direct interpolation. The current arm removes the whole custom
gasfactor mechanism while retaining the upstream Odyssey ceiling, raw `ACCEL_COMMAND`,
domains, brake behavior, and lateral behavior. Accept only after ordinary-road gas following is at
least as smooth and accurate; reject for repeatable eager acceleration, surge, or driver overrides.

Fixed-input current-code replay establishes that this is a material command arm, but changes its
primary risk from the static-map intuition. On common positive-gas frames from routes `61`, `64`,
and `68`, upstream direct `GAS_COMMAND` was lower than the recorded learner-on command by median
`59/125/85` counts. Recorded versus direct median commands were `320/252`, `374/245`, and
`364/257`; their 95th percentiles were `1117/1009`, `1311/935`, and `1545/905`. Where direct replay
was at least 50 counts lower, the recorded stronger command still had median `request-aEgo`
`+0.063/+0.074/+0.084 m/s2`, with `64.8/71.3/69.9%` under-response. This is not a causal response
prediction: the replay freezes the old `aEgo`, and the old learner increased gas from that same
tracking error. It does prove that the direct arm is commonly weaker than recent driven output and
must be rejected for repeatable sluggishness or set-speed loss, not screened only for eager
acceleration, surge, and gas overrides.

The remaining fresh-negative road-speed gas suppression is a separate unresolved mechanism. On
exact-source routes `45`, `61`-`64`, `66`, and `68`, a settled-window audit of requests from
`-0.18` to `-0.02 m/s2` found 33 coast windows from 14 physical episodes and 714 active-gas windows
from 102 episodes. No coast/gas episode pair within the same route matched within `0.025 m/s2`
request, `2.0 m/s` speed, and `0.010 rad` pitch; unmatched route medians were mixed rather than
repeatably favoring either domain. The older raw-split routes `41`/`42` are not an isolated
counterfactual because their source also added wind/grade feedforward, rate-limited gas handoffs,
and used different learner gates. This history therefore cannot establish that suppressing fresh
negative gas improves achieved command following. Do not stack its removal onto the unroad-tested
upstream-direct gas arm: first collect an engaged ordinary-road route on the current mapping, then
change only fresh road-speed requests above the upstream `-0.20` split if a matched road comparison
is available. Active brake release must remain at a nonnegative request during that test.

- **`DOMAIN_HYST_EXIT` must stay a constant.** It is a state-selection parameter, not a plant
  estimate, and descents are only 2-5% of driving (0.17-2.09 min per drive measured), so a learner
  would spend every drive re-converging. Size it offline from road evidence rather than adapting it
  from transition counts.
- **Historical `hill_brake` gravity-gain candidate — NOT worth learning.** It is physical and has a clean error signal, so it passes tests 1 and 2. But measured over 328k learner-eligible gas-domain frames across 5 drives, the residual `gas_error` regressed on the hill term gives slope +0.092, r = +0.145, implying a correction of only **0.91x** - about 9%, or 0.02 m/s^2 on a typical -0.22 hill term. The residual is dominated by a **pitch-independent** intercept (-0.069) that gasfactor already absorbs. Note the trap: run this regression over ALL historical frames rather than gas-domain-only and the slope inflates, because the former road-speed `brake_pid` made the wire more negative exactly on descents where the hill term was also negative - manufacturing a correlation that had nothing to do with gravity.
- **Never learn**: `BRAKE_PID_KI` (adapting a gain against Honda's own brake loop is the #2347 instability by construction), `min_gas_accel` or any domain threshold, and the learn divisors themselves.

## Where the constants belong (updated 2026-08-30)
Custom gas calibration constants are removed from production. Remaining Odyssey behavior must stay
explicitly fingerprint-gated so it cannot silently affect every Bosch Honda.
- **Historical only**: the former Odyssey gasfactor seed table remains in this evidence and old
  ledger rows. The active validator no longer computes or recommends it, and it is not production
  parameter data.
- **Odyssey-only**: `ODYSSEY_LOW_SPEED_DOMAIN_VEGO` and `ODYSSEY_ROAD_BRAKE_ENTRY` are module-level
  physical/domain constants used only inside the Odyssey fingerprint branch.
- **Upstream behavior**: Odyssey retains `BOSCH_GAS_LOOKUP_V = [0, 2000]` through the existing
  `interface.py` parameter path; this branch no longer relocates that behavior.

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

## Historical queue (superseded): decouple the domain threshold from the gas-lookup floor
This section records the 2026-07-29 queue and its measurements. The work is closed: current
`ody-op` retains the independently screened `-0.30 m/s2` road-speed entry and does not reopen the
old width/threshold architecture without a new first-divergence result.

`BRAKE_DOMAIN_ENTRY=-0.20` is now named separately from the gas lookup with no behavior change.
Do not combine a future entry experiment with a release-band change: entry at -0.10 addresses
delayed brake entry, while route `00000002--412e40c6a0` exposed an excessive release hold. Moving
entry alone to -0.10 increased frozen-replay brake exposure from 13.7% to 18.0%; it is not the fix
for the reported underspeed. A combined -0.10 entry / 0.15 band released that event 1.12 s earlier
on frozen inputs, but 0.15 is narrower than the 0.20 band that already failed on road and the pair
changes both sides of the state machine. Keep it experimental until a clean baseline drive exists.

At the time, the next drive was intended to be the `0000002f`/`00000030` descent route carrying a
CANDIDATE value rather than another baseline. The 0.50 baseline arm is closed (26 pooled
hold-episodes, see the restated gate above); the historical plan and its width/threshold candidate
are not an active queue. Later road screens selected the `-0.30` entry and retired the width arm.
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

**The one genuinely untested state.** `GAS_COMMAND` has never been sent as **0** on this car: measured over `0000000d`/`00000003`, GAS_COMMAND is the -30000 inactive constant 4%/21% of engaged frames and positive 96%/79%, and **exactly 0 on 0.0%**. The +43 vs -139 torque contrast above is *low gas in the gas domain* vs *inactive in the brake domain*, so it conflates the domain flag with the gas value and cannot answer whether `GAS_COMMAND = 0` alone avoids the overrun fuel-cut. Per the current [car-port standards](car-port-standards.md), this signal is opaque/unitless in the DBC and must not be extrapolated. Answering it needs a deliberate probe, not a log query - and no existing route can substitute, because the state has never been on the wire.

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
- **`git_commit` is the PARENT commit; the tune lives in the submodule. Pool on `opendbc_commit`, not on branch or parent commit.** Grouping by the parent is what made the 0.50 analysis wrong on 2026-07-30: routes `32`/`33` were treated as "baseline" when their pointers were `BRAKE_RELEASE_HOLD` and 0.20, two configurations already known worse than no hysteresis. `_provenance` resolves `git ls-tree <git_commit> opendbc_repo` and stores the short display key plus exact `git_commit_full`/`opendbc_commit_full` for each clean row. It also records the observed model kind and exact parent-tree model blobs, Experimental/personality state, and an allowlisted `settings` snapshot; dirty or mixed-source logs are explicitly marked `provenance_exact=false`. The short fields remain for compatibility with historical rows and `suggest_status`, while new comparisons should prefer the full fields when available. It is deliberately blank for a dirty tree - the pointer then describes what was committed, not necessarily what was flashed. `suggest_status` enforces the same boundary, so an old tune cannot vote to promote a warning against the current one.
  - Found while adding that column: the MD table had been emitting **16 cells against 15 headers** when `windf mean` was first added without a header, so every column from `follow gas` rightward was labelled one to the left - the "follow gas" column was showing `windf_mean`. The `.jsonl` was always correct and all analysis to date read from it, so no conclusion moved. The renderer now derives header and rows from the same 20-column list; check data rows with `awk -F'|' 'NR > 6 && NF != 22' .agents/log-validation-ledger.md`.

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
- **Rate-limited / jerk-limited ACCEL_COMMAND** (Toyota does `rate_limit(pcm_accel_cmd, prev, ±0.12/frame)`; **Ford** does a brake-jerk limit `accel = max(accel, self.accel - 3.5*step*DT)` = 3.5 m/s³ on the ACCEL/brake side, `ford/carcontroller.py` L124-126): the old symmetric 2.0 m/s³ experiment and the later isolated 3.0 m/s³ moderate-brake limiter are both retired after road screens found no attributable benefit. This upstream-style pattern remains a rationale to revisit only if a new repeatable onset symptom appears; it is not active Odyssey behavior.
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

## Vision-only command-fidelity route 44 (2026-08-25)

Route `00000044--1f70122a52` ran parent `78562c509663` with nested opendbc
`09a52a2bf003`, the vision-only `ody-op` command-fidelity baseline. The later nested
`e86b4ba94621` commit only moves the unchanged Odyssey gas seed table into per-car parameters, so
it does not alter the behavior measured here. The route logged 45.1 minutes, 12.8 engaged minutes,
and 9.4 engaged miles. It produced six driver brake takeovers and 28 physical `BRAKE_REQUEST`
edges, peaking at 6/10 s; 17 edges occurred over 1.32 downhill minutes (12.85/min).

The two driver-reported late lead stops map to takeovers at 11:57:35.717 and 12:00:58.065 local
time. Both were non-Experimental, standard-personality, vision-only lead approaches. In the final
20 seconds before intervention, planner-to-`carControl` RMS was 0.0140 and 0.0080 m/s2, and
`carControl`-to-wire RMS was 0.0110 and 0.0072 m/s2. The first takeover occurred at 1.2 mph with a
2.7 m lead distance; the second at 0.9 mph and 3.2 m. `longitudinalPlan.shouldStop` remained false
through both interventions and became true only after the driver had disengaged longitudinal
control. The first divergence is therefore the upstream lead/stop-spacing decision, not
`longcontrol` or radar input. The port nevertheless contributed a second divergence: with the
numeric negative request already present on `ACCEL_COMMAND`, both gas and brake domains remained
inactive until the request crossed `-0.50 m/s2`. Against the same frozen request, a `-0.30` entry
would have selected physical braking 10.05 s and 2.45 s earlier. That does not repair the planner's
late `shouldStop`, but it does reject treating numeric passthrough alone as complete actuation
fidelity.

The reported downhill complaints align with four brake episodes at 12:17:01.638-12:17:16.832,
one at 12:24:12.094-12:24:14.292, and one at 12:25:46.754-12:25:48.652. Every episode was sourced
from non-Experimental `cruise`; planner requests crossed from minima of -0.53 to -0.66 m/s2 back
to zero or positive, and the retained domain logic followed those crossings. Episode-local
planner-to-`carControl` RMS was 0.012-0.018 m/s2 and request-to-wire RMS was 0.011-0.016 m/s2.
Achieved acceleration ranged as low as -1.26 m/s2 and rebounded as high as +0.44 m/s2, making the
vehicle response visibly harsher than the already pulsed command. The command-shape divergence is
upstream cruise planning, but the `-0.50` binary brake entry delayed the six physical applications
by 0.44-2.85 s versus `-0.30` and then exposed Honda to a deeper initial target. Honda's actuator
response amplified that combined input.

The exact route-wide result is consistent: achieved-versus-`carControl` RMS 0.233 m/s2,
request-to-wire passthrough RMS 0.006 m/s2, gas/brake-domain following RMS 0.0077/0.0108 m/s2,
and no sustained sign disagreement. Felt jerk RMS was 0.331 m/s3 versus 0.192 commanded (1.7x),
with braking at 0.52 versus gas at 0.30 m/s3. This route is strong evidence that the reported
symptoms are real and that the current Honda port follows the requests numerically; it is not
evidence that the request was physically actionable while both domains were inactive.

After mapping the exact historical opendbc revision, the validator also measures 33.03 s over 18
negative-request brake-release-hold events, longest 6.93 s, with a mean request of -0.24 m/s2. This
diagnostic is not a frozen-response comfort claim; it confirms that the earlier validation's
numeric request-to-wire pass omitted meaningful binary-domain exposure.

A frozen-input threshold comparison preserves the closed-loop boundary while selecting the next
minimal road arm. Replaying the exact request yields 28/40/58 route-wide physical edges for entries
at `-0.50/-0.30/-0.20`, with the same peak of 6 edges/10 s. The six reported downhill applications
do not multiply at `-0.30`; they enter at about `-0.30` instead of `-0.50` and begin 0.44-2.85 s
earlier. The two lead approaches also enter 10.05 s and 2.45 s earlier. `-0.30` is therefore the
narrower compromise: change that constant only, freeze gasfactor, gas re-entry, low-speed domains,
numeric `ACCEL_COMMAND`, and all command shaping. It remains road-unproven because replay freezes
the vehicle response and predicts 12 additional route-wide edges; reject it for renewed tapping,
excess braking, or incomplete stops.

### Post-`-0.30` route 45 (2026-08-25)

Route `00000045--6774d01fb4` ran parent `7e315df79887` with nested opendbc
`6ff9761fc72e`, the isolated `-0.30` road-speed brake-entry arm. It logged 40.1 minutes but only
7.9 engaged minutes / 8.4 engaged miles, so it is thin context rather than a promotion drive. It
had only 0.009 downhill minutes and therefore does not test the reported descent behavior.

The route produced 16 physical brake-domain edges, 2.02/min overall, peak 2/10 s, minimum gap
5.46 s, and eight brake episodes with median duration 7.92 s and 80% command depth in 1.15 s.
All observed road-speed brake entries occurred at approximately `-0.30` to `-0.32 m/s2`; there
were no direct gas/brake handoffs, no sub-second coast-to-gas re-entries, and no sustained sign
disagreement. `carControl`-to-wire following remained close in both gas and brake domains
(`0.0057/0.0055 m/s2` RMS). Achieved jerk remained amplified downstream (`0.240` versus `0.125
m/s3` commanded, 1.9x; brake `0.291`), so this route does not establish a vehicle-comfort fix.

The two driver brake presses are not clean failures of the new threshold. At `500.539 s`, the
vehicle had no lead and the request had moved from about `-0.09` to `+0.02 m/s2` with no
`BRAKE_REQUEST`; at `2214.640 s`, a lead was present, but the request had moved from a prior
`-0.33` brake request through `+0.16 m/s2`, releasing the brake domain before the press. Both
events are retained as thin driver-intervention context, not as evidence to add brake authority.

**Decision at the time:** retain `-0.30` for a matched descent and lead-stop drive, but do not call
it a comfort improvement. Route 45 did not reject the arm, and its absence of downhill exposure
could not answer the then-active road question. Subsequent route 68 and later baseline screens kept
the same domain entry while rejecting additional brake shaping. No other lateral or longitudinal
tuning change was authorized from this route; lateral remains diagnostic-only at the stock 2560
range with no saturation or fault evidence.

### Current-code `-0.30` descent screen: route 68 (2026-08-30)

Route `00000068--bbbfad9947` ran parent `533f4cd91ef8` and nested opendbc
`929540bbcf79`, the current three-domain source after retirement of the independent `+0.02 m/s2`
gas re-entry gate. It logged 24.76 minutes, 8.71 engaged minutes / 7.13 miles, and 0.903 downhill
minutes. It produced 40 physical `BRAKE_REQUEST` edges, peak 9/10 s, including 27 downhill edges
(29.9/min), so it supplies the substantial descent exposure route 45 lacked.

The worst window ran from `1270.62` through `1280.17 s` and contained five brake entries plus four
releases. It had no lead, `shouldStop=false`, `allowThrottle=true`, and the upstream source was
`cruise`. The planner repeatedly reversed from approximately `-0.31..-0.44 m/s2` to
`+0.00..+0.05`; `carControl` and `ACCEL_COMMAND` followed. Achieved acceleration was commonly
`+0.4..+0.5 m/s2` at entry and then reached `-0.55..-0.73 m/s2`, so Honda amplified an already
pulsed request. Across the route, planner-to-`carControl` RMS was `0.0090 m/s2`, brake-domain wire
RMS was `0.0126 m/s2`, all 20 physical entries occurred below `-0.30`, all 20 releases occurred at
nonnegative requests, and entry request-to-wire error was `0.003/0.005 m/s2` median/max. Seventeen
entries were `cruise`-sourced, fourteen were downhill, and there were no direct gas-to-brake
handoffs. The single brake takeover at `1466.44 s` occurred with no lead, no `BRAKE_REQUEST`, and a
request/wire of about `-0.03 m/s2`; it is not a late-brake failure of the threshold.

A fixed-input selector comparison isolates domain timing without claiming closed-loop response. On
the exact recorded inputs, entries at `-0.20/-0.30/-0.50` produce `72/40/6` physical edges, peaks of
`10/9/2` per 10 s, `30/27/0` downhill edges, `0.01/47.78/88.06 s` of coast, and `36/0/0` direct
gas-to-brake handoffs. Moving to `-0.20` would therefore increase transitions and collapse the
deliberate separation from Honda's active-gas release split. The apparent `-0.50` improvement comes
from withholding requested brake for substantially longer; route 44 already rejects that mechanism
for 10.05/2.45 s late lead entries and 0.44-2.85 s late downhill entries.

**Decision: KEEP `-0.30`.** It now has an attributable command-domain benefit: current road routes
avoid direct gas-to-brake handoffs, and route 68's exact inputs predict a material regression if the
entry returns to the upstream `-0.20` split. This does not claim a comfort improvement. Route 68's
worst burst first diverges in the upstream no-lead `cruise` trajectory, while the additional bite is
downstream of a faithful wire command. Do not compensate either contributor with a new Honda
threshold, brake supplement, release hold, gas deadband, or command shaper. Reopen `-0.30` only if a
matched road result contradicts its domain-separation benefit or shows a repeatable first divergence
at the selector itself.

### Direct-mapping pre-sync context: routes 6a/6b/6c/6d/6e/70 (2026-08-31)

The six newly pulled full-rate routes all predate the master merge and ran parent
`0cdcc917185a` with nested opendbc `f52c828fdf49`. Routes `00000070--16f597b10c`,
`0000006e--a6330d5491`, `0000006d--f3475cee48`, and `0000006b--6f4ad5c4f2`
provided only 5.6, 4.2, 2.8, and 2.6 engaged minutes respectively; routes
`0000006a--82ebb3e2e6` and `0000006c--e03f45c15b` had no engagement. All are thin context,
not independent adequately exposed road examples.

Across the four engaged routes, planner-to-`carControl` RMS was `0.0074-0.0105 m/s2`, gas-domain
request-to-wire RMS was `0.0069-0.0097 m/s2`, and brake-domain RMS was `0.0076-0.0185 m/s2`.
There was no sustained sign disagreement, no gas-to-brake handoff above 5 m/s, no rail saturation,
and no `controlsd` crash. Route 6e still produced 25 physical brake edges, peak 6/10 s, and 2.0x
achieved-versus-commanded jerk amplification; route 6b measured 1.7x amplification. Those flags
remain driver-felt context downstream of a close numeric command path, not authority for a new
Honda threshold or command shaper. Exact-source review proves `5144f8b2fe94`, `9d6f42dd4fce`, and
`f52c828fdf49` retain the same scalar three-domain selector and `-0.30` road-speed entry as
`929540bbcf79`; they only retire gas calibration, adopt upstream gas mapping, and simplify the
helper. Revalidation therefore enables the source-matched domain checks. The four engaged routes
had no sustained positive-request/brake-domain disagreement. Their expected stateful negative-
request brake holds were 10.04, 0.19, 27.61, and 1.87 s on routes 6b, 6d, 6e, and 70 respectively.

The reported 07:15 lead approach is route 6d at `379.5-383.0 s`. OpenPilot remained in non-
Experimental standard-personality lead MPC control and never asserted planner or model
`shouldStop`. It reduced speed from 2.8 to 1.2 mph, but relaxed the plan/controller/CAN command from
about `-1.03/-1.05/-1.05` to `-0.21/-0.21/-0.21 m/s2` as the logged lead distance fell to about
2.8 m. Achieved acceleration was near zero during the final rolling second. The driver pressed the
brake at `382.97 s` with speed about 1.2 mph and logged lead distance about 2.6 m; that press ended
OpenPilot control before a counterfactual full stop can be observed. The first actionable
divergence is the upstream stop-spacing/stop-state decision and its mild command, not Honda command
translation. The low-speed brake domain, Honda `COMPUTER_BRAKING`, and numeric CAN command were all
active before takeover.

The reported no-lead braking is route 70 at `1088.5-1091.9 s` (13:44:47-13:44:50). There was no
lead, set speed was 39.8 mph, and speed fell from about 40.1 to 35.8 mph. This was a real upstream
`cruise` request: the standard model's horizon-1 gas-press probability was mostly below the 0.40
threshold, making `allowThrottle` false for most of the interval. On the logged positive pitch,
the upstream coast formula then capped cruise acceleration near `-0.35..-0.50 m/s2`, even after
speed dropped below the set speed. Direct model desired acceleration was only `+0.03..-0.13`, but
the model's throttle gate indirectly selected the stronger negative cruise request. `carControl`
and `ACCEL_COMMAND` followed it at about `-0.33..-0.50`, and Honda `COMPUTER_BRAKING` followed the
wire. The brief brake after re-engagement at `1097.9 s` instead came from planner state initialized
to the vehicle's existing deceleration while `allowThrottle` was true.

Route 6d supplied 11.01 s of lateral high-authority exposure at the stock 2560 CAN limit. Its
actual-versus-desired lateral-acceleration RMS was `0.092 m/s2`, with median sign-corrected
under-response `+0.030 m/s2`, but the route had only 2.8 engaged minutes and 5.2% saturation. That
is insufficient to reopen the retired 3840 arm.

**Decision: NO CHANGE.** Preserve these routes as pre-sync direct-mapping context. None is an
adequately exposed example for the three-example retirement rule, and none moves the first
repeatable divergence into the Honda wire translation. Do not compensate either reported event in
the Honda port. The next useful evidence is an ordinary-road route on a parent containing upstream
merge `6681d1e9e856` and nested `f52c828fdf49`, using the standard model. This C3X has no Chestnut,
so the big-model-only payload from `commaai/openpilot#38681` is not a road-test variable on this
device.

### Experimental uphill under-power archive audit (2026-08-31)

The retained local full-rate archive was screened across all 22 engaged Alpha-Long-capable routes,
not just the initially reported drives. Seven routes actually recorded Experimental mode while
longitudinal control was active. Routes `00000026--8d38fff2db` and
`00000044--1f70122a52` had no comparable uphill/no-lead exposure. The other five supplied 958.42 s
with speed above 5 m/s, pitch above 0.01 rad, at least 1 m/s below the set speed, no selected lead,
and no driver pedal override:

- Route `00000031--781e1d39f2` had 14.15 s at a median 35.5 mph set-speed deficit and 2.06 degree
  uphill pitch. The E2E/plan/`carControl`/CAN medians were
  `-0.571/-0.570/-0.564/-0.560 m/s2`; gas was inactive and achieved acceleration was
  `-0.346 m/s2`.
- Route `00000035--cdd11a0ea4` had 9.92 s at a 30.1 mph deficit and 3.25 degrees. The same medians
  were `0.000/-0.008/-0.008/-0.010 m/s2`, `GAS_COMMAND` was 188, and achieved acceleration was
  `-0.362 m/s2`.
- Routes `00000037--0c6fc80a62`, `00000038--c43a0ecf6c`, and
  `00000039--39fdbea04c` supplied 261.90, 466.66, and 205.79 s. Their median deficits were
  17.0, 7.7, and 23.6 mph, while E2E/plan/`carControl`/CAN stayed near
  `0.038/0.038/0.038/0.040`, `0.054/0.053/0.053/0.050`, and
  `0.106/0.106/0.106/0.110 m/s2`. Median `GAS_COMMAND` was only 203, 212, and 245; achieved
  acceleration was `-0.059`, `-0.044`, and `+0.063 m/s2`.

The planner selected `e2e` for 92.6-100% of those samples. Planner-to-`carControl` RMS was
`0.0065-0.0140 m/s2` and `carControl`-to-CAN RMS was `0.0065-0.0194 m/s2`, so neither
`longcontrol` nor the Honda translation created the weak request. Same-route non-Experimental
uphill/no-lead windows on routes 31, 35, 37, and 38 instead requested median acceleration of
`1.151`, `0.915`, `0.797`, and `0.858 m/s2`, producing median gas commands of 1227, 664, 989,
and 1391. This is a mode-dependent command difference, not evidence that the Odyssey gas map failed
to carry a stronger command.

Route `00000070--16f597b10c` is a checked negative example. It never recorded
`selfdriveState.experimentalMode=true`. Segment 22 stayed `cruise`-sourced at about 69.5 mph with a
69.6 mph set speed; its median plan/`carControl`/CAN request was approximately
`0.061/0.062/0.060 m/s2`, so its low command reflects negligible speed error rather than the
reported Experimental uphill symptom.

All eight retained device routes were pulled from official Sunnypilot staging commit
`70bf4f1791cd`. The six usable Odyssey routes (`00000000--12e3cbba46` through
`00000005--47b7f9af6b`) all confirm Alpha Long disabled. They are stock-radar longitudinal traces
even if Experimental UI features are selected, and cannot validate OpenPilot Experimental gas
command following. Routes `00000006--9c514718e2` and `00000007--378414eda0` are sparse boot/offroad
logs with no usable driving exposure.

**Decision: NO HONDA CHANGE.** Experimental adds the model's direct desired-acceleration candidate
and the planner selects the minimum candidate. In all five uphill examples, that E2E candidate won
and was already near zero or negative despite the large speed deficit; downstream stages followed
it closely. Increasing gasfactor, adding grade feedforward, or otherwise inflating `GAS_COMMAND`
would intentionally diverge from OpenPilot's command and would also disturb standard-mode behavior.
Treat this as an upstream Experimental model/planner limitation. Any future mitigation must be an
isolated, upstream-style planner guard or fallback on a temporary child branch with matched
Experimental road evidence; do not compensate in the Honda controller.

### Current-production delta hygiene audit (2026-08-31)

After parent `ody-op` advanced to upstream master `da8ce858ec`, openpilot still pinned opendbc
`b4ef5e1cf406`. The retained nested `f52c828fdf49` correctly descended from that pin, but its net
Honda production diff still touched three files. The `interface.py` difference only deleted three
upstream comments beside the already-stock 2560 map; it changed no parameter or executable code.
`carcontroller.py` also calculated the Bosch-only `stopping` state before the Bosch/Nidec branch,
making Nidec evaluate an unused value. Neither difference supported or changed a road decision.

Nested `b5b9f861aa18` removes those behaviorally dead fork differences. `interface.py` is now byte-
identical to the upstream pin, and `stopping` is again evaluated only in the Bosch branch. The net
production delta is limited to `carcontroller.py` and `hondacan.py`: 46 insertions and 4 deletions.
Those remaining lines are all active behavior or state required by the road-supported Odyssey
domain selector: the 5 m/s low-speed split, `-0.30 m/s2` road-speed brake entry, active-gas and
active-brake continuity, disengagement reset, Odyssey-only gas masking, and optional CAN-domain
arguments whose defaults preserve every other Honda platform.

Ruff passed on all three audited Honda files. The post-cleanup pre-flash gate passed seven Odyssey
model/interface/radar/safety tests plus 20 command-rail tests and 58 subtests. This is source-delta
hygiene, not a tuning candidate: it changes no Odyssey command, domain transition, or vehicle
response, and creates no new replay or road claim. Exact-source comparisons may treat
`f52c828fdf49` and `b5b9f861aa18` as behavior-identical for command following.

The retained road-entry assertion is mutation-verified. Temporarily changing
`ODYSSEY_ROAD_BRAKE_ENTRY` from `-0.30` to `-0.50` made
`test_road_speed_coasts_through_raw_split_chatter` fail in all nine speed/pitch subcases because a
`-0.31 m/s2` request no longer selected braking. Restoring the published `-0.30` source passed the
test and all nine subcases.

**Decision: REMOVE the dead fork differences; KEEP the evidence-backed command-domain delta.** No
further behaviorally dead production difference was found in this audit. Revisit the remaining
two-file delta only when a new full-rate route moves the first divergence into that selector or its
CAN-domain translation.

### Retired gasfactor seed reporter removed from active validation (2026-08-31)

The production gasfactor learner and its Odyssey seed table were already retired, but
`validate_log.py` still calculated per-breakpoint learned-versus-seed fields for legacy telemetry
and automatically printed a cross-route seed recommendation after every ledger update. A complete
reference trace found that the report fed no current verdict, no status suggestion, no command-
following metric, and no production parameter. Its breakpoint helper had no other caller, and its
three tests only proved the retired report's own aggregation policy. Current routes cannot populate
the input because `carOutput.actuatorsOutput` again carries actuator output rather than fork-only
learner state.

The active reporter, its seed constants, breakpoint helper, empty current-route fields, automatic
call, and three self-tests are removed. Historical JSONL rows retain their original
`gasf_by_speed`, `gasf_seed_by_speed`, and `gasf_seconds_by_speed` fields, and the derivation remains
in this evidence file, so no historical result is rewritten or lost. Legacy route-level learner
telemetry decoding remains available where exact source provenance proves those old `carOutput`
semantics.

The focused validator suite passes 37 tests after the removal; the broader tooling group passes 50.
**Decision: RETIRE this report.** A future gas calibration must begin as a new offline identification
question with current actuator semantics and its own evidence, not by reviving a recommendation for
a production mechanism that no longer exists.

### Bosch-A object-bank decoder arm (2026-08-25)

`ody-op-radar` ports the five-file decoder change from `mvl-boston/opendbc#669` at exact source
commit `cd9a3683dc479bbc8c46427569ef6e45354f7e1f`, but gates it only on
`HONDA_ODYSSEY_5G_MMR`; the source PR's ten-platform enablement is not carried. It adds the
80-message DBC and publishes the decoded bank through `RadarInterface` from physical bus 2. It does
not alter the Odyssey longitudinal CAN translation or its retained gas/brake domain candidate.

Full-rate replay confirms that the implementation parses the available bank rather than merely
passing synthetic tests. On route `0000003b--955515bf1c`, it produced 7,430 updates over 500.4 s
(14.85 Hz), no CAN errors, 5,100 point samples, and up to three points at the 95th percentile. On
the longer existing Alpha-Long route `00000025--2db306153b`, it produced 36,701 updates over
2,465.9 s (14.88 Hz), no CAN errors, 37,292 point samples, and 63 observed track identities. The
decoded ranges were 2.65-119.87 m on that route, with 99.7% of published samples marked measured.

This result changes the implementation verdict, not the source attribution. The decoded bank is
still received on the camera side of the split ACC-CAN, so it is structured camera-originated
object/fusion traffic sent toward the Bosch-A module, not a measurement list returned by the radar.
It may be useful as an independent OEM-camera perception source, but it must not be called raw Bosch
radar output without new physical-bus evidence.

There is also a planner-facing validation gap. Current `radard` can select any point within 1 m
lateral and 0.75-25 m longitudinal below 4 m/s without model confirmation, and it does not consume
the point's deprecated `measured` flag. Replaying route `00000025` found 4,331 decoder updates with
such a point, including 62 updates where the latest model lead was absent, stale, or below 0.5
probability. Those may be valid stationary-object observations, but replay cannot establish false-
positive safety or ride behavior. The arm therefore remains software-valid and road-unproven: use
an offroad/device integration check first, then a disengaged low-speed visualization drive, before
any engaged following or stop validation.

The first engaged route closes that road arm without promotion. Route
`00000043--a13083ebb4` ran the exact published pair, parent `b61fcf4fd329` and nested opendbc
`955bd74c3562`, for 11.8 logged minutes but only 2.55 engaged minutes / 1.96 engaged miles. The short
exposure is not a general decoder verdict, but it is sufficient to reject this branch for engaged
use because the driver reported worse gas/braking and the full-rate trace identifies the same
mechanism:

- `radarState.leadOne` was present for 97.8% and radar-marked for 87.3% of engaged samples; 11,313 of
  15,253 active planner samples selected `lead0`. Twenty of 25 physical brake-domain edges occurred
  while the selected lead was radar-marked.
- Selected-lead continuity changed sharply at the reported cycling. At 182.90 s the radar-marked
  lead was 65.4 m away at `vRel=-13.5 m/s` and the plan requested `-0.59 m/s2`; at 183.40 s the
  selected lead was no longer radar-marked, moved to 90.0 m at `vRel=+1.41 m/s`, and the plan
  requested `+0.09 m/s2`. At 185.25-185.35 s the selected lead changed from non-radar 73.1 m /
  `-1.74 m/s` to radar-marked 58.7 m / `-12.36 m/s` while the plan and `carControl` crossed gas and
  brake requests.
- The command path was mostly faithful but less clean than recent vision-only routes: planner to
  `carControl` RMS was `0.0328 m/s2`; overall request-to-wire RMS was `0.0250 m/s2`, with gas/brake
  domain RMS `0.0266/0.0372 m/s2` and no sustained sign disagreement. Achieved-response RMS versus
  `carControl` was `0.280 m/s2`.
- A source diff proved that nested commits `41aaf59ee6f2`, merge baseline `507559bc03ba`, and radar
  child `955bd74c3562` have identical Honda `carcontroller.py` and `hondacan.py`. After mapping that
  exact provenance, revalidation enabled the three-domain model and measured 18.18 s over 21
  brake-release-hold diagnostic events, longest 4.91 s. Their mean request remained negative at
  `-0.29 m/s2`, with zero sustained sign disagreement, so this is the retained domain following the
  changed request—not a radar-branch positive-request hold or new CAN-translation mechanism.
- The short route still produced 25 physical brake edges, peak 9/10 s, 3 direct gas-to-brake and 4
  direct brake-to-gas handoffs, and `0.489 m/s3` achieved jerk RMS versus `0.440 m/s3` commanded.
  That near-one amplification locates most of the felt harshness in the command sequence rather than
  a new Honda actuator-map error; the validator separately measured Honda bite on 9.3% of braking
  frames.
- Lateral remained a separate thin diagnostic: 2.6 active minutes, command/output p95
  `0.332/0.328`, command-following RMS `0.024`, actual-versus-desired lateral-acceleration RMS
  `0.040 m/s2`, and zero saturation, overrides, or steering faults. It adds no evidence to retain
  the custom 3840 arm and does not independently prove the 2560 restoration's road behavior.

The second engaged radar route `00000042--73aeb05783` ran the same published radar pair for 9.31
engaged minutes / 6.95 engaged miles. It measured 22 physical brake-domain edges, 3 brake-to-gas
handoffs above 5 m/s, 18 coast-to-gas re-entries (3 shorter than 1 s), 2 brake takeovers, and felt
jerk RMS `0.462 m/s3` versus `0.356 m/s3` commanded. Request-to-wire following remained numerically
close (`0.0098/0.0248 m/s2` gas/brake RMS), while Honda actuator bite appeared on 10.0% of braking
frames. This reinforces rejecting the radar arm for engaged use, but it is not a radar-only causal
comparison: the route also exercised the then-current low-speed brake-PID stack (`1,405` eligible
frames), and terrain/session effects are not controlled. Preserve it as supporting failure evidence,
not as permission to retune gas, brake, or the planner.

The branch changed only radar availability, the radar DBC, and `RadarInterface`; it did not change
Honda `carcontroller.py`. The first new divergence is therefore the camera-side object bank feeding
`radard`/lead selection and the resulting planner command, not direct gas/brake CAN translation.
Keep vision-only `ody-op` as the road baseline. Both `ody-op-radar` implementation branches are
deleted; retain this route/source record as failed historical evidence, and do not alter gasfactor,
brake thresholds, or command shaping to compensate for it.

### Asymmetric road-speed brake-command arm (2026-09-02)

The former `ody-op-onset` pair is integrated into `ody-op` as one bounded road candidate: parent
`a73515428b5c` and nested opendbc `871b98a64f6e` before the 2026-09-02 upstream merge. It changes
only downward moderate `ACCEL_COMMAND` steps while Odyssey's road-speed brake domain is selected.
The command can deepen by at most `0.06 m/s2` per 50 Hz Honda ACC command (`3.0 m/s3`), but easing
and release remain immediate, commands below `-1.5 m/s2` bypass the limiter, and low-speed stop
authority remains raw. Gas mapping, domain thresholds, lateral behavior, planner, and `longcontrol`
are unchanged.

The physical rationale is narrow: prior exact-source routes located some bite downstream of a
correct request/domain transition, and current Ford/Toyota ports demonstrate asymmetric brake or
ACC command-rate limits. This does not revive the rejected symmetric 2.0 m/s3 plus domain-hysteresis
stack, and those peer mechanisms do not prove that 3.0 m/s3 is correct for the Odyssey. Focused
rail/safety tests cover the ramp, exact steady state, immediate firm-brake bypass, low-speed raw
commands, release, mutual exclusion, and disengagement; the onset assertion is mutation-verified.
Frozen-input replay may establish only the changed command shape, never hydraulic timing or comfort.

Both new invariants are mutation-verified. Raising the downward limit from `3.0` to `30.0 m/s3`
made all four road-speed ramp subcases fail because the first `-0.60 m/s2` command was no longer
limited. Moving the firm-brake floor from `-1.5` to `-3.5 m/s2` made the panic test fail because a
`-2.0 m/s2` request was delayed to `-0.06 m/s2`; restoring the candidate source passes both tests.

Frozen-input replay over baseline route `00000068--bbbfad9947` processed 147,908 controller frames,
including 52,391 engaged frames. Candidate-versus-recorded wire RMS was `0.00845 m/s2`; candidate
request-to-wire RMS was `0.00486 m/s2` versus `0.00985 m/s2` for the resampled recording. The
windowed command-jerk maximum was effectively unchanged (`0.990` versus `0.993 m/s3`), with 15
detected onsets in each and 3,442 versus 3,446 deep-brake frames. That verifies a bounded command
delta and shows that this historical request stream only weakly exercises it; it is not evidence of
closed-loop comfort, onset timing, or improvement.

Eight newly pulled full-rate routes (`00000008--2d8415b010` through
`0000000f--8cf83efeea`) resolve to Sunnypilot `staging` parents `70bf4f1791cd`, `4d54539482d9`, or
`5345c80b8b3f`, with Alpha Long disabled and no nested opendbc provenance. They contain zero engaged
OpenPilot-longitudinal exposure, so none counts toward this arm. Route `00000009` has one isolated
steering-fault event; route `0000000e` records one `micd` crash; route `0000000f` peaks at 91 C and
supplies 9.72 s of stock-2560 high-authority lateral exposure with no steering faults. These are
separate software/device/lateral observations and do not authorize a lateral or longitudinal tune.

**Decision: CHANGE `ody-op` to carry this isolated arm for evaluation; road verdict pending.** The
road question is whether comparable moderate road-speed brake entries reduce downstream Honda onset
bite and achieved jerk without delayed braking, worse `aEgo` versus `carControl` tracking, longer
stops, or takeovers. Retire immediately for a safety or clear drivability regression, or after three
independent adequately exposed current-source routes without attributable improvement.

### First two asymmetric-onset road examples (2026-09-03)

Routes `00000010--2b60bf438c` and `00000011--dc727a0bb7` both resolve to the exact current source:
parent `678bfa0bc5dc`, nested opendbc `0bd54951753f`, clean `ody-op`, and Alpha Long enabled. A
source diff proves `871b98a64f6e..0bd54951753f` changes only comments in Honda longitudinal code;
the immediate no-limiter source is `b5b9f861aa18`. The validator now maps all three exact onset-arm
revisions to the retained `-0.30 m/s2` three-domain selector while excluding them from raw brake-
passthrough expectations. Changing the deployed hash in that map made
`test_domain_model_selects_exact_opendbc_source_semantics` fail; restoration passes all 36 focused
validator tests.

The independent command traces locate no new planner, domain, or transport divergence:

- Route 10 logged 38.0 minutes / 7.47 engaged minutes / 5.81 engaged miles. Route 11 logged 28.2 /
  8.72 minutes / 8.53 miles. Each supplied seven road-speed brake episodes and 11/7 wire onsets;
  both had zero managed-process crashes and zero rail saturation.
- Planner-to-`carControl` RMS was `0.0088/0.0068 m/s2`. Gas-domain request-to-wire RMS was
  `0.0081/0.0065 m/s2`, brake-domain RMS `0.0141/0.0139 m/s2`, and sustained sign disagreement was
  zero. Each produced 13 physical brake edges with peaks of 4/3 per 10 seconds and zero direct
  gas-to-brake handoffs. The retained domain selector, not the onset limiter, accounts for those
  domain results.
- Brake-domain achieved-response RMS was `0.206/0.251 m/s2`, with mean `aEgo-request`
  `-0.055/-0.160 m/s2`; Honda bite appeared on 4.8/8.7% of braking frames. Route-wide achieved jerk
  was `0.317/0.276 m/s3`, split to `0.453/0.345 m/s3` in brake. Route 10's seven brake takeovers and
  route 11's four did not occur within 1.5 seconds of a shaped fresh brake entry, so they are not
  attributable onset-arm regressions.

The arm had narrow but real exposure. On route 10, controller output withheld more than
`0.03 m/s2` from the raw request for 0.48 s across four fresh road-speed brake entries; route 11 had
0.24 s and one substantial fresh entry. The two largest started at 10.5 and 16.7 m/s: requests were
`-0.35/-0.48 m/s2`, the selected brake command began near `-0.03 m/s2`, and the ramp lasted
0.11/0.13 s. Neither event had a gas or brake pedal edge in the following two seconds. This is the
intended hydraulic-onset mechanism, but it is also measurable delayed braking that must earn a
closed-loop benefit.

Replaying the exact current controller reproduced the recorded command with `0.00885/0.00772 m/s2`
RMS. Replaying the immediate no-limiter source on the same frozen inputs showed no command-shape
benefit: route 10's candidate/no-limiter peak wire jerk was `1.720/1.705 m/s3`, and route 11's was
`1.262/1.019 m/s3`; p99 and onset counts were effectively unchanged. Forceful edge counts fell by
one on each fixed-input replay only because the ramp held the first command shallower, which is not
a closed-loop transition prediction or comfort improvement. Five nearest historical brake-entry
matches conditioned on speed, request, pitch, lead state, and planner source were mixed: two favored
the arm, two were worse, and one was effectively equal. Route-level achieved onset jerk medians
`-1.35/-0.57 m/s3` and 80%-depth times `0.60/2.27 s` likewise do not establish a repeatable gain.

The gas domain separately supplies the first ordinary-road result for the upstream-direct mapping,
which the onset arm cannot affect. Routes 10/11 provided 372.6/460.7 clean gas-domain seconds,
achieved RMS `0.216/0.200 m/s2`, material-command under-response medians `+0.096/+0.083 m/s2`, and
gas jerk `0.302/0.267 m/s3`. Against routes 61-64 and 68, 348 one-second samples matched on command,
speed, pitch, and lead state had current-minus-prior achieved-error median/mean
`-0.010/-0.007 m/s2`; route 10 was slightly worse (`+0.007` mean) and route 11 better (`-0.021`).
There were no sub-second coast-to-gas re-entries. **KEEP upstream direct gas mapping**: it is at
least as smooth and accurate as the retained custom mapping in this exposure and removes fork-only
calibration.

Lateral remains independent and stock-2560. Request-to-controller-output RMS was `0.0525/0.0511`;
after Honda sign normalization, output-to-CAN RMS was `0.00021/0.00021`. Actual-versus-desired
lateral-acceleration RMS was `0.068/0.083 m/s2`, with 9.80/10.65 high-authority seconds. Route 11's
single active steering-fault frame occurred at the stock 2560 cap while the driver was overriding
the wheel; route 10 had none. **KEEP stock lateral**; neither route supports reopening authority.

Hardware is separate: route 11 began at 70 C, had a 72 C median, and peaked at 87 C. It stayed below
the 94 C on-road critical threshold, but three of the latest five cold starts were at or above 70 C;
remove or shade the device while parked in this heat.

**Onset decision after examples 1 and 2: KEEP only for the final bounded road example, not as a
promotion.** Neither route shows attributable improvement, but neither has an onset-adjacent safety
or driver-intervention regression. The third route must contain several fresh moderate road-speed
brake entries, preferably both flat and downhill, and answer whether achieved onset bite/jerk falls
without extra response delay or stopping distance. If it does not, retire the rate limiter and
restore raw `ACCEL_COMMAND`; do not add another threshold or shaper.

### Final asymmetric-onset screen and 2026-09-04 driver notes

Ten newly pulled private full-rate routes, `00000012--9ea63a15e3` through
`0000001b--3ae9413062`, all resolve from their own logs to clean parent `5838b4b0c5d0`, nested
opendbc `0bd54951753f`, branch `ody-op`, and Alpha Long enabled. Routes `12`, `19`, and `1a` supply
71.78/11.77/58.78 engaged minutes; routes `14`-`18` and `1b` have zero engagement, and sparse route
`13` has no usable car-control stream. The no-engagement routes are provenance and device context,
not lateral or longitudinal evidence.

The driver-note clock times map through the last NTP-corrected `clocks` sample, not the device's
unsynchronised boot RTC:

- **08:38, route 12 at 4761.5--4769.0 s, rolling through the stop.** A lead-sourced approach progressed
  from `-0.38` to `-2.29 m/s2`; planner, `carControl`, and CAN agreed. Below 2 mph the request relaxed
  from `-0.49` to `-0.13 m/s2` while both planner and model `shouldStop` remained false. The Odyssey
  low-speed brake domain stayed selected, but `aEgo` reached zero and the van remained near 1 mph
  until the driver braked; `shouldStop` became true only afterward. First divergence is the upstream
  stop decision, with downstream Honda response to the relaxed command as a secondary contributor.
  The road-speed onset limiter is bypassed at this speed and cannot explain the roll.
- **09:43, route 12 at 8635.7 s.** A tracked lead moved from roughly 93 m to 43 m while closing, the
  planner selected `lead0` and requested about `-0.64 m/s2`, and `carControl`/CAN followed. Honda
  reached about `-0.90 m/s2` and speed fell from 77 to 62 mph before the planner requested up to
  `+0.76 m/s2` to recover. The limiter changed brake entry by only `0.014 m/s2`. The braking request
  originated upstream; the excess achieved deceleration is downstream of CAN.
- **09:45, route 12 at 8755.7 s.** No friction-brake request occurred in the noted window. The lead
  planner later relaxed gas/coasted at about `-0.21 m/s2` on a positive-grade section; achieved
  deceleration reached about `-0.44 m/s2` and speed fell toward 69 mph before a positive recovery
  request. This is a planner-plus-plant response event, not a brake-domain or onset event.
- **12:55, route 19 at 339.6 s.** The lead planner stepped from `-0.17` to `-0.53 m/s2`; request,
  controller output, and CAN agreed, then Honda reached `-0.83 m/s2` as the request relaxed near
  zero. A similar lead-sourced cycle had occurred about 36 s earlier. The limiter changed the entry
  by only `0.007 m/s2`, so it neither caused nor improved the reported behavior.
- **13:34-13:52, route 1a.** Experimental became true at 13:33:43 and false at 13:51:50. On 4-8%
  positive-grade sections, the e2e planner repeatedly requested only about `-0.09..+0.15 m/s2` while
  speed fell as much as 10 mph below set. The port carried those requests to CAN. Near the end the
  driver used gas and disengaged; after Experimental was disabled, ordinary cruise requested up to
  `+0.74 m/s2`. The dominant terrible-uphill divergence is Experimental planning. Current gas
  mapping also shows ordinary downstream grade under-response, but that is present outside
  Experimental and does not justify restoring the retired learner or feedforward from this event.
- **14:12-14:13, route 1a.** Two `lead0` brake/recovery cycles dropped roughly 71 to 62 mph and 66
  to 61 mph. Planner-to-`carControl` and request-to-CAN remained aligned; the limiter changed their
  entries by only `0.002` and `0.014 m/s2`. These are upstream lead requests with downstream Honda
  amplification, not invented braking in the port.

Across routes 12/19/1a, planner-to-`carControl` RMS was `0.0053/0.0055/0.0046 m/s2`; gas-domain
request-to-wire RMS was `0.0054/0.0054/0.0049`, brake-domain RMS was
`0.0127/0.0076/0.0193`, and sustained sign disagreement was zero. They contained 18/12/17 brake
episodes and 33/21/33 physical edges. Brake-domain achieved RMS was `0.245/0.227/0.230 m/s2`, with
mean `aEgo-request` `-0.085/-0.134/-0.142`; achieved brake jerk RMS was
`0.422/0.347/0.286 m/s3`. Numeric transport was correct, while Honda commonly amplified braking.

The same routes add 4,133.6/612.1/3,427.8 seconds of gas-domain exposure. Achieved RMS was
`0.143/0.200/0.123 m/s2`, and material-command under-response medians were
`+0.085/+0.113/+0.069 m/s2` on 87.3/84.3/79.8% of samples. **KEEP upstream direct gas mapping for
now**: this is a repeatable downstream residual, but the reported uphill failure first diverged in
Experimental planning and there is no isolated mapping A/B here. Reopen gas calibration only with a
non-Experimental, command/speed/grade-controlled comparison.

Lateral remains independent. Routes 12/19/1a had request-to-controller-output RMS
`0.0347/0.0352/0.0250`; controller-output-to-CAN RMS after Honda sign normalization was
`0.000209/0.000210/0.000210`, and actual-versus-desired lateral-acceleration RMS was
`0.070/0.092/0.082 m/s2`. Routes 12/1a supplied 9.35/5.84 high-authority seconds at the stock 2560
cap with RMS `0.356/0.445`. Route 12's three temporary steering-fault events all occurred under a
driver steering override at 2511-2560 counts; actual lateral acceleration remained close to desired
at those instants. **KEEP stock-2560 lateral**; these routes show no isolated lateral mechanism to
change.

Exact fixed-input replay reproduced the deployed controller with `0.00449/0.00564/0.00377 m/s2`
RMS on routes 12/19/1a. Candidate versus raw-no-limiter peak command jerk was
`1.398/1.393`, `0.706/0.735`, and `1.297/0.984 m/s3`; p99 was effectively unchanged. The new routes
contained real shaped exposure, including four fresh route-1a entries that initially withheld
`0.270-0.507 m/s2`, but no repeatable closed-loop benefit appeared and the reported events were
almost untouched. **Final onset decision: RETIRE.** Route 12 is the third independent adequately
exposed example without attributable improvement after routes 10/11; routes 19/1a independently
corroborate the rejection. Nested commit `31a1776c7bf4` removes only the limiter constants/state and
restores raw clipped `ACCEL_COMMAND`; the retained three-domain selector, direct gas map, low-speed
domains, and lateral behavior are unchanged. The focused raw-command rail check was mutation-
verified by reintroducing a shaped entry and observing all four road/descent/low-speed/stopping
subcases fail.

With the onset arm retired, that post-deployment question is closed. Current investigation is
planner-side stopped-lead intent plus independent low-speed actuator-response screening; those
mechanisms remain separate from the retained raw Honda command path. New logs can add evidence to
either stream, while replay remains command-shape evidence rather than a road result.

### Unroaded combined agile package audit (2026-09-04)

Nested commit `4dc05c99cf7a` briefly added three simultaneous Odyssey command changes: positive-gas
 pitch feedforward, a `0.85` moderate road-speed brake scale, and a `-0.35 m/s2` crawl floor below
 `2 m/s`. The package had no route exposure, no isolated comparison, and no attributable first-
 divergence evidence. Existing route 1a uphill failures first diverged in Experimental planning;
 existing route 12 stop-roll evidence first diverged in upstream `shouldStop`; and the Honda
 `GAS_COMMAND` field is opaque/unitless. The peer-brand review permits pitch compensation only on
 the real `ACCEL_COMMAND` brake side, not by inflating Honda gas counts.

 **Decision: RETIRE the combined package from active `ody-op`.** Nested `825642c421` is an explicit
 revert to the raw-command baseline; parent validator and rail expectations were reverted with it.
 The original package remains reachable in backup refs `backup/ody-op-agile-20260904-4dc` and
 `backup/ody-op-agile-upstream-merge-20260904-904b6027cb` for historical comparison, but it is not
 a road candidate. Any future brake-scale or low-speed authority work must be split into its own
 candidate with a first-divergence hypothesis, mutation check, replay shape check, and closed-loop
exposure.

### Upstream model and baseline refresh (2026-09-05)

After the previous sync, `upstream/master` advanced to `675ff569818f` (`tools: add op docs command`);
the change is documentation tooling only and was cherry-picked into `ody-op` as `287eaddf86`.
The current `driving_supercombo.onnx` blob is `f0672eab4856`, identical on the route-12 parent,
current `ody-op`, and `upstream/master`. The latest small driving-model change remains
`93f5aa469a` (Rebellious Hope), which was reverted by `b361e952c9` on 2026-08-04; no newer small
model release is present through `675ff569818f`. Model selection therefore supplies no new
candidate for the stopped-lead symptom; keep the planner-side experiment isolated from model and
opendbc changes.

The nested-source audit resolves the same invariant: `upstream/master` at `675ff569818f` pins
public opendbc `b4ef5e1cf406`, while `opendbc_repo` `825642c4218b` is a descendant of that exact
pin with only the retained Odyssey command-domain delta. Standalone opendbc `upstream/master`
currently points to `3e92d1121295`, but it is newer than the parent pin and must not be advanced
independently; doing so risks the parent/opendbc schema mismatch documented in `AGENTS.md`.

### Route 0000001c--ca2ae44633 provenance (2026-09-05)

The newly pulled 55-segment route resolves to parent `cc87e07f4a3b` (`Odyssey: retire unproven
brake onset limiter`), nested opendbc `31a1776c7bf4` (`honda: retire unproven Odyssey brake onset
limiter`), branch `ody-op`, and Alpha Long enabled. It contains 24.9 logged minutes but zero
engaged minutes in the initial pull, so that first validator row had no usable lateral or
longitudinal command exposure. The complete local reread (all 55 numeric-order segments) corrected
the row to 50.0 logged minutes
and 2.3 engaged minutes. It remains thin context: only gas-domain exposure was usable, with no
brake-domain or candidate stop-intent exposure, and it remains excluded from pooled decisions.

### Low-speed stopped-lead stop-intent candidate screen (2026-09-04)

The next candidate is planner-side and remains inactive on `ody-op`. Symptom: on route 12's
08:38 stopped-lead approach, the request and Honda wire stayed aligned while the request relaxed
near 1 mph and both planner and model `shouldStop` stayed false. The first repeatable divergence is
therefore the planner's stop intent, not Honda CAN translation. The physical hypothesis is that a
near-stopped lead at a short, closing gap while the ego vehicle is already crawling should enter
the generic stopping state before the current `vEgo < 0.3 m/s` gate, while a slowly moving lead
must remain a normal following target.

The provisional replay-screen predicate is deliberately conservative and diagnostic only:
`vEgo < 1.0 m/s`, `aTarget < -0.05 m/s2`, a present lead with `vLead < 0.35 m/s`,
`vRel < 0`, and `dRel < 6.5 m`. It would set stop intent; it would not alter the raw
`ACCEL_COMMAND` or Honda domain selection. This follows the existing upstream planner/MPC lead
trajectory and `LongCtrlState.stopping` mechanisms rather than adding a Honda brake floor. Baseline
is current raw-command `ody-op`; the candidate lives on a temporary child and rolls back by deleting
the child without changing the parent or nested gitlink.

The expected downstream effect is also existing Honda plumbing: `shouldStop` moves `longcontrol`
into `LongCtrlState.stopping`, Honda's controller advances its existing `stopping_counter`, and
`hondacan.create_acc_commands()` emits the established `STANDSTILL=1`/`STANDSTILL_RELEASE=0`
state while retaining the same raw `ACCEL_COMMAND` and gas/brake-domain selection. No new Honda CAN
field or brake shaping is introduced by this candidate.
A direct pack/decode check against nested `825642c421` confirms the boundary: with the same active
`ACCEL_COMMAND=-0.50 m/s2`, `BRAKE_REQUEST=1`, and inactive `GAS_COMMAND`, changing
`stopping_counter` from `0` to `1` changes only `STANDSTILL` from `0` to `1` and
`STANDSTILL_RELEASE` from `1` to `0`. This is software command-shape evidence, not a claim about
Honda's closed-loop response.

The raw route-12 segment-79 trace makes the ownership boundary concrete. At the provisional trigger
near `53267.70 s` (route-relative `4766.79 s`), baseline `longitudinalPlan.aTarget` and
`carControl.actuators.accel` were about `-0.20 m/s2`, decoded `ACCEL_COMMAND` was `-0.21 m/s2`,
`BRAKE_REQUEST=1`, and `STANDSTILL=0`/`STANDSTILL_RELEASE=1`. The planner then relaxed toward
`-0.17 m/s2` while the controller stayed in PID; `aEgo` became positive and `vEgo` rose to about
`0.57 m/s`. The driver brake at `53269.936 s` disabled longitudinal control, while generic
`shouldStop` did not become true until about `53271.10 s`, after the takeover. This is first a
planner stop-intent miss, with Honda response to the relaxed request as a secondary contributor;
the candidate's unroaded counterfactual would enter the existing stopping/standstill path earlier.

Frozen-input counterfactual command shaping, holding the candidate stop intent through this window,
uses the recorded `-0.21 m/s2` output as the stopping-state initial value and the route's
`CP.stopAccel=-2.00 m/s2`. The existing `LongControl` stopping ramp reaches approximately
`-0.71/-1.21/-1.71/-2.00 m/s2` at 0.5/1.0/1.5/2.0 s; Honda decoding follows those values exactly
with `BRAKE_REQUEST=1`, inactive gas, and `STANDSTILL=1`/`STANDSTILL_RELEASE=0`. This verifies
counterfactual command shape and domain selection only; it uses frozen `aEgo` and cannot predict
the vehicle's closed-loop stop distance, jerk, or actuator response.

Applying the predicate with the planner's actual lead selection (`leadOne` for `lead0`, `leadTwo`
for `lead1`/E2E) to the raw full-rate route messages found seven candidate episodes: one each on
routes 10, 12, and 38, two on route 44, and two on route 6d. Five reached the recorded generic
`shouldStop` within four seconds; the other two reached it after about 4.35 s and 6.65 s. The
candidate windows began at roughly 0.85-1.00 m/s (1.9-2.2 mph), so this is not a sub-1.6-mph
screen. These are useful exposure checks, not counterfactual or closed-loop proof: frozen logs
cannot show whether an earlier stop intent would false-stop a moving lead or improve the gap.
At the fifth consecutive candidate frame (about 0.20 s into each window), the frozen-input screen
had ego speed near 1.00 m/s, gaps of 4.43-6.31 m, model probabilities of 0.999-1.000, and
closing time-to-collision of 5.5-29.5 s. This bounds the candidate's initial trigger context for
the controlled arm; it does not establish that the vehicle will stop safely on-road.
On the recorded baseline, driver brake/longitudinal disengagement followed the fifth-frame trigger
in five of the seven windows (about 0.73, 2.23, 2.39, 5.89, and 2.90 s later on routes 10, 12,
44-segment-9, 44-segment-12, and 6d-segment-6); routes 38 and 6d-segment-5 had no such intervention
before generic stop intent. These are baseline exposure markers for the controlled arm, not a
counterfactual candidate benefit claim.

Success requires mutation-verified predicate tests, planner replay showing earlier stop intent with
unchanged request-to-wire/domain fidelity, then controlled stopped-lead and at least three
independent ordinary-road examples with complete stop, no false stop on a moving lead, no added
onset/lurch/pulsing, and no driver takeover. Reject immediately for a false stop, late or unsafe
gap, clear drivability regression, or any wire/domain mismatch; otherwise retire after three
adequately exposed examples without attributable improvement. No production or device change is
authorized by this screen.

### Upstream generic stopping PR screen (2026-09-05)

OpenPilot PR [#38658](https://github.com/commaai/openpilot/pull/38658) was inspected as a
possible stopping precedent, but it is not a Honda-port change. Its current tip
`1aa815ed0851` changes the generic `shouldStop` speed gate from `0.30` to `0.25 m/s` and changes
the `LongControl` stopping ramp from `1.0` to `0.3 m/s3`; its replay report shows one changed
segment and 65 unchanged segments, with a Corolla road report. The speed-gate tightening does not
address the Odyssey's earlier stopped-lead trigger, while the slower ramp trades away stop
authority.

For the Odyssey stopped-lead screen's recorded initial output of `-0.21 m/s2` and
`CP.stopAccel=-2.00 m/s2`, the current ramp reaches approximately `-0.71/-1.21/-1.71/-2.00`
at `0.5/1.0/1.5/1.79 s`. The PR ramp would reach only `-0.36/-0.51/-0.66/-0.81` at
`0.5/1.0/1.5/2.0 s` and would not reach `-2.00` within 2.5 s. This is frozen command-shape
evidence, not a vehicle-response result, but it makes the tradeoff material for a car whose
reported failure is rolling through a lead stop. **Decision: do not import #38658 into the
Odyssey arm.** Keep the existing stopping ramp and evaluate planner stop intent independently;
reopen the generic ramp only with matched Odyssey stopped-lead stop-distance, jerk, and
moving-lead-release evidence.

The temporary child `tmp/ody-op-stop-intent-20260904` added a five-frame persistence gate after the
first planner replay exposed a one-frame true/false/true flicker. Mutation testing made the focused
test fail when the persistence comparison changed from `>= 5` to `> 5`. On route 12 segment 79,
baseline plannerd replay produced 319 `shouldStop` frames and first asserted at 4770.193 s; the
candidate produced 387 frames and first asserted at 4766.792 s, about 3.4 s earlier, with no
intermediate flicker. The candidate did not change `aTarget`; this planner-only replay does not
exercise `card` or Honda CAN generation. Both replays produced 1,200 plans from 2,400 process
outputs; the repeated initial MPC reset messages were the same on both arms.

Three additional segment A/B screens were consistent with earlier intent: route 44 candidate
replayed 870 stop frames and first asserted at 540.602 s versus 810/543.603 s on baseline; route
6d replayed 420 versus 337 and first asserted at 311.309 s versus 315.459 s, with the same release
at 332.306 s; route 38 replayed 396 versus 331 and first asserted at 98.804 s versus 102.054 s.
The route-38 segment emitted identical intermittent SQP solver-status-3 warnings on both arms, so
it is only a software screen. The repeated later route-44 transitions were identical, suggesting
the candidate changes the early lead-stop state rather than general planner timing. None of these
replays is closed-loop evidence or permission to deploy.

The fixed-input Honda controller replay over the adjacent route-12 stop segment (using recorded
`carControl`, so it does not apply the candidate's counterfactual stopping state) had
request-to-wire RMS `0.00594 m/s2`, replay-vs-recorded wire RMS `0.00968 m/s2`, with two open-loop
brake-domain flips and no forceful flip. This validates baseline command/domain translation only;
it cannot predict the candidate's earlier `STANDSTILL` state or vehicle response. **KEEP the
candidate as an unroaded child for controlled exposure; keep `ody-op` unchanged and do not claim
stopping improvement until closed-loop evidence exists.**

Route `0000001d--2e324ec2ce` (2026-09-05) is a new full-rate baseline exposure, not a stop-intent
candidate drive. Its exact source was parent `784b05ce670a`, nested opendbc `825642c4218b`, clean
`ody-op`, Alpha Long enabled, and Experimental mode off. It contained 18.5 engaged minutes and
24 driver brake presses, of which 8 were attributed takeovers. The eight takeover contexts were
all high-speed cruise/lead approaches (about 18.9-69.4 mph); none met the candidate's low-speed,
close, near-stopped-lead screen. The route still records 73 physical brake-domain edges (peak 8
per 10 s; 18/min on descents), felt-jerk RMS `0.376 m/s3` versus commanded `0.221`, and a PID
stop-lurch readout, but those are baseline downhill/actuator symptoms rather than evidence for
widening the stopped-lead predicate. Keep the stop-intent child unchanged and classify this route
as baseline context; it supplies no closed-loop candidate example.

An additional frozen-input screen of route `0000001d` found one relevant baseline context at about
route-relative `1207.7-1211.5 s`. The car remained engaged with no driver brake, `carControl` and
decoded Honda wire stayed aligned near `-0.19..-0.18 m/s2` in the brake domain, and `aEgo` remained
near zero while a high-confidence lead moved from about `0.30` to `0.15 m/s` at a gap shrinking
from `6.3` to `4.9 m`. The five-frame candidate predicate would have become true while ego speed
was below `0.86 m/s` and generic `shouldStop` was still false; the recorded planner then relaxed
through zero as the lead moved and the vehicle accelerated. This is not a candidate road result,
because the route ran on baseline, but it is a required false-stop/early-standstill safety check:
the current `vLead < 0.35` screen may also match a slowly moving lead. Do not broaden the predicate
or claim benefit from this replay; require a controlled candidate approach with human override and
compare against the route-12 stopped-lead context before changing thresholds.

The lead-acceleration field does not separate the contexts cleanly: route 1d had `aLeadK` near
`-0.03 m/s2` before the lead accelerated, while route 12 also passed through near-zero `aLeadK`
as its lead settled. Do not add an `aLeadK` gate from these frozen inputs alone.

The same route's downhill brake-domain cycling remains upstream-request driven. Representative
edges near route-relative `669.33-678.18 s` had no lead, `cruise` plan source, and
`allowThrottle=true`: `longitudinalPlan`/`carControl` swung from about `-0.33` to `+0.01 m/s2`
and back, while decoded `ACCEL_COMMAND` followed at about `-0.33` to `+0.01 m/s2` with the
corresponding `BRAKE_REQUEST` transitions. This is command/domain fidelity through the Honda port,
not a carControl-to-CAN divergence; do not use opendbc shaping to hide the upstream cruise pulse.

Deployment decision: after repeated inventory checks found no post-deployment route, and the frozen
route-1d screen raised a moving-lead early-standstill safety question, remove
`tmp/ody-op-stop-intent-current-20260905` from active device behavior. Preserve its published commits,
tests, replay results, and safety screen for a deliberate supervised re-deploy; this is not a
three-route road retirement or a claim that the mechanism failed closed-loop. The device is restored
to the known-good `ody-op @ 407f780a7c` with nested opendbc `825642c4218b`, Alpha Long enabled, and
Experimental mode disabled.

Route `0000001d` also supplies a lateral boundary. Eleven high-authority windows (27.96 s total)
hit exactly `+/-2560` CAN counts with normalized lateral request/output at `+/-1.0`, no steering
faults, and no request-to-wire mismatch. Actual-versus-desired lateral acceleration error ranged
from roughly `0.60 m/s2` in short transients to near zero during sustained high steer. The command
is therefore faithfully reaching the Honda wire; this route does not justify extending the stock
2560 map or changing opendbc. Reopen steering authority only with a repeatable matched-road
vehicle-response symptom and an isolated comparison.

### Routes 0000001e/0000001f baseline stop-intent exposure (2026-09-05)

The next two full-rate routes were both recorded on the clean baseline: parent `400cfefaaa8e`,
nested opendbc `825642c4218b`, branch `ody-op`, current driving model `f0672eab4856`, Alpha Long
enabled, and Experimental mode disabled. Route `0000001e--bce126e36c` supplied 10.2 engaged
minutes; route `0000001f--51e2cb8cb9` supplied 5.4 engaged minutes and is thin context. Both routes
carried the requested acceleration through Honda's wire (request-to-wire RMS `0.0066`/`0.0076`
m/s2, no sustained sign disagreement). The validator nevertheless flagged five of 32 brake
presses as takeovers on route 1e and two of 15 on route 1f, plus 22/26 physical brake-domain
edges with peaks of 5/9 per 10 seconds. These are baseline observations, not candidate-arm
exposure.

Route 1e contains two source-selected, close-lead approaches that meet the unroaded stopped-lead
screen (`vEgo < 1.0`, negative request below `-0.05`, model probability above `0.9`,
`vLead < 0.35`, closing `vRel < 0`, and gap below 6.5 m). The first runs from about
2320.00--2323.58 s: ego speed falls from 0.98 to 0.40 m/s while the request and decoded wire
relax from roughly `-1.04` to `-0.13 m/s2`; generic `shouldStop` appears only intermittently near
0.30 m/s, and the driver presses the brake at 2323.59 s while still engaged. The second runs
about 2376.63--2381.92 s: the vehicle remains near 0.30 m/s for several seconds at a 4--5 m gap
with request about `-0.12 m/s2` and generic `shouldStop` false most of the time, then the lead
accelerates and the request becomes positive. The planner and Honda translation remain numerically
aligned in both windows, so the repeatable first divergence is stop intent, not opendbc encoding.

Applying the current candidate predicate to the recorded inputs would assert its five-frame
intent around 2320.20 s and 2376.83 s, well before the intermittent generic stop flag. This is a
useful baseline exposure marker and a plausible explanation for the route-1e low-speed takeover,
but it is not counterfactual vehicle evidence: the route ran on baseline and cannot show whether
the existing stopping ramp would have avoided the takeover or produced an unwanted hold.

Route 1f supplies the required moving-lead safety counterexample. Its candidate predicate is true
for about 151.84--152.44 s while ego speed falls through 1.0--0.86 m/s, the gap is about 6.0 m,
and the lead accelerates from roughly 0.09 to 0.31 m/s; by 152.64 s the lead is at 0.49 m/s and
the closing speed has nearly disappeared, after which the request turns positive and the car
accelerates. No driver takeover occurs in this low-speed window, but a candidate stop state would
briefly overlap the lead's release. This confirms that the current bounds do not distinguish a
settling stopped lead from a lead about to move. Do not tighten or broaden the predicate from this
frozen input alone; use it to require a supervised candidate route with both stationary-lead and
moving-lead release cases.

The same routes also confirm that the high-speed downhill burst is upstream-request driven. The
representative transitions on both routes occur with `cruise` source, no meaningful stop intent,
and request oscillation around the `-0.30` Honda brake-domain split; the decoded `ACCEL_COMMAND`
follows the request and the domain changes with it. Keep the `-0.30` command-domain rule and do
not use these edges to justify an opendbc brake threshold or a stop-intent change.

**Decision: KEEP the stopped-lead candidate as an inactive child for supervised exposure; keep
`ody-op` unchanged.** The new route-1e windows strengthen the planner-side symptom and supply a
likely benefit case, while route 1f preserves the moving-lead safety concern. No production or
device change is authorized by these baseline routes. Candidate promotion still requires mutation
tests, planner/CAN replay, and closed-loop stationary-lead and moving-lead-release evidence.

### Upstream refresh after routes 1e/1f (2026-09-05)

`upstream/master` advanced from `675ff569818f` to `0ec3a082c7`. The new commits only change
`tools/op.sh` (Linux host detection, vendored Git-LFS configuration, and the corresponding revert/
reapply sequence); they do not change the longitudinal planner, `longcontrol`, Honda CAN
translation, or the driving model. The upstream driving-model blob remains `f0672eab4856`, and
the latest small-model release remains `93f5aa469a`, reverted by `b361e952c9`; no newer model
release is available. Standalone opendbc `upstream/master` remains `3e92d1121295`, while the
OpenPilot parent still pins public opendbc `b4ef5e1cf406`; no new Honda stopping or peer-brand
mechanism appeared after that pin. The five host-tool commits are now merged into `ody-op` at
parent merge `c4fce9bf05`, retaining the local memory-safe `op.sh switch` fetch/submodule limits;
no Honda or deployed stop-intent behavior changed.
The validator now maps nested `825642c4218b` to the retained raw three-domain Odyssey selector at
the `-0.30 m/s2` road-speed entry, so current baseline rows retain their domain attribution instead
of being reported as unmapped.

### Baseline brake-response bias screen (2026-09-05)

To decide whether the observed stop lurch warrants a separate brake-response arm, the full-rate
baseline routes were screened with zero-order-held Honda domains. Eligible samples were engaged,
`BRAKE_REQUEST=1`, negative request below `-0.03 m/s2`, finite `aEgo`, and no driver brake. The
diagnostic error is `aEgo - carControl.actuators.accel`; negative values mean the vehicle achieved
more deceleration than requested, while positive values mean less. This is an offline actuator
screen, not a closed-loop tuning result.

The route-level medians do not identify a stable global gain or offset: route 1d was `-0.074`,
route 1e `+0.024`, route 1f `-0.065`, route 68 `-0.099`, route 64 `-0.022`, and route 44
`-0.045 m/s2`. Command-magnitude bins also change sign within routes. At speeds below 1 m/s,
the same baseline was usually less decelerating than requested (route 1d `+0.098`, route 1e
`+0.133` in the 0--0.5 m/s bin, route 1f `+0.185`), while the route-1e stop-lurch readout at
1.18 m/s was a short transient with `aEgo=-1.64` against a `-1.19` wire request. The route-1f
readout at 1.36 m/s was only `-0.13 m/s2` extra. These opposite signs across speed, command,
terrain, and episode state are inconsistent with a safe global brake scale or fixed offset.

The command boundary itself remains clean in the same samples: request-to-wire RMS was
`0.0066--0.0137 m/s2`, with no sustained sign disagreement. Therefore a brake mapping change
would trade under-braking for over-braking in different contexts without correcting the planner's
late stop intent. This also matches peer-brand precedent: Hyundai sends the raw acceleration
request with a separate stop bit, and Toyota's additional PCM ramp is specific to its internal
cruise controller rather than a Honda `ACCEL_COMMAND` scale.

**Decision: RETAIN no new brake-response tuning arm.** Keep the raw Honda acceleration command,
the existing `-0.30` domain entry, and the stopped-lead planner child independently. Reopen brake
actuator tuning only after a controlled candidate route repeatedly shows the same post-wire
over/under-response under matched speed, request, and terrain; then test one bounded, upstream-style
mechanism with stationary-lead and no-lead safety exposure.

### Repeated low-speed brake-response screen (2026-09-05)

The baseline bias result has one narrower signal worth carrying into the next road question. Using
the same zero-order-held mask (`longActive`, `BRAKE_REQUEST=1`, no driver brake, request below
`-0.03 m/s2`, finite `aEgo`), the low-speed portions below `1.0 m/s` repeatedly measured a positive
`aEgo - carControl.actuators.accel` residual, i.e. less deceleration than requested. The exposed
segments were:

- Route `0000001d--2e324ec2ce`, parent `784b05ce670a`, nested `825642c4218b`: 5.53 s at
  `1206.53--1212.06`, median speed `0.75 m/s`, median request `-0.193 m/s2`, median residual
  `+0.089 m/s2`.
- Route `0000001e--bce126e36c`, parent `400cfefaaa8e`, nested `825642c4218b`: 3.58 s at
  `2320.00--2323.58` (median residual `+0.155 m/s2`) and 5.63 s at `2376.63--2382.27`
  (median residual `+0.122 m/s2`). The first ended in a driver brake, so it is an exposure marker,
  not a candidate result.
- Route `0000001f--51e2cb8cb9`, parent `400cfefaaa8e`, nested `825642c4218b`: 1.29 s at
  `151.84--153.14`, median speed `0.85 m/s`, median request `-0.344 m/s2`, median residual
  `+0.185 m/s2`; the lead was accelerating during this window, so it is a moving-lead safety
  counterexample as well as a thin response sample.

This recurrence is stronger than a single lurch, but it does not identify a safe global brake gain:
the same baseline over-braked in the separate route-1e `1.18 m/s` lurch, and the route-level and
command-magnitude residuals change sign. The low-speed residual may also include filtered/quantized
`aEgo` near standstill. A supplemental PID or brake scale would therefore alter the requested
`ACCEL_COMMAND` before a controlled test proves that the post-wire plant error is repeatable.

**Decision: KEEP the raw low-speed command and existing brake domain; do not create a production
brake-tuning arm from this screen.** Treat these segments as the minimum exposure for a future
isolated comparison: stationary-lead and no-lead crawl stops, matched request/speed/grade, and a
moving-lead release case. The inactive stopped-lead planner candidate remains the narrower way to
test the route-1e stop-intent symptom without adding an unverified Honda brake correction.

### Low-speed residual derivative cross-check and bounded trim replay (2026-09-05)

The low-speed residual was cross-checked against a finite-difference derivative of `vEgo` on the
same carControl grid, with a 25-sample (~0.25 s) moving average. This is still an offline screen,
but it tests whether the positive `aEgo - request` residual is only a standstill-filter artifact.
The median residuals were:

- Route `0000001d--2e324ec2ce` (parent `784b05ce670a`, nested `825642c4218b`): `+0.089 m/s2`
  from `aEgo - request` versus `+0.094 m/s2` from `dvEgo/dt - request` over 5.53 s; the two
  acceleration estimates differed by only `+0.001 m/s2`.
- Route `0000001e--bce126e36c` (parent `400cfefaaa8e`, nested `825642c4218b`): `+0.128` versus
  `+0.142 m/s2` over 9.23 s across the two low-speed segments. Segment medians were
  `+0.155/+0.122` from `aEgo` and `+0.185/+0.128` from the derivative.
- Route `0000001f--51e2cb8cb9` (parent `400cfefaaa8e`, nested `825642c4218b`): `+0.185` versus
  `+0.214 m/s2` over 1.30 s. Its accelerating lead makes it a safety counterexample, not a tuning
  result.

This supports a real low-speed response deficit in these episodes, while the sign-changing
route-level and 1.18 m/s stop-lurch residuals still rule out a global gain or offset. A temporary
command-shape candidate was therefore screened but not retained: subtract `0.10 m/s2` only when
the upstream state was `stopping`, `vEgo < 1.0 m/s`, no driver brake was pressed, and the raw request
was in `[-0.35, -0.03)`. A focused test passed, then failed after deliberate mutation, proving the
guard; the source was restored afterward. Exact-route replay changed 38 frames (0.38 s) on route
`0000001e`, and zero frames on routes `0000001d`/`0000001f`; route-1e replay request-error RMS
rose from `0.0077` baseline to `0.0085` because the candidate intentionally changes `ACCEL_COMMAND`.
Jerk and domain-edge shape were effectively unchanged in frozen input. This is not closed-loop
evidence and does not justify deployment.

**Decision: keep the production baseline unchanged; change the next road question to a supervised
low-speed stopping-trim screen only if a route deliberately exercises stationary-lead and no-lead
crawl stops, plus a moving-lead release.** Reject the trim for any false stop, extra onset bite,
late release, intervention, or command-domain mismatch; otherwise compare achieved acceleration,
stop distance, jerk, and request-to-wire fidelity before considering promotion.

### Low-speed sample lead-context safety audit (2026-09-05)

The three derivative-positive samples do not yet provide stationary-stop exposure. In route `1d`,
the lead was moving (`vLead` about `0.17--0.34 m/s`, `dRel` about `4.5--8.2 m`) while
`shouldStop` stayed false. Route `1f` likewise had a moving/accelerating lead (`vLead` rising
roughly `0.27--0.76 m/s`, `dRel` about `5.4--6.2 m`) and `shouldStop` false. Route `1e` briefly
flickered `shouldStop` during the first approach, but its lead was still moving at about
`0.15--0.23 m/s`; during the second approach it accelerated from roughly `0.06` to `0.97 m/s`
as the vehicle released. The temporary stopping-only trim consequently changed only 38 frames
on route `1e`, all in a moving-lead context, and none on routes `1d`/`1f`.

**Decision: treat all three as actuator-response context and a moving-lead safety screen, not stop
authority evidence.** Do not road-promote a low-speed brake trim from these samples. A valid arm
still needs a genuinely stationary lead and a no-lead crawl stop before the moving-lead release
case.

### Stopped-lead predicate safety refinement screen (2026-09-05)

Before changing the inactive planner child, the recorded lead signals were replay-screened at the
planner rate with tighter lead-speed and persistence bounds. The current predicate (`vLead < 0.35`
m/s, five planner frames, about 0.25 s) remains true for roughly 2.85 s on the slowly moving lead
in route `0000001d`, 3.35/5.05 s on the two route-`0000001e` approaches, and 0.40 s on the
accelerating lead in route `0000001f`. These are frozen-input safety screens, not counterfactual
vehicle results.

The most useful conservative tradeoff was `vLead < 0.25 m/s` with 15 planner frames (about
0.75 s): it removed the route-`0000001f` moving-lead trigger while retaining 1.35 s of the route-
`0000001d` moving-lead context and 2.85/4.55 s of route `0000001e`. A still tighter `vLead < 0.15`
m/s with the same persistence removed the sustained route-`0000001d` trigger, but it also removed
the route-12 stopped-lead replay exposure that motivated this candidate. Adding a lower ego-speed
gate has the same tradeoff: it delays or loses the early route-12 stop intent without proving a
safer stationary-lead classifier.

**Decision: KEEP the current inactive predicate unchanged; do not promote a threshold refinement
from frozen inputs.** The sweep establishes a bounded design choice for a future road arm, not a
safe classifier. Any refinement must be tested with a human override on both a genuinely stationary
lead and a lead that accelerates through the candidate window, while preserving raw
`ACCEL_COMMAND`, Honda domain bits, and the existing stopping ramp.

### Raw lead-dynamics check for the 08:38 stop report (2026-09-05)

The raw `radarState` samples sharpen the route-12 (`00000012--9ea63a15e3`) attribution without
turning the vision lead into radar truth. Around the reported 08:38 approach (route time
4766.5--4770.0 s), the selected lead was still moving at about `0.18--0.42 m/s`, closing at
`-0.25..-0.01 m/s`, and had `aLeadK` from `-0.10` to `-0.01 m/s2` at a 4.6--5.1 m gap. The
planner kept `shouldStop=false`; `carControl` and the wire request relaxed from roughly
`-0.25` to `-0.17 m/s2`, then the driver brake was pressed as the system became inactive at about
4769.03 s. The lead settled near zero speed only afterward. Route-level request-to-wire passthrough
RMS was `0.005 m/s2`, so this event does not identify an opendbc encoding or domain divergence.

The same low-speed/low-`aLeadK` signature is not sufficient to assert a stopped lead: route `1d`
began with `vLead=0.20..0.33` and `aLeadK=-0.03` before the lead accelerated; route `1e` began
with `vLead=-0.25..0.05`, `aLeadK=-0.05..-0.02` and later accelerated; and route `1f` began with
`vLead=-0.04..0.29`, `aLeadK=-0.08..+0.08` before rising above `+1.0 m/s2`. Every selected lead
in these windows carried `radar=false`. **Decision: retain the inactive stopped-lead child and
keep the production Honda path unchanged.** `aLeadK` is useful context for road-arm logging, but
it cannot justify a replay-only classifier or a downstream brake supplement. The required next
comparison remains a supervised stationary-lead approach against a lead that accelerates through
the same window, with first-divergence logging through `shouldStop` and `LongCtrlState`.

### Supervised stopped-lead road-arm deployment (2026-09-05)

The reported repeated stop misses provide the requested reason to exercise the planner candidate,
but not to promote it. A reproducible child was published at parent `e3c55df25213`, based on the
current `ody-op` evidence baseline `dcdabbd766ce` plus planner commits `136d1ebd24` and
`e3c55df252`; its nested opendbc gitlink remains `825642c4218b`. The device was switched to branch
`tmp/ody-op-stop-intent-road-20260905` with `UpdaterTargetBranch` set to that branch, rebuilt with
the virtualenv tools on `PATH`, rebooted, and verified clean. Alpha Long remains enabled and
Experimental mode remains disabled. The production branch `ody-op` is unchanged and remains the
rollback target (`dcdabbd766ce` parent, nested `825642c4218b`).

This is an unpromoted, human-supervised road arm. Record each close-lead approach with
`shouldStop`, `longitudinalPlan.aTarget`, `carControl.actuators.accel`, decoded
`ACCEL_COMMAND`, `BRAKE_REQUEST`/`GAS_COMMAND`, `LongCtrlState`, `aEgo`, lead speed/gap, and any
driver intervention. Reject immediately for a false stop on a moving lead, extra onset bite,
stale stopping after lead release, late stop, or clear drivability regression. Keep or retire only
after the candidate has stationary-lead, no-lead crawl-stop, and moving-lead-release exposure;
this deployment itself is not a road result.

A post-deployment inventory check on 2026-09-05 still found 14 device routes, all already validated,
with no route recorded after the candidate switch. The candidate therefore remains road-pending;
the last available routes (`1d`, `1e`, and `1f`) ran on the baseline before deployment and cannot
count as candidate exposure.

### Current repository and device audit (2026-09-05)

At the latest audit, local and `origin/ody-op` both resolve to parent
`307b50adcff96c8f75968c84769cdb6543f15b17`, whose `opendbc_repo` gitlink and clean nested checkout
resolve to `825642c4218b3c71f74053264882e40971cc10f5`. `upstream/master` is
`0ec3a082c7ca3302c171b03ff5cd43be61309f13` and still pins public opendbc
`b4ef5e1cf406ff143fa67bdbfb154739d43279c9`; the nested tuned branch remains based on that pin.
The published branch is clean, and no `ody-op-onset` ref remains.

The device intentionally remains on the supervised child
`tmp/ody-op-stop-intent-road-20260905` at parent `71b708453fb4564be21da783cb2036776dcc3573`,
nested `825642c4218b3c71f74053264882e40971cc10f5`, with `UpdaterState=idle`,
`UpdateAvailable=0`, no `LastUpdateException`, Alpha Long enabled, Experimental mode disabled, and
no failed services. The 14-route private inventory is fully validated and contains no route after
the candidate switch. The latest parent changes are tooling/documentation only; no source rebuild
or device replacement was performed, and no new road conclusion is claimed.

### Upstream PR and model refresh (2026-09-05)

The live upstream refs were refreshed before this audit. Parent `upstream/master` is
`0ec3a082c7ca3302c171b03ff5cd43be61309f13`; `ody-op` is `ca3337d11e0b55e9cb47aa8adc48580604343c17`,
with zero commits missing from the parent upstream history. The parent still pins public opendbc
`b4ef5e1cf406ff143fa67bdbfb154739d43279c9`. Standalone opendbc `upstream/master` is
`3e92d112129507debe45364891954db70238997a`, three commits beyond tuned nested `825642c4218b3c71f74053264882e40971cc10f5`.
Those commits add 2027 HR-V fingerprints/docs and VW MEB harness work; the Honda diff also removes
the Odyssey command-domain selector. Do not advance the nested gitlink independently: it would
discard the retained Odyssey domain behavior and violate the parent pin/schema invariant.

Three relevant openpilot PR heads were fetched for exact, read-only comparison. PR [#38658](https://github.com/commaai/openpilot/pull/38658)
(`1aa815ed08`) changes shared `should_stop()` from `vEgo < 0.30` to `0.25 m/s` and reduces the
`LongCtrlState.stopping` ramp from `1.0` to `0.3 m/s2/s`. Its own replay report shows stop-intent
rises lagging by 1--2 frames on the tested Hyundai route. That is a generic comfort/stop-state
change, not a Honda CAN divergence; the later threshold and slower ramp are not an evidence-based
response to the Odyssey's missed stopped-lead approaches. Do not merge it into `ody-op` without a
separate matched road arm.

PR [#38726](https://github.com/commaai/openpilot/pull/38726) (`5a658611a8`) is a big-model/spatial-feature
change (including `LAT_SMOOTH_SECONDS=0.1`), not a small-model release. PR [#38098](https://github.com/commaai/openpilot/pull/38098)
(`82ed2b4ffd`) is a broad big-model fallback/router architecture, also not a small-model release
or an Odyssey command-path change. The current upstream small driving-model blob remains
`f0672eab4856`; the prior `93f5aa469a` Rebellious Hope release was reverted by `b361e952c9`, and
no newer small-model release is present in the refreshed upstream master. **Decision: KEEP the
current parent/nested pins and Odyssey baseline; do not import these open PRs or a model change.**

### Repository and device recheck after provenance backfill (2026-09-05)

The current published parent is `efbac937c76871f6b28caf46067ee426c8c8cf44` on `ody-op`, with a
clean checkout and `origin/ody-op` at the same commit. Its gitlink and clean nested checkout are
both `825642c4218b3c71f74053264882e40971cc10f5`; nested `origin/ody-op` matches. The parent is
`196/0` ahead/behind the freshly fetched `upstream/master` `0ec3a082c7ca3302c171b03ff5cd43be61309f13`.
Nested `upstream/master` is `3e92d112129507debe45364891954db70238997a`, three commits beyond the
tuned checkout; those commits are unrelated VW/HR-V/docs changes and must not be merged
independently of the parent pin. `ody-op-onset` and the superseded stop-intent refs are absent from
both remotes; only the supervised road-arm ref `tmp/ody-op-stop-intent-road-20260905` remains.

The fresh SSH check to `192.168.1.200` timed out; a network-layer ping had 100% loss and the local
ARP entry remained incomplete. The device's present checkout, updater state, services, and road-arm
route inventory are therefore not claimed current. The last successful probe remains
the supervised road arm at parent `71b708453fb4564be21da783cb2036776dcc3573`, nested
`825642c4218b`, with Alpha Long enabled and Experimental mode disabled. Reverify that state before
any further drive or deployment; no device change was made for this documentation-only backfill.

### Latest repository, provenance, and cleanup audit (2026-09-05)

This entry supersedes the earlier same-day snapshots above. The last source-bearing production
snapshot in this audit was clean `ody-op` parent `0b3e4a1d279b66fe4b161e1ba9ddeb77a7bafe14`; the
later publication steps are documentation/ignore-only commits and leave runtime behavior unchanged.
Its nested checkout and gitlink were both `825642c4218b3c71f74053264882e40971cc10f5`; nested
`origin/ody-op` matched as well. Fresh `upstream/master` is
`0ec3a082c7ca3302c171b03ff5cd43be61309f13`: the parent is `198/0` ahead/behind, while standalone
opendbc is `35/3` ahead/behind its `3e92d112129507debe45364891954db70238997a` upstream. The three
new nested commits are unrelated VW/HR-V/docs changes and must not be merged independently of the
parent's public-opendbc pin. No `ody-op-onset` ref remains.

The private ledger currently contains 266 historical rows. Sixty-eight rows now resolve exact parent,
nested-source, model, mode, and selected-setting provenance; the remaining 198 stay historical or
source-incomplete, and no row is treated as exact when its source or operating-state identity
cannot be resolved. No newer small driving-model blob is present:
`driving_supercombo.onnx` remains
`f0672eab4856`, and the prior `93f5aa469a` release was reverted upstream.

Cleanup removed the superseded stop-intent refs, one-off replay/analysis artifacts, generated Python
caches, stale HTML maneuver reports, nested safety-test object/coverage files, the candidate's empty
legacy `.claude` tree, and the separate staging worktree's editor/cache/gcov debris. Empty maneuver
report directories were also removed; their generators recreate them on demand. The active supervised
worktree `tmp/ody-op-stop-intent-road-20260905`, private route/download/extract caches, and reusable
build/UV caches are intentionally retained. No tracked Claude skill or root `CLAUDE.md` remains;
project guidance is `AGENTS.md` plus `.agents/`.

The parent and nested repositories also had five old stash refs: one automatic pre-sync snapshot and
four superseded ledger, task, or Honda-tune work-in-progress snapshots. Their committed history or
ledger records are already retained, so the stash refs were dropped during this audit; no working-tree
or active branch depended on them. No garbage collection was run, preserving normal Git recovery until
the repositories next expire unreachable objects.

The current device check still has no LAN presence (SSH timeout, ping loss, incomplete ARP), so its
checkout, updater target, services, and route inventory remain unverified until it reconnects. The
last successful state was the supervised child at parent `71b708453fb4564be21da783cb2036776dcc3573`
with nested `825642c4218b`, Alpha Long enabled, and Experimental mode disabled.

### Git temporary-pack cleanup (2026-09-05)

The parent object store had five unreachable `tmp_pack_*` files left by interrupted July/August
fetches (`3,323,740,155` bytes total). No Git fetch or pack process was active, and `git
count-objects -v` classified them as garbage. They were removed by exact path; all refs, commits,
reflogs, and worktrees were left intact. Parent and nested object stores now report zero garbage.
No `git gc` or unreachable-object pruning was run, so historical recovery remains available until
normal Git expiry. Reusable private-log, download, extraction, build, and UV caches remain outside
the repositories; the supervised stop-intent worktree remains the only active temporary road arm.

### Source-aware extraction refresh (2026-09-05)

The exploratory extractor previously cached only `radarState.leadOne`, even though the planner's
lead MPC uses `leadOne` for `lead0` and `leadTwo` for `lead1`. `.agents/extract.py` now retains both
leads and adds `lead_selected_*`, selecting only for published lead-plan sources (raw enum 1/2);
the historical `lead_*` names remain explicit `leadOne` aliases. Cache schema 5 was rebuilt for all
26 retained routes, and the 26 obsolete schema-4 files were removed. The selector has focused tests;
the source mapping mutation was observed failing before restoration.

The refreshed source-aware stopped-lead screen leaves the current inactive predicate unchanged:
`vEgo < 1.0`, `aTarget < -0.05`, model probability above `0.9`, `vLead < 0.35`, closing `vRel`,
and gap below `6.5 m`, with five-frame persistence. On published lead-plan samples it would assert
17 debounced runs (35.65 s) across eight routes; only 5.27 s of candidate frames across four routes
survive a `vLead < 0.05` screen, so most of the current exposure is a slow-moving rather than
stationary lead by this conservative proxy. The latter
includes already-generic-stop intervals on routes `00000038`/`0000006d` and has no closed-loop
stationary-lead versus moving-lead release result. This is a frozen-input classifier screen, not a
road result. **Decision: KEEP the candidate inactive and require a supervised stationary-lead and
moving-lead-release comparison; do not tune the planner or Honda command path from this replay.**

The same tooling-only extractor/test sync is published on the supervised candidate as
`e31690fa6d39e5516dd07e0a55f5ecde58c20735`; its runtime planner, Honda CAN, and nested gitlink are
unchanged. Parent and candidate local refs match their respective remotes after publication. The
candidate checkout has no local virtualenv, so its hook could not run; the parent virtualenv ran
candidate Ruff plus the stopped-lead and extractor tests (`5 passed`).

### Upstream refresh after source-aware extraction (2026-09-05)

Parent `upstream/master` advanced to `f9dacd0d6b` with Cabana's build-directly change. The
non-runtime commit was imported into `ody-op` as `3f510eb070`; `openpilot/tools/cabana` is now
content-identical to upstream and the wrapper script is gone. The same commit is present on the
supervised candidate as `915cba1651`. No longitudinal planner, lateral controller, Honda CAN, or
nested gitlink behavior changed. The parent graph remains one commit behind upstream by object
identity because this was a clean cherry-pick; no source delta remains for that upstream change.

Nested `opendbc_repo/upstream/master` remains `3e92d1121295`, with only the unrelated VW MEB,
scheduled-CARS, and 2027 HR-V commits beyond the pinned `825642c4218b`; they remain intentionally
unmerged to preserve the parent/opendbc schema pairing.

### Upstream Cabana UI refresh and final cleanup pass (2026-09-05)

`upstream/master` advanced from `f9dacd0d6b` to `a989bc0b50` with Cabana-only UI and test
formatting changes (`#38782`). The diff touches no planner, longcontrol, lateral controller, Honda
CAN, safety, model, or nested-opendbc code. It was cherry-picked into the published parent as
`73177efafd` and the supervised candidate as `f56976611c`; the nested pin remains
`825642c4218b3c71f74053264882e40971cc10f5`.

The follow-up hygiene pass removed stale in-tree build products, generated bindings, old binaries,
and nested safety-test coverage/object debris (about 500 MB). It did not remove tracked source,
private route/download/extract evidence, model/font assets, virtualenvs, reusable UV/SCons caches,
historical refs, or the active supervised worktree. No `.claude` files, `.DS_Store`, stale worktree,
or Git garbage remain; parent and nested `git count-objects` report zero garbage. Test-generated
cache/debris was removed again after the focused suite (`29 passed, 58 subtests passed`).

The parent and supervised candidate branches are published and clean, and direct remote lookup
confirms no `ody-op-onset` ref. The device remains
unreachable over SSH, so its current checkout/updater/services and any road result remain
unverified; no deployment or reboot was performed for this UI-only sync or cleanup.

### Live upstream model/PR recheck (2026-09-05)

The current public PR heads were checked against `commaai/openpilot` after the previous model
audit. PR [#38771](https://github.com/commaai/openpilot/pull/38771) (`68b5f8e486`) is the **Cinque
Terre big model**: its only model-file change is the `big_driving_supercombo.onnx` pointer. The
small `driving_supercombo.onnx` pointer remains `f0672eab4856`, identical to `upstream/master` and
`ody-op`; it is not a small-model release for this car.

PR [#38746](https://github.com/commaai/openpilot/pull/38746) (`f7a158371f`) is BMRLNAP v6's
precompiled Chestnut/big-model loader and 17-file tinygrad big-model bundle. PR
[#38726](https://github.com/commaai/openpilot/pull/38726) (`5a658611a8`) is the Time to Go
spatial/big-model change. Neither changes the small model or the Odyssey Honda command path. The
public PR list shows no newer small-model candidate, and the latest small-model history remains
the reverted `93f5aa469a` Rebellious Hope release. **Decision: keep the current small model,
parent/nested pins, and Odyssey production baseline; do not import these big-model or loader PRs.**

### Route 00000070 transition-frame audit (2026-09-05)

Route `00000070--16f597b10c` is a full-rate baseline capture from parent
`0cdcc917185aee0c80b7af996d8dff9d17ac3903`, nested opendbc
`f52c828fdf49275534d3a0c25030ee157c647f80`, branch `ody-op`, small model
`f0672eab48566d395e49407293579b817f3e9d22`, Alpha Long enabled, Experimental mode disabled, and
standard longitudinal personality. The nested source differs from the current pin only by a
comment, moving the non-Bosch `stopping` local into the Bosch branch, and an interface assertion;
the Odyssey command-domain function and Honda CAN encoding are behaviorally identical to current
`825642c4218b3c71f74053264882e40971cc10f5`.

The route's aggregate request-to-wire result is `0.0185 m/s2` RMS in the brake domain, with no
sustained sign disagreement and three transition frames ignored by the validator. The two worst
frames occur at route-relative `1126.43 s` and `1217.23 s`: `carControl.actuators.accel` has just
crossed from about `-0.01` to `+0.04 m/s2`, while the zero-order-held Honda wire is still about
`-0.01 m/s2` for one 20-ms command period before the positive gas command appears. The next samples
carry the positive request and gas command; there is no sustained positive-request brake hold or
request-to-wire/domain event. This is the expected 100-Hz controller versus 50-Hz Honda-command
transition/quantization boundary, not a repeatable opendbc divergence.

**Decision: KEEP the current command-domain implementation and make no Honda change from route
70.** Retain the transition frames as a diagnostic boundary; reopen only if a full-rate route shows
the same mismatch beyond the command-period transition or with measurable withheld acceleration.

### Route 00000044 ledger provenance refresh (2026-09-05)

The retained route `00000044--1f70122a52` was revalidated from all local full-rate segments after
its older ledger row was found to lack source fields. Its `initData` resolves a clean parent
`78562c509663722bc77bdef5747f1d6f0008cbb0`, nested opendbc
`09a52a2bf00317ae1a26255058eec0e4b164703b`, small model
`f0672eab48566d395e49407293579b817f3e9d22`, Alpha Long enabled, and mixed Experimental/personality
state. The refreshed metrics are unchanged (`0.0077/0.0108 m/s2` gas/brake wire RMS, 28 physical
brake edges, and six driver brake takeovers); this is a provenance correction, not a new behavioral
result. The ledger now has 68 exact-provenance rows; no comparison is pooled across the mixed
operating-state route without conditioning on those settings.

### Live upstream PR/model recheck (2026-09-05, second pass)

The current public pull-request list now includes #38772 (setup/check tooling), #38771 (Cinque
Terre model), #38767 and #38763 (driver-monitoring warp/JIT build packaging), #38757 (model replay),
and #38768 (Hyundai set-speed behavior), alongside the previously reviewed BMRLNAP, Time to Go, and
one-stopping-tune PRs. None is a new small driving-model release or a Honda longitudinal/lateral
command-path change. In particular, #38771 changes only the big-model pointer; the small
`driving_supercombo.onnx` pointer remains `f0672eab48566d395e49407293579b817f3e9d22`. PRs #38767
and #38763 restore/package DM artifacts for both camera resolutions and report zero replay changes;
they do not alter driving weights or control commands.

**Decision: keep the current small model and `ody-op` source pins.** Do not import these PRs into the
Odyssey arm. Recheck the list and model pointers after the next upstream fetch succeeds; this web
check does not replace exact local source resolution or a road result.

### Live upstream model PR boundary (2026-09-06)

The current public openpilot PR list still shows BMRLNAP v6 (`#38746`) and Time to Go Model
(`#38726`) as open. The former is a Chestnut/precompiled big-model arm with its own model-replay
artifact; the latter changes big-model spatial-feature/JIT input handling, sets modeld's long-output
smoothing, and updates the big-model pointer. Neither changes `driving_supercombo.onnx`, Honda
`longcontrol`, Honda CAN translation, or the nested opendbc pin. The route-22 device provenance
records a Tizi device with `chestnutPresent=false`, so these PRs cannot change its active driving
model without changing hardware/runtime and planner behavior together. Keep them out of `ody-op`;
they remain model/runtime research references rather than isolated Odyssey candidates.

### Upstream Cabana refresh after live fetch (2026-09-05)

The live fetch advanced `upstream/master` from `a989bc0b50` through `444be0a649` and
`a4f7c50d2a` (Cabana frame pacing and sparkline rendering fixes). These commits touch only
`openpilot/tools/cabana`; they do not change the longitudinal planner, `longcontrol`, lateral
controller, Honda CAN translation, safety limits, model pointers, or the nested opendbc pin. The
same content is now in the parent as clean cherry-picks `34a638d6d3` and `2d6131d840`, and in the
supervised stopped-lead child as `c002d4ed9a` and `2243a6d349`. A direct path diff against
`upstream/master` is empty for the Cabana files, while the remaining parent-only delta is the
documented Odyssey tooling/evidence surface.

The nested `opendbc_repo/upstream/master` remains `3e92d1121295`, three commits beyond the pinned
`825642c4218b`; those VW/HR-V/docs changes remain unrelated and must not be merged independently.
**Decision: keep the current Odyssey runtime and nested pin; import only the non-runtime Cabana
refresh, with no Honda behavior change.**

### Published baseline validation after upstream refresh (2026-09-05)

On the clean published `ody-op` checkout (`bea2652d1f`, nested `825642c4218b`), the Honda interface
and Odyssey rail gates pass: `270 passed, 58 subtests passed`. The repository pre-commit hook also
passes its focused 39-test tooling suite. The full `opendbc_repo/test.sh` invocation remains
dependency-blocked: the runner cannot resolve the Hugging Face `comma-car-segments==0.1.0` wheel;
no source or test failure was reported. Test-generated caches and bytecode were removed afterward,
leaving only the intentionally retained virtualenvs and reusable external caches.

This is software/CAN-safety validation only. It does not change the road decision: the current
Honda command-domain implementation and inactive stopped-lead planner child remain unchanged, and
the device is still awaiting a reachable supervised road run.

### Stopped-lead classifier refinement screen (2026-09-05)

With the current source-aware extraction cache (schema 5), I screened one bounded classifier
variant against every locally retained full-rate route. The existing inactive child uses
`vEgo < 1.0 m/s`, `aTarget < -0.05 m/s2`, model probability above `0.9`, `vLead < 0.35 m/s`,
closing `vRel`, `dRel < 6.5 m`, and five planner frames. A conservative screen using
`vLead < 0.20 m/s`, `vRel > -0.40 m/s`, `dRel < 5.5 m`, and 15 frames would remove the
route-`1f` accelerating-lead trigger and reduce route `1d` to only `0.15 s`, while retaining
`2.02 s` of the route-12 exposure. It still matches moving-lead portions of route `1e` (`6.27 s`)
and route `44`, so it is not a safe stationary-lead classifier. The `vRel` lower bound also trades
away earlier intent for a faster-closing genuine stop.

This is a frozen-input screen only; it changes neither planner output nor Honda CAN. **Decision:
keep the existing child predicate and production baseline unchanged.** If a future supervised arm
needs a safer refinement, test this as a separate candidate with a stationary lead, a fast-closing
lead, and a lead that accelerates through the window; do not silently replace the current child.

### Latest upstream refresh and workspace hygiene (2026-09-05)

The next successful upstream fetch advanced `upstream/master` to
`cb0da74b414363f4cdb15c2897f8bb1202bc7e79` (`#38785`, Cabana speed-label and toolbar-divider
cleanup). It was cherry-picked into `ody-op` as `4183635c608d5fd2b18050ebd0acf5cbff9e722d`.
The changed files are limited to `openpilot/tools/cabana`; direct diffs for the planner,
`longcontrol`, lateral controller, Honda CAN, safety, model, and nested-opendbc paths are empty.
The parent still pins nested `opendbc_repo` at `825642c4218b3c71f74053264882e40971cc10f5`; the
nested upstream-only commits at `3e92d112129507debe45364891954db70238997a` remain unrelated
VW/HR-V/docs work and were not merged independently.

The `Inspect Upstream Delta` VS Code task now calls its counts “upstream-only/local-only history
objects” instead of “missing commits,” documenting that cherry-picks can be source-equivalent
despite different object IDs. Its JSON parses successfully, and the wording change is published in
parent commit `134a4286bf` alongside `tools/README.md`.

The final workspace scan found no project-owned temporary or generated debris: no `.claude` tree,
`.DS_Store`, Python/build/test caches outside virtualenvs, stale maneuver reports, nested safety
objects/coverage, or stale worktree. The supervised stop-intent worktree, private route/download/
extract caches, virtualenvs, model/font assets, and reusable UV/SCons caches are intentionally
retained because they support reproducible analysis or fallback deployment. Parent and nested stash
lists are empty and both object stores report zero garbage; no broad garbage collection was run.

This is a tooling/source-refresh and hygiene result only. The device remains unreachable (SSH
timeout, ping loss, incomplete ARP), so no deployment, reboot, updater verification, or road result
is claimed. Recheck the device separately before the next supervised route.

The staging fallback verifier now asserts both official Sunnypilot remote URLs and
`AlphaLongitudinalEnabled=1` in addition to its branch, updater, and failed-service checks. The
guard is published in `fa80422d79`; `bash -n` and the help path pass. No device mutation was
attempted while the LAN target remained unreachable.

### Route 0000001a uphill and Experimental-mode report (2026-09-05)

The newly reviewed route `0000001a--936af9eafa` has exact provenance: parent
`5838b4b0c5d0efccdca82db006f0ffe8c6cf5623`, nested opendbc
`0bd54951753feb21234c0142dc06723c36a43ba3`, branch `ody-op`, small model
`f0672eab48566d395e49407293579b817f3e9d22`, Alpha Long enabled, standard personality, and mixed
Experimental mode. Its `start_wall` maps route-relative `t=968.46 s` to about 13:33:43 CDT, the
reported 13:34 mode change. Before and after that transition, `aTarget` and
`carControl.actuators.accel` remain closely aligned and the Honda command is the expected raw
request/domain result; the brief later inactive interval is not a command-following exposure.

The reported 13:52 uphill segment is route-relative `t=2032--2041 s`. While `longActive` was true,
no pedals were pressed, and the model's Experimental (`e2e`) source was selected, pitch reached
`+0.072 rad` and speed fell from roughly 29.7 to 26.1 m/s. The planner requested near-zero to
slightly negative acceleration (mean `aTarget=-0.025 m/s²`), `carControl` followed it
(`plan→carControl RMS=0.0056 m/s²`), and the decoded Honda `ACCEL_COMMAND` followed the controller
(`carControl→wire RMS=0.0057 m/s²`, `BRAKE_REQUEST=0` throughout). Achieved acceleration was about
`-0.410 m/s²` on average (`aEgo-request≈-0.386 m/s²`), so the first repeatable divergence in this
window is vehicle response under an uphill/near-zero request, not Honda CAN translation or domain
arbitration. From approximately `t=2041 s` onward `longActive` dropped while the driver pressed the
accelerator; the subsequent re-engagement and braking are driver/control-state exposure, not a
valid port comparison.

**Decision: keep the production Honda command path and make no brake/gas tuning change from this
route.** Investigate the Experimental model/planner trajectory or repeat an engaged, no-pedal uphill
hold if the question is whether OpenPilot should request more acceleration; do not compensate for
the model's near-zero request in opendbc.

### Generated-artifact cleanup follow-up (2026-09-05)

The follow-up hygiene pass removed the regenerated parent/nested Python, pytest, and Ruff caches
and the resolved candidate-worktree `AUTO_MERGE` marker. A project-owned scan now finds no
`.claude` tree, Claude skill file, `CLAUDE.md`, `.DS_Store`, bytecode, coverage/object output,
stale maneuver report, or orphaned worktree. The active stopped-lead worktree, private route and
download/extract caches, virtualenvs/model/font assets, reusable UV/SCons caches, and backup refs
remain intentionally available for reproducible analysis or rollback. No source/runtime behavior
changed, no broad Git garbage collection was run, and no historical backup refs were deleted.

### Device recheck after cleanup (2026-09-05)

The device is reachable again. `/data/openpilot` is clean on the intentionally supervised
`tmp/ody-op-stop-intent-road-20260905` branch at parent `71b708453fb4564be21da783cb2036776dcc3573`,
with nested `opendbc_repo` clean on `ody-op` at `825642c4218b3c71f74053264882e40971cc10f5`; the
parent gitlink matches. Its `origin` and `sunnypilot` remotes use the expected repositories,
`UpdaterTargetBranch` points to the supervised child, Alpha Long is `1`, Experimental mode is `0`,
`UpdateAvailable` is `0`, and `UpdaterState` is `idle`; `LastUpdateException` is absent. No failed
systemd units were reported and manager is running; `controlsd` is not running while offroad. Recent
boot errors are limited to pre-existing udev rule warnings and a missing DSA SSH host key. This
recheck changes no device state and does not promote the candidate to production `ody-op`.

### Routes 00000020/21 supervised candidate screen (2026-09-05/06)

The two newly retained full-rate routes were recorded on the intentionally supervised child
`tmp/ody-op-stop-intent-road-20260905`, parent `71b708453fb4564be21da783cb2036776dcc3573`, nested
opendbc `825642c4218b3c71f74053264882e40971cc10f5`, and small model
`f0672eab48566d395e49407293579b817f3e9d22`. Alpha Long was enabled, Experimental mode was disabled,
and both repositories were clean. The ledger date is 2026-09-06 because the device's UTC clock had
already crossed midnight.

Route `00000020--f8047564cf` supplied 44.9 logged minutes and 16.7 engaged minutes; route
`00000021--9cdb50c5da` supplied 28.4 logged and 19.1 engaged minutes. In both, the complete
planner-to-`carControl` and controller-to-Honda-wire paths remained aligned: plan→`carControl` RMS
was 0.0071/0.0068 m/s² and request→wire RMS was 0.0071/0.0081 m/s² respectively, with no sustained
sign disagreement, no low-speed domain conflict, no stale brake on re-engagement, and no direct
gas→brake handoff. The one route-20 worst frame was a single 100-Hz-to-50-Hz transition sample
(`carControl` had just become positive while the zero-order-held wire was still zero); the next
sample carried the expected gas command. This is the same bounded transition quantization seen on
route 70, not a persistent opendbc mismatch.

The source-aware stopped-lead predicate (including its conservative refinement), active speed below
2 m/s, and active `shouldStop` all had zero qualifying frames on both routes. The reported brake
takeovers were driver-initiated while the system was either already inactive or following the
request/domain correctly; after disengagement the zero wire command is expected. These routes
therefore add no stationary-lead, low-speed stop, or moving-lead-release exposure for the inactive
stop-intent child.

The only repeatable physical lead is uphill positive-request response. No-pedal, positive-request
uphill windows had median pitch/request/aEgo of about `+0.049/+0.151/-0.006 m/s²` on route 20 and
`+0.041/+0.190/+0.005 m/s²` on route 21, leaving achieved-minus-request residuals near `-0.18` and
`-0.19 m/s²` after the wire followed the command. This is a downstream Honda/vehicle-response or
grade-frame question, not a CAN-domain divergence. Ford and Toyota peer ports use pitch terms only
for their OEM-specific PCM behavior; neither establishes a Honda Bosch gas-map change, and no
production compensation is justified by these unmatched windows. Route 20 also began hot-soaked
(75.4 °C, peak 87.5 °C), so its response is not a clean thermal baseline.

**Decisions:** keep the current Honda command-domain implementation and raw `ACCEL_COMMAND` path;
make no opendbc or brake/gas tuning change from these routes. Keep the stopped-lead child inactive
and road-pending because it received no qualifying stop exposure. Retain the uphill residual as a
diagnostic question for a matched, no-pedal grade comparison; do not hide it with Honda command
shaping or treat replay as vehicle-response proof.

### Cross-route uphill positive-request screen (2026-09-06)

To test whether the route-20/21 uphill residual was a child-branch artifact, I replay-screened the
same no-pedal, active, moving, positive-request, gas-domain mask across exact-source full-rate
routes. The result persists on multiple parent and nested pins:

| route | uphill-positive exposure | median pitch | median request | mean `(aEgo - request)` | wire RMS |
|---|---:|---:|---:|---:|---:|
| `00000012--9ea63a15e3` | 892.8 s | +0.033 rad | +0.116 | -0.148 | 0.006 |
| `00000019--51c121c792` | 88.4 s | +0.042 rad | +0.296 | -0.264 | 0.004 |
| `0000001a--936af9eafa` | 254.1 s | +0.038 rad | +0.174 | -0.186 | 0.006 |
| `00000020--f8047564cf` | 47.3 s | +0.042 rad | +0.140 | -0.171 | 0.004 |
| `00000021--9cdb50c5da` | 269.7 s | +0.038 rad | +0.178 | -0.152 | 0.006 |
| `00000044--1f70122a52` | 166.2 s | +0.049 rad | +0.176 | -0.142 | 0.010 |
| `00000068--bbbfad9947` | 86.5 s | +0.061 rad | +0.222 | -0.144 | 0.009 |
| `00000070--16f597b10c` | 86.3 s | +0.047 rad | +0.302 | -0.195 | 0.007 |

The exact nested sources span `0bd54951753f`, `09a52a2bf003`, `825642c4218b`, `929540bbcf79`, and
`f52c828fdf49`; the Honda command path is behaviorally unchanged across these pins for this
question. The residual is correlated with positive pitch (a pooled regression of achieved-minus-
request on pitch/request/speed gives a negative pitch term of roughly 5--10 m/s² per rad), while
the decoded wire remains within about 0.004--0.010 m/s² RMS of the controller request. This makes
the repeatable divergence vehicle response or acceleration-frame/grade handling after the wire,
not Honda CAN encoding or domain arbitration. The planner's existing `get_coast_accel(pitch)` is a
no-throttle speed-limit mechanism; it is not evidence that a Bosch Honda gas command should be
reshaped. Ford's and Toyota's pitch compensation is tied to their respective PCM behavior and does
not provide a Honda precedent.

**Decision: keep the current Honda translation and do not add pitch compensation, a gas multiplier,
or a brake supplement.** The next useful comparison is a matched uphill hold with a cool device and
the same planner command, followed by actuator/grade attribution; replay can screen command shape
but cannot establish that response improvement.

### Upstream Cabana refresh: video-pane fill and reset (2026-09-06)

`upstream/master` advanced to `3bc6701f34553a709d3d5c50be3b1265c77bb67d` with upstream PR #38786,
which changes only Cabana's video placement/settings and UI tests. Direct source comparison against
`ody-op` found no planner, `longcontrol`, lateral controller, Honda CAN, safety, model, or nested
opendbc change. The commit was cherry-picked into the baseline as `8a96adba48` and applied to the
supervised child as `888b587323`.

The child already carried a local Cabana speed-label spacing change, so its cherry-pick required one
UI-only conflict resolution. The resolved child retains that existing spacing while taking the full
upstream crop-video setting, toolbar control, aspect-ratio placement, and thumbnail changes. The
parent and child both pass whitespace and Cabana Python lint; the child hook could not run because
the active worktree has no local virtualenv, so its equivalent checks use the parent environment.

**Decision: keep the upstream Cabana refresh in both histories; no vehicle source or device state
change is warranted.** The nested opendbc pin remains `825642c4218b` and no new small driving model
was introduced by this upstream commit.

### New routes 00000022/23/24 (2026-09-06)

Routes `00000023--e2190ad2b7` and `00000024--8ed656b4ba` were fully pulled from the supervised
`tmp/ody-op-stop-intent-road-20260905` child at parent `71b708453fb4564be21da783cb2036776dcc3573`,
nested opendbc `825642c4218b3c71f74053264882e40971cc10f5`, small model
`f0672eab48566d395e49407293579b817f3e9d22`, Alpha Long enabled, and Experimental mode disabled.
Route 24 supplied 31.5 engaged minutes with no controlsd crash, takeover, or sustained sign
disagreement; plan-to-`carControl` RMS was `0.006` m/s2 and request-to-wire RMS was `0.005` m/s2.
Route 23 supplied only 3.0 engaged minutes and remains thin context.

Route 24 repeatedly exposed a separate, no-lead, standard-cruise uphill residual: 45.7 s in the
0.5-1.5 mph-below-set and positive-request mask had median set-speed error `0.61` mph, request and
wire `+0.272` m/s2, pitch `+0.05` rad, and achieved `aEgo` approximately `0.00` m/s2. The planner
uses the upstream proportional cruise request `vCruise - vEgo`, so a roughly 0.3 m/s speed error
produces only roughly `+0.3` m/s2; the positive grade/load consumes that request. This is a
vehicle/grade response after a faithful wire command, not a Honda domain or CAN encoding mismatch.
The lead-transition window on the same route likewise followed planner braking and recovered;
it is not a fixed one-mph limiter.

Route `00000022--34677013ac` was subsequently completed (47/47 segments; 46.8 logged and 28.6
engaged minutes). It ran the same exact child source and settings as routes 23/24: parent
`71b708453fb4564be21da783cb2036776dcc3573`, nested opendbc
`825642c4218b3c71f74053264882e40971cc10f5`, small model
`f0672eab48566d395e49407293579b817f3e9d22`, Alpha Long enabled, and Experimental mode disabled.
There were no controlsd crashes or sustained sign disagreements, no gas overrides, and no creep;
plan-to-`carControl` RMS was `0.0066` m/s2, gas request-to-wire RMS `0.0063` m/s2, and brake
request-to-wire RMS `0.0175` m/s2. Three brake takeovers occurred among 29 brake presses, so the
route is useful for attribution but not a claim of universally good stopping.

The reported 08:29 stop is a real candidate exposure. A close vision lead (about 3.36 m, relative
velocity `-0.595` m/s, lead velocity `+0.045` m/s) qualified the child's stopped-lead predicate
from 08:29:19.197 to 08:29:19.890 while the vehicle slowed from 1.83 to 0.69 mph. The candidate
made `longitudinalPlan.shouldStop` true about `0.70` s before the ordinary
`vEgo < 0.3 m/s`/low-target predicate. `longcontrol` then intentionally entered its stopping
ramp: the request moved from about `-1.21` to `-1.71` m/s2 and the wire followed it, reaching zero
around 08:29:20.27 and holding until the stop-intent interval ended around 08:29:23.34. The driver
pressed the accelerator at 08:29:25.84 (about 2.5 s later), after OpenPilot had already released
the brake and commanded the restart. This is one good stop-intent road example, not enough to
promote the child; routes 20/21/23/24 had no qualifying candidate exposure.

The same completed route also gives three clean near-one-mph-under-set windows. They were no-lead,
standard-cruise, `allowThrottle=true` intervals with the positive planner request carried to the
wire and near-zero achieved acceleration:

- 08:39:11.711-16.018: gap `0.65` mph, request/plan/wire about `+0.290/+0.289/+0.289` m/s2,
  `aEgo -0.026`, pitch `+0.071` rad.
- 08:43:44.975-53.289: gap `0.71` mph, request/plan/wire about `+0.316/+0.316/+0.316` m/s2,
  `aEgo +0.006`, pitch `+0.055` rad.
- 08:44:47.437-50.440: gap `0.55` mph, request/plan/wire about `+0.248/+0.246/+0.246` m/s2,
  `aEgo -0.009`, pitch `+0.049` rad.

Thus these cases are not a Honda CAN/domain failure: the first divergence is after a faithful wire
command, where positive grade/load consumes the modest upstream proportional cruise request. The
larger below-set intervals elsewhere on the route are ordinary lead or setpoint transitions, not a
fixed one-mph limiter. This agrees with the uphill residual on routes 20/21/24; do not add pitch
feedforward, a gas multiplier, or a brake supplement without a matched response experiment.

The physical scale is consistent with that attribution, but the known standing pitch bias must be
included. Treating the raw measured `+0.05..+0.07` rad as true grade gives an upper-bound gravity
component of roughly `+0.48..+0.69 m/s2`; the measured signal carries about `+0.02` rad of mount
bias, so subtracting that bias still leaves roughly `+0.29..+0.49 m/s2` from gravity. The upstream
`get_coast_accel()` fit also includes rolling/aero load and predicts about `+0.47..+0.58 m/s2` of
positive acceleration to hold speed at those corrected pitches. The observed `+0.25..+0.32 m/s2`
requests can therefore leave a material residual while `aEgo` remains near zero. This explains the
modest steady deficit without indicating that Honda dropped part of the command.

The open-loop Honda controller replay over the completed route 22 also reproduces the recorded
command shape: replay-versus-recorded `carOutput` acceleration RMS is `0.0097` m/s2, with the
replayed wire jerk peak/p99 `2.09/0.17` m/s3 versus recorded `2.07/0.17`. The apparent worst positive
request mismatch (`-0.60` m/s2) is the first active frame at route-relative `1216.24` s: the
previous frame was disengaged, so the 50-Hz Honda command is still zero; the next frame carries
`+0.60` m/s2 and gas. It is the expected 100-Hz controller/50-Hz CAN freshness boundary, not a
sustained command or domain loss. As with all replay, this verifies command shape only.

The route-22 stop-lurch attribution also survives an independent acceleration estimate. At the
worst low-speed frame (route-relative `652.23` s, about 08:29:18.30), the request/wire/aEgo were
`-1.53/-1.57/-1.93` m/s2; a 25-sample (`~0.25` s) speed derivative gave `-1.73` m/s2, still
`+0.20` m/s2 beyond the request (the corresponding smoothed `aEgo` residual was `+0.32`). This
frame precedes the child's stop-intent trigger and was in `longControlState=pid`, so it is not a
candidate stopping-ramp effect. Together with the sign-changing low-speed residuals on baseline
routes 1d/1e/1f, it supports a Honda actuator transient but still rejects a global brake scale or
offset; no production brake-response arm is warranted.

**Decision: keep the current Honda command-domain and raw `ACCEL_COMMAND` path; make no brake/gas
tuning change. Keep the stop-intent child road-pending after its one exposed good stop, and use a
second independently exposed stopped-lead event to decide whether to promote it.**

### Upstream model refresh after 2026-09-06 fetch

`upstream/master` advanced from `3bc6701f34553a709d3d5c50be3b1265c77bb67d` to
`c51e3e5a71d6ea25e59c0683d683c1092c7c3f69` with PR `#38771` (Cinque Terre). The commit changes
only the LFS pointer for `big_driving_supercombo.onnx` (`1791d5940b2c` to `e8d821733be1`); the
small `driving_supercombo.onnx` payload remains SHA-256 `659727c4d483` in both upstream and
`ody-op`; the committed LFS pointer blob recorded by the validator is `f0672eab4856`.
There is therefore no new small-model release or Honda command-path change to evaluate, and the
upstream commit remains intentionally unimported.

### Sunnypilot v2026.003.000 model-package check (2026-09-06)

The cached Sunnypilot nightly release `d656ce307e7f2dad7ad065643f06070cf4ec8c53` (release
`v2026.003.000`, source `6135084c941d4d947dd90c78326a557c3c857f89`) contains a packaged
`driving_supercombo.onnx` whose SHA-256 is `659727c4d4839adc4992a254409a54259a8756a743f2d567bf5fdc6579f8009b`,
exactly matching the current `ody-op` working-tree model payload. Its source tree still carries
the same `f0672eab4856` LFS pointer; the release is packaging, not a new small-model weight set.
No model or Honda command-path candidate is opened from this release, and no deployment is made.

The freshly fetched official `sunnypilot/staging` (`40d6afd30042e9a1bb452f42d3b6e67ecd00c98f`)
and `sunnypilot/staging-chestnut` (`787f5f4aa9d0d15532971da50c07e410091d01c4`) refs carry the
same v2026.003.000 source commit `6135084c941d4d947dd90c78326a557c3c857f89`, but package the
Tinygrad small model as four chunks (`b8626c4cff28` manifest) instead of the older two-chunk
artifact (`d8263ee98605`). Their source also adds model-execution changes and Sunnypilot
planner/long-control extensions (SCC/SLA/DEC and gas-interceptor handling). Those are runtime and
planner changes, not an isolated Honda or small-weight change; they can alter the requested command
and therefore are not imported into `ody-op` or treated as a tuning result. Any future staging
comparison must resolve the complete model artifact and settings, then use replay and a separate
road arm.

### Exploratory under-set screen without route pooling (2026-09-06)

As a triage check, the existing v5 extract caches were screened independently (no source-hash
pooling) for active moving, valid-setpoint, no-lead standard-cruise windows 0.5-1.5 mph below set
with a positive request. Across 23 cached routes there was no interval lasting at least 2 s with
near-level pitch (`|pitch| < 0.02` rad). The sustained exposure was 225 s at `+0.04..+0.06` rad
(median request `+0.296`, median achieved `+0.001` m/s2) and 108 s at `+0.06..+0.10` rad
(median request `+0.363`, median achieved `+0.006` m/s2); the short `+0.02..+0.04` exposure was
only 4.8 s. This is consistent with the route-22/24 uphill examples and is diagnostic rather
than a pooled A/B result.

**Decision: keep the existing Honda translation and do not add grade feedforward or gas scaling.**
The next discriminating road exposure is a sustained level-road hold with a positive request while
0.5-1.5 mph below set; until then, the observed one-mph deficit remains a post-wire grade/load
response rather than an opendbc mismatch.

### Under-set-speed physics sanity check (2026-09-06)

For the exact rows above (and the independently revalidated route 70), the diagnostic's stored
speed gap is in m/s, matching `get_cruise_accel()`'s `v_cruise - v_ego` target. The observed pairs
are therefore internally consistent: a 0.264-0.490 m/s2 request corresponds to a 0.59-1.09 mph
gap, while `aEgo` remains near zero. At the measured uphill pitches (`+0.048..+0.086` rad),
`g*sin(pitch)` is approximately `+0.475..+0.840 m/s2`; the finite speed-error feedback can thus
settle below the displayed set speed while its positive request balances grade and rolling/load
resistance. This is a physical interpretation of the repeated post-wire residual, not a fitted
vehicle model or proof that every uphill interval is at equilibrium. The mixed route 26 interval
is not used for this inference. A sustained near-level hold remains required before considering
planner calibration or a Honda-specific change.

The planner's combined-acceleration turn limit is not the active limiter in the route-22
under-set windows. Recomputing `get_cruise_accel()`'s speed/steering terms from the cached
full-rate signals gives the following medians:

| window | speed | steering angle | lateral accel | speed-only max accel | turn-limited max accel | request |
|---|---:|---:|---:|---:|---:|---:|
| 08:39:11 | 38.3 mph | 1.8 deg | 0.16 m/s2 | 0.92 m/s2 | 1.69 m/s2 | +0.28 m/s2 |
| 08:43:45 | 63.9 mph | 1.1 deg | 0.27 m/s2 | 0.75 m/s2 | 2.33 m/s2 | +0.32 m/s2 |
| 08:44:47 | 64.1 mph | 1.3 deg | 0.32 m/s2 | 0.75 m/s2 | 2.33 m/s2 | +0.25 m/s2 |

The request is below the speed-only limit in all three cases, so neither the lateral demand nor
the planner's combined-acceleration cap explains the residual. This is an additional attribution
check, not a reason to raise the cruise request: the command still reaches the gas domain and the
remaining mismatch is after the wire under positive grade/load.

The logged dashboard-cluster speed does not explain the observation as a telemetry artifact. The
cluster is quantized to whole displayed mph, but it remains below the corresponding set speed in
the same windows:

| window | set speed | controller `vEgo` | cluster speed | set minus `vEgo` | set minus cluster |
|---|---:|---:|---:|---:|---:|
| 08:39:11 | 38.90 mph | 38.25 mph | 38.00 mph | 0.65 mph | 0.90 mph |
| 08:43:45 | 64.62 mph | 63.91 mph | 64.00 mph | 0.71 mph | 0.62 mph |
| 08:44:47 | 64.62 mph | 64.07 mph | 64.00 mph | 0.55 mph | 0.62 mph |

`vEgoCluster` is display telemetry and is not the planner input; this cross-check only shows that
the one-mph report is not caused solely by a controller-speed/display conversion mismatch.

### Reusable under-set-speed diagnostic (2026-09-06)

`validate_log.py` now emits an ungraded `under-set speed (diagnostic)` readout. It selects only
moving, engaged, no-pedal frames where the displayed `carControl.hudControl.setSpeed` is visible,
the held `longitudinalPlan` source is `cruise`, `hasLead` is false, `allowThrottle` is true, and
the speed is 0.5-1.5 mph below set with a positive `carControl.actuators.accel` request. Runs must
last at least two seconds. The readout reports the qualifying duration, gap, controller request,
achieved `aEgo`, pitch, and achieved-minus-request residual; it is a route-local exposure counter,
not a pass/fail threshold or permission to tune. The plan booleans use zero-order hold, matching
the planner-to-controller timing boundary.

The exact-source candidate routes were revalidated with this diagnostic:

| route | qualifying sec / events / longest | gap (mph) | request | aEgo | pitch (rad) | aEgo-request |
|---|---:|---:|---:|---:|---:|---:|
| `00000020` | 13.95 / 3 / 5.41 | 0.72 | +0.320 | -0.031 | +0.068 | -0.406 |
| `00000021` | 17.20 / 3 / 6.74 | 0.59 | +0.264 | +0.004 | +0.050 | -0.290 |
| `00000022` | 14.04 / 3 / 8.30 | 0.67 | +0.299 | -0.000 | +0.055 | -0.297 |
| `00000024` | 32.70 / 5 / 15.11 | 0.63 | +0.282 | +0.003 | +0.050 | -0.283 |

The corresponding gas-domain request-to-wire RMS values are 0.0071, 0.0069, 0.0063, and 0.0058
m/s2, respectively. This extends the repeated attribution: the command reaches `ACCEL_COMMAND`
and the vehicle settles near zero acceleration under positive grade/load. The diagnostic still
does not supply the missing near-level road exposure, so the current Honda path remains unchanged.

The same diagnostic was also run against the earlier `f52c828fdf49` nested source on routes
`0000006d`, `0000006e`, and `00000070`. A source diff against current `fb8a8f98e6` shows no
Odyssey longitudinal output change (the remaining differences are comments, a lateral-only
commented block, and the generic Bosch stop-state placement repaired separately); those routes
can therefore provide longitudinal context but are not mixed into the current road-tune decision.
Route `0000006d` supplied 15.15 s over two episodes at a 1.09 mph gap, `+0.490 m/s2` request,
`-0.007 m/s2` achieved acceleration, and `+0.086` rad pitch. Route `00000070` supplied 24.20 s
over three episodes at a 0.67 mph gap, `+0.298 m/s2` request, `-0.010 m/s2` achieved acceleration,
and `+0.048` rad pitch. Route `0000006e` supplied no qualifying episode. The older routes reinforce
the uphill correlation, while their short/thin exposures still do not replace the requested
near-level road hold.

### Legacy Sunnypilot vendor provenance backfill (2026-09-06)

The local full-rate captures `00000025--2db306153b`, `00000026--8d38fff2db`, and
`00000046--86d6f4b278` record clean Sunnypilot staging parents but their parent trees contain
`opendbc_repo` as a vendored directory rather than a submodule gitlink. Their release messages
identify upstream bases `5ecd05aedf247ee3a09796546cca5993bc8eb6ce` and
`b742b96c4482aced861525c33c55e1374aa8bb0c`; both bases pin the same nested opendbc commit
`06743dfb39cff0f0cd5ddae244afef42891f4b93`. Comparing the vendor tree with that nested commit
matched every source path; only the nested repository's GitHub workflow files were absent from the
vendor snapshot. The parents contain the older tinygrad small-model bundles, identified by
manifests `d8263ee9860594d2806b0dfd1bfd17528b0ba2a4` (routes 25/26) and
`0cfbf08886fca9a91cb753ec8734c84fcbe52c9f` (route 46).

`validate_log.py` now resolves this historical vendor format only when the parent is clean, the
message has a Sunnypilot release signature and a full `master commit`, and that base resolves to a
real opendbc gitlink. It also records the tinygrad manifest as the small-model pointer and maps
`06743dfb39cf` to the upstream raw `-0.20` domain semantics. The fallback is mutation-tested: a
deliberately broken Sunnypilot signature makes the focused test fail, and the restored suite passes
42 tests. Revalidation backfilled exact provenance for all three rows without changing source or
road conclusions. Route 25 still shows the old raw-split transition burst (120 edges, 24/10 s);
route 26 shows 323 edges (36/10 s) and one 2.59 s, 0.64-mph below-set diagnostic interval but
mixed Experimental/personality state; route 46 is thin at 2.8 engaged minutes. These remain
historical context, not a new candidate or a clean comparison against current `ody-op`.

### Additional retained vendor-route provenance backfill (2026-09-06)

The remaining locally retained routes whose clean parent objects were available were revalidated
without changing production code. Routes `00000024--6cf011019c`, `00000027--381c48225a`,
`00000028--678a1d5028`, `00000029--b43171dfe1`, `0000002b--86502a744c`,
`0000002c--ee62c7d75b`, `0000002d--f6f9c44676`, and `0000002e--a9907b2070` resolve to the
Sunnypilot parent `b2ee22854616343b46f285d531007a0557232809`, nested opendbc
`06743dfb39cff0f0cd5ddae244afef42891f4b93`, and tinygrad small-model manifest
`d8263ee9860594d2806b0dfd1bfd17528b0ba2a4`. Routes `00000047--50d32bfcd3`,
`00000048--b890dd0d9a`, `00000049--fd8b934bd3`, and `0000004a--b8518d776c` resolve to
Sunnypilot parent `3277b0445f66af83b20ceb89b3336e4d4c051612`, the same nested opendbc commit,
and manifest `0cfbf08886fca9a91cb753ec8734c84fcbe52c9f`. All twelve are stock-radar captures with
zero engaged minutes, so they improve reproducibility only; they add no command-following or road
quality evidence. Route 28's two recorded controlsd crash markers remain historical context.

Two one-segment captures (`00000013--dee84c0d75` and `0000001b--3ae9413062`) were also rechecked,
but their logs do not contain a model pointer or a complete operating-state identity. They remain
explicitly provenance-incomplete rather than being inferred from the branch name. The ledger now
has 68 exact-provenance rows; no comparison or tuning decision changed. Targeted fetches of
representative missing parent hashes from `origin` and `sunnypilot` returned no remote ref, so the
remaining historical rows are intentionally not assigned guessed source identities.

### Under-set-speed powertrain cross-check (2026-09-06)

The same qualifying windows were cross-checked against the decoded Honda powertrain messages to
make sure the positive request was not merely an inactive or zero-torque gas-domain command. The
table reports medians over each interval; `GAS_COMMAND` is the opaque Honda count and
`ENGINE_TORQUE_ESTIMATE` is the received powertrain estimate.

| route / interval (s) | gap (mph) | request / wire (m/s2) | aEgo (m/s2) | pitch (rad) | GAS_COMMAND | torque estimate | rpm | target gears |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `00000022` 1247.21-1249.95 | 0.68 | +.305 / +.310 | -.006 | +.070 | 459 | 498 | 1958 | 5-6 |
| `00000022` 1518.90-1527.22 | 0.71 | +.316 / +.320 | +.006 | +.055 | 469 | 458 | 1777 | 7-9 |
| `00000024` 152.79-167.95 | 0.66 | +.294 / +.290 | +.004 | +.056 | 449 | 452 | 2166 | 7-9 |
| `00000024` 1717.30-1721.34 | 0.61 | +.272 / +.270 | -.000 | +.047 | 429 | 406 | 1657 | 8-9 |
| `00000070` 1264.93-1273.91 | 0.66 | +.296 / +.300 | -.003 | +.048 | 452 | 440 | 1904 | 7-9 |
| `00000070` 1274.28-1285.20 | 0.66 | +.294 / +.290 | -.002 | +.048 | 449 | 445 | 2277 | 7-8 |

These windows all carried a live gas command and positive estimated engine torque, although some
include normal target-gear changes. This rules out the simplest domain-arbitration failure (gas
silently inactive) but does not identify a torque calibration, shift-transient, or grade-estimation
error. It also does not prove a steady-state level-road deficit: the qualifying archive remains
predominantly uphill. **Decision: keep the current Honda translation and raw `ACCEL_COMMAND`; do
not add a gas multiplier or gear/torque compensation.** The next discriminating exposure remains
a sustained near-level, no-lead hold with the same positive request.

### Route 00000028 lead/grade trace (2026-09-06)

The new full-rate route `00000028--342d541799` starts at 2026-09-06 12:44:42.8 local, so the
reported 13:15-13:19 interval is approximately route-relative 1817-2057 seconds. Its exact
provenance is parent `18377cc4357cc4a5e8f1fef3adb579a063345db5` on
`tmp/ody-op-stop-intent-road-20260905`, nested opendbc `825642c4218b3c71f74053264882e40971cc10f5`,
and small model `f0672eab48566d395e49407293579b817f3e9d22`; Alpha Long was enabled, Experimental
was off, and personality was standard. The parent includes the temporary stopped-lead stop-intent
planner candidate later removed from `ody-op`; its screen requires ego speed below 1.0 m/s and a
near-stopped lead within 6.5 m. None of the reported 13:15-13:19 hill windows is near that gate
(ego is roughly 28-50 mph), so those traces exercise the same planner/Honda path as current
`ody-op`. The nested difference is only the generic Bosch stop-state placement, with no Odyssey
longitudinal output change; the route is useful for command/response evidence but is not a
production-baseline promotion.

At 13:15:01-04 a selected vision lead was about 30 to 16 m ahead, with relative speed about
`-4.35` to `-1.51 m/s` and lead speed about 13.5 to 11.3 m/s. OpenPilot reduced the request from
roughly `-0.90` to `-1.67 m/s2`; `ACCEL_COMMAND` followed it and `aEgo` reached about `-1.9 m/s2`.
That large uphill/lead slowdown is a real upstream following command in response to a rapidly
closing lead, not a Honda CAN command being lost. A second closure at 13:15:35-40 shows the same
planner-to-wire agreement.

The reported downhill speed-up contains an explicit cruise-speed input that must be accounted for
before judging the planner. Just before 13:17:24.5, the set speed was 63.8 km/h (39.64 mph), ego
speed was about 39.7 mph, and the request was negative. `carState.buttonEvents` then records
`accelCruise` pressed at route-relative 1961.684 s and released at 1963.373 s; during that hold
the set speed changed to 80.0 km/h (49.71 mph). The planner consequently changed its cruise
request from near zero to about `+0.97 m/s2` while pitch was negative, the wire matched, and
`aEgo` reached about `+1.35 m/s2`. This first divergence is the recorded cruise-button/set-speed
input, not a Honda CAN translation error. If that button hold was not intentional, it is a
separate steering-wheel-button/CAN-input question. On this port `accelCruise` is Honda
`CruiseButtons.RES_ACCEL`, and the upstream cruise helper uses that event to raise the local set
speed. A fresh zero-order-held decode of bus-1 `SCM_BUTTONS` (CAN ID 662) independently shows
`CRUISE_BUTTONS=4` for that hold, then `0`, followed by `CRUISE_BUTTONS=2` for the cancel event.

The same interval then records `cancel` at 1965.010 s (active goes false) and `accelCruise` at
1970.162 s (re-engagement). After re-engagement, the selected lead closed from roughly 93 to 35 m;
the source moved through lead2/lead1, the request changed from about `+0.75` to `-1.18 m/s2`, and
the vehicle braked after reaching about 50 mph. That later braking is still planner/lead timing
plus grade and actuator response, but it is downstream of the set-speed change and disengagement,
not an independent no-input downhill test. At 13:18:40-52, a separate positive request on an
uphill segment also took time to overcome the already-negative achieved acceleration, showing
plant lag rather than a dropped command.

Route-level attribution is consistent with those traces: planner-to-`carControl` RMS was 0.011
`m/s2`, gas-wire RMS was 0.008, brake-wire RMS was 0.017, and there was no sustained sign
disagreement. Closed-loop following was not perfect: achieved gas and brake RMS were about 0.268
and 0.262 `m/s2`, with visible grade/actuator lag and overshoot. The log has two takeovers and a
recorded brake press at 13:16:18, but no pedal edge in the 13:17-19 speed-up segment; it does
record the cruise-button hold and subsequent cancel, so the exact reported manual-brake instant
cannot be assigned from this route alone.

**Decision: keep the current Honda translation, raw `ACCEL_COMMAND`, and `-0.30` brake-domain
entry; make no pitch compensation, gas multiplier, or brake-PID change from this route.** The
uphill event is commanded lead following. The downhill event is not a clean planner-only test
because the driver-input stream raised the set speed and then cancelled/re-engaged control; if
that input was unintended, investigate the button path first. Routes
`00000025`-`00000027` are thin context (respectively one short under-set interval, no under-set
exposure with brake-domain cycling, and no engaged control), so they do not change that decision.

### Upstream/model and peer-domain audit (2026-09-06)

The exact current upstream refs are parent `c51e3e5a71d6ea25e59c0683d683c1092c7c3f69` and nested
opendbc `3e92d112129507debe45364891954db70238997a`. The parent is seven commits ahead of `ody-op`:
the only control-relevant change is the `cinque terre` **big** driving-model pointer
(`big_driving_supercombo.onnx`, LFS SHA-256 `e8d821733be15ebe9e27498bc27ad8bbbd741980ece37d77f377294010b8ff28`,
replacing `1791d5940b2c048d0639813426dd2cf1d6f2a6727ed51e17c8bcea8bbe754123`). The small
`driving_supercombo.onnx` pointer is unchanged, and the other six parent commits are Cabana UI
changes. Nested opendbc is three commits behind master; they touch VW harness/docs and a 2027 HRV
fingerprint, not Honda longitudinal translation.

The Sunnypilot model-package comparison is recorded in the preceding model-refresh section:
staging packages a four-chunk Tinygrad artifact while route `00000028` used the unchanged ONNX
small model. That is a runtime/package difference, not evidence of new small-model weights or
improved Odyssey hill behavior, and it remains outside the `ody-op` baseline.

Peer-port inspection found no transferable Honda-specific grade correction. Ford adds pitch only to
its brake/pre-charge-domain decision while preserving the requested acceleration values, and VW
uses explicit vehicle-specific stopping/hold/start flags. Those mechanisms depend on their OEM
signals and do not establish a Honda `ACCEL_COMMAND` multiplier or pitch rewrite. **Decision: keep
the Honda raw-command/domain implementation unchanged; do not import peer pitch or hold logic for
the route-28 downhill behavior.**

### Route 28 no-input downhill screen (2026-09-06)

As a route-local check, I excluded a two-second window around every recorded cruise button edge
and the subsequent cancel/re-engagement, then screened moving, engaged, no-pedal, negative-pitch
frames. The remaining downhill mask contained 111.7 s, but no clean no-lead positive-request
exposure. The no-lead negative-request portion supplied 12.4 s with median request `-0.187
m/s2`, mean achieved `aEgo -0.040 m/s2`, and mean achieved-minus-request `+0.136 m/s2`; the
longest interval (route-relative 2070.59-2074.47 s) had request `-0.203`, achieved `-0.037`,
and pitch `-0.027` rad. A near-zero-request no-lead mask supplied only 3.5 s. These cases show
the vehicle did not accelerate against a positive OpenPilot request in a clean downhill window;
they do show that a modest negative request can be partly consumed by downhill load and Honda
response. This is closed-loop context, not enough exposure to change the Honda command path or
to claim a brake-tuning benefit.

### Sunnypilot fallback Alpha Long default (2026-09-06)

The earlier staging-verifier note above records its historical `AlphaLongitudinalEnabled=1`
expectation. The current **Recover device on sunnypilot/staging** and **Verify device on
sunnypilot/staging** tasks now explicitly set and require `AlphaLongitudinalEnabled=0`, preserving
Sunnypilot as the non-Alpha-Long known-good fallback between Odyssey experiments. This changes
only deployment configuration; it does not change `ody-op` production behavior or the device until
the recovery task is run.

### Retire the PR-38547 model arm and resume the stopped-lead arm (2026-09-07)

The post-reflash route `00000000--6d7dd19370` was recorded on the temporary
`tmp/ody-op-pr-38547-test` parent `aa7b1c4a0e54`, nested opendbc `fb8a8f98e6e5`, with Alpha Long
and Experimental mode enabled. Its 18.9 engaged minutes carried the planner request through
`carControl` and the Honda wire (`plan→carControl` RMS `0.007`, request→wire RMS `0.006`
m/s2). The principal no-lead uphill deficit instead had a median request of only about
`+0.08 m/s2` while the vehicle was roughly 24 mph below set speed; this is upstream
model/planner/grade behavior, not a lost Honda command. The branch changed only model LFS
pointers and `LAT_SMOOTH_SECONDS` (`0.0→0.1`), with no longitudinal or Honda CAN change.

**Decision: RETIRE the PR-38547 model arm.** Its local and remote branches were deleted after
the validation row was preserved in `ody-op` commit `d7751db297`; no model or lateral smoothing
change was promoted.

The stopped-lead planner arm remains separate and road-pending. Route `00000022--34677013ac`
is its one attributable complete stop-intent exposure (about `0.70 s` earlier stop intent and
wire-followed stopping ramp); routes `20`, `21`, `23`, `24`, and `28` supplied no qualifying
candidate trigger, so they neither prove benefit nor retire the arm. The device is restored to
that published supervised branch at parent `18377cc4357c` with nested opendbc `825642c4218b`;
`UpdaterTargetBranch` matches, Alpha Long is `1`, Experimental mode is `0`, both repositories
are clean, and no systemd service is failed. Continue only with deliberately exposed stationary-
lead, moving-lead-release, and no-lead crawl-stop cases; keep the uphill question separate.

### Current response-attribution focus (2026-09-07)

The current work is to explain the remaining difference between OpenPilot's requested motion and the
Odyssey's physical response without confusing it with a command-path failure. The latest full-rate
diagnostic route `00000000--6d7dd19370` carried the request through `carControl` and Honda CAN with
small planner-to-controller and request-to-wire residuals (about `0.007` and `0.006 m/s2`). It still
measured achieved-response RMS of about `0.218 m/s2` in the gas domain and `0.264 m/s2` in the brake
domain. That route was an Experimental model-arm screen and is not a production A/B or a tuning
verdict; it is a response-diagnosis lead.

Use the following ownership sequence for every new symptom:

1. Verify provenance, full-rate sampling, and zero-order-held CAN/domain state.
2. Compare planner output with `carControl`; if they diverge, assign the issue to OpenPilot's
   planner, model, or `longcontrol` rather than Honda.
3. Compare `carControl` with numeric CAN and active gas/brake domain; if they diverge, assign the
   issue to the Honda translation or safety boundary.
4. If command and domain agree, characterize the response with an estimated delay and separate gas,
   brake, and coast. Condition the comparison on request magnitude, speed, pitch/grade, gear/shift,
   lead state, and driver input, and cross-check the relevant powertrain and brake signals.
5. Only a repeatable residual after those controls can justify Honda actuator calibration. Do not
   reshape `ACCEL_COMMAND` or import a peer-brand mechanism to hide a response residual.

The next analysis is therefore read-only response characterization on the current baseline, followed
by a matched controlled or ordinary-road comparison if a specific Honda-side mechanism is identified.
If the residual disappears after conditioning, the correct decision is no production change. Keep
stopped-lead/planner behavior, gas response, brake response, and lateral response as separate evidence
streams with separate keep/change/retire decisions.

### Route-28 stopped-lead exposure clarification (2026-09-07)

A source-aware full-rate, zero-order-held rescreen of the stopped-lead child found the same
approximately `0.70 s` candidate-only stop-intent window on route `00000022--34677013ac` already
recorded above. It also found three inferred candidate-only windows on route
`00000028--342d541799`, totaling about `2.20 s`. These are reconstructions from the published
`longitudinalPlan.shouldStop` and lead fields; the candidate does not publish a dedicated trigger
telemetry field, and `shouldStop` is aggregated across planner candidates.

The route-28 windows involved slow-moving leads: one eventually approached a near-stop, one released
as the lead moved away, and one had lead speed spanning approximately zero to `0.20 m/s`. They do not
form a clean, independently matched stationary-lead complete-stop exposure. Therefore route 28 does
not count as the second qualifying promotion example, and the stopped-lead child remains road-pending.
The preceding “no qualifying candidate trigger” wording means no qualifying complete/independent
exposure, not zero predicate frames. No production source, candidate threshold, or baseline decision
changed.

### Stock-2560 high-authority lateral rescreen (2026-09-07)

A separate source-aware rescreen checked the stock lateral path on exact full-rate routes using a
clean mask of `lat_active`, speed at least `70 km/h`, no steering pedal input, no temporary or
permanent steering fault, finite torque-controller actual/desired acceleration, and controller CAN
output at `+/-2560`. Route `0000001d--2e324ec2ce` was the `ody-op` baseline (parent
`784b05ce670a`, nested opendbc `825642c4218b`); routes `00000020--f8047564cf`,
`00000021--9cdb50c5da`, `00000022--34677013ac`, and `00000024--8ed656b4ba` were the supervised
child at parent `71b708453fb4`; route `00000028--342d541799` was the same child source at parent
`18377cc4357c`. All used nested opendbc `825642c4218b` and the stock `+/-2560` map.

The actual lateral acceleration was compared with the desired setpoint both at the same timestamp
and after moving the measured response 0.15 s forward. The latter is a diagnostic alignment with
the configured actuator delay, not a proven physical delay estimate:

| route | clean cap sec | same-time RMS / under median | +0.15 s RMS / under median |
|---|---:|---:|---:|
| `0000001d` | 3.16 | 0.357 / +0.288 | 0.326 / +0.292 |
| `00000020` | 2.22 | 0.112 / +0.076 | 0.107 / +0.061 |
| `00000021` | 2.92 | 0.378 / +0.032 | 0.336 / +0.026 |
| `00000022` | 6.45 | 0.632 / +0.286 | 0.576 / +0.233 |
| `00000024` | 15.55 | 0.499 / +0.181 | 0.460 / +0.165 |
| `00000028` | 0.40 | 0.043 / -0.015 | 0.056 / -0.037 |

At representative route-22 cap intervals, `carControl` and `carOutput` torque were both at the
normalized limit and `torqueOutputCan` was `+/-2560`; for example, a 1.71 s window requested
approximately `+1.60 m/s2` while measured lateral acceleration was `+0.74 m/s2`, and a later 1.42 s
window requested `+1.58` while measuring `+1.34 m/s2`. The source path also packs the same
`apply_torque` value recorded in `torqueOutputCan`, so these intervals do not show a controller-to-
CAN numeric loss. The first actionable boundary is therefore stock-map authority versus Honda
response, not a DBC or transport mismatch. Route 22 has one steering fault and many overrides at
route level, but the clean cap mask excludes those frames; route 24 supplies the longest clean
exposure without a steering fault.

This is a repeatable authority symptom, not a lane-tracking result. The prior nonlinear 3840 arm is
still retired, and the current stopped-lead child must not be changed to combine the hypotheses.
**Decision: keep the stock-2560 production map and open only a separate, temporary lateral arm if
an isolated 2560-versus-nonlinear-3840 road comparison is available.** That arm must match speed,
desired lateral demand, road direction, and authority, and must grade actual-versus-desired response,
steering faults, overrides, and driver feel. No 3840 promotion or production change follows from
this rescreen alone.

### Exact model-to-lateral-CAN trace (2026-09-07)

A native-timestamp trace was run independently of the cached lateral metrics on routes
`0000001d--2e324ec2ce`, `00000020--f8047564cf`, `00000021--9cdb50c5da`,
`00000022--34677013ac`, `00000024--8ed656b4ba`, and `00000028--342d541799`. The first route is
the `ody-op` source at parent `784b05ce670a0712d8439ee6aa369605c789b303`; routes `20` through `24`
are the supervised child at parent `71b708453fb4564be21da783cb2036776dcc3573`; route `28` is the
same child after the documentation refresh at parent `18377cc4357cc4a5e8f1fef3adb579a063345db5`.
Every route used nested opendbc `825642c4218b3c71f74053264882e40971cc10f5`, the small model
`f0672eab48566d395e49407293579b817f3e9d22`, and native approximately 100 Hz `carControl` and
approximately 20 Hz `modelV2`. None published `lateralManeuverPlan`, so the controlsd source branch
was the model action on every route.

The model action was zero-order-held onto the `carControl` grid, as controlsd does when it consumes
the latest model decision. Model-to-`carControl.actuators.curvature` lateral-acceleration RMS was
`0.0052`, `0.0063`, `0.0098`, `0.0062`, `0.0108`, and `0.0036 m/s2` respectively on the six
routes, after requiring lateral-active, at least 5 m/s, no steering override, and no steering fault.
The median error was effectively zero on every route, and fewer than `0.36%` of clean samples
exceeded `0.05 m/s2`. `carControl.actuators.curvature` and `controlsState.desiredCurvature` also
matched to the trace precision. The controller's delayed desired-lateral-acceleration field is a
separate setpoint after the configured roughly `0.35-0.36 s` lateral delay; it must not be mistaken
for a plan-to-`carControl` divergence.

The route-22 raw `sendcan` trace contained `279,157` direct bus-1 `STEERING_CONTROL` frames, with
decoded `STEER_TORQUE` ranging from `-2560` to `+2560`. The current Honda source rate-limits the
`carControl` torque, converts it to `apply_torque`, stores that same value in
`carOutput.actuatorsOutput.torqueOutputCan`, and passes the same value to
`hondacan.create_steering_control`; the DBC then packs it as `STEER_TORQUE`. Thus the repeatable
breakdown is not model-to-controller, controller-to-`carControl`, or a port/DBC numeric loss.
It remains the stock-2560 authority/physical-response boundary described above. **Decision: keep
the lateral path and the stopped-lead child unchanged; do not combine a lateral authority arm with
the longitudinal planner experiment.**

### Exact longitudinal plan-to-CAN and response screen (2026-09-07)

The same routes were traced with the published `longitudinalPlan.aTarget` held at its native 20 Hz
publication times before comparison with the 100 Hz `carControl` grid. The exact-ZOH plan-to-
`carControl` RMS and zero-order-held `ACCEL_COMMAND`-to-`carControl.actuators.accel` RMS were:

| route | plan → `carControl` RMS | wire → `carControl` RMS |
|---|---:|---:|
| `0000001d` (`ody-op`) | 0.0027 | 0.0112 |
| `00000020` | 0.0013 | 0.0071 |
| `00000021` | 0.0019 | 0.0081 |
| `00000022` | 0.0860 | 0.0067 |
| `00000024` | 0.0017 | 0.0061 |
| `00000028` | 0.5181 | 0.0111 |

The route-22 plan-to-`carControl` residual is localized to a 4.13 s `LongCtrlState.stopping`
interval at about 0.3 mph: `shouldStop` was true, the plan ranged from `-0.80` to `+0.09 m/s2`,
and `carControl` ranged from `-2.00` to `-0.85 m/s2`. Route 28 contains the same state-machine
behavior for 63.46 s at standstill and another 6.96 s near 0.2 mph. The current `LongControl`
implementation intentionally holds and ramps its previous output while `shouldStop` is true; this
is an OpenPilot state-machine boundary, not a Honda CAN divergence. The small wire residuals on
those routes show that the Honda port carried the resulting `carControl` request through
`ACCEL_COMMAND` and its selected domain. These stopping intervals therefore do not count as
evidence for gas/brake translation changes or as independent stopped-lead benefit exposures.

On stable, material-command samples with driver input excluded, gear transitions excluded, and
speed above 5 m/s, a diagnostic response-lag sweep found the lowest `aEgo - carControl` RMS at
approximately `+0.4` to `+0.8 s` in the gas domain on the six routes. The best brake lag varied
from approximately `+0.3` to `+1.5 s`, with thin brake exposure on most candidate routes. Gas
residual medians changed sign across routes (`+0.026`, `+0.101`, `-0.122`, `-0.107`, `-0.138`,
and `-0.028 m/s2` at each route's best lag), so this is not a repeatable static mapping error.
The screen did not correct `aEgo` for grade or establish a matched closed-loop A/B; it is only a
response-characterization lead. **Decision: keep raw `ACCEL_COMMAND`, the current gas/brake domain
selector, and the Honda port unchanged.** A future actuator change needs matched full-rate drives
conditioned on request, speed, grade, gear, lead state, and response timing; it must not reshape the
OpenPilot request based on these unmatched residuals.

### Live supervised-arm recheck (2026-09-07)

The comma device still runs `tmp/ody-op-stop-intent-road-20260905` at parent
`18377cc4357cc4a5e8f1fef3adb579a063345db5`, nested opendbc
`825642c4218b3c71f74053264882e40971cc10f5`, with the updater idle, Alpha Long enabled, and
Experimental mode disabled. Its private inventory still contains only segments of
`00000000--6d7dd19370`, the retired PR-38547 model-arm route; no route recorded after the stopped-
lead child was activated. The child therefore has not gained a second qualifying stopped-lead
exposure. **Decision: keep the child available only for a deliberately exposed, human-supervised
stationary-lead, moving-lead-release, or no-lead crawl-stop run; do not continue it for undirected
mileage. Return to `ody-op` when that targeted evidence is unavailable, and preserve `ody-op` as the
rollback baseline.**

### Planner-decision resampling correction (2026-09-07)

The exact plan-to-control audit found that the offline diagnostic path was linearly interpolating
`longitudinalPlan.aTarget`. `controlsd` consumes the latest published planner decision through
`SubMaster`, so `aTarget` must be held until the next plan publication; interpolation invents an
upstream command and can hide a real `LongControl` state-machine transition. `extract.py` now uses a
zero-order-held planner target and bumps its cache schema from 5 to 6; `inspect_following.py` and
`validate_log.py` use the same rule.

The new helper was mutation-verified: replacing the hold with `np.interp` made the focused
transition test fail on both interpolated samples, then restoring the hold passed the focused test
and the full extraction/validation tooling suite (`46 passed`). The corrected validator was rerun
on the matched baseline and supervised-child routes `0000001d`, `00000020`, `00000021`, `00000022`,
`00000024`, and `00000028`, updating the authoritative ledger. `git diff --check` passed. No
production controller, Honda port, DBC, or device branch changed.

This correction makes the route-22 and route-28 low-speed plan-to-`carControl` residuals visible as
the existing stopping-state behavior; it does not create a Honda command-path mismatch or a second
stopped-lead promotion exposure. **Decision: keep the diagnostic correction, keep `ody-op` as the
rollback baseline, and continue the temporary child only for a deliberately exposed supervised
event. Do not spend general road mileage on the child.**

### Conditioned response screen (2026-09-07)

A read-only screen used the same six exact-source full-rate routes and compared future `aEgo` with
the held `carControl.actuators.accel` request at fixed response lags of `0.4`, `0.6`, `0.8`, and
`1.0 s`. Samples required motion above `5 m/s`, a material request of at least `0.10 m/s2`, no
driver gas or brake input, and no sample within one second of a reported target-gear transition.
Gas and brake domains came from the held `GAS_COMMAND` and `BRAKE_REQUEST` values, so this screen
did not infer the domain from the numeric acceleration request.

At the common `0.6 s` alignment, gas-domain residual medians in route order
`0000001d`, `00000020`, `00000021`, `00000022`, `00000024`, and `00000028` were respectively
`+0.105`, `+0.112`, `-0.122`, `-0.106`, `-0.117`, and `+0.081 m/s2`. Within-route terrain splits
also changed sign: route `0000001d` was `-0.002` uphill versus `+0.182` level, route `00000022`
was `-0.118` versus `+0.121`, and route `00000028` was `-0.082` versus `+0.152`. Brake exposure
was substantial only on routes `0000001d`, `00000020`, and `00000028`; their corresponding all-
brake medians were `-0.069`, `-0.122`, and `-0.044 m/s2`, while the other routes were too thin for
a brake conclusion.

The route-to-route sign changes and terrain dependence persist across the lag sweep. This is a
response-characterization lead, not a repeatable static gas map, grade feedforward, or brake map
error; it is also not a matched closed-loop A/B. **Decision: keep raw `ACCEL_COMMAND`, the current
gas/brake domain selector, and the Honda port unchanged.** Any actuator calibration must use matched
full-rate road evidence with a fixed request profile and explicit speed, grade, gear, lead, and
timing conditioning.

### Honda ECU telemetry boundary (2026-09-07)

An exact-DBC received-CAN probe was run on the same six full-rate routes. The pinned
`acura_rdx_2020_can_generated` source decodes `GAS_PEDAL_2`, `VSA_STATUS`, and `GEARBOX_AUTO`, but
does not contain `BRAKE_PRESSURE`; no brake-pressure claim is made from these logs. Strict
checksum/counter parsing accepted the available received frames. The payload semantics were still
not repeatable across routes: baseline route `0000001d` and child route `00000020` carried nonzero
`CAR_GAS`, engine-torque, and shift-activity values, while routes `00000021`, `00000022`,
`00000024`, and `00000028` carried zero/sentinel values over their gas-domain exposure. The DBC
`COMPUTER_BRAKING` bit was materially present only on the baseline route; its p95 was zero on the
other five routes, including the routes with brake-domain exposure.

These are valid decoded payloads, but their route-dependent availability and semantics make them
unsuitable as a matched Honda-actuator response measurement. The authoritative command boundary
remains held `ACCEL_COMMAND`/`GAS_COMMAND`/`BRAKE_REQUEST` versus `carControl`, and the physical
response remains `aEgo` conditioned on the road variables above. **Decision: do not infer a gas map,
brake-pressure map, or ECU correction from these labels; keep the Honda command path unchanged and
require a future matched route with independently valid actuator telemetry before assigning a
Honda-side response change.**

### DBC provenance alignment with current Sunnypilot staging (2026-09-07)

The `ody-op` root at `8991a440a9e85fd896bae6de7df2f982106276a7` pins nested `opendbc` at
`fb8a8f98e6e592d5fae1d3b518eadac805242fbe`. The current local
`refs/remotes/sunnypilot/staging` ref is `40d6afd30042e9a1bb452f42d3b6e67ecd00c98f`; its tracked
`opendbc_repo` tree has the same generator and all seven imports used by
`acura_rdx_2020_can_generated`: `_honda_common.dbc`, `_bosch_2018.dbc`, `_bosch_radar_acc.dbc`,
`_lkas_hud_5byte.dbc`, `_bosch_standstill.dbc`, `_steering_sensors_b.dbc`, and
`_gearbox_common.dbc`. The source SHA-256 values match the `ody-op` nested revision for the base
`acura_rdx_2020_can.dbc`, the generator, and each imported file.

Therefore the DBC definitions used for the prior trace align at the signal-definition level across
these exact revisions: `ACC_CONTROL` (`ACCEL_COMMAND`, `GAS_COMMAND`, `BRAKE_REQUEST`),
`STEERING_CONTROL` (`STEER_TORQUE`), `GAS_PEDAL_2`, `VSA_STATUS` (`COMPUTER_BRAKING`), and
`GEARBOX_AUTO` have the same source names, message IDs, bit positions, widths, and scaling. This
does not establish Honda-port alignment: the `hondacan.py` and platform files differ and remain a
separate runtime comparison. An older detached staging worktree at `7fbd9456` had an enum-only
`_gearbox_common` difference and is not evidence about current `sunnypilot/staging`. **Decision:
keep the DBC interpretation for these signals, do not change the DBC, and audit port/runtime
differences separately.**

### Current staging runtime comparison (2026-09-07)

After refreshing `refs/remotes/sunnypilot/staging` to `40d6afd30042e9a1bb452f42d3b6e67ecd00c98f`,
the DBC-source alignment remained unchanged, but the Honda runtime comparison was not identical.
Staging's `hondacan.py` retains Sunnypilot extension imports and generic Bosch gas/brake selection;
`ody-op` adds the Odyssey-specific stateful domain selector and passes explicit gas/brake-domain
selection while preserving the raw clipped acceleration request. Staging's `carcontroller.py` also
retains Sunnypilot mixins and gas-interceptor/button-management paths that are absent from `ody-op`.
The Honda safety file differs in interceptor/hybrid handling and the lateral enable boundary, while
the Odyssey platform still maps to `acura_rdx_2020_can_generated` in both source trees.

This is a source-level branch difference, not evidence that either runtime is better on the Odyssey.
It means the staging branch can validate DBC provenance but cannot serve as a command-path baseline for
the current `ody-op` road results. **Decision: keep the pinned `ody-op` Honda port and its isolated
domain behavior; do not transplant staging runtime code or attribute a DBC finding to it without a
separate full-rate command/CAN/road comparison.**

### Recent-looking route provenance recheck (2026-09-07)

The device retained route `00000000--6d7dd19370` with segment filesystem times on September 7,
which initially suggested a post-activation candidate drive. Pulling and validating the complete
private full-rate route resolved the ambiguity: its exact route provenance is
`tmp/ody-op-pr-38547-test` at parent `aa7b1c4a0e5464ea6bda9b1d52a4a8a94dbac9d3`, nested
`opendbc` `fb8a8f98e6e592d5fae1d3b518eadac805242fbe`, and `Experimental=true`. It began at
`2026-09-07T22:24:29Z`, with 29.99 logged minutes and 18.88 engaged minutes. The device’s current
stopped-lead branch is `18377cc4357cc4a5e8f1fef3adb579a063345db5`, so this route is not an exposure
of that candidate and cannot count toward its promotion or retirement screen.

The route remains useful historical full-rate evidence: the corrected validator measured small
wire residuals, 48 physical brake-domain edges with a 6/10-second peak, and no qualifying sustained
no-lead cruise exposure. Those observations belong to the retired PR-38547/model arm and must not
authorize a current Honda-domain or stopped-lead change. **Decision: retain the route as historical
evidence only; require a route whose embedded parent is `18377cc4…` for the stopped-lead candidate.**

### Current-parent candidate route full-rate screen (2026-09-08)

Route `00000001--55d5451393` completed its private full-rate pull and validation with exact clean
provenance: branch `tmp/ody-op-stop-intent-road-20260905`, parent
`18377cc4357cc4a5e8f1fef3adb579a063345db5`, nested `opendbc`
`825642c4218b3c71f74053264882e40971cc10f5`, and small model
`f0672eab48566d395e49407293579b817f3e9d22`. It contains 64.1 logged minutes and 14.1 engaged
minutes at native approximately 100 Hz `carControl` and 20 Hz planner rates. The route-wide mode is
mixed, but both qualifying candidate windows were enabled, non-Experimental, lead-source plans
with `e2e_should_stop=false` and vision-only selected leads (`radar=false`).

The source-aware, held-sample stopped-lead predicate was active for 5.74 s in two physical
episodes (four short held windows around state transitions). `longitudinalPlan.shouldStop` was true
for 5.13 s of that exposure (89.4%), versus 0/3.65 s on source-matched `ody-op` route `1d`,
0.70/8.85 s on route `1e`, and 0/0.60 s on route `1f` (stop seconds/predicate seconds). This
supports planner ownership of the stop-intent difference, not a Honda translation change. Around
the approximately 1528 s episode, the lead slowed to about `0.34 m/s` at a 5.1 m gap and then
accelerated to about `1.0 m/s`; the candidate stopped the Odyssey and released when the lead moved.
Around 2871 s, a lead at about 5.0 m and `-1.1 m/s` relative speed brought the Odyssey to a stop;
no-lead crawl-stop exposure occurred on this route.
Neither window had driver brake or gas input in the surrounding 13-second inspection window, so
the recorded stops were not driver-forced completions; the nine route-level brake takeovers occurred
elsewhere and remain separate response context.

The full-rate command path remained faithful: plan→`carControl` RMS was `0.0026 m/s2`,
`carControl`→wire RMS was `0.0076 m/s2`, and sustained sign disagreement was zero. The route's
separate response/watchlist findings were 39 physical brake-domain edges (peak 8/10 s, 24/min on
the short downhill exposure), 9 brake takeovers among 56 brake presses, and achieved jerk RMS
`0.357 m/s3` versus commanded `0.188` (1.9x). These identify physical/road-response context;
they do not show that the planner candidate changed the Honda port or DBC domain.

**Decision: KEEP the stopped-lead candidate as an inactive supervised child; do not promote or
change its predicate.** This is a second independent candidate exposure with a moving-lead release
case, but it does not complete the promotion gate: there is no qualifying no-lead crawl stop, no
matched route A/B, and the route-level takeover/harshness findings require separate response
analysis. Keep `ody-op` unchanged and require a deliberately exposed no-lead crawl-stop route plus
the matched planner-to-CAN trace before any promotion or retirement decision.

### Latest stopped-lead child route and 12:18 takeover (2026-09-08)

Route `00000008--7f195b6742` was recorded on the same clean supervised child: branch
`tmp/ody-op-stop-intent-road-20260905`, parent `18377cc4357cc4a5e8f1fef3adb579a063345db5`,
nested `opendbc` `825642c4218b3c71f74053264882e40971cc10f5`, and small model
`f0672eab48566d395e49407293579b817f3e9d22`. It began at approximately 11:57:57 CDT, contains
44.2 logged minutes and 21.9 engaged minutes, and ran with Alpha Long enabled, standard personality,
and Experimental mode disabled.

The reported 12:18 event is route-relative `1204.79 s` (approximately 12:18:02.8 CDT). Immediately
before the driver brake edge, the Odyssey was at about `0.52 m/s` (1.2 mph), the selected lead was
about `3.26 m` ahead, closing at `-0.13 m/s`, and the lead estimate was `0.39 m/s`. The planner had
relaxed to `-0.18 m/s2`; `carControl` and the decoded `ACCEL_COMMAND` both carried `-0.18 m/s2`,
`BRAKE_REQUEST=1`, and Honda `COMPUTER_BRAKING=1`. `longitudinalPlan.shouldStop` and model
`e2e_should_stop` were false at the takeover. After the driver brake, `longActive` dropped and the
zero command was expected; this is not evidence of a CAN value being lost before the takeover.

The child’s stopped-lead intent did not hold through the final approach. A brief
`longitudinalPlan.shouldStop` interval occurred around `1201.42-1201.75 s`, then cleared while the
lead remained close and closing. The held full-rate predicate flickered as the selected lead and
near-stop lead-speed estimate moved around its `0.35 m/s` threshold; it did not maintain stop intent
through the `3.3 m`/`1.2 mph` approach. The request consequently relaxed from roughly `-1.5` to
`-0.18 m/s2` before the takeover. This is the first actionable divergence: the planner/temporary
stop-intent state did not sustain the required stop decision. The command and Honda domain remained
faithful, with physical response lag as a secondary contributor.

The route had three brake takeovers, 95 physical brake-domain edges, and felt jerk RMS `0.379 m/s3`
versus commanded `0.244 m/s3`. These route-level findings are not a controlled comparison proving
that the child caused every event, but the 12:18 takeover is sufficient to fail the child’s road
safety screen.

**Decision: RETIRE the current `tmp` road arm from further driving and return the device to
`ody-op`; do not promote or retune the predicate from the vehicle.** Preserve this branch and route
for offline analysis. Any successor must first test a single hypothesis for stable stop-intent
latching and safe release against lead acceleration, lead-estimate dropout, and no-lead inputs,
with mutation-verified tests and an isolated `ody-op` comparison before another supervised road run.

### Route 8 lateral attribution screen (2026-09-08)

The same exact-source route `00000008--7f195b6742` was screened independently for lateral behavior;
its provenance is the child parent `18377cc4357cc4a5e8f1fef3adb579a063345db5` with nested
`opendbc` `825642c4218b3c71f74053264882e40971cc10f5`. The root diff from `ody-op` changes only the
stopped-lead planner path and its tests; no lateral controller path was changed. The route's
validator measured 19.4 active lateral minutes, request/output absolute p95 `0.863/0.801`,
controller CAN absolute p95/max `2051/2560`, `0.3%` saturation, and zero steering faults. The
full-rate controller output followed the request with `0.072` RMS in its native normalized units.

At the stock CAN cap, the route supplied only `2.13 s` of high-authority exposure. Actual-versus-
desired lateral acceleration RMS there was `0.080 m/s2`, with sign-corrected under-response median
`+0.077 m/s2` on `98.6%` of samples. The command reached the stock wire cap without a CAN/fault
divergence, so this is a thin physical-response observation rather than evidence for a wider Honda
command range. It is not a matched lateral A/B and cannot justify restoring the retired 3840 arm.
**Decision: KEEP the stock 2560 lateral baseline; reopen authority only after a repeatable symptom
and an isolated matched full-rate comparison.**

### Near-level positive-request response screen (2026-09-08)

An offline cache search checked the available v6 full-rate routes for at least two seconds of
engaged, no-pedal, no-lead `cruise` planning with `allowThrottle=true`, positive
`carControl.actuators.accel >= +0.10 m/s2`, and `|pitch| < 0.02 rad`. This is a broader response
screen than the missing under-set-speed hold: it does not require a fixed set-speed gap, matched
gear, or a matched request profile, so it cannot authorize a gas calibration.

After deduplicating route caches, the meaningful windows were:

| route / provenance | interval | request median | wire RMS | `aEgo-request` median / RMS | pitch | gear |
|---|---:|---:|---:|---:|---:|---:|
| `0000001d` / parent `784b05ce670a`, nested `825642c4218b` | 666.37-668.89 s | +0.763 | 0.0266 | +0.267 / 0.472 | +0.0064 | 5 |
| `0000001d` / same source | 1662.74-1669.05 s | +0.969 | 0.0092 | +0.151 / 0.351 | -0.0023 | 5 |
| `00000024` / parent `71b708453fb4`, nested `825642c4218b` | 137.77-141.10 s | +0.733 | 0.0190 | -0.201 / 0.287 | -0.0076 | 7 |
| `00000028` / parent `18377cc4357c`, nested `825642c4218b` | 1634.05-1636.85 s | +1.033 | 0.0393 | -0.194 / 0.287 | +0.0053 | 4 |

At an illustrative `+0.6 s` response alignment, the residual medians were approximately `+0.118`
on the longer route-1d window, `-0.065` on route 24, and `-0.064` on route 28. The sign change
across route, gear, and parent remains after a plausible timing shift. These are not matched A/B
windows and the short route-1d interval has transition-shaped wire error; they are diagnostic
context only. **Decision: KEEP raw `ACCEL_COMMAND`, the current gas/brake domain selector, and
the Honda port unchanged. The missing discriminating drive is still a matched level-road,
no-pedal, no-lead hold at a fixed request and gear; do not fit a static gas multiplier or grade
feedforward from these mixed windows.**

### Isolated nonlinear lateral authority screen (2026-09-08)

A new temporary child, `tmp/ody-op-lateral-authority-screen-20260908`, was created from parent
`57131f21ea5ffe28f7dfdd2a8339a400d111f74b` (`ody-op`). Its nested `opendbc` experiment is
`9e9eeeb250849a33940280d74b53f33ca099d80b`. The only vehicle-runtime change is the Odyssey
`lateralParams` map from `[0,2560] -> [0,2560]` to
`torqueBP=[0,2560,3072]`, `torqueV=[0,2560,3840]`; the lateral factor, 0.15 s delay,
controller, Honda CAN/DBC, safety, and all longitudinal code remain unchanged.

This is a reproducibility commit for a single authority hypothesis, not a promotion or a new
baseline. The focused Odyssey rail suite passes 20 tests and 58 subtests, Honda tests pass, and
Honda lint and diff checks pass. Deliberately restoring the stock Odyssey map makes the new
parameter assertion fail, then restoring the candidate passes again. The standard preflash check
also passes its 7 Honda model/interface tests and the Odyssey rail suite after downloading the
documented model fixture into the local test cache. This remains a software gate and does not
replace the required device build gate.

The candidate remains undeployed. If road-tested, leave Experimental mode as a separate choice and
compare against `ody-op` using matched speed, desired lateral demand, road direction, and authority
exposure. Grade actual-versus-desired lateral acceleration, controller-to-wire fidelity, steering
faults, overrides, and driver feel. Keep, change, or retire the arm only after that isolated
full-rate comparison; no production or DBC conclusion follows from this software screen.

### Archived stopped-lead latch experiment (2026-09-08)

The retired offline latch is archived at root `a409c9667043f5c2519f86bec3368672a551b476`.
Its runtime ancestor was `7c794a33e75d90374b6aabbf9f30b5932f3a1b83`, based on root
`2b217516a8714ed4d1e531f412cb10ee702bd95c` with nested `opendbc`
`fb8a8f98e6e592d5fae1d3b518eadac805242fbe`. It was not merged into `ody-op`: it changed
planner/model stop intent, not Honda CAN, DBC, or safety translation. The hypothesis latched a
close, closing, near-stopped lead after five planner frames and released after five clear frames.

Full-rate zero-order-held replay of child routes `00000001--55d5451393` and
`00000008--7f195b6742`, plus baseline `0000001f--51e2cb8cb9`, showed that the latch could carry
`shouldStop` into LongControl stopping and drive the existing stop ramp to about `-3.5 m/s2`
before moving-lead release. Route 8 trigger flicker came from the hard `0.35 m/s` lead-speed
threshold and source-rate changes while `e2e_should_stop=false`; `carControl`,
`ACCEL_COMMAND`, and the Honda domain remained aligned. Mutation of the trigger comparison caused
three test failures; removing the hold caused two.

**Decision: RETIRE the latch as a road-tunable mechanism. Preserve this archive and evidence only;
do not compensate in Honda CAN or deploy it. A future planner candidate requires a new hypothesis
and a safe, observable release contract.** The retired road arm remains preserved at root
`18377cc4357cc4a5e8f1fef3adb579a063345db5`.

### Exact-source nonlinear lateral retirement and steep-downhill pulse attribution (2026-09-08)

Routes `00000009--8ce01166d6` and `0000000c--37845b37d1` were recorded on the deployed
`ody-op` runtime at parent `7f235e09796633b1e216a0acf5747fee6a2a97ad`, nested `opendbc`
`9e9eeeb250849a33940280d74b53f33ca099d80b`, small model
`f0672eab48566d395e49407293579b817f3e9d22`, standard personality, and
`ExperimentalMode=false`. The nested source changed the Odyssey lateral map only (plus a
semantically neutral stop-state scope move); the longitudinal Honda source and exact DBC remained
the raw three-domain path.

Route `00000009` supplied 22.8 engaged minutes and the qualifying steep-downhill exposure. It
measured 101 physical `BRAKE_REQUEST` edges, a 9/10-second peak, and about 20 edges/minute on
the descent mask. In representative cycles the `cruise` planner request moved from about
`-0.31..-0.325 m/s2` to approximately `0..+0.014 m/s2`; full-rate zero-order-held
`longitudinalPlan.aTarget` matched `carControl.actuators.accel` within about `0.003 m/s2`, and
`ACCEL_COMMAND` matched `carControl` within about `0.013 m/s2` in the brake domain with no
sustained sign disagreement. The repeated command/domain cycle therefore begins at the upstream
cruise trajectory, not in the Honda DBC translation. Achieved jerk was `0.413 m/s3` versus
commanded `0.249 m/s3`, with the validator attributing the stop-lurch excess to Honda actuator
response rather than port-added braking.

Route `0000000c` contains the user's approximately 6:24pm segment. It supplied only 5.4 engaged
minutes, one short brake episode, two domain edges, and zero minutes in the validator's steep-
descent mask. The interval showed one smooth braking ramp, so it is useful mild-grade context but
not a matched test of route 09's repeated steep-descent cycle.

The same arm's lateral result did not establish benefit: route 09 had normal-demand
actual-versus-desired RMS `0.110 m/s2`, but `0.420 m/s2` over only 3.03 high-authority seconds
with 90.1% sign-corrected under-response; route 0c had `0.087/0.203 m/s2` normal/high-authority
RMS over a thin 5.4-minute exposure. Both had zero steering faults. These observations do not
overturn the prior matched-evidence decision for stock 2560.

**Decision: RETIRE the nonlinear 3840 lateral arm.** Nested commit `ce9ec545e1dfc88b5f0b7c6e56f5cbb05be8a108`
reverts `9e9eeeb250849a33940280d74b53f33ca099d80b` and restores the stock `[0,2560]` map;
the parent gitlink and stock assertion are being committed on `ody-op`. Preserve the candidate
commit and route evidence; do not reopen the range without a new repeatable lateral symptom and a
matched comparison.

**Longitudinal decision: KEEP the current raw command/domain translation while changing the
investigation target.** Do not change `ACCEL_COMMAND`, the exact DBC definitions, or the `-0.30`
domain threshold to mask this pulse. The next longitudinal candidate must separately test one
upstream cruise-trajectory or actuator-response hypothesis against the immediately preceding
road-known-good `ody-op` pair; the present routes do not justify a Honda command shaper.

### Retired steep-downhill planner throttle-gate candidate (2026-09-08)

The first repeatable divergence on route `00000009--8ce01166d6` is the non-Experimental `cruise`
planner request: near set speed on the steep descent, `aTarget` repeatedly crosses from roughly
`-0.31..-0.325 m/s2` to `0..+0.014 m/s2` and back. Full-rate zero-order-held plan-to-
`carControl` RMS is about `0.003 m/s2`, and the exact nested DBC at source
`9e9eeeb250849a33940280d74b53f33ca099d80b` carries `ACCEL_COMMAND` and the binary
`BRAKE_REQUEST` faithfully. Route `0000000c--37845b37d1` supplied the contrasting mild-grade
case: one smooth short brake ramp and no qualifying steep-descent exposure.

Candidate hypothesis: for `HONDA_ODYSSEY_5G_MMR` in non-Experimental cruise above 5 m/s, a
grade estimate above `-0.20 m/s2` means natural coast is available; suppressing model-approved
throttle lets `get_cruise_accel()` remain on that coast limit instead of re-entering gas after a
Honda brake-domain event. This changes the upstream cruise request only; it does not reshape
`ACCEL_COMMAND`, alter `BRAKE_REQUEST`, change the exact DBC, or add a Honda-side controller.

The candidate was first captured before history condensation at root `7eaa67c5c6` and nested
`ce9ec545e1dfc88b5f0b7c6e56f5cbb05be8a108`; its runtime nested source is now the single squashed
commit `3d2280daf310e942a1ee3f246f6cd768f5b198bd`. The root parent is upstream
`f23e65768cd2b1bb59939990edef21d9be4ea860`, which pins nested base
`b4ef5e1cf406ff143fa67bdbfb154739d43279c9`; the exact deployed root is authoritative in each
validation-ledger row's `git_commit_full` field, paired with its `opendbc_commit_full`. Route 09/0c
remain the source-equivalent command baseline for the affected controls path, with the parent/model
and nested lateral-source differences recorded above. The device pair, gitlink, clean state, build,
reboot, and startup health were verified; no road evidence has been collected for this pair yet.
**Decision: RETIRE before road testing.** The candidate changed the upstream planner request rather
than the Honda command translation, which violates the command-source boundary for this objective
and could mask planner/model behavior that should remain observable as OpenPilot improves. No road
promotion evidence was collected for it. Preserve this hypothesis and its route analysis as
historical evidence; do not reopen it under the Honda port objective. A future upstream runtime
change requires a separately authorized planner/model objective.

### Stock-radar staging provenance audit (2026-09-12)

The newly pulled Sunnypilot staging routes `00000008--0ae67238ab` through
`00000017--7db38e968b` all report parent `40d6afd30042e9a1bb452f42d3b6e67ecd00c98f`,
which is the `sunnypilot v2026.003.000` release built from upstream parent
`6135084c941d4d947dd90c78326a557c3c857f89`. The vendor tree resolves to exact nested
`opendbc` source `f95f996f5917dcbbf2e32fe51b606a24cf836af6` through that upstream parent's
gitlink. All sixteen routes have Alpha Long disabled and zero OpenPilot engaged minutes, so
they are not closed-loop candidate evidence.

Route `00000017--7db38e968b` is still useful as an offline stock-radar command reference: its
native bus-0 `ACC_CONTROL` stream contains 114,890 frames at 50.1 Hz, 12 brake episodes, no
direct gas-to-brake transitions, and zero `AEB_STATUS`, `AEB_PREPARE`, or `AEB_BRAKING` frames.
Those observations describe stock command shape only; they do not justify a Honda tune change or
provide Alpha-Long CMBS/AEB evidence.

### Strict zero-order-held command-path recheck (2026-09-12)

After diagnostic commit `826ffea5b6`, the command-path readout was rerun with causal
zero-order hold for the plan, `carControl`, and Honda wire signals. Route
`00000009--8ce01166d6` (parent `7f235e09796633b1e216a0acf5747fee6a2a97ad`, nested
`9e9eeeb250849a33940280d74b53f33ca099d80b`) measured `0.0028 m/s2` RMS from plan to
`carControl` and `0.0125 m/s2` RMS from `carControl` to the brake wire, with only isolated
sample-level sign disagreement. Route `00000068--bbbfad9947` (parent
`533f4cd91ef857fa2721586c9a15a57651a64c80`, nested `929540bbcf79868945c38fc6b33a5c5794b08887b`)
measured `0.0027` and `0.0126 m/s2` respectively, with the same no-sustained-mismatch result.
The mild route `0000000c--37845b37d1` measured `0.0025` plan-to-`carControl` and `0.0251`
`carControl`-to-wire RMS over one short brake episode and had no steep-descent exposure.

These are exact-source command-path checks, not matched closed-loop A/B evidence. They reinforce
that the repeated steep-descent pulse begins in the upstream request trajectory and that the
remaining response amplification is downstream in the Honda plant. **Decision: keep the raw
command/domain translation and stock lateral map; make no Honda CAN/DBC change for this symptom.**
Alpha Long's separate safety boundary remains unchanged: its Bosch radar disable makes Honda CMBS,
including factory AEB and FCW, unavailable during those routes; this is not evidence that the
Honda command path should be reshaped to restore it.

### Deployment gate recheck (2026-09-11)

Before any device switch, the current clean root `6f2033e9e5f0fd1231caa66ea0645eedec0ceeef`
and nested `opendbc` `3d2280daf310e942a1ee3f246f6cd768f5b198bd` passed the Odyssey longitudinal
rail suite (`20 passed, 58 subtests`). The Honda model preflash test could not construct its
fixture because route `d7233a428eb7d0b5/00000001--9b99b04d43`, declared in
`opendbc/car/tests/routes.py`, is absent from the local replay cache. The preflash result is
therefore **FAIL / DO NOT FLASH**, not a runtime regression finding. The device remains clean on
Sunnypilot `staging` at root `40d6afd30042e9a1bb452f42d3b6e67ecd00c98f`; no deployment was made.

### Device restored to official Sunnypilot staging (2026-09-11)

After the interrupted, canceled `ody-op` switch was stopped, the device checkout was restored
from the verified official staging ref and the interrupted checkout artifacts were removed. The
device now verifies clean on branch `staging` at parent `40d6afd30042e9a1bb452f42d3b6e67ecd00c98f`
(`sunnypilot v2026.003.000`, upstream base `6135084c941d4d947dd90c78326a557c3c857f89`, exact
embedded `opendbc` source `f95f996f5917dcbbf2e32fe51b606a24cf836af6`). Both `origin` and
`sunnypilot` point to `https://github.com/sunnypilot/sunnypilot.git`; the in-tree source is clean,
`UpdaterTargetBranch=staging`, `UpdaterState=idle`, `UpdateAvailable=0`,
`AlphaLongitudinalEnabled=0`, and no services are failed. The device was rebooted after recovery.
This is deployment-health evidence only; it is not Odyssey command-following or road evidence.

### Current-source response and stock-command cross-check (2026-09-17)

The retained `ody-op` pair is parent `6e69ffa8559638454b90d91500112ce58334b36a`
with nested `opendbc` `909b12c8e21857984d9995e0e59543d0401c514f`. A source diff grouped
the longitudinally equivalent nested revisions `f52c828f`, `31a1776c`, `825642c4`,
`fb8a8f98`, and `9e9eeeb2`; the last revision differs only in the now-retired lateral map.
Nineteen retained full-rate routes from that source pool supplied about 240 engaged minutes.

With active PID, no pedal input, speed at least 5 m/s, stable gear/domain/request, and
`carControl`-to-wire error no greater than `0.05 m/s2`, pooled response alignment favored about
`0.8 s` in gas and `0.5 s` in brake. Gas response error was `0.219 m/s2` RMS with median
`-0.104 m/s2` over 2,309 seconds; brake response error was `0.177 m/s2` RMS with median
`-0.084 m/s2` over 414 seconds. A stricter no-lead cruise gas screen retained 831.7 seconds
across 14 routes and measured median `aEgo-request=-0.140 m/s2`, RMS `0.175 m/s2`. A
route-fixed regression left pitch as the dominant observed term at about
`-7.26 m/s2/rad`, with residual RMS `0.076 m/s2`. Strict no-lead brake exposure was only
4.1 seconds across two routes and is not calibration evidence.

The pitch result identifies road load in the achieved response, not a causal error in the opaque
Honda gas command. The current direct request-to-`GAS_COMMAND` mapping cannot be independently
identified from ordinary-road logs because request and gas count are deterministic. It also does
not overturn the prior retirement of grade feedforward, gasfactor, or windfactor.

As a command-shape cross-check, a route-held-out stock-radar shadow used
`00000017--7db38e968b`, `00000049--fd8b934bd3`, and `0000004a--b8518d776c`. Its held-out
MAE was 71.1, 40.7, and 107.5 opaque gas counts. Current-source OpenPilot routes
`0000001d--2e324ec2ce`, `00000024--8ed656b4ba`, `00000009--8ce01166d6`, and
`00000070--16f597b10c` had model-minus-command biases of `-4.1`, `+19.8`, `+18.1`, and
`-5.4` counts. The mixed biases are smaller than the shadow's own held-out error and do not show
a repeatable under-command that could own the grade-correlated vehicle response.

**Decision: KEEP the current longitudinal command/domain translation and direct upstream gas
mapping. Make no Honda implementation, DBC, or safety change from this observational pool.** The
next longitudinal production hypothesis requires a matched, level-road fixed-request comparison
that varies the Honda gas command independently and records speed, pitch, gear, engine torque,
and achieved acceleration. Lateral received no new symptom or matched exposure in this audit;
keep the stock 2560 map unchanged.

### Active-zero neutral-gas candidate (2026-09-17)

The current-source-equivalent pool was split by physical command domain before proposing another
gas change. Stable inactive coast with raw requests between `-0.30` and zero supplied 368.1 seconds.
At a `+0.6 s` response alignment, `aEgo-request` had median `+0.081 m/s2` in the
`-0.30..-0.20` bin and `+0.065 m/s2` in `-0.20..-0.10`, so replacing the whole coast band with
active gas would weaken requested deceleration. In the narrower `-0.10..0` recovery bin, however,
28.7 seconds had median `-0.148 m/s2`, mean `-0.182`, and RMS `0.312`: inactive coast commonly
decelerated more than the near-zero request. Dropping each of the six largest route contributors
left pooled medians from `-0.093` through `-0.218 m/s2`, so the sign did not depend on one route.

Across 237 clean gas-to-inactive-coast transitions, median engine torque fell from about `+39` at
the transition to `-115` after 0.6 seconds and `-159` after 1.0 second while the request settled
near `-0.21 m/s2`; achieved acceleration moved from `+0.087` to `-0.176 m/s2`. That supports
retaining inactive coast around `-0.20`, not applying a broad neutral override.

The retained stock-radar streams establish a narrower Honda state. Routes
`00000017--7db38e968b`, `00000049--fd8b934bd3`, and `0000004a--b8518d776c` contained 179 valid
frames in which `CONTROL_ON=5`, `BRAKE_REQUEST=0`, and `GAS_COMMAND=0`. They formed 23 episodes;
route 49 included sustained runs of 0.67, 1.08, and 1.15 seconds, while routes 17 and 4a included
active-zero frames at `ACCEL_COMMAND=-0.10 m/s2`. Route 49's sustained zero-command windows held
estimated engine torque near zero. These observations establish active-zero reachability and
semantics, not closed-loop calibration for OpenPilot.

Nested `opendbc` `bee068d882d1ce1f20e7db8ecbaeac38d3080e72` is therefore one isolated,
road-pending translation experiment on `ody-op`; `909b12c8e21857984d9995e0e59543d0401c514f`
is its direct nested rollback parent, and root `a1dd8e58bec7c4b508738d297b51d34c42078528`
is the paired root rollback. After inactive coast, a raw request above `-0.10 m/s2` selects
active `GAS_COMMAND=0`; that neutral state remains selected down to the upstream `-0.20 m/s2`
split. A prior brake still requires a positive request to release, positive gas retains the direct
upstream map, and `ACCEL_COMMAND`, the `-0.30` brake entry, low-speed brake authority, DBC, and
Panda rails are unchanged.

Frozen-input projection over the 19-route source-equivalent pool changes 140.46 seconds across
154 neutral entries; 120 projected entries are under one second, so transition smoothness is an
explicit rejection risk rather than an assumed benefit. Representative projections were 23.82
seconds on route 09, 3.73 seconds on route 22, and 6.79 seconds on route 1d. The projection adds
one zero-command-to-brake transition and no positive-gas overlap; the regression requires that
boundary to drop gas inactive and apply the raw brake request in the same frame. Mutation first made
the neutral-state regression fail; the implementation then passed all 20 Odyssey rail tests and
58 subtests, 27 focused Honda interface tests, 247 Honda safety tests, and the preflash gate's
7 model/interface tests plus the rail suite. Replay retained raw request shape and did not add
brake authority. These are software and command-shape results only.

The road validator maps `bee068d882d1` to the unchanged raw brake-domain model and now reports
active-zero exposure, event and sub-one-second counts, request range, and aligned
`aEgo-carControl` mean/RMS separately from positive live gas. This is an ungraded state and
response diagnostic, not an acceptance threshold. Mutation from exact zero to nonnegative gas
incorrectly admitted a positive 100-count command and failed the synthetic exposure assertion;
restoring the exact-zero selector passed all 45 focused validator tests.

**Decision: CHANGE to the active-zero candidate for one supervised road screen; do not promote it
yet.** Compare against the direct parent and report neutral entries/minute and duration, engine
torque across inactive-to-zero and zero-to-positive transitions, aligned `aEgo-request` in the
`-0.10..0` band, achieved jerk, set-speed error, gas/brake handoffs, interventions, and driver
feel. Retire immediately for a positive surge, increased short pulsing, delayed required braking,
brake-to-neutral release before a positive request, or any safety regression. Lateral is unchanged
and remains stock 2560.

### Active-zero road screen and retirement (2026-09-18)

Four full-rate routes resolved to candidate `bee068d882d1`: `00000002--81d8e3cb2d`,
`00000003--cb9f703767`, `00000004--ca0260cf8f`, and `00000005--a5d819505c`. They supplied
3.85, 3.92, 3.08, and 7.61 engaged minutes. Planner-to-`carControl` acceleration RMS remained
`0.0018..0.0037 m/s2`; gas/brake-domain `carControl`-to-wire RMS remained
`0.0058..0.0118 m/s2`. No route showed a sustained command-sign disagreement. The first
repeatable divergence therefore remained downstream of Honda command translation, in achieved
vehicle response.

The candidate exposed active-zero gas for 46.76 seconds across 22 episodes, including nine under
one second. After requiring 0.6 seconds of a stable same-domain request and matching 15-25 m/s,
mild-downhill samples, the `-0.20..-0.10 m/s2` hold band had 10.97 candidate seconds with median,
mean, and RMS `aEgo-request` error of `+0.152`, `+0.149`, and `0.172 m/s2`. The available
inactive-coast baseline had 49.77 seconds and conditioned median, mean, and RMS errors of `+0.098`,
`+0.091`, and `0.124 m/s2`. In the `-0.10..0` recovery band, candidate exposure was 8.18 seconds
with `+0.074`, `+0.078`, and `0.117 m/s2`; baseline inactive coast was approximately zero median,
`-0.016` mean, and `0.102 m/s2` RMS. Three independent candidate routes supplied adequately
exposed recovery samples: route 02 had 2.38 seconds and `+0.074 m/s2` median error, route 04 had
1.57 seconds and `+0.117`, and route 05 had 4.19 seconds and `+0.054`. Route 03 added only 0.04
conditioned seconds and is not counted as an independent example.

The screen contained 20 inactive-coast-to-active-zero entries and no direct gas-to-brake
regression, but the changed Honda state consistently reduced requested deceleration and did not
improve matched response RMS in either target band. This is Honda-response evidence against the
translation hypothesis; it does not justify changing the pinned planner, `carControl`, raw
`ACCEL_COMMAND`, DBC, or Panda rails.

**Decision: RETIRE active-zero neutral gas after three independent exposed routes.** Nested revert
`c16579385f569300c373f36dddefbd980b4d5e22` restores the retained three-domain behavior and is
source-equivalent to direct parent `909b12c8e21857984d9995e0e59543d0401c514f`. Keep positive gas
directly mapped, inactive coast for non-positive road-speed requests above the `-0.30 m/s2` brake
entry, low-speed stop authority, and stock 2560 lateral control. Alpha Long was restored to enabled
after this offroad audit at the user's direction; deployment tooling reports but does not manage
that user-owned parameter.

### Post-active-zero harshness attribution (2026-09-18)

The two candidate routes flagged for achieved ride harshness were screened separately from the
retired active-zero state. Route `00000005--a5d819505c` measured achieved jerk RMS `0.391 m/s3`
versus commanded `0.207` (`1.9x`), and route `00000003--cb9f703767` measured `0.403` versus
`0.229` (`1.8x`). Their planner-to-`carControl` RMS remained `0.0028/0.0037 m/s2`, brake-domain
request-to-wire RMS remained `0.0106/0.0100 m/s2`, and neither had sustained sign disagreement.
Thus the harshness is not a hidden active-zero, planner, numeric-CAN, or DBC divergence.

New diagnostic `.agents/inspect_response.py` ranks achieved-jerk peaks using the same causal
low-pass/windowed derivative as the validator, retains the strongest wire-command jerk in the
preceding 1.5 seconds, and reports exact domain-edge age, local plan/request/wire residuals, speed,
pitch, lead source, gear changes, engine torque, and RPM. Its pure metric is mutation-verified: a
deliberate loss of causal command history and a sign-inverted summary correlation each failed the
focused assertions, and restoration passed.
Per-route and combined summaries consume every qualifying event before `--limit` trims detailed
display rows; this corrected an initial top-N count of 14 to the complete 21-event set below.

Across source-equivalent routes `00000003`, `00000004`, and `00000005`, the diagnostic found 21
negative achieved-jerk peaks of at least `1.0 m/s3` in the brake domain `0.34..0.73 s` after a
physical domain edge. Their median achieved-to-wire-jerk amplification was about `2.9x`; 19 of 21
had no gear edge in the preceding 1.5 seconds. The events span positive and negative pitch and both
lead and cruise sources; all 21 followed a physical coast-to-brake transition. Local
plan-to-request RMS was at most about `0.024 m/s2`, and local request-to-wire RMS was at most about
`0.028 m/s2`. Route `00000002` supplied no qualifying
brake-entry peak and is not counted as a fourth independent example. Across the 21 events, median
prior-wire jerk magnitude was `0.46 m/s3` and absolute wire/response jerk correlation was `+0.50`:
command slope contributes, but Honda still amplifies it and the discrete transition does not reduce
to a static command-jerk multiplier.

The same metric was then applied to exact historical asymmetric-onset routes
`00000010--2b60bf438c`, `00000011--dc727a0bb7`, and `00000012--9ea63a15e3`. Despite the deployed
`3.0 m/s3` limiter, they retained 11 qualifying delayed brake-entry peaks at `0.45..0.62 s`, with
median response jerk `-1.56 m/s3`, median prior-wire magnitude `0.78 m/s3`, median amplification
`2.7x`, and absolute wire/response correlation `+0.37`. Seven had no nearby gear edge. This is not
a matched candidate-versus-baseline comparison and route counts must not be compared as rates. Ten
of the 11 peaks followed coast-to-brake and one followed gas-to-brake, directly confirming that the
same delayed response mode survived the retired shaper. Mutation of the prior-domain lookup to the
post-edge state failed the synthetic transition assertion before restoration.

This is repeatable Honda-response evidence, but it does not identify a new command-translation
mechanism. The retired `3.0 m/s3` asymmetric onset limiter changed only the first roughly 0.1 second
of moderate entries and already failed three adequately exposed road examples; its exact-arm routes
showed no attributable closed-loop improvement. The current peaks occur roughly half a second after
the discrete domain transition, including several after small wire-jerk inputs, so merely restoring
or retuning that shaper would repeat a closed experiment. Delaying `BRAKE_REQUEST` or scaling the
real `ACCEL_COMMAND` from this unmatched screen would also trade command fidelity and stopping
response without isolated proof.

**Decision: KEEP nested baseline `c16579385f56` and raw clipped `ACCEL_COMMAND`; make no Honda
behavior change from this screen.** Preserve the event diagnostic for the next exact-baseline route.
A new production arm requires a distinct mechanism that explains the delayed response peak and an
isolated matched comparison; the prior onset limiter remains retired.

### Current-pool stock-2560 lateral rescreen (2026-09-18)

Lateral was reviewed independently on the same four routes. Candidate `bee068d882d1` changes only
Odyssey longitudinal domain state, so its stock-2560 lateral source is behavior-identical to
restored baseline `c16579385f56`. Routes `00000002`, `00000003`, and `00000005` supplied 1.46,
8.72, and 3.31 clean high-authority seconds at CAN 2560; route `00000004` never reached the cap.
Their route-level cap RMS actual-versus-desired lateral acceleration was `0.641`, `0.157`, and
`0.547 m/s2`, with sign-corrected under-response medians `+0.722`, `+0.050`, and `+0.251`.
All four routes had zero steering-fault events. Their all-active lateral RMS remained
`0.094/0.070/0.041/0.077 m/s2` for routes 02 through 05.

Conditioning exposes why those route-level cap values are not one calibration result. On route 02,
0.67 seconds at 22-25 m/s and desired magnitude above `1.0 m/s2` tracked at only `0.020..0.030`
RMS, while 0.79 seconds at 25-30 m/s and desired magnitude below `1.5` had `0.860..0.948` RMS.
Route 03's dominant 22-25 m/s, `1.0..1.5 m/s2` cell supplied 6.47 seconds at `0.147` RMS and
`+0.042 m/s2` median under-response; its 1.05-second higher-demand cell rose to `0.255` RMS.
Route 05 supplied 1.14 seconds in the comparable 22-25 m/s high-demand cell at `0.798` RMS and
`+0.842 m/s2` median under-response, while its 1.32-second lower-speed high-demand cell had
`0.430` RMS but only `+0.034` median under-response. The sign and magnitude therefore depend on
route/episode conditions rather than repeating as a matched stock-authority deficit.

The controller is reaching the exact 2560 output recorded in `torqueOutputCan`; the current source
packs that same value into `STEERING_CONTROL`, and no route reports a fault. The first possible
boundary in the cap intervals is physical stock authority/vehicle response, not model-to-controller
or DBC numeric loss. These thin unmatched episodes do not overturn the prior three-route nonlinear
3840 retirement or the passive stock-camera evidence that nonzero OEM steering stays within 2560.

**Lateral decision: KEEP stock 2560, `latAccelFactor 0.9`, and `steerActuatorDelay 0.15`; make no
lateral behavior change.** Reopen authority only for a repeatable driver-observed lateral symptom
with an isolated matched road comparison and explicit fault/override grading.

### Brake-state timing boundary (2026-09-18)

The event diagnostic now aligns each physical brake-domain entry with received
`VSA_STATUS.COMPUTER_BRAKING`, preserving that decoded status as zero-order-held state. This is a
downstream Honda/VSA state bit, not a pressure measurement. The exact Bosch DBC has no brake-pressure
message; Honda's neighboring Nidec DBC labels `0x1E7` as `BRAKE_PRESSURE`, but a full raw-CAN scan
found no `0x1E7` frame on any bus across all 47 retained segments of routes `00000002` through
`00000005`. Its Nidec signal meaning therefore cannot be imported into this Odyssey analysis.

All 21 qualifying current-pool coast-to-brake jerk events had a distinct received computer-braking
rise and the bit was active at every achieved-jerk peak. The request-to-state delay was `0.061 s`
median (`0.048..0.142 s`), while state-to-achieved-jerk-peak delay was `0.494 s` median
(`0.290..0.654 s`). The exact historical asymmetric-onset routes showed the same split: all 11
events had the state edge and active bit at the peak, with `0.068 s` median request-to-state and
`0.461 s` median state-to-peak. Thus the retired `3.0 m/s3` command shaper did not remove either the
prompt Honda brake-state transition or the later physical jerk mode.

The synthetic timing assertion was mutation-verified by collapsing its `0.080 s` computer-braking
delay to zero: the focused test failed on the expected delay comparison, then all three response
tests passed after restoration. Missing status streams remain explicit as `n/a` rather than being
coerced to active state.

**Decision: KEEP nested baseline `c16579385f56`; make no Honda behavior change.** The repeatable
first unresolved boundary now lies after correct planner/request/wire translation and after the
decoded VSA brake-state transition. Without physical pressure telemetry or a matched exact-baseline
road comparison, the logs cannot separate Honda's internal brake-pressure control from actuator and
vehicle response, and they do not justify delaying, scaling, or reshaping `ACCEL_COMMAND`.

### Brake-off dwell and release-hold closure (2026-09-18)

The same events were screened for a narrower lifecycle hypothesis: whether Honda's later brake bite
gets worse after the brake state has been inactive long enough to require hydraulic re-priming. Each
dwell is the contiguous clean-active interval before the physical brake-domain edge, measured from
zero-order-held gas/brake domain and received `VSA_STATUS.COMPUTER_BRAKING` state. This is still a
state-duration diagnostic, not pressure telemetry.

Across all 21 source-equivalent current-pool events, prior-coast dwell versus achieved-jerk magnitude
had correlation `-0.499`, and computer-braking-off dwell versus jerk had correlation `-0.470`.
Longer inactive dwell therefore did not precede a larger response peak. A tighter 13-event subset
required 16-19 m/s, `0.20..0.50 m/s2` request magnitude, and no nearby gear edge; its correlations
remained `-0.543` for coast dwell and `-0.483` for computer-braking-off dwell. The six events below
two seconds off had `1.79 m/s3` median jerk versus `1.29` for the seven longer-off events, but their
median prior-wire jerk was also `0.378` versus `0.167 m/s3`, and three of the six short-off events
came from the single harsher route `00000005`. That split cannot isolate dwell from command slope or
route conditions.

The exact historical asymmetric-onset cohort provides no independent positive dwell relationship.
Across its 11 events, computer-braking-off dwell versus achieved jerk was `-0.155`; prior-domain
dwell versus jerk was only `+0.300`, compared with `+0.372` for prior-wire jerk, and the sole
gas-to-brake event carried a 14.4-second prior-domain dwell. The ten coast-to-brake events span
roughly `0.02..0.48 s` of clean prior coast without a monotonic severity ordering.

The current selector already retains `BRAKE_REQUEST` for every negative request after entry and
releases at zero. Extending it through nonnegative coast would recreate the time-based
`BRAKE_RELEASE_HOLD` or wider-domain family: those mechanisms already failed road screens, and the
new dwell evidence neither identifies a selector divergence nor contradicts their retirement.

**Decision: KEEP the existing brake lifecycle and retire a new dwell/hold experiment.** Do not add
a time hold, widen the release threshold, or keep `COMPUTER_BRAKING` active to mask this response
mode. The next production hypothesis still requires exact-baseline evidence for a distinct mechanism
that owns the downstream response without withholding a correct `carControl` command.

### Active-gas response-boundary experiment (2026-09-18)

Fresh route `00000009--019ee79ffb` and seven source-equivalent baseline routes isolate a narrower
domain question than the active-zero experiment. The current direct map uses `-0.20 m/s2` both as
its zero-count scaling floor and as the release point for an already-active gas domain. Stable
15-25 m/s, mild-downhill samples showed a response crossover inside that interval: in
`-0.20..-0.15`, gas-domain error was `+0.170 m/s2` mean and `+0.177` median versus coast
`-0.122` mean and `-0.132` median; in `-0.15..-0.10`, gas was closer at `+0.125` mean and
`+0.129` median versus coast `-0.231` mean and `-0.247` median. Positive error means the Odyssey
decelerated less than requested.

A route-held-out one-to-one match in the lower band paired 149 samples with request within
`0.015 m/s2`, speed within `1.5 m/s`, pitch within `0.005`, and different route provenance. The
matched requests were `-0.178/-0.179 m/s2`; gas/coast response error was `+0.179/-0.038` mean,
`+0.200/+0.007` median, and `0.215/0.165` RMS. Inactive coast reduced mean absolute error by
`0.074 m/s2`, reduced median absolute error by `0.110`, and was closer in 75.8% of pairs. Median
engine torque was `+39` in gas versus `-145` in coast. This identifies Honda response to the domain
choice as the first divergence; planner-to-`carControl` and numeric request-to-wire fidelity remain
close.

The isolated candidate therefore releases an already-active road-speed gas domain at
`-0.15 m/s2`. Fresh entry still requires a positive request. Raw `ACCEL_COMMAND`, direct positive
gas mapping, `-0.30` brake entry, negative-request brake hold, low-speed stop authority, and all
lateral behavior are unchanged. A deliberate pre-change mutation test failed because the prior
`-0.20` boundary kept gas live at `-0.15`; the implementation then passed the focused test and all
20 Odyssey rail tests (58 subtests).

Frozen-input route-09 command analysis changes coast exposure from 43.1 to 101.1 seconds,
gas-to-coast edges from 31 to 36, and coast-to-gas edges from 14 to 18; coast-to-brake and
brake-to-gas remain 17 each. Across the eight routes, natural gas-to-coast transitions had
`0.70/2.32 m/s3` median/p90 peak absolute achieved jerk and coast-to-gas had `0.82/1.71`, compared
with `1.28/2.45` for coast-to-brake. These measurements bound exposure but do not predict the
candidate's closed-loop response or comfort.

The deployed pair is parent `5a0a53fced39` with nested `409c25925c19`; the device remained clean
and healthy with Alpha Long enabled after reboot. The validator now resolves that exact nested SHA
to the unchanged raw three-domain brake semantics and reports sustained response separately for gas
and coast in the `-0.20..-0.15` band. A deliberate missing-metric mutation failed collection before
the pure metric was implemented; 49 tooling tests and project lint then passed. Revalidating
pre-candidate route 09 found 18.86 seconds over 13 sustained gas episodes at `+0.185 m/s2` mean
response error, versus 0.60 seconds of natural coast at `+0.087` mean, with separate speed/pitch
medians (`22.389 m/s`, `+0.003 rad` gas; `22.386 m/s`, `-0.004 rad` coast). This is a concrete
baseline readout, not a matched road result. As of the post-deployment inventory check, all ten
recent retained routes were already validated and none carried `409c25925c19`, so the candidate has
no closed-loop exposure yet.

**Decision: CHANGE for one supervised road screen on the single linear `ody-op` line; this is not
promotion evidence.** Reject the candidate for increased gas/coast pulsing, achieved jerk, set-speed
overshoot, delayed brake response, driver intervention, incomplete stopping, lifecycle leakage, or
safety failure. Keep it only if full-rate road evidence confirms improved request tracking in the
lower band without those regressions; otherwise revert the candidate commit on `ody-op`.

### Active-gas response-boundary road decision (2026-09-18)

Route `0000000b--c529eb1e28` supplied the first closed-loop candidate exposure: 63.9 logged minutes,
21.0 engaged minutes, and 14.4 engaged miles at parent `5a0a53fced39` and nested
`409c25925c19396bc58f72f00fcc5b2b61a795d9`. Alpha Long was enabled, Experimental Mode was off,
the small-model blob was `f030157ccd2bacbdc6d7b98358903cbacc0e0b34`, and the longitudinal
personality was standard. Planner-to-`carControl` RMS was `0.0027 m/s2`; request-to-wire RMS was
`0.0082` in gas and `0.0103` in brake, with no sustained sign disagreement. The candidate therefore
reached Honda CAN as intended; the comparison below is vehicle response, not command-path error.

The candidate produced 8.95 seconds over ten sustained coast episodes in the intended
`-0.20..-0.15 m/s2` band. Its pooled mean/median/RMS response error was
`+0.002/+0.047/0.199 m/s2`, but that near-zero pooled mean hid opposite response modes. A one-to-one
comparison against source-equivalent baseline gas samples held request within `0.015 m/s2`, speed
within `1.5 m/s`, pitch within `0.005 rad`, and lead-presence state equal. Across 52 pairs, baseline
gas versus candidate coast mean absolute error was `0.175/0.198 m/s2`; candidate error increased by
`0.023 m/s2` and was closer in only 44.2% of pairs. In 30 lead-present pairs, candidate coast flipped
from baseline under-deceleration (`+0.153`) to over-deceleration (`-0.136`) and increased mean
absolute error by `0.024`. In 22 no-lead pairs it retained under-deceleration and worsened from
`+0.180` to `+0.203`, increasing mean absolute error by `0.022`. The domain change therefore did not
provide a stable response correction in either context.

The comfort screen also moved in the rejected direction. Candidate gas-to-coast transitions occurred
at 3.57/minute with `0.77/2.72 m/s3` median/p90 achieved jerk, versus route-09 baseline at
2.67/minute and `0.60/2.29`. Coast-to-gas transitions rose from 1.38 to 2.48/minute, with p90 jerk
increasing from `1.05` to `1.41 m/s3`. Nine of twelve brake takeovers had no candidate-band coast
exposure in the prior five seconds, so the route's takeover count is not assigned wholesale to this
mechanism; the matched tracking and transition results are sufficient to reject it.

**Decision: RETIRE and revert.** Nested commit `196119896d73` reverts `409c25925c19` on the same
linear `ody-op` line and restores the `c16579385f56` three-domain behavior. The result falsifies this
release-threshold hypothesis; it does not justify a lead-dependent Honda selector, because lead state
describes upstream context rather than a distinct actuator command contract. Reopen domain selection
only from a new repeatable first-divergence mechanism, not from the canceled pooled mean.

### Device updater ownership repair (2026-09-18)

The on-device update failure was a filesystem ownership defect, not a source or network failure.
`git clean -xdff` could not remove root-owned rednose editable-install metadata under
`/data/openpilot/.venv`, while updater and manager run as `comma`. With the device offroad, ownership
was repaired only for the affected rednose metadata and the updater was retriggered through its
supported signal. `UpdaterState` returned to `idle`, `UpdateFailedCount` to `0`, and
`LastUpdateException` to empty; Alpha Long remained enabled. The first rollback deployment recreated
the same ownership fault, proving that a one-time repair was insufficient. `tools/deploy_ody_op.sh`
now normalizes `.venv` ownership after its build and before reboot, while `verify` rejects any
non-`comma`-owned path so this failure cannot be mistaken for a healthy deploy.

### Stock-ACC brake-entry response cross-check (2026-09-18)

The newest route's 22 qualifying delayed brake-entry peaks made domain timing worth checking
against Honda's own controller before opening another threshold arm. The retained stock-radar
routes `00000017--7db38e968b`, `00000049--fd8b934bd3`, and `0000004a--b8518d776c` supplied 16
moving, no-pedal brake entries after excluding any target-gear change in the preceding 1.5 seconds.
The OpenPilot side used behavior-equivalent brake-entry source from routes
`0000000b--c529eb1e28`, `00000009--019ee79ffb`, `0000001d--2e324ec2ce`,
`00000024--8ed656b4ba`, and `00000070--16f597b10c`; the route-0b candidate changed only active-gas
release and left brake entry and brake-domain output unchanged. It supplied 82 clean entries under
the same filter.

Stock Honda always passed through coast before these brake entries, but its coast dwell was much
shorter: `0.039/0.060/0.230 s` q10/median/q90 versus OpenPilot
`0.170/0.411/2.019 s`. That difference alone did not explain smoothness. Stock entry
`ACCEL_COMMAND` was broad (`-0.435/-0.275/-0.025 m/s2`) and prior command jerk was
`-0.600/-0.164/-0.031 m/s3`; OpenPilot entry was concentrated at its selector boundary
(`-0.330/-0.310/-0.300`) with stronger prior command jerk
(`-0.798/-0.375/-0.150`). Unmatched 0.20-to-0.75-second achieved-jerk minima were therefore
`-1.794/-0.818/-0.428 m/s3` stock versus `-2.350/-1.292/-0.366` OpenPilot.

A greedy one-to-one comparison then required the same lead-presence state, entry request within
`0.12 m/s2`, speed within `2.0 m/s`, pitch within `0.015 rad`, and prior command jerk within
`0.4 m/s3`. Across nine pairs, stock achieved-jerk mean/median was `-0.927/-0.775 m/s3` versus
OpenPilot `-0.748/-0.607`; OpenPilot was harsher in only three pairs. This small stock cohort does
not prove OpenPilot is smoother, but it rejects the narrower hypothesis that Honda's shorter coast
dwell is itself the missing comfort mechanism. The unmatched difference is materially confounded
by the command trajectory Honda receives, while the current port reproduces the pinned
`carControl` request accurately.

**Decision: KEEP the `-0.30 m/s2` brake entry and do not open an earlier-entry or coast-dwell arm.**
Earlier entry would add brake exposure and transitions without matched evidence of a smoother
physical response. The remaining delayed bite is after correct command translation and Honda's
prompt VSA state transition; the previously failed onset shaper also remains closed absent a new
mechanism. A next longitudinal behavior experiment still requires a distinct Honda-side cause or a
controlled fixed-request comparison that varies only the opaque gas/brake actuation input.

### Stock-supported negative-live gas bridge (2026-09-18)

Stock-radar routes `00000017--7db38e968b`, `00000049--fd8b934bd3`, and
`0000004a--b8518d776c` establish that Odyssey `GAS_COMMAND` is signed and that Honda uses a live
negative transition state distinct from inactive `-30000`. After excluding pedals, speeds below
5 m/s, and discontinuous samples, 405 frames were in `-88..-3` counts (median `-28`). Nineteen
clean gas entries started negative (median `-60`): nine from coast and ten from brake. Mild
coast entries commonly rose from about `-60` to zero over roughly `0.4..0.65 s`; this is not the
historical +60-count-per-frame OpenPilot limiter.

The OpenPilot comparison used longitudinally behavior-equivalent nested revisions on routes
`00000009--019ee79ffb`, `00000009--8ce01166d6`, `0000001d--2e324ec2ce`,
`00000024--8ed656b4ba`, and `00000070--16f597b10c`. For the first screen, matching held origin,
lead state, request within `0.15 m/s2`, speed within `2.0 m/s`, pitch within `0.015 rad`, and prior
command jerk within `0.5 m/s3`. Seven matched coast-to-gas pairs had stock versus OpenPilot median
positive response jerk `0.493/0.626 m/s3` and median achieved error `-0.015/+0.061 m/s2`.

Because OpenPilot fresh gas begins near zero request while stock often begins near `-0.10`, a second
comparison aligned the same upward `-0.10 m/s2` crossing. Six stock slow negative-live coast entries
matched six OpenPilot inactive-coast crossings. Stock versus OpenPilot median positive response jerk
was `0.526/0.358 m/s3`, but achieved error was `-0.011/-0.129 m/s2`; OpenPilot coast over-decelerated
in all six pairs and waited a median `0.67 s` for positive gas. Together the two screens locate a
response gap between over-decelerating coast and the later, sharper positive-gas handoff. The prior
active-zero arm crossed too far toward acceleration; a bounded negative live command is a distinct
intermediate hypothesis.

Nested commit `147e1d732eaa0328168c9e1b6f9741712222c6a1` implements only that bridge. At road speed,
a fresh coast recovery crossing nominal `-0.10 m/s2` selects gas at `-60` while the request remains
negative, then restores the existing direct map at a nonnegative request. It cannot enter from the
brake domain, does not alter an already-active gas domain, resets on disengagement, preserves raw
`ACCEL_COMMAND`, and leaves low-speed, braking, lateral, DBC, and other Honda behavior unchanged.
Panda safety receives an Odyssey-only flag permitting `-60..2000`; standard Bosch remains
`0..2000`, and `-61` is rejected.

Controller-entry, wire-value, and Panda-minimum mutations each made their focused tests fail before
restoration. Focused Honda/interface coverage passed 501 tests with 244 platform skips. Preflash
passed the Odyssey model suite and 20 command-rail tests with 58 subtests. Open-loop replay exposed
14 negative-live events on baseline route `00000009--019ee79ffb` and 20 on long route
`0000000b--c529eb1e28`; replay request-to-wire RMS remained `0.0092/0.0063 m/s2`. Frozen response
cannot grade the bridge.

**Decision: CHANGE to the negative-live bridge for one supervised road screen.** Compare against
nested baseline `196119896d73` in mild road-speed coast recovery, separately checking response error
through `-0.10..0`, coast-to-gas achieved jerk, acceleration delay, brake timing, and interventions.
Retire for positive surge, increased handoff jerk, delayed required acceleration, late braking, or
any safety/lifecycle regression. This is a software-qualified candidate, not a promotion.

#### First bridge route and bounded-recovery correction (2026-09-18)

Route `0000000c--25d237b5ee` is exact root `e7a68cb5b612` / nested
`147e1d732eaa`, small model `f030157ccd2bacbdc6d7b98358903cbacc0e0b34`, standard personality,
Experimental off, and Alpha Long enabled. It supplied 13.2 engaged minutes and four reconstructed
bridge events totaling 3.30 seconds, with zero brake or low-speed overlap. Planner-to-`carControl`
RMS was `0.0024 m/s2`; gas/brake request-to-wire RMS was `0.0083/0.0101`, so the route does not
locate a numeric upstream or CAN-packing divergence.

The four entries were genuine recoveries: their request increased by `+0.020..+0.083 m/s2` over the
preceding 0.20 seconds before crossing the nominal `-0.10` entry. Two continued to positive gas.
Their bridge durations were 0.70/0.20 seconds, response errors `-0.113/-0.288 m/s2`, and positive-exit
jerk maxima `0.588/1.093 m/s3`; two examples are too thin and mixed to establish a comfort gain.
The other two reversed after entry, but the bridge-originated gas latch inherited ordinary active-
gas hysteresis and remained at `-60` down to requests of `-0.216/-0.202 m/s2`. Those 1.14/1.26-second
events under-decelerated by `+0.199/+0.196 m/s2` on average before returning to coast. This is the
first repeatable divergence: the upstream request changed direction correctly, while the candidate
Honda domain lifecycle kept its recovery command active outside its owned entry band.

**Decision: CHANGE the same bridge hypothesis, not its command value.** Nested
`afc133f343d84c1a6ecf15320fd4ba684ca0e9c8` makes only bridge-originated gas return to coast below `-0.101 m/s2`; ordinary already-
active gas retains the existing `-0.20` hysteresis, and braking, low speed, raw `ACCEL_COMMAND`,
lateral, DBC, and safety bounds are unchanged. Mutation of that release guard made the focused test
fail. The full nested gate passed 3,978 tests with 702 skips; preflash passed seven model tests and
20 command-rail tests with 58 subtests. Frozen-input replay on route 0c retained four entries but
reduced negative-live exposure from the recorded 3.30 seconds to about 1.94 seconds, with
request-error RMS `0.0056 m/s2`; it does not predict closed-loop response. Deploy this bounded
revision for the second supervised road example and compare reversal handling and positive exits
separately before keep or revert.

### Odyssey uphill gas-load candidate (2026-09-18)

Current MVL source was resolved rather than inferred from its branch name: parent
`08d0461df067227a40684ca633633697a026f9a0` pins nested
`c68be364cc10a258eea50bce12c57e2b8be2edf9`. Its Honda path combines raw pitch gravity,
speed-scheduled drag, persistent gas/wind learners, compensated gas/brake domain selection, a
60-count gas ramp, and a low-speed brake PID. Only the static gravity principle is transferred
here. The adaptive factors reached both `0.01/3.0` gas-factor rails in frozen-route execution and
predicted substantial max-gas exposure; frozen response cannot grade the resulting closed loop,
but it does not establish the full learner as a bounded candidate. The brake PID also modifies
`ACCEL_COMMAND`, outside this command-fidelity objective.

Seven recent Alpha Long routes (`00000002`, `03`, `04`, `05`, `09`, `0b`, and `0c`) locate the
repeatable gap after correct command translation. On route `0000000c--25d237b5ee`, planner-to-
`carControl` RMS was `0.0024 m/s2`, gas request-to-wire RMS was `0.0083 m/s2`, and the qualifying
uphill hold requested `+0.309 m/s2` while achieving about `+0.005 m/s2` at median pitch
`+0.072 rad`. Across the seven routes, nominal gravity was `+0.57..+0.71 m/s2` in the selected
uphill samples. A source-matched shadow of the bounded candidate changed only positive PID gas
samples: median whole-route additions were `78..181` gas counts, uphill compensation medians were
`0.44..0.63 m/s2`, and predicted gas-rail exposure was `0.0..2.7%`. These are command-shape and
exposure results, not closed-loop proof.

Nested commit `0a81d3bd4` adds an Odyssey-only, `0.5 s` filtered uphill load term to the opaque
`GAS_COMMAND` mapping. It runs only for a positive raw request in PID state, with a valid positive
pitch and no driver gas, and is capped at `+1.0 m/s2`. `ACCEL_COMMAND`, gas/brake/coast selection,
downhill output, stopping output, missing-pose output, the negative-request bridge, DBC, safety,
lateral, and other Honda platforms remain unchanged. The bridge and grade mechanisms occupy
negative- and positive-request regions respectively; bridge positive exits must still be scored by
grade so the two effects are not conflated.

Removing the grade term made both the focused helper test and decoded controller-wire regression
fail before restoration. The full nested gate passed 3,979 tests with 702 skips plus lint, typing,
MISRA, and code checks. Controller/Panda preflash passed seven model tests and 20 rail tests with 58
subtests; its strengthened grade regression confirms identical decoded `ACCEL_COMMAND`, level,
downhill, stopping, missing-pose, and driver-override output while uphill `GAS_COMMAND` rises
smoothly and remains inside the 2,000-count safety rail.

**Decision: CHANGE to this software-qualified uphill candidate for a supervised road screen.** On
the same hills, compare steady positive-request `aEgo-carControl` error, speed-gap recovery, gas rail
exposure, driver overrides, and crest overshoot/jerk against the seven-route baseline. Separately
score bridge reversals below `-0.101 m/s2`; score positive bridge exits only after conditioning on
pitch/grade compensation. Revert for sustained over-response, crest surge, increased jerk,
material gas rail exposure, or any command/domain/safety regression.

#### First uphill route and request-aware bound (2026-09-19)

Route `0000000d--b4ced526db` is exact root `5821ee978c93` / nested `0a81d3bd4a29`,
small model `f030157ccd2bacbdc6d7b98358903cbacc0e0b34`, standard personality, Experimental
off, and Alpha Long enabled. It supplied 14.3 engaged minutes and 14.1 engaged miles. The command
path remained faithful: planner-to-`carControl` RMS was `0.0025 m/s2`, gas request-to-wire RMS was
`0.0087 m/s2`, and brake request-to-wire RMS was `0.0080 m/s2`. The candidate added grade load for
437.5 seconds, with median/p95/max additions of `263/595/763` gas counts and no gas-rail exposure.

Matched steady-climb bins showed a small overall movement toward the requested acceleration:
candidate-minus-baseline `aEgo-request` error was median `+0.042 m/s2` over 50 route-bins. That
aggregate concealed a repeatable steep-grade over-response. Three independent climb episodes at
route-relative `224`, `870`, and `1165` seconds had raw requests of about `+0.83..+0.99 m/s2` and
median achieved over-response of about `+0.39..+0.52 m/s2`. Steady samples above `+0.06 rad` had
median error `+0.464 m/s2`; comparable retained-baseline route medians were generally
`-0.24..-0.34 m/s2`. Other steep episodes with lower raw requests (`+0.13..+0.39 m/s2`) still
under-responded. This separates the useful low-request load assistance from stacking full gravity
after longcontrol has already raised its request and the transmission responds.

Five validator brake-takeover flags did not coincide with those three over-response episodes. Three
presses began after disengagement; the two active presses were near `187` seconds on a descent with
a negative request and near `1210` seconds during uphill under-response. The route's downhill brake
cycling and felt-jerk flags therefore remain separate Honda-response findings, not evidence that the
positive uphill gas term caused driver braking.

**Decision: CHANGE the same uphill hypothesis by bounding only its combined gas-map input.** Nested
commit `8feab4fe7657a69258cfb8e4717d7e5469f6a3c4` allows full filtered grade assistance while the raw
request is low, tapers the added term as the raw request approaches `+1.0 m/s2`, and never clips a
raw request already above that bound. `ACCEL_COMMAND`, command-domain selection, negative-live
bridge, downhill, stopping, missing-pose, driver-gas, lateral, DBC, and safety behavior are
unchanged. On the recorded input this reduces median steep-grade added gas from `605` to `182`
counts while retaining the lower-request assistance; that is a frozen-input command-shape result,
not closed-loop road proof. Removing the bound made the focused helper test fail. The nested gate
passed 3,979 tests with 702 skips, and preflash passed seven model tests plus 20 rail tests with 58
subtests. Use the next supervised route to recheck the same high-grade episodes, under-speed
recovery, crest response, interventions, and gas rail exposure before keep or revert.

### Odyssey nonlinear 3840 steering road screen (2026-09-19)

The user requested a fresh 3840 trial for today's longer drives, on the single linear `ody-op`
line. The pre-change pair is root `ecf77f2a9c192e761f14cba4fde4713b62e6d043` and nested
`8feab4fe7657a69258cfb8e4717d7e5469f6a3c4`. The earlier three-route nonlinear screen
did not establish an attributable benefit; it is a caution, not a claim that later evidence
cannot change the decision. The most recent stock route `0000000d--b4ced526db` offered only
4.9 seconds of high-authority lateral exposure, with actual-minus-desired lateral-acceleration
RMS `0.174 m/s2`, median under-response `+0.131 m/s2`, and no steering faults.

This candidate restores the exact prior Odyssey-only nonlinear map, breakpoints
`[0, 2560, 3072]` and values `[0, 2560, 3840]`; lateral torque tuning and delay remain
`0.9` and `0.15 s`. Because Honda `STEER_MAX` is the last breakpoint, normalized steering
requests also scale: at 0.5 the command becomes 1536 counts versus the stock 1280. This is a
combined midrange-gain and peak-authority experiment, not an isolated cap extension. The stock
camera's observed LKA ceiling of 2560 is not proof that 3840 has equivalent steering authority
or fault tolerance. No longitudinal, DBC, or safety code changes accompany this experiment;
today's longitudinal observations must independently account for the still-unproven uphill
gas-load bound in the pre-change pair.

**Decision: CHANGE for a supervised road screen, not yet KEEP.** The hypothesis is that this
map reduces high-demand actual-versus-desired lateral-acceleration error without worsening
steering faults, overrides, oscillation, or comfort. Compare resolved-source full-rate routes
against stock in matched speed, demand, grade, and authority bins; examine normalized controller
request to bus-0 wire and physical bus-1 forwarding, as well as actual vehicle response.
Long mileage alone is not high-authority exposure. Retire via revert if adequately exposed
routes do not show an attributable gain or show a safety/comfort regression. Preserve the
pre-change pair as the rollback point. The focused regression was mutation-verified by restoring
the stock Odyssey map and observing its expected failure. The nested suite passed 3,979 tests
with 702 skips plus lint, typing, and MISRA; preflash passed seven model tests and 20 command-rail
tests with 58 subtests. These are software gates, not road proof.

### Uphill gas pulse first-divergence and retirement (2026-09-19)

The driver reported severe gas pulsing and disabled Alpha Long to finish on stock radar. Keep the
device setting off until a replacement Honda translation is built and verified. The current
deployed pair before this fix is root `fdc1d7651a91ec80c9130341fa11f10149beac16` / nested
`359f3574d67f11e5723cd79840471529ac4af85b`. Route
`0000000f--26687b4500` retained only segments 4-6, so it is a partial diagnostic, not a
whole-route verdict; its logged `carParams` has Alpha Long on and `initData` resolves to this pair.
The much longer `00000013--bd53602052` has only segments 137-170 retained, with Alpha Long
already off. The missing initial segments prevent whole-route attribution there.

The retained Alpha-on tail nevertheless locates a specific first divergence. Around route-relative
100-113 seconds on a +0.030 rad climb, `carControl` hovered near zero (5th-95th percentile
`-0.064..+0.024 m/s2`), while `GAS_COMMAND` alternated roughly 180 to 450 counts with each
small sign crossing. `ACCEL_COMMAND` stayed near the raw request; `aEgo` spanned
`-0.147..+0.228 m/s2` (5th-95th percentile). The current Honda code activates filtered
gravity assistance only when the raw request is positive, adding about 270-300 gas counts at
these pitches and abruptly removing them on a tiny negative request. The same behavior repeats
around 120-129 seconds. This is Honda translation, not a planner or `longcontrol` acceleration
step; physical closed-loop causality beyond these windows still needs a post-fix drive.

For a reproducible transition screen, condition on engaged, speed above 10 m/s, pitch
`+0.02..+0.06 rad`, `|carControl.accel| < 0.03 m/s2`, both adjacent samples in the live-gas
domain, `|delta request| < 0.05 m/s2`, and count `|delta GAS_COMMAND| > 150` counts. The
pre-grade direct-gas route `0000000c--25d237b5ee` had zero such jumps; the complete first
grade candidate route `0000000d--b4ced526db` had 358 with median 279 counts, and the
retained current-version `0000000f` tail had 44 with median 299 counts. These routes differ in
exposure and other revisions, so those counts diagnose the discontinuity; they are not a matched
whole-route comfort A/B.

**Decision: RETIRE the Odyssey uphill gas-load correction now.** Remove only its filtered pitch
state and addition to `GAS_COMMAND`; keep raw `ACCEL_COMMAND`, the existing domain selector and
negative-live bridge, the 3840 lateral road arm, DBC, and Panda safety unchanged. This restores
direct request-to-gas mapping and a continuous live-gas command across a near-zero uphill request.
It also restores the known uphill under-response risk, which must be measured independently after
the pulsing is stopped. Nested commit `69a81e7da7f45067df7cd732fcef4833f5e71f1d` contains
the removal. The new decoded-controller regression failed on the deployed code and passes after
removing the correction. The nested gate passed 3,978 tests with 702 skips plus lint, typing,
and MISRA; preflash passed seven model tests and 20 command-rail tests with 58 subtests. A
frozen-input replay checks command shape, not whether the vehicle will ride smoothly; Alpha Long
should be re-enabled only after a clean, exact-pair build and post-reboot checks, followed by
supervised road confirmation.

#### Reproducible live-gas pulse diagnostic (2026-09-19)

The pre-existing gas re-entry metric counts inactive-to-live domain edges and misses the reported
within-domain toggling. A new ungraded full-rate readout counts adjacent samples only while Alpha
Long is engaged, speed exceeds 10 m/s, pitch is `+0.02..+0.06 rad`, both requests are within
`0.03 m/s2` of zero, the request changes less than `0.05 m/s2`, both gas commands are positive,
and neither brake is active. It reports exposure seconds, count of gas steps above 150 counts, and
their median size. A synthetic test excludes domain edges and flat terrain and was made to fail
by deliberately disabling step detection. On the source logs it reads 0 steps in 48.3 eligible
seconds on pre-grade route `0000000c`, 353 in 95.9 seconds on full first-grade route `0000000d`,
and 44 in 15.9 seconds on the partial current-grade route `0000000f`. The more restrictive
adjacent-sample mask explains the small count difference from the initial exploratory screen.
No post-fix Alpha Long road route was available when this diagnostic was added. Its zero count
on a future route would establish removal of this command discontinuity in exposed conditions,
not by itself prove smooth physical response or adequate uphill acceleration.

#### Request-ramped uphill response candidate (2026-09-19)

The pre-grade Alpha Long routes already establish uphill under-response after faithful
planner-to-`carControl` and raw `ACCEL_COMMAND` translation; a post-retirement route is not needed
to rediscover that baseline. The first grade candidate showed only a small matched aggregate
improvement and high-request over-response, while its on/off-at-zero gas mapping produced the
repeatable 280-300-count discontinuity documented above. This candidate tests whether a continuous,
request-scaled uphill gas load improves **achieved `aEgo` versus `carControl`**, with the raw request,
domain selection, negative bridge, and `ACCEL_COMMAND` untouched. It does not try to alter the
planner or optimize subjective ride comfort.

The Odyssey-only gas-map input adds filtered positive-pitch gravity times a smoothstep weight
from zero at a zero request to full weight at `+0.30 m/s2`; the combined gas-map input is bounded
at `+1.0 m/s2` without clipping a larger raw request. The 0.30 ramp endpoint is the approximately
0.309-m/s2 qualifying uphill-hold request on pre-grade route `0000000c`, not a fitted vehicle
response coefficient. The existing 0.5-second pitch filter, PID-state, valid pose, positive raw
pitch, and no-driver-gas gates are retained. At pitch `+0.03 rad`, a `+0.01` request adds about
one gas count instead of roughly 270; at `+0.03` it adds about seven. At the known `+0.30` request
and `+0.072 rad` it can add about 636 counts, so the actual uphill response effect must still be
graded on road. At `+0.83` and `+0.072 rad`, the high-request bound limits the addition to about
155 counts, but that too is only command-shape evidence.

The focused unit check was mutation-verified by replacing the smoothstep weight with one: the
near-zero bound failed (`0.294` versus less than `0.002 m/s2`) and passed when restored. Decoded
controller/Panda tests passed 20 tests and 58 subtests; the full nested `test.sh` passed 3,979
tests (702 skipped) plus lint, typing, and MISRA; preflash passed seven interface/model tests
and the same 20 rail tests. Frozen-input CAN replay of partial pulse route `0000000f` produced
zero `>150`-count near-zero eligible steps over 773 adjacent frames (max 22 counts); replay of
full first-grade route `0000000d` produced zero over 4,630 frames (max 39 counts). These are
open-loop command-shape screens, not a claim that `aEgo` will follow better. Route `0000000f`
remains partial; its missing earlier segments cannot be used for a whole-drive outcome.

**Decision: CHANGE to an unpromoted, software-qualified response candidate.** A supervised Alpha
Long route must compare `aEgo-carControl` against the existing pre-grade and first-grade routes
in matched speed, request, pitch, and domain bins. Specifically check the `+0.1..+0.4 m/s2`
uphill under-response bin, high-request steep-climb over-response, and near-zero uphill command
steps. Retire if tracking is not better across adequately exposed independent climbs, or if
high-request error or Honda domain behavior regresses. Command continuity alone is not a keep
decision.

A read-only uphill tracking diagnostic now reports settled (`>=2.0 s` episodes with the first
`0.5 s` removed) live-gas cruise response in moderate `+0.10..+0.40` and high
`+0.80..+1.05 m/s2` request bands at `+0.04..+0.09 rad` pitch and above 10 m/s. It excludes
leads, driver pedals, and brake domains, and keeps request-to-wire RMS separate from physical
response. Its lead-mask mutation failed the synthetic test as intended. On pre-grade route
`0000000c` (root `e7a68cb5b612`, nested `147e1d732eaa`), moderate exposure was two episodes /
15.9 seconds with median `aEgo-carControl=-0.258 m/s2`; high exposure was one episode /
11.0 seconds at `-0.100 m/s2`. On first-grade route `0000000d` (root `5821ee978c93`, nested
`0a81d3bd4a29`), moderate exposure was zero under this restrictive mask; high exposure was
four episodes / 16.5 seconds at `+0.388 m/s2`. These are baseline coverage and first-grade
response screens, not a matched A/B or a prediction for the newly deployed ramped candidate.
At that time no candidate road route was available; the dated screen below supersedes that state.
The tracking readout now splits episodes at native `carControl` timestamp gaps above 2.5
nominal sample periods. A synthetic missing-segment mutation joined two climbs into one and
failed the test; restoring the split passed. Read-only reruns left the 0c/0d exposure and
response results above unchanged, with request-to-wire RMS `0.004/0.003 m/s2` for 0c's
moderate/high bins and `0.004 m/s2` for 0d's high bin.

#### First request-ramped uphill road screen (2026-09-20)

Full-rate route `0000001b--7bfc61a2d5` (69 retained segments, 25.6 engaged minutes) and short
route `0000001d--014f262dad` (11 segments, 4.2 engaged minutes) both resolve exactly to parent
`c29771b935db` / nested `d50a3a4843ed`, small model
`f030157ccd2bacbdc6d7b98358903cbacc0e0b34`, standard personality, Experimental off, and
Alpha Long on. Route `0000001c--7ac0c4a5ea` has no engaged exposure; the single startup segment
`0000001e--4a2fdc0d97` lacks usable driving signals. The older partial `0000000f` still begins
at segment 4; its missing initial segments could not be recovered and it is not a whole-route
comparison.

The source-matched validator previously suppressed the three-domain check for nested `d50`.
Diffing `8feab4fe` through `d50` confirms Odyssey's raw domain selector and `-0.30 m/s2`
road brake entry are unchanged; the grade experiment changes `GAS_COMMAND` mapping only, while
the intervening 3840 commit is lateral. Adding exact `359f`, `69a`, and `d50` SHAs to the
validator restored domain-model and brake-passthrough checks. Deliberately removing `d50` from
the mapped set made the focused test fail; restored code passes. Both candidate routes now have
valid source-matched domain reads. Request-to-wire RMS is roughly `0.005 m/s2` on both routes;
the first divergence under review remains Honda response after faithful command translation.

Route 1b has four moderate uphill episodes / 14.1 settled seconds: median request `+0.129`,
speed `31.4 m/s`, pitch `+0.051 rad`, and median `aEgo-carControl=-0.124 m/s2`. Its one high-
request episode / 8.5 seconds has median request `+0.902`, speed `21.2 m/s`, pitch `+0.063`,
and response error `+0.034 m/s2`. Route 1d has only one moderate episode / 1.9 settled seconds
at `-0.073 m/s2` and one high episode / 6.1 seconds at `-0.065 m/s2`; these are thin and
transmission changes confound the latter. Both routes show zero `>150`-count near-zero uphill
live-gas steps, over 263.8 and 9.2 eligible seconds respectively. This verifies removal of the
specific command discontinuity on road, not an accuracy gain by itself.

A reproducible exploratory match in `.agents/compare_uphill_response.py` excludes lead following,
driver pedals, non-gas domains, and 1.5 seconds around gear changes; it requires a positive-pitch
cruise request held for at least 2 seconds, drops the first 0.5 seconds, samples at about 10 Hz,
and matches speed within `2 m/s`, request within `0.10 m/s2`, pitch within `0.015 rad`, and exact
transmission gear. The long candidate route's high-request climb matches pre-grade route 0c in
all 65 sampled candidate points, but those reuse only 25 distinct baseline points and represent
one episode per route. Matched median `aEgo-carControl` is `+0.052` versus `-0.058 m/s2`;
matched mean absolute error is `0.078` versus `0.080 m/s2`. Thus it shifted response toward
more acceleration without establishing better absolute tracking. The candidate's moderate
points have no match to route 0c (median speed/request/pitch about `31.4/+0.125/+0.052`
versus `21.5/+0.296/+0.069`); route 0d has no qualifying moderate episode. Route 0d's
high-request examples are in gear 4 versus the candidate's matched gear 5, so the apparent
fall from its `+0.388 m/s2` bin error to the candidate's `+0.034` cannot isolate the ramp or
the high-request cap. Removing the exact-gear match deliberately made the matcher test fail.

Lateral is separate: route 1b supplied 8.62 high-authority 3840 seconds, actual-desired lateral
acceleration RMS `0.268 m/s2`, median sign-corrected under-response `+0.048 m/s2`, and zero
steering faults. Route 1d supplied only 1.31 high-authority seconds with RMS `1.114 m/s2` and
no steering faults. Neither is a matched stock-2560 benefit demonstration. In the earlier
20-24 m/s, desired `0.5..2.0 m/s2`, pitch `+0.015..+0.055 rad`, stable-demand, high-output
comparison slice, route 1b has zero eligible seconds; its high-authority frames are instead
centered near 31.4 m/s and stronger positive lateral demand. A separate 29-33 m/s, positive
desired `1.5..2.5 m/s2`, pitch `0..+0.04 rad`, stable-demand, output-at-least-2559 screen has
zero eligible stock-2560 seconds on routes 0b/0c/0d and on the additional same-small-model
stock-2560 routes `00000003--cb9f703767`, `00000005--a5d819505c`, and
`00000009--019ee79ffb`. The root lateral controller source is identical between their parents
and the candidate parent; their high-authority exposure is mainly near 21-22 m/s, not 31 m/s.
The high-speed slice has 1.79 seconds on candidate route 1a
(median demand `1.73 m/s2`, RMS `0.042 m/s2`) and 3.31 seconds on route 1b (median demand
`2.22 m/s2`, RMS `0.265 m/s2`); different demand and Alpha Long mode prevent an attributable
candidate-to-candidate or stock comparison. Do not infer 3840 benefit from either aggregate.

**Decision: CHANGE the evidence status, not the deployed code.** The ramped gas candidate has
now passed its first full road command-continuity screen, but has not shown an attributable
`aEgo-carControl` accuracy gain; keep it unpromoted for a comparable moderate climb and another
gear-matched high-request example. The 3840 lateral arm likewise remains unpromoted. Retire either
arm after the bounded adequately exposed screen if it still lacks an attributable improvement;
do not count unmatched bins or multiple samples from one climb as independent evidence.

#### First long 3840 screen with stock radar (2026-09-19)

Route `0000001a--d4ee53e0c3` resolves to parent `fdc1d7651a91` / nested
`359f3574d67f`; Alpha Long was off, so it is lateral-only evidence and cannot validate the
uphill gas-pulse fix. It contains 40.43 seconds of high-authority 3840 output, actual-desired
lateral-acceleration RMS `0.229 m/s2`, sign-corrected median under-response `+0.070 m/s2`, and
zero steering-fault events. The 3840 wire range was actually used; clean operation alone does
not establish tracking benefit.

For a narrower comparison, stock-2560 routes `0000000b--c529eb1e28`,
`0000000c--25d237b5ee`, and `0000000d--b4ced526db` retain the same Honda lateral mapping;
the root lateral controller path did not change before the 3840 arm. Filter both arms to
20-24 m/s, `0.5..2.0 m/s2` absolute desired lateral acceleration, `+0.015..+0.055 rad`
pitch, less than `0.5 m/s3` absolute 0.2-second desired-acceleration slope, CAN output at
least 2559 counts, and no driver steering press or steering fault. The three stock routes
contribute 18.46 seconds across ten episodes of at least 0.2 seconds (median sign-corrected
under-response `+0.074 m/s2`, RMS `0.147 m/s2`); the 3840 route contributes only 3.07 seconds
across four such episodes (`+0.190 m/s2`, RMS `0.243 m/s2`). Episodes within one route are not
independent road examples. Different roads and Alpha Long mode still confound this screen, so
it does not prove 3840 caused worse tracking, but it does not demonstrate a benefit either.

**Decision: CHANGE the trial status, not the deployed code:** 3840 remains an unpromoted,
bounded road candidate while a genuinely comparable second drive is sought. Do not infer from
the 40.43-second aggregate that added steering authority improved response. Retire it if the
next adequately matched exposure again shows no attributable gain, or sooner for steering faults,
oscillation, or driver-felt regression. Keep the prior stock-2560 pair reachable for revert.

#### Third 3840 road screen and lateral retirement (2026-09-20)

New full-rate routes `0000001f--48b00753c6` and `00000020--6b6bd8baed` resolve to root
`c29771b935db` / nested `d50a3a4843ed`, with the same small model, Alpha Long enabled,
and the 3840 lateral map. Route 1f has only 1.34 seconds of high-authority lateral output;
route 20 has 5.78 seconds, reaches 3840, and has no steering-fault events. On route 20,
high-authority actual-versus-desired lateral-acceleration RMS is `0.220 m/s2` and median
sign-corrected under-response is `+0.202 m/s2`. With Alpha Long active, the Bosch controller
sends steering directly on bus 1, rather than through the stock-radar bus-0-to-bus-1 forwarding
path. Direct decoding of route 20's five retained segments found 25,987 bus-1 `sendcan`
`STEERING_CONTROL` frames, of which 575 exceeded 2560 and the maximum was 3840. Matching each
transmit frame to the next `carOutput.actuatorsOutput.torqueOutputCan` within 50 ms gave 25,986
pairs, 25,984 exactly equal (MAE `0.008` counts; two outliers). The `lat_direct_*` validator
diagnostic now reproduces these values without changing the route ledger. Thus the larger controller output
reached the logged transmit path; the radar-forwarding metric is inapplicable to this Alpha Long
path. Logs do not prove EPS acceptance or that the Odyssey followed sharper turns accurately.

The reproducible `.agents/compare_lateral_response.py` screen filters speed to `20..24 m/s`,
absolute desired lateral acceleration to `0.5..2.0 m/s2`, pitch to `+0.015..+0.055 rad`,
absolute 0.2-second desired-acceleration slope below `0.5 m/s3`, output at least 2559 counts,
active lateral control, and no driver override or steering fault. It samples about 10 Hz and
nearest-matches route 20 to stock routes 0b/0c/0d within speed `1.5 m/s`, signed desired
acceleration `0.2 m/s2`, pitch `0.01 rad`, and desired slope `0.25 m/s3`. It matches 45/46
candidate samples to 20 distinct stock samples; reused stock samples are *not* independent
exposures. Candidate versus stock median speed is `21.79/22.07 m/s`, desired acceleration
`1.845/1.827 m/s2`, pitch `+0.041/+0.042 rad`. Candidate versus matched-stock lateral
tracking MAE is `0.214/0.160 m/s2`, RMS `0.232/0.176 m/s2`, and median signed under-response
`+0.220/+0.193 m/s2`. Different roads and reused baseline samples prevent a causal claim that
3840 worsened response, but there is no attributable accuracy gain. The previous route 1a has
40.43 seconds of high-authority output but only one point in this narrow overlap; route 1b
has 8.62 seconds high-authority but no overlap in this slice. These are three independent
adequately exposed 3840 routes (1a, 1b, 20), not three matched A/B trials.

**Lateral decision: RETIRE** the nonlinear 3840 map after the bounded three-route screen showed
no attributable improvement in following the requested lateral acceleration. Revert only nested
commit `359f3574d67f11e5723cd79840471529ac4af85b`; retain the later request-ramped
longitudinal code. This is an accuracy decision, not a comfort verdict. The map combined a
larger cap with higher normalized midrange gain, so these logs cannot separate those effects.
The stock-2560 rollback itself still needs a new road comparison; it is not proof that 2560 is
optimal at every turn or speed.

**Longitudinal decision: CHANGE trial status only, not code.** Neither new route supplies a
qualifying sustained uphill moderate/high-request comparison. Their small request-to-wire
residuals and lack of large near-zero live-gas steps do not establish better physical
`aEgo-carControl` tracking. Continue to evaluate the ramped candidate independently of lateral.

#### Post-rollback and swap-route audit (2026-09-22)

The 48-hour private-log audit retained and ledgered 16 additional routes (215 full-rate segments,
about 2 GB) rather than selecting by outcome. They span three separate source families and must not
be pooled by date or device: staging routes with unresolved nested provenance, `ody-op-swap`
revisions `df01ae3a7925` and `bef3e9148377`, and one `ody-op` stock-lateral route on nested
`ae81f00f905e`. Several sessions had no engagement or Alpha Long disabled.

Route `00000016--faa3964417` resolves to parent `9b8eb0fe04b6` / nested `ae81f00f905e` and is
lateral-only because Alpha Long was off. It supplies 88.10 active lateral seconds, 2.16 seconds at
the 2560 cap, zero steering faults, high-authority actual-versus-desired RMS `0.104 m/s2`, and
median signed under-response `-0.076 m/s2`. Stock-radar forwarding was counter-matched for 21,992
frames; its stable-cap median gain was exactly `1.000`, with source/output maxima both 2560. The
root lateral controller files are unchanged from 3840 route 20. Applying the existing narrow
20-24 m/s, demand, pitch, slope, and no-override matcher to 3840 route 20 against route 16 matches
15/46 candidate samples to 10 distinct stock samples: 3840 versus stock MAE is `0.148/0.088 m/s2`,
RMS `0.166/0.103 m/s2`, and median signed under-response `+0.167/-0.073 m/s2`. Different roads,
Alpha Long mode, and reused nearest-neighbor samples prevent a causal superiority claim. This new
exposure nevertheless shows no hidden sharper-turn accuracy benefit that would reopen 3840.

Nested `bef3e9148377` adds only live Alpha Long radar handoff and readiness gating around the same
settled Odyssey command-domain, bridge, and request-ramped uphill mapping. Exact source diff—not
the `ody-op-swap` branch name—therefore permits its active-long portions to use the three-domain
validator model. Route `00000010--768e1357e5` has 4.92 engaged minutes, request-to-wire RMS
`0.008 m/s2`, gas/brake achieved RMS `0.179/0.209 m/s2`, and no qualifying uphill moderate/high
episode. Route `00000012--18d8134f31` has 2.75 engaged minutes, request-to-wire RMS `0.005 m/s2`,
gas achieved RMS `0.121 m/s2`, and zero large uphill near-zero gas steps across 40.79 seconds, but
also no qualifying moderate/high uphill episode. These are useful response context, not a third
isolated uphill comparison.

**Decisions:** KEEP the stock-2560 rollback as the lateral baseline; it carried the requested cap
through the applicable steering path without faults and the matched slice does not reopen 3840.
CHANGE no longitudinal production code: the request-ramped candidate remains unpromoted pending a
third qualifying uphill moderate/high-request exposure. The current rebased/squashed device pair is
root `d9a951e814e0` / nested `da430e9591b8`; Alpha Long was restored to enabled after this audit.

#### Source-equivalent response timing follow-up (2026-09-22)

`inspect_response.py` adds one qualifying coast-to-brake response event from source-equivalent
route `00000010--768e1357e5` to two events on `0000001b--7bfc61a2d5`. Across these three events,
planner-to-request and request-to-wire RMS stay at or below `0.0196/0.0238 m/s2`. Honda's received
`COMPUTER_BRAKING` state follows the request after a median `0.080 s`; the strongest negative
achieved-response slope follows that state edge after a median `0.612 s`. Median achieved jerk is
`-1.66 m/s3` versus `0.68 m/s3` prior wire-command magnitude (`2.4x`), and two of three events have
no nearby gear edge. This extends the downstream brake-response symptom to the swap-gated but
command-source-equivalent revision; it does not identify a new controller-to-wire divergence.

An exploratory stable-domain time-shift screen does not support one fixed actuator-delay correction.
Across routes 10, 12, 1b, 1d, 1f, and 20, the gas-domain RMS-minimizing shift ranges from `0.00` to
the `1.00 s` search boundary; brake minima range from `0.10` to `0.50 s`, with several brake routes
providing only thin material-command exposure. Grade, gearing, slowly varying commands, and route
mix remain confounds. **Decision: no production change.** A fixed delay or command lead would alter
`carControl` timing without a repeatable response model. Continue using event-level state-edge timing
and require another independent, adequately exposed route before proposing a distinct brake-response
mechanism; do not restore the earlier onset limiter merely because the downstream symptom repeats.

### Crest and matched grade-gain decision (2026-09-23)

Three new full-rate routes resolve exactly to root `d9a951e814e0` / nested
`da430e9591b80d38556d8751ab8e67c92637d008`, small model
`f030157ccd2bacbdc6d7b98358903cbacc0e0b34`, standard personality, Experimental off, and Alpha
Long enabled: `00000017--fb0d39431f`, `00000018--fb4f0c5faf`, and
`00000019--5ff1b32941`. They provide 17.1 engaged minutes without a `controlsd` crash. Pooled
gas-domain achieved-response RMS is `0.215 m/s2` over 824.2 seconds; brake-domain RMS is
`0.223 m/s2` over 110.9 seconds. Planner-to-`carControl` error remains about `0.001..0.003 m/s2`
in inspected lead intervals, and request-to-wire RMS is `0.006..0.011 m/s2`. The first repeatable
gap therefore remains vehicle response after faithful command translation.

The reported crest release is not owned by the raw-pitch zero gate. On route 18 around 109-111
seconds, pitch remained positive (`+0.057` to `+0.044 rad`) while the planner and `carControl`
reduced acceleration from about `+0.92 m/s2` to zero, `GAS_COMMAND` fell from 1091 to about 200,
and the transmission shifted from fifth to sixth; achieved acceleration moved from about `+1.0`
to `-0.29 m/s2`. Route 19 around 532 seconds similarly changed from lead to cruise planning while
the request moved from about `+0.54` to `-0.26 m/s2` and the wire followed. The only qualifying
positive-to-nonpositive raw-pitch edge retained about `+0.0025 rad` filtered pitch and removed an
estimated 23 gas counts while the planner was already reducing the request. Do not change the raw
pitch gate to explain the larger crest symptom.

The existing log pool is sufficient to make the grade-gain decision; the prior note that deferred
action until a third specially shaped uphill route is superseded. `.agents/compare_grade_gain.py`
uses stable positive-request gas samples, excludes 1.5 seconds around gear changes, and greedily
matches candidate to pre-grade route `0000000c--25d237b5ee` one-to-one by speed within `2 m/s`,
request within `0.10 m/s2`, pitch within `0.015 rad`, exact gear, and lead-presence state. Across
1,816 matched pairs, the full request-ramped grade candidate reduces response MAE from `0.115` to
`0.106 m/s2` and is closer in 55.9% of pairs. No-lead MAE changes from `0.111` to `0.101`; lead
MAE changes from `0.126` to `0.121`. Reverting all grade assistance would therefore discard a
measured aggregate accuracy benefit.

Interpolating only along the observed matched baseline-to-candidate response effect gives a
minimum-MAE gain of `0.61` overall, `0.67` without a lead, and `0.41` with a lead; least-squares
fits are `0.49`, `0.58`, and `0.38`. A single `0.6` gain is chosen instead of lead-specific logic:
it is the rounded overall optimum, agrees with the no-lead fit, and moves lead response toward its
lower optimum without making Honda translation depend on planner source. This interpolation is an
observational fit, not a claim of perfectly linear actuator response, so the candidate remains an
isolated road-test arm rather than a promoted final calibration.

Nested Odyssey code now scales only the filtered positive-pitch load term by `0.6`. Raw
`ACCEL_COMMAND`, brake/coast/gas domain selection, the negative-live bridge, downhill behavior,
stopping, DBC, safety, lateral, other Honda platforms, and upstream commands are unchanged. In
frozen-input replay of route 17's matched lead over-response window at 313-316 seconds, median
`GAS_COMMAND` falls from 1091 to 807 counts; route 18's 108-112-second crest window falls from
1091 to 787 counts. This verifies command shape only. The gain check was mutation-verified by
setting it back to `1.0`, which failed the focused test. Restored `0.6` passes four Honda helper
tests, seven Odyssey model/interface tests, 20 rail tests with 58 subtests, and the full nested gate
of 3,946 tests with 703 skips plus ruff, codespell, typing, cpplint, and MISRA.

**Decision: CHANGE the request-ramped uphill candidate to a single `0.6` grade gain.** This is an
accuracy decision from the existing matched full-rate evidence, not a request for more examples.
The next ordinary drive grades the already-chosen candidate against the retained rollback; it does
not gate making the change.

The nested commit `9b4cbf40f63b` and parent commit `bc63ee6be25c` were published in that order and
deployed with the guarded `ody-op` workflow. After the offroad build and reboot, the device verified
branch `ody-op`, exact parent/gitlink/nested SHAs, clean parent and nested trees, comma-owned `.venv`,
`AlphaLongitudinalEnabled=1`, updater target `ody-op`, updater idle, no available update or updater
exception, active comma/manager/Panda processes, and no failed services. This proves installation
health only; the next route is the first closed-loop road result for the `0.6` candidate.

### First closed-loop 0.6 route and grade-gain refinement (2026-09-24)

The all-retained 72-hour pull added three routes on nested `9b4cbf40f63b`. Route
`0000001a--0505a229ca` is a zero-engagement startup fragment and cannot grade behavior. Route
`0000001b--6a9525565f` has 3.1 engaged minutes but no qualifying uphill moderate/high-request
episode. Route `0000001c--c1af7573e1` resolves exactly to deployed root `dbf479df165d`, nested
`9b4cbf40f63b`, small model `f030157ccd2bacbdc6d7b98358903cbacc0e0b34`, standard personality,
Experimental off, and Alpha Long enabled. It has 6.56 engaged minutes, no `controlsd` crash, and no
gas override. Request-to-wire RMS is `0.006 m/s2` overall and `0.0057 m/s2` in its five settled
moderate-uphill episodes, so the remaining response error is downstream of command translation.

Those five episodes provide 22.23 seconds at median request `+0.146 m/s2`, speed `22.0 m/s`, and
pitch `+0.0738 rad`. Median achieved `aEgo-carControl` error is `-0.137 m/s2` and RMS is
`0.211 m/s2`. Matching the route's stable positive-request gas samples one-to-one to the no-grade
route `0000000c--25d237b5ee` gives 121 pairs: gain `0.6` reduces response MAE from `0.223` to
`0.180 m/s2`. Interpolating from gain `0.0` to the observed `0.6` response puts the absolute optimum
at `0.70` by least squares and `0.78` by minimum MAE.

The stronger cross-check matches the same `0.6` route as baseline against all nine source-equivalent
gain-`1.0` routes used in the earlier 1,816-pair decision. It produces 549 one-to-one pairs. Full
gain has MAE `0.147 m/s2` versus `0.113 m/s2` at gain `0.6`; interpolation between the two observed
arms puts the absolute optimum at `0.68` by least squares and `0.67` by minimum MAE. The 539-pair
no-lead slice gives `0.68/0.65`; the lead slice has only ten pairs and gives `0.68/0.67`, so no
lead-specific translation is introduced. `.agents/compare_grade_gain.py` now accepts the tested
baseline and candidate gains and reports these absolute values directly. The complete gain-`1.0`
pool also reproduces the archived 1,816-pair `0.49/0.61` result; the earlier apparent discrepancy
came from invoking the tool with only the newest three of the nine source-equivalent routes.

Separately, routes 1b/1c add six coast-to-brake response peaks. Planner/request/wire RMS remains at
or below `0.0022/0.0200 m/s2`; Honda's received computer-braking state rises after median `0.065 s`,
and strongest achieved deceleration follows that state after median `0.555 s`, with `6.3x` median
response-jerk amplification and no nearby gear edge in all six events. This repeats the downstream
brake-response symptom but does not assign it to the grade gain or justify changing brake commands.

**Decision: CHANGE the single Odyssey grade gain from `0.6` to `0.7`.** The rounded value is shared
by the independent no-grade-to-0.6 and 0.6-to-full-gain fits. Raw `ACCEL_COMMAND`, filtering,
request ramp, command domains, braking, negative-live bridge, safety limits, lateral control, and
other Honda platforms remain unchanged. Nested commit `899548275` contains only the gain and its
assertion. Mutating the implementation back to `0.6` made the focused test fail; restored `0.7`
passes four helper tests, the full nested gate of 3,946 tests with 703 skips plus all lint/type/C
safety checks, and preflash's seven Odyssey interface/model tests plus 20 rail tests with 58
subtests. This establishes software and command-shape validity, not the new gain's road response.

Nested `899548275b8f` and parent `a16e89b1ae97` were published in that order and deployed through
the guarded `ody-op` workflow. After build and reboot, the device verified branch `ody-op`, exact
parent/gitlink/nested SHAs, clean parent and nested trees, comma-owned `.venv`,
`AlphaLongitudinalEnabled=1`, updater target `ody-op`, updater idle, no available update or updater
exception, two manager processes, one Panda process, and no failed services. This is installation
health only; a subsequent full-rate route will measure the closed-loop `0.7` response.

### Odyssey brake grade translation candidate (2026-09-24)

The retained full-rate pool is sufficient to separate Honda brake response from upstream command
shape. Across routes `00000003--cb9f703767`, `00000004--ca0260cf8f`,
`00000005--a5d819505c`, `00000009--019ee79ffb`, `0000000b--c529eb1e28`,
`0000001b--6a9525565f`, and `0000001c--c1af7573e1`, 62 coast-to-brake response peaks all follow
Honda's received `COMPUTER_BRAKING` rise. The state-to-peak median is `0.502 s`; median achieved
jerk is `-1.69 m/s3` versus `0.50 m/s3` median prior-wire magnitude, and planner/request/wire RMS
is at most `0.024/0.063 m/s2`. Fifty-six events have no nearby gear edge. A separate phase-aligned
screen of 63 stable entries removes each entry's initial response bias and finds median extra
deceleration of `-0.283 m/s2` by `0.6 s` and a median peak of `-0.419 m/s2`.

The historical `3.0 m/s3` onset-limiter routes do not identify the solution. Sixteen stable entries
retain the same response shape; conditioning on pitch, request, request change, and speed estimates
the limiter at `-0.089 +/- 0.109 m/s2` relative to raw command, while nearest physical-context
matching gives `-0.090 m/s2` median. Restoring that arm would therefore repeat a mechanism that did
not improve response. The MVL Boston `0111-op-honda` brake PID is also directionally incompatible:
its non-positive integral term can only make `ACCEL_COMMAND` more negative when Honda already
over-decelerates.

Settled response identifies grade as the attributable calibration input. After one second in a
stable road-speed brake domain, 1,117 samples across all seven routes fit achieved acceleration as
`-0.081 + 0.849 * lagged ACCEL_COMMAND - 3.163 * pitch - 0.0046 * speed + 0.017 * lead`.
Projecting only a physical `g*sin(pitch)` command term selects gains `0.313` by least squares and
`0.271` by minimum MAE; the lead/no-lead least-squares slices select `0.333/0.190`. Every route's
independent least-squares gain is positive (`0.162..0.516`). A rounded `0.3` gain reduces aggregate
projected MAE from `0.152` to `0.136 m/s2`; six routes improve or hold and one changes from `0.202`
to `0.212`. This is an observational response projection, not closed-loop proof.

**Decision: CHANGE to a `0.3` Odyssey brake grade translation as the next supervised road arm.**
Raw `carControl` still selects the gas/coast/brake domain. Only road-speed brake-domain PID frames
with valid pose and no driver brake translate the net acceleration target by
`0.3*g*sin(filtered_pitch)`, capped at zero and the existing acceleration rails. Level road, low
speed, stopping, missing pose, gas behavior, safety limits, lateral, and other Honda platforms are
unchanged. Frozen replay preserves all 2,620 brake-domain frames and all ten physical domain edges
on route 1c, reduces forceful edges from five to three, and does not increase worst wire jerk; it
does not predict closed-loop response. Reversing the pitch sign made the focused assertion fail.
Restored code passes 3,947 nested tests with 703 skips plus lint/type/C safety checks and preflash's
seven interface/model tests plus 20 rail tests with 60 subtests. Nested `0fbe4df19eea` and parent
`e958229994ff` were published in that order and deployed through the guarded `ody-op` workflow.
After build and reboot, the device verified those exact parent/gitlink/nested SHAs, clean parent and
nested trees, comma-owned `.venv`, `AlphaLongitudinalEnabled=1`, updater target `ody-op`, updater
idle, no available update or updater exception, two manager processes, one Panda process, and no
failed services. This proves installation health only; the next full-rate route grades the brake
translation and the already-deployed `0.7` gas gain independently.

The first 48-hour device query after deployment found 18 retained routes, all already validated and
none recorded after the candidate installation. No closed-loop brake-grade result is therefore
claimed. Before the next route, `validate_log.py` gained an exact `0fbe4df19` expected-wire model:
it reconstructs the controller's 0.5-second pitch filter, `0.3*g*sin(pitch)` term, road-speed/PID/
brake-domain eligibility, zero cap, and Honda acceleration rails. Candidate rows now grade
`ACCEL_COMMAND` against that source-matched expectation while retaining raw wire-minus-`carControl`
RMS and translation exposure/delta separately. Reversing the diagnostic gain sign fails the focused
synthetic assertion; restored code passes all 54 validator tests. This is offline attribution
tooling only and does not alter vehicle behavior.

`.agents/compare_brake_grade_gain.py` makes the pre-deployment gain fit reproducible from the seven
named full-rate routes. It requires PID, no pedals, road speed, at least one second in the brake
domain, and no more than `0.08 m/s2` request span over the prior 0.5 seconds; it uses the exact
zero-initialized 0.5-second pitch filter and thins each route to 5 Hz. The resulting 1,132 samples
fit gain `0.305/0.263` by least squares/minimum MAE, with projected MAE changing from `0.153` to
`0.139 m/s2` at gain `0.3`. Equal route weighting fits `0.272/0.187` and changes MAE from `0.144`
to `0.135`. All seven route-level least-squares gains remain positive (`0.155..0.473`); six routes
improve and route 1c is effectively flat (`0.112` to `0.114`), while route 09 worsens (`0.205` to
`0.215`). Lead/no-lead fits are `0.325/0.301` and `0.182/0.152`; the single `0.3` candidate remains
the rounded pooled/route-balanced calibration rather than adding planner-source-dependent behavior.
Four pure tests cover the trailing stability window, gain recovery, response sensitivity, and
route/sample weighting. These are still frozen-response projections, not road proof.

### 07:51 lead-following oscillation and bounded uphill gas hold (2026-09-24)

Complete route `0000001e--295c52755b` started at 07:46:24 local and resolves exactly to parent
`f951584ad758` / nested `0fbe4df19eea`, small model
`f030157ccd2bacbdc6d7b98358903cbacc0e0b34`, standard personality, Experimental off, and Alpha
Long enabled. The reported 07:51 event is route-relative 275.35 seconds. The selected lead was
present and the planner source was `lead0`; across the surrounding 250--325-second window the
planner used `lead0` for 69.18 of 71.28 engaged seconds. Planner-to-`carControl` RMS was
`0.0010 m/s2`, and raw `carControl`-to-wire RMS was `0.0138 m/s2`, while achieved
`aEgo-carControl` RMS was `0.1692 m/s2`.

The first repeatable downstream divergence is the uphill negative gas/coast transition. At
275.35 seconds the request/wire/actual values were `-0.099/-0.100/-0.223 m/s2` at `+0.0206 rad`
pitch with live gas. At 276.91 seconds the raw request crossed `-0.201 m/s2`, gas became inactive,
and actual acceleration was already `-0.269 m/s2`. When the request recovered to `-0.098 m/s2`
at 281.30 seconds, the `-60` bridge entered but actual acceleration had reached `-0.403 m/s2`.
Across the full window, mean `aEgo-carControl` error was `+0.024` in live gas but `-0.169` in
inactive coast and `-0.167 m/s2` in the brake domain. The vehicle therefore lost speed and gap
in coast/brake, causing the lead planner to request positive recovery acceleration; this is not a
planner-to-controller or numeric CAN-packing error.

Nested candidate `ff33e79f665a` preserves raw `ACCEL_COMMAND`, positive-request grade mapping,
fresh coast-to-`-60` bridge entry, level/downhill behavior, low-speed stopping, and raw
`-0.30 m/s2` brake selection. Only when gas is already active on a positive-pitch road-speed PID
frame, it adds a smooth negative-request grade term capped at `+0.10 m/s2`. The term is zero at
both zero request and the raw brake boundary and peaks at the stock gas split, so it neither
reintroduces the former sign-crossing step nor arms gas from inactive coast. On frozen 1e inputs,
the candidate reduces inactive coast from 22.96 to 14.11 seconds and coast entries from 12 to 7;
wire-jerk peak/p99 remain `0.863/0.221 m/s3`, and brake frames remain 530 versus 531 recorded.
This verifies command shape only, not the closed-loop response.

Setting the new correction cap to zero made two focused Honda tests and the decoded
controller/Panda lifecycle test fail; restoring `0.10` passes six Honda helper tests and 21 rail
tests with 60 subtests. The full nested gate passes 3,948 tests with 703 skips plus ruff, codespell,
typing, cpplint, and MISRA. Preflash passes seven Odyssey model/interface tests and the same 21 rail
tests with 60 subtests.

**Decision: CHANGE to this bounded uphill negative-request gas-hold candidate for a supervised road
screen.** Grade the same mild-negative lead-following window by coast dwell/entries,
`aEgo-carControl`, speed-gap oscillation, gas steps, direct gas/brake handoffs, and interventions.
Retire for positive surge, renewed near-zero gas pulsing, delayed needed braking, or failure to
reduce the downstream coast deficit. Keep the `-60` bridge; this candidate prevents avoidable
uphill releases but does not replace fresh coast recovery.

Nested `ff33e79f665a` and parent `6e14266902f4` were published in that order and deployed through
the guarded `ody-op` workflow. After the device build and reboot, it verified those exact
parent/gitlink/nested SHAs, clean parent and nested trees, comma-owned `.venv`,
`AlphaLongitudinalEnabled=1`, updater target `ody-op`, updater idle, no available update or updater
exception, two manager processes, one Panda process, and no failed services. This proves exact
installation health only; closed-loop retention depends on a subsequent full-rate route.

The interrupted companion route `0000001d--cce80a222e` was subsequently recovered in full. It is
the same exact pre-candidate parent/nested/model/mode pair and contains 46.9 logged minutes with
7.0 engaged minutes. Source-matched brake wire RMS is `0.0098 m/s2`; achieved gas/brake RMS is
`0.188/0.249 m/s2`. Whole-route replay changes inactive coast only from 5.46 to 5.26 seconds because
this route's sustained `-0.20..-0.15` active-gas release-band exposure is slightly downhill at
median pitch `-0.008 rad`; it is not an uphill domain A/B.

Its positive-pitch negative-gas samples independently support the bounded correction's direction.
After filtering pitch as the controller does, requiring at least `+0.015 rad`, and aligning response
by `+0.6 s`, route 1d supplies 3.78 seconds in `-0.20..-0.15 m/s2` with mean
`aEgo-carControl=-0.277 m/s2`; the candidate adds `+0.094 m/s2` mean gas-map input. Route 1e adds
1.09 seconds at `-0.218/+0.095`. In `-0.15..-0.10`, route 1d supplies 9.67 seconds at
`-0.137/+0.070`, and route 1e supplies 2.25 seconds at `-0.124/+0.064`. By contrast, the
`-0.10..-0.05` response means are approximately zero on both routes while the candidate addition
is only `+0.029`; the smooth taper toward zero remains necessary and is an explicit over-response
screen. These frozen-response bins support the candidate's sign and bounded shape but do not replace
its post-deployment closed-loop check.

The validator now reports those two candidate-specific bands directly on every full-rate route.
It requires longitudinal PID, no driver pedals, live gas without `BRAKE_REQUEST`, at least
`10 m/s`, and controller-filtered pitch of at least `+0.015 rad`, then compares achieved
acceleration `0.6 s` later with the current `carControl` request without interpolating across log
gaps. On the pre-candidate routes, the combined `-0.20..-0.10 m/s2` band measures 13.45 seconds
at mean error `-0.177 m/s2` on 1d and 3.34 seconds at `-0.155 m/s2` on 1e. The tapered
`-0.10..0` guard measures 51.17 seconds at `-0.000 m/s2` and 36.03 seconds at `-0.005 m/s2`.
These are the frozen pre-candidate reference values for the next source-exact route, not a
matched-road verdict. Raising the synthetic test's pitch threshold above its uphill trace makes
the focused check fail; restored tooling passes all 55 validator tests.

## 2026-09-24 — route 1f lead cycling, launch response, and Experimental hill

Route `0000001f--3c3caa3f64` started at 11:44:58 CDT with exact parent
`6e14266902f41a100bd29223ec9fcd2e63fd875b` and nested `opendbc`
`ff33e79f665a518be8812e8346a1f50a10100fe8`. It logged 36.5 minutes and 12.2 engaged
miles with Alpha Long enabled. Aggregate planner-to-`carControl` RMS was `0.002 m/s2`, gas-wire
RMS was `0.008 m/s2`, and source-matched brake-wire RMS was `0.010 m/s2`; the route-level
`aEgo-carControl` RMS was `0.273 m/s2`. Thus the command path remained close while physical
response did not.

At 11:50:21 the takeover alert was `commIssue/softDisable`: `longitudinalPlan`,
`driverAssistance`, `alertDebug`, and `lateralManeuverPlan` were invalid, with the last two also
not alive and below expected frequency. The condition cleared after about 1.9 seconds and no
managed process crash appeared. This is a root process/service communication fault, not a Honda
translation or safety divergence, so it is diagnosed here but is outside the behavioral scope.

The 11:50:44–11:53:23 highway lead-following episode was predominantly `lead0`. The planner and
`carControl` matched at `0.001 m/s2` RMS and raw wire matched `carControl` at `0.018 m/s2` RMS,
while the `+0.6 s` achieved-response error was `-0.036 m/s2` mean and `0.166 m/s2` RMS. The
request itself ranged from `-0.514` to `+0.617 m/s2`, producing repeated catch and deceleration
commands; achieved acceleration ranged from `-0.735` to `+0.952 m/s2` and amplified portions of
that cycle. The Honda port did not invent the oscillation, but vehicle response made the planner's
cycle more pronounced.

The 11:55:11–11:55:56 Moore Street episode was also predominantly `lead0`. Planner-to-control RMS
was `0.002 m/s2`, wire RMS was `0.061 m/s2` including intentional brake-grade compensation, and
achieved-response error was `+0.148 m/s2` mean and `0.340 m/s2` RMS. During the launch the request
reached `+1.432 m/s2`; actual acceleration remained around `+1.0 m/s2` after the request had
fallen to roughly `+0.3`, causing the planner to reverse into braking. Three low-speed-to-road-speed
accelerations on this route had mean achieved errors of `+0.192`, `+0.315`, and `+0.154 m/s2`.
Command transport was accurate; the Odyssey accelerated more eagerly and retained response after
the command fell.

At 12:06:41–12:08:18 in Experimental, planner-to-control RMS remained `0.003 m/s2` and wire RMS
`0.034 m/s2`, but achieved-response RMS was `0.323 m/s2`. On the steep ascent, at filtered pitch
near `+0.10 rad`, the Experimental source itself requested approximately `-0.10..-0.17 m/s2`;
the wire followed and the Odyssey decelerated about `-0.69..-0.82 m/s2`. The first divergence for
the uphill slowdown is therefore upstream of `carControl`. After the crest, pitch became negative
while the model requested `+0.17..+0.32 m/s2`; the deployed positive-gas grade map ignored descent
and the Odyssey reached about `+0.86..+1.18 m/s2` before the planner commanded braking. The
downhill surge begins upstream but was materially amplified by Honda response and the one-sided
grade translation.

The source-exact grade screen supplies 448 stable positive-uphill matches across routes 1c and 1f.
The tested `0.7` gain had `0.112 m/s2` MAE versus `0.106 m/s2` for `0.6`, with fitted absolute
gain about `0.63`; this supports restoring `0.6`. Removing grade entirely was worse on route 1f
(`0.144` versus `0.136 m/s2` MAE for the deployed compensation). The current negative-request
uphill candidate improved comparable lead-present under-response by roughly `0.10 m/s2`, although
steady no-lead uphill exposure over-corrected; it remains bounded and unpromoted rather than being
discarded or made planner-source-specific.

The next isolated Honda candidate therefore restores positive-request uphill gain `0.6` and applies
the same signed grade estimate on descents, flooring the translated gas input at the stock Bosch
gas breakpoint. Raw `ACCEL_COMMAND`, negative-request uphill behavior, domain selection, DBC, and
safety are unchanged. Raw and filtered pitch signs must agree before compensation is applied, so a
stale filter cannot carry uphill compensation through a crest. On route 1f shadow evaluation the
candidate changed only positive gas: 46.70 downhill seconds changed by median `-4` counts over the
whole route, median `-151` during Moore Street downhill exposure, and median `-144` during the hill
crest. The hill-crest minimum was `-269` counts. Open-loop replay kept the same 2,089 negative-live
bridge frames and brake-domain behavior.

Mutation checks showed that restoring gain `0.7` or disabling downhill compensation fails the
focused Honda test. The restored candidate passes the Honda helper tests, Odyssey preflash suite,
and full nested test suite: 3,948 passed and 703 skipped, with lint, type, spelling, C++ style, and
MISRA checks passing. This is a command-response candidate; its road response is not established by
the frozen-input shadow.

The candidate was published and installed offroad as parent `0bd9816712b10f66ef7bf7aeb96947e03f1eca45`
with nested `6915be202bb769199905c307e5f72b9bc62345dd`. Post-reboot verification found clean paired
trees, updater idle with no available update or exception, active manager and Panda services, no
failed services, and `AlphaLongitudinalEnabled=1`. This establishes deployment health only; the
signed-grade candidate remains road-unmeasured.

An additional response-lag screen of the pre-candidate route 1f separates positive-gas overshoot
from simple time alignment. During 20.34 seconds of active Moore Street positive gas above
`+0.10 m/s2`, mean `aEgo-carControl` error was `+0.306`, `+0.312`, and `+0.229 m/s2` when
response was aligned at `0`, `+0.6`, and `+1.5 s`, respectively. At `+0.6 s`, 7.51 seconds of
locally steady request still averaged `+0.265 m/s2` error; 5.58 seconds of falling request
averaged `+0.383`. Across this route's 256.06 seconds of positive gas, the `+0.6 s` error was
`+0.164 m/s2` mean, but terrain conditioning matters: near-level samples averaged `+0.312`,
uphill `+0.062`, and downhill `+0.703 m/s2`. These are within-route descriptive exposures, not
independent route counts or proof of the exact map correction. The signed-grade candidate directly
changes downhill gas, while the near-level and request-fall overshoot remain separate Honda-response
targets for source-compatible conditioning by speed, gear, request, and terrain. The device route
listing at this evidence check showed no full-rate drive after the signed-grade deployment.

A stricter fourth-gear launch match repeats the near-level over-response independently of the
Moore lead episode. On pre-candidate routes 1c (`9b4cbf40f63b`), 1e
(`0fbe4df19eea`), and 1f (`ff33e79f665a`), restrict to active PID, no lead or driver pedals,
live positive gas, `12..20 m/s`, `+0.8..+1.6 m/s2` request, absolute pitch below `0.025 rad`,
locally steady request, fourth gear unchanged for at least one second, and `1600..2500 rpm`.
At 5 Hz, the eligible exposure is only `2.0`, `2.0`, and `3.2 s`, respectively, so this is a
repeatable direction rather than a fitted gas-scale estimate. The three median requests are
`+1.106`, `+1.102`, and `+1.087 m/s2`; gas commands `1188`, `1184`, and `1171` counts; speeds
`13.58`, `13.74`, and `14.29 m/s`; and `aEgo(t+0.6)-carControl(t)` means are `+0.307`,
`+0.464`, and `+0.415 m/s2`. The positive gas maps differ only in grade gain across these
revisions, and the matched wire commands are nearly equal. This supports a Honda positive-gas
response issue around low-road-speed fourth-gear acceleration, separate from the lead planner's
cycle. It does not identify the exact gas decrement or establish response after the new signed-grade
candidate, so retain that isolated candidate pending its road readout rather than combining
mechanisms.

For this matched positive-request band, the current Odyssey interface selects the upstream
`[0, 2000]` Bosch gas map over acceleration breakpoints `[-0.2, 2.0]`. At fixed pitch, its
`GAS_COMMAND` is therefore almost an affine function of the same request carried as
`ACCEL_COMMAND`; the fourth-gear samples cannot independently identify the vehicle's response per
gas count. Their `1171..1188` count spread is too small to size a correction from the observed
`+0.31..+0.46 m/s2` overshoot. The historical static gasfactor seed was materially weaker but
under-responded in its recorded cold-start exposure; its result does not identify a current
low-speed scale either. Preserve the observed overshoot as an actionable response target without
reviving that old learner or inventing a count decrement from collinear commands.

### 2026-09-24 post-deployment routes and 16:42–16:43 uphill lead cycle

Full-rate routes `00000020--f90697dedf`, `00000021--5468eedff4`, and
`00000022--1326e023d1` all resolve to behavioral parent `0bd9816712b1`, nested
`6915be202bb7`, small model `f030157`, Standard mode, and Alpha Long enabled. Their
engaged exposures are 1.7, 1.6, and 6.8 minutes. These are road exposures for the build,
but none contains a positive-gas interval with filtered pitch below `-0.015 rad` and raw
pitch negative lasting at least 0.5 seconds. Thus the new downhill positive-gas branch has
no relevant road exposure yet; neither benefit nor harm can be assigned to it. The 16:42–16:43
episode in route 22 is uphill, with pitch approximately `+0.01..+0.03 rad`.

For route 22, 16:42:00–16:43:00 CDT has 59.75 active seconds: 18.74 seconds sourced from
cruise and 41.01 from `lead0`. Planner-to-`carControl` acceleration RMS is `0.002 m/s2`;
`carControl`-to-wire RMS is `0.025 m/s2`, including deliberate grade-relative brake
translation. The request spans `-0.555..+0.689 m/s2`, with 43.2 seconds gas, 1.3 coast,
and 15.2 brake. Achieved acceleration aligned `+0.6 s` differs from request by
`-0.078 m/s2` mean and `0.163 m/s2` RMS. The following 16:43:00–16:43:37 `lead0`
interval is all gas, with planner-to-control RMS `0.0007`, wire RMS `0.004`, and achieved
error `-0.001` mean / `0.097 m/s2` RMS: positive-gas command following there is close.

The first divergence driving the catch/brake pattern is upstream of `carControl`.
The raw `modelV2.leadsV3` range/velocity values themselves jump; `radarState` is vision-only
and reflects those values, rather than inventing the jumps. Around 16:42:21, model lead
range falls from roughly 75 to 65 m within a second while its reported relative velocity
is only about `-0.5..-1 m/s`; the planner switches from positive acceleration to braking
by 16:42:23.52. Around 16:42:56.18–16:42:57.68, raw lead range moves
`51.8 -> 43.9 -> 56.9 m`; at the middle point the reported lead velocity jumps to
`35.9 m/s` versus stable model ego speed near `30.3 m/s`, inconsistent with the shrinking
gap. Lead-presence probability remains about `0.98..1.00` and no lost-lead event appears;
probability is not a guarantee that range or velocity is accurate. Across 73 one-second
continuity checks, median range-versus-relative-velocity discrepancy is `1.0 m`, 95th
percentile `4.13 m`, and seven exceed 3 m. Private road-camera frames show the same dark
SUV remaining in the lane ahead; a blue SUV passes on the left, without an obvious cut-in.
The video does not establish precise physical range or acceleration, but it rules out an
obvious lane-change explanation for the raw-model discontinuities.

Honda response is a secondary, separable contributor. In the 16:42:17–39 and
16:42:39–16:43:00 `lead0` portions, gas-domain achieved-minus-request mean is about
`-0.033` and `-0.011 m/s2`, respectively; brake-domain mean is `-0.127` and
`-0.099 m/s2` even though the grade-relative brake wire command is about `+0.054`
and `+0.036 m/s2` less negative than raw request. Brake release at 16:42:32.58 and
16:42:56.42 occurs as the raw request crosses zero, while achieved acceleration remains
negative for about 0.44 and 0.34 seconds before crossing zero. Source-matched validation
reports 12.88 seconds of brake-release hold over seven events, with mean achieved error
`-0.17 m/s2`; this mechanism predates the signed-grade update (route 1f had 50.10 seconds
over 32 events and mean error `-0.22 m/s2`). These are evidence for Honda braking/response
work, not evidence that the new downhill branch created the lead oscillation. Keep the
current candidate pending direct downhill exposure; do not tune Honda gas to erase the
vision/planner catch/brake cycle.

The post-deployment uphill positive-gas comparison is source-compatible: nested
`ff33e79f665a` and `6915be202bb7` differ in positive gas only by gain `0.7` versus
`0.6`, signed descent handling, and a raw/filtered pitch-sign guard. Descent handling
is inactive on the matched uphill samples; the matcher does not independently verify
the sign guard's state on every frame, so this remains a conditioned observational screen.
Using the established one-to-one speed/request/pitch/gear/lead matcher, route 1f versus
route 22 yields 105 matches. Achieved-error MAE is `0.084 m/s2` at `0.7` versus
`0.095 m/s2` at `0.6`; interpolated absolute optima are `0.66` by least squares and
`0.65` by MAE. The 58 no-lead matches favor about `0.68..0.69`, while 47 lead matches
favor about `0.64`. This is not a basis to restore `0.7` or to make grade gain
planner-source-specific; retain `0.6` while the exact downhill branch remains unexposed.

Settled road-speed brake-domain samples on the same brake-translation source are also
mixed: route 1f contributes 370 thinned samples with mean achieved-minus-request
`-0.105 m/s2`, and route 22 contributes 91 with `-0.126 m/s2`. Projecting an *incremental*
gain on top of the deployed brake gain `0.3` fits `-0.005` for route 1f but `+0.183` for
route 22 by least squares. In the narrower uphill highway-lead band
(`28..36 m/s`, request `-0.6..-0.15 m/s2`, pitch basis `0.1..0.4 m/s2`), the two routes
have only 20 and 45 thinned samples and mean response errors `-0.208` and
`-0.109 m/s2`, respectively, despite the same brake source. Thus a single new brake
grade coefficient is not identified by this symptom; the remaining Honda brake
overdeceleration and release dynamics need to be separated from grade before changing
the wire command.

The current brake-translation source also reproduces the delayed Honda brake-entry
response independently of the older seven-route calibration pool. Running the
full-rate `inspect_response.py` event diagnostic on routes 1f and 22 finds 15 and
four qualifying negative achieved-jerk peaks, all after coast-to-brake edges and
all with received `COMPUTER_BRAKING` active at the peak. Combined median
request-to-state delay is `0.062 s`, state-to-peak delay `0.492 s`, and achieved
jerk `-1.73 m/s3` versus `0.55 m/s3` median preceding wire-jerk magnitude;
18/19 have no gear edge. Local plan-to-`carControl` RMS is at most `0.007 m/s2`.
The two routes' median peak jerk is `-1.60` and `-2.12 m/s3` with median preceding
wire magnitudes `0.55` and `0.78 m/s3`, respectively. This confirms that the
grade-translated brake command has not removed the delayed brake-response mode.
It does not make the old `3.0 m/s3` onset limiter newly attractive: that limiter
altered only the first roughly 0.1 seconds, while the received-state-to-peak
delay remained about half a second on its own road arm. **Decision: KEEP the
current brake translation; do not delay a lead's requested braking or scale
`ACCEL_COMMAND` from this event screen alone.** The distinct Honda-side target
is the post-entry response after computer-braking activation, to be separated
from requested brake depth and terrain using the retained full-rate pool.

The new `inspect_response.py` brake-entry tracking profile resolves the sign of
the response error after a physical coast-to-brake edge. It requires 0.3 seconds
without braking before entry, coast immediately before entry, one continuous
brake-domain second afterward, PID with no driver pedals, speed at least 10 m/s,
and unchanged gear. At `+0.2/+0.5/+0.8/+1.0 s`, it compares 0.2-second-filtered
`aEgo` with the *active* `ACCEL_COMMAND` at the same times; numeric command values
before the brake-domain edge are not treated as applied brake force. Route 1f
has 26 eligible edges with median errors `+0.338/+0.243/-0.074/-0.139 m/s2`;
route 22 has six with `+0.258/+0.235/-0.035/-0.045 m/s2`. Positive means
less deceleration than the wire request. Route 1e has three edges with
`-0.013/-0.041/-0.030/-0.079 m/s2`, so this transient is not uniform across
every exposure. On the 1f/22 events, removing the extra acceleration filter
still gives early positive and late negative median error (`+0.259/+0.064/-0.151/-0.131`
and `+0.194/+0.084/-0.169/-0.064 m/s2`). The sign reversal is therefore not
created by the diagnostic's 0.2-second filter. This is direct current-source
evidence against a simple static brake-offset change: weakening the wire to fix
the late overdeceleration would worsen the early underbraking. The local
coast-only screen found just two comparable negative-command changes, so it
does not isolate a fixed brake-domain step from all possible powertrain/terrain
effects. Retain the current brake command while investigating the response
dynamics rather than treating the `0.3` grade gain as the cause.

Speed conditioning changes the interpretation of that pooled profile. The
diagnostic now prints entry-speed bins. Route 1f's 20 entries at `10..20 m/s`
have median active-wire errors `+0.416/+0.295/-0.083/-0.143 m/s2` at
`+0.2/+0.5/+0.8/+1.0 s`; its three entries at `30..40 m/s` have
`+0.065/+0.033/+0.018/-0.051`. Route 22's two `10..20 m/s` entries have
`+0.685/+0.627/+0.318/+0.186`, while its three `30..40 m/s` entries have
`+0.014/-0.024/-0.054/-0.048`. Route 1e adds three `30..40 m/s` entries
near the active wire throughout (`-0.013/-0.041/-0.030/-0.079`). These are
small high-speed event counts, but they establish that the large early lag
in the pooled current-source screen is concentrated at lower road speeds;
the 16:42 uphill highway lead episode must not be described as suffering
the same large early brake lag. The lower-speed pattern is not yet uniform
in its late phase, so do not infer one speed-scheduled command offset from
these medians.

The diagnostic now also splits `10..20 m/s` entries by active wire depth at
`+0.5 s` (`>-0.5` versus `<=-0.5 m/s2`). In route 1f, 17 mild entries have
median errors `+0.401/+0.264/-0.091/-0.154 m/s2`; three firm entries have
`+0.863/+0.741/+0.376/-0.006`. Route 22's two lower-speed entries (one per
depth bin) remain under the active wire at `+1.0 s` by `+0.238/+0.134 m/s2`.
The depth split does not fully explain the route difference, but it makes
clear that strong-command underbraking and mild-command late overbraking
must not be collapsed into one static brake gain or one speed-only correction.

### Bounded low-road-speed positive-gas response trial (2026-09-24)

The Honda-owned near-level acceleration overshoot remains visible on the current
behavioral source. Reapplying the steady fourth-gear screen at `12..20 m/s`,
`+0.8..+1.6 m/s2` raw request, pitch magnitude below `0.025 rad`, no lead or
driver pedals, stable gear, and `1600..2500 rpm` gives 2.8 seconds on route
1f (`ff33e79f665a`) at median request `+1.094`, gas `1178`, and
`aEgo(t+0.6)-carControl(t)` mean `+0.420 m/s2`. Post-deployment route
`00000020--f90697dedf` (`6915be202bb7`) contributes only 0.2 seconds
at request `+1.088`, gas `1172`, and error `+0.317 m/s2`; routes 21 and 22
do not exercise this narrow band. This is corroboration of direction, not a
current-build gain fit. A broader `10..22 m/s`, `+0.5..+1.6 m/s2` no-lead
screen finds 3.0 seconds in fourth gear and 1.8 in fifth on route 1f,
with mean errors `+0.414` and `+0.478 m/s2`.

For a bounded trial size, seven learner-era routes were screened with the
same strict fourth-gear conditioning. Only routes `00000061--b8f07e1ca7`,
`00000062--e38819678c`, and `00000066--a1ef887d10` contain eligible
samples (five, six, and seven at 5 Hz). One-to-one matching against routes
1f/20 within `1.5 m/s` speed, `0.1 m/s2` request, `0.01 rad` pitch, and
`300 rpm` yields three pairs: two are adjacent samples from one route-1f
episode matched to route 62, and one route-1f sample matches route 61.
The actual feature differences are tighter than the limits: speed within
`0.25 m/s`, request `0.007 m/s2`, pitch `0.002 rad`, and RPM `77`.
Both sources send `ACCEL_COMMAND` within `0.006 m/s2` of raw request.
Median current versus learner-era gas is `1205` versus `1012` counts;
median achieved error is `+0.405` versus `+0.158 m/s2`, and the paired
error difference is `+0.223 m/s2`. These are only two independent old-route
comparisons, not an isolated gas-count causal experiment: the older Honda
controller has other changes. The exact `ACC_CONTROL` packing/DBC remains
the same and positive gas with raw numeric acceleration is comparable, so
the contrast supplies direction and an approximately 200-count *trial*
magnitude, not a promoted calibration or predicted road improvement.

The nested Odyssey candidate subtracts at most 200 opaque `GAS_COMMAND`
counts for positive PID requests with no driver gas. Smooth zero-slope
ramps make the trim full only from `12..20 m/s` and `+0.8..+1.6 m/s2`,
tapering to zero by `8/24 m/s` and `+0.4/+2.0 m/s2`. Raw
`ACCEL_COMMAND`, gas/brake-domain selection, negative-live bridge, brake
translation, low-speed stop behavior, highway gas, DBC, safety rails, and
lateral control remain unchanged. On frozen recorded inputs thinned to
5 Hz, the helper changes 55.2 seconds of positive gas on route 1f
(median/minimum `-157/-200` counts), 8.2 seconds on route 20
(`-200/-200`), none on route 21, and 12.8 seconds on route 22
(`-185/-200`). No sampled negative-request, brake-domain, or speed-at-least-
24 m/s frame changes. These are command-shape observations only; the
closed-loop vehicle response to this trim is not yet known.

The focused unit and decoded-controller/Panda tests deliberately fail when
the 200-count trim is mutated to zero, then pass when restored. The helper
test also checks dense monotonicity of gas versus request and continuity at
the four speed-ramp boundaries. Odyssey preflash passes seven interface/model
tests and 22 rail tests with 60 subtests; Honda helper and safety coverage
passes 255 tests with 244 skips and 20 safety subtests. A one-segment
controller replay on route 1f processes 5,974 frames, including 3,656
engaged frames, retaining two physical brake-domain flips and 46 negative-
live-gas frames; its numeric `ACCEL_COMMAND` comparison is not a gas-response
prediction. The broader root-environment nested pytest run gives 3,600
passes and 1,677 skips; three MISRA mutation-harness cases fail because that
separate shell script invokes the unavailable nested `uv sync`/Cppcheck
environment. There are no C or safety-source changes in this candidate.
**Decision: CHANGE to this bounded, unpromoted positive-gas trial for a
supervised road screen, not as a confirmed calibration.** Publish/deploy only
after paired source and device checks; compare source-compatible achieved
acceleration with the requested value inside and outside the trim band and
retire the trial if low-speed under-response or lead-gap loss replaces the
recorded overshoot.
The isolated nested candidate is published on `ody-op` as `47196b9a4`,
and parent `a8d11cd9aa` pins it. The first device SSH precheck timed out,
so no deployment, build, or device-state check was attempted. The last
verified device pair remains the behavioral road baseline, not proof of its
current state. Device and parent gitlink must match the exact candidate
before its road response can count.

The next threshold screen conditions on active PID, no driver pedals, request
`-0.30..-0.20 m/s2`, pitch magnitude below `0.03 rad`, at least 0.5 seconds
before and 0.6 seconds after each sample continuously in the recorded coast
or brake domain, and 5 Hz thinning. It
compares `aEgo(t+0.6)-carControl(t)` without treating brake and coast as
counterfactual pairs. On route 1f at `10..20 m/s`, coast has 30 samples,
median request `-0.227`, and mean/median tracking error `+0.066/+0.061 m/s2`;
brake has 50, median request `-0.260`, and `-0.164/-0.173 m/s2`.
At `30..40 m/s`, route 1e coast has 53 samples and mean error `-0.158`,
while its brake has 30 and `-0.103`; route 1f coast has seven and `-0.107`,
brake six and `-0.110`; route 22 coast has only one and `-0.073`, brake
eight and `-0.106 m/s2`. These domain samples have different prior command
histories, so the contrast does **not** estimate the response to switching
the entry threshold. It does rule out the simple assumption that earlier
braking is uniformly needed: highway coast already overdecelerates, and
settled lower-speed braking overshoots where coast underdecelerates.

For the 20 eligible `10..20 m/s` route-1f brake entries in the entry-profile
screen, the median request had already been at or below `-0.20 m/s2` for
roughly a few tenths of a second before the recorded `-0.30` entry, but the
duration varies from about `0.06` to `2.23 s` and may include gas-active
frames. An earlier entry could shift the delayed response, but the available
request history and settled-domain contrast do not establish a safe net
benefit or an appropriate speed-dependent threshold. **Decision: KEEP the
current raw `-0.30` road-speed brake entry.** Do not use a global threshold
change to mask the upstream lead-estimate cycle; pursue command-conditioned
Honda brake entry/release response only with a source-compatible mechanism
that improves both the early and late tracking phases.
