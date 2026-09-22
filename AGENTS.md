# Odyssey command-following — cold-start rules

Read this before changing lateral or longitudinal behavior or its tooling. This file holds decisions
and invariants; route history and derivations belong in [`.agents/tune-evidence.md`](.agents/tune-evidence.md).

## Project objective

Make the Odyssey follow upstream OpenPilot's lateral and longitudinal commands as accurately and
smoothly as its Honda actuators allow. Preserve `ody-op` as the known-good rollback baseline and keep
production changes minimal relative to current `commaai/openpilot` and `commaai/opendbc`.

For every comparable private full-rate route, resolve the exact parent and nested `opendbc` revisions,
reconstruct the command path with zero-order-held CAN, and identify the first repeatable breakdown:

- If the upstream plan or model asks for the wrong motion, investigate OpenPilot planning or model
  behavior.
- If the plan is sound but `carControl` is wrong, investigate OpenPilot's controller or state machine.
- If `carControl` is right but CAN values or gas/brake domains are wrong, investigate the Honda port,
  DBC translation, or safety boundary.
- If the command and domain are right but the vehicle responds incorrectly, investigate Honda ECU and
  actuator response without reshaping the OpenPilot command.

Apply the same ownership rule independently to lateral and longitudinal control. Treat command/CAN
fidelity and physical response as separate outcomes: replay validates command shape, while matched
controlled or ordinary-road drives validate closed-loop behavior. Every candidate needs
mutation-verified tests, an isolated baseline comparison, and an explicit keep/change/retire decision.
Historical keep/change/retire labels are evidence receipts, not permanent exclusions. New
full-rate logs may reopen any mechanism when they supply a repeatable first-divergence hypothesis;
re-audit the cited exposure instead of treating an absence of proof as proof of failure. Preserve
the verified safety, provenance, and ownership boundaries below.

For this Honda command-following objective, treat the pinned upstream OpenPilot planner, model, and
controllers as the command source. Vehicle-runtime changes are limited to the nested `opendbc`
Honda port, DBC, and safety translation; root OpenPilot changes may add diagnostics, tests, or
evidence but must not alter vehicle behavior. If the first divergence is upstream of `carControl`,
document and diagnose it rather than masking it in the Honda port. An upstream runtime fix requires
a separate explicitly authorized planner/model objective.

## What this branch is

`ody-op` is the recovery baseline and shared tooling/evidence branch for Honda Bosch command following on
`HONDA_ODYSSEY_5G_MMR`. All mechanism changes, validator updates, evidence, and directly related
tests are integrated linearly on this branch. Keep the parent and nested opendbc SHAs paired; use
`git revert` to change or retire a candidate, and keep the prior road-known-good pair reachable.

`ody-op-test` is a frozen failed experiment. Do not add commits to it or treat its coast interlock,
raw `-0.40` entry, zero brake integral, onset shaper, or direct brake release as accepted knowledge.
The former `ody-op-test2` final candidate is now the `ody-op` baseline: it changes only Odyssey
command-domain selection around the raw `ACCEL_COMMAND` (road-speed brake/coast separation,
low-speed stop authority, and an OEM-aligned active-gas hold). It does not restore the retired brake
PID, compensated input, coast interlock, raw-split reference, or historical symmetric onset stack.
The earlier asymmetric onset limiter did not establish a benefit in its tested exposures, so it is
not part of the current baseline: `ACCEL_COMMAND` delivers raw clipped acceleration while the
three-domain selector and low-speed stop authority remain active. The prior active-zero gas screen
also did not improve its matched routes and shifted the measured near-zero response; nested revert
`c16579385f56` therefore remains the comparison baseline. Those are exposure-scoped results, not
universal exclusions: a new exact-provenance route may reopen either mechanism as a fresh isolated
hypothesis with its own safety and response comparison.

Alpha Long has a separate safety boundary on this Bosch Odyssey: enabling
`openpilotLongitudinalControl` disables the Bosch radar ECU through the Honda UDS
communication-control path, and the controller keeps it disabled with tester-present messages.
Treat Honda CMBS, including stock AEB and FCW, as unavailable during Alpha Long road tests.
This is independent of the Panda `alternativeExperience` AEB-forwarding flag and of safety
guards that reject OpenPilot AEB bits; neither mechanism restores CMBS while the radar ECU is
disabled.

The former `ody-op-radar` arm is historical after its first engaged route, and both implementation
branches are deleted. It changed radar availability and published a camera-side object/fusion bank;
it did not change the retained Honda longitudinal CAN translation. On route
`00000043--a13083ebb4`, radar-marked lead selection and the planner command changed abruptly while
physical brake-domain cycling and driver-felt gas/brake behavior worsened. Keep this
perception/planner result separate from Honda command translation; it is not a permanent ban on a
future radar hypothesis or on Honda tuning. Preserve its route/source findings as historical
evidence and use the vision-only `ody-op` baseline for future comparisons unless a new matched
comparison establishes different ownership.

The current local Odyssey lateral candidate restores the stock `[0, 2560]` LKA map, with
`latAccelFactor 0.9` and `steerActuatorDelay 0.15`; deployment status must be checked separately.
The recent nonlinear `[0, 2560, 3072]` request to `[0, 2560, 3840]` map is retired after three
adequately exposed routes failed to establish a tracking-accuracy improvement. See the dated
lateral screen in `.agents/tune-evidence.md`. An earlier isolated nonlinear 3840 arm
also did not establish an attributable improvement in its bounded three-route screen. Route
`0000005d--ed7df97035` was mixed and
only favored the arm in a thin unmatched comparison; route `00000061--b8f07e1ca7` supplied 15.61
high-authority seconds but still had `0.245 m/s2` actual-desired RMS and three steering-fault events;
route `00000064--898a884741` was clean for 5.09 seconds at 3840 but its `+0.009 m/s2` median
under-response was effectively the same as the comparable stock-2560 readout. Clean operation is not
proof of benefit; that earlier custom arm did not meet the PR-minimal retention burden. The former
linear 3840 RDM map and 0.20 s delay fallback remain historical comparison arms. Reopen steering
authority decisions require a repeatable logged lateral symptom and an isolated matched-road
comparison; the prior screen alone is not a permanent exclusion. Passive route
`00000069--eab494ffc4` independently captured the stock camera source with no OpenPilot steering
frames: every nonzero steering request stayed within 2560, including 216 full-rate frames exactly at
the cap, while the DBC-labeled RDM/haptic state carried zero torque. This confirms the stock LKA wire
range; it does not establish a separate 3840 RDM range or prove lane-tracking quality.

`extract.py` and `validate_log.py` retain controller-side lateral command/output, saturation,
steering response, overrides, and fault diagnostics. For full-rate Odyssey stock-radar routes,
`validate_log.py` also counter-matches bus-0 `sendcan` to the physical bus-1 steering frame, so radar
forwarding or attenuation is measured separately from the controller's map. On Alpha Long routes,
the controller instead sends steering directly on bus 1; compare that `sendcan` to same-cycle
`carOutput`, not to the stock-radar forwarding path. Neither TX comparison proves EPS acceptance. These
diagnostics do not by themselves prove lane tracking or closed-loop road behavior.

## Attribution boundary

Trace questionable lateral and longitudinal behavior independently in this order:

`longitudinalPlan` → `carControl.actuators.accel` → `ACCEL_COMMAND` plus
`GAS_COMMAND`/`BRAKE_REQUEST` → Honda ECU/vehicle response.

For lateral behavior, trace the upstream lateral plan/controller command → `carControl` steering
actuator output → Honda steering CAN → Honda ECU/vehicle response.

`carControl.actuators.accel` is the controller input; `longitudinalPlan.aTarget` is upstream and
`longcontrol` may legitimately override it. Numeric `ACCEL_COMMAND` fidelity is not sufficient if
the domain bits leave gas inactive. Locate the first divergence before assigning the symptom.

Use that first divergence to choose the work:

- If the model/planner command pulses or fails to stop, investigate Experimental/model/planner
  behavior; do not compensate for it in the car port.
- If the planner is smooth but `carControl` is not, investigate `longcontrol`.
- If `carControl` is correct but numeric CAN or the active gas/brake domain differs, investigate the
  Honda translation.
- If numeric CAN and its domain are correct but `aEgo` bites or lags, calibrate Honda actuator
  response without reshaping the model command.
- Apply the same boundary to lateral behavior: do not use Honda steering shaping to compensate for an
  upstream lateral-plan or controller error, and do not retune a correct command path without a
  repeatable vehicle-response symptom.

## Evidence rules

1. **Replay checks command shape, not closed-loop timing.** It freezes the recorded inputs; only a
   drive measures when the controller changes domains.
2. **Pool on resolved `opendbc_commit`, not branch or parent commit.** Pool different hashes only
   after a source diff proves them behavior-identical. Route `00000005` is excluded from pooled
   comparisons.
3. **Mutation-verify a check when you write it.** A check you have never seen fail is not evidence.
   If it cannot be made to fail, that is the finding.
4. Before adding a check, measure overlap with existing checks and verify its mask against a known
   event. Name it after the symptom, not a proposed fix.
5. A threshold flag identifies an event to inspect; it is not permission to tune.
6. Treat comments and prose as leads. Verify current code, DBC semantics, safety limits, and logs.
7. Compare the outcome OpenPilot requested, not merely whether two drives used the same road. For
   lateral, compare actual versus desired lateral acceleration in comparable speed, demand, and
   authority bins. For longitudinal, compare `aEgo` versus `carControl.actuators.accel` separately in
   gas and brake domains, conditioned on comparable speed, request, and terrain. Use controller-to-
   wire fidelity and domain bits to locate the first divergence. Exact-route A/B is preferred when
   available, but unmatched whole-route averages are not evidence.
8. Every unpromoted custom arm gets at most three independent, adequately exposed road examples of
   the same mechanism. If three fail to show an attributable improvement in OpenPilot-command
   following, retire it. Do not count multiple thresholds, metrics, or transitions from one episode
   as independent examples; a safety regression can retire an arm sooner.
9. Every candidate must have an explicit keep, change, or retire decision after checking the relevant
   lateral or longitudinal exposure. Do not retain tuning merely because it is historical or already
   present.

## Workflow

- Pull private full-rate rlogs with `.agents/pull_logs.py`; qlogs are too decimated for the
  transition metrics. Use `.agents/extract.py` for repeat exploratory analysis.
- Run every drive through `.agents/validate_log.py`, which writes one row per route to
  `.agents/log-validation-ledger.jsonl` (authoritative) and `.md` (human view).
- Use `.agents/inspect_following.py` plus cached upstream signals to locate the first divergence.
- Use `.agents/inspect_response.py` to rank achieved-jerk peaks against the causal wire-command
  history, physical command-domain edges, gear changes, terrain, lead state, and powertrain context.
- Review lateral and longitudinal behavior as separate evidence streams; a result on one axis does
  not authorize a change on the other.
- Car-port edits follow [`.agents/car-port-standards.md`](.agents/car-port-standards.md). Keep
  production comments PR-lean:
  explain the invariant or reason; keep route numbers, dates, and experiment history in evidence.
- `carOutput.actuatorsOutput` must describe actuator output, not internal learner state. The
  historical deployed child used its `gas`/`brake` fields for learned-factor telemetry; the
  upstream-rooted port restores actuator semantics. Any future learner telemetry must be
  reconstructed offline or moved to an explicitly named diagnostic event accepted by the
  corresponding schema owner.
- **Never sync opendbc to its own master.** Rebase it to the commit openpilot master pins, or
  `controlsd` crashes on-road from a `car.capnp` schema mismatch.
- `lefthook run pre-commit` covers focused lint and pure metric tests. `.agents/preflash.py` adds
  Odyssey interface and panda-safety coverage; neither substitutes for a road drive.

## Commit and promotion gate

Commit at a stable evidence boundary, not merely because tests pass or a worktree is dirty. Before
committing, classify every diff as production behavior, diagnostic tooling, evidence/docs, or
unrelated user work; never mix unrelated work.

A diagnostic/tooling commit is ready when its semantics and ownership are documented, deliberate
mutation makes the relevant check fail, focused tests and `git diff --check` pass, and no vehicle
runtime behavior changes. Evidence or ledger updates may be a separate commit when they are useful
for reproducibility, but they must not be mixed with unrelated changes.

A production commit or promotion additionally requires exact route, parent, and nested `opendbc`
provenance; first-divergence ownership; one hypothesis; an isolated matched full-rate baseline
comparison; an attributable improvement or required safety fix without unacceptable regression; and
an explicit keep/change/retire decision. Resolve DBC signal meaning from the exact nested revision;
do not infer alignment from matching signal names across `ody-op`, `sunnypilot/staging`, or another
branch.

A candidate is committed directly to `ody-op` to preserve reproducibility, but the commit is not a
promotion. After the source, mutation, focused-test, preflash, and provenance gates pass, deployment
is the default next step for a supervised road test; do not defer it merely because the candidate is
unpromoted. Verify the root SHA, nested `opendbc` gitlink SHA, remote refs, and clean state separately
from device health and road behavior. Keep the `ody-op` and nested `opendbc` rollback SHAs reachable
throughout.

## Current focus

As of 2026-09-20, the device has the request-ramped uphill `GAS_COMMAND` candidate from nested
`d50a3a4843ed` on the single `ody-op` line. It retains raw `ACCEL_COMMAND` and domain selection,
and was introduced after the previous all-at-once grade addition caused near-zero gas steps.
Alpha Long is enabled and remains enabled unless the user changes it; Honda CMBS is unavailable
while it is active. Road routes on this ramped candidate have not established improved uphill
`aEgo-carControl` tracking. The separate 3840 lateral trial is being retired on the local line;
verify the device pair before attributing any new route to that rollback.
The dated candidate descriptions below are historical; their uses of “current” do not supersede
this state. See the latest dated entry in `.agents/tune-evidence.md` for provenance and uncertainty.

### Dated prior screens (historical)

Nested `opendbc` `147e1d732eaa` was a road-pending candidate on top of comparison
baseline `196119896d73`. It preserves raw clipped `ACCEL_COMMAND`, brake selection, low-speed stop
authority, direct nonnegative gas mapping, and stock lateral authority. At road speed only, a fresh
coast recovery crossing nominal `-0.10 m/s2` pre-activates Honda's gas domain with the stock-observed
`-60` live command until the request becomes nonnegative. It does not apply after braking or to an
already-active gas domain. A dedicated Odyssey Panda flag permits `-60..2000`; every other Honda
Bosch longitudinal mode retains `0..2000` plus the inactive sentinel.

Stock full-rate matching supports the hypothesis but is not road proof. At matched `-0.10 m/s2`
upward crossings, six stock negative-live transitions had median response error `-0.011 m/s2`
versus OpenPilot coast at `-0.129`, while OpenPilot waited a median `0.67 s` for positive gas. At
the later gas handoff, seven matched examples showed higher OpenPilot response jerk and positive
error. Replay exposes the bridge without changing request-to-wire acceleration fidelity. Reject it
for a positive surge, increased handoff jerk, delayed needed acceleration, late braking, or driver
intervention; keep/change/retire requires isolated full-rate road evidence against `196119896d73`.

Gasfactor, windfactor, low-speed PID, onset shaping, gas re-entry or release logic, active-zero
neutral gas, and earlier 3840 steering arms are historical comparison mechanisms rather than
permanent exclusions. Reopen any one when new logs locate a repeatable first divergence it could
own, including a response or domain symptom not present in the original exposure. Re-derive the
hypothesis from current exact-provenance data and current safety semantics instead of inheriting an
old conclusion.

The reverted `-0.15 m/s2` release arm had one long road exposure. Its request-to-wire path remained
accurate, but matched achieved response and transition jerk did not improve relative to the
`-0.20 m/s2` comparison baseline. That result rejects that exact candidate on that exposure; it
does not establish a universal gas-release threshold or exclude a differently owned transition
mechanism.

The active-zero road screen carried planner requests through `carControl` and `ACCEL_COMMAND` with
small residuals, but Honda response crossed past the requested acceleration. In matched 15-25 m/s,
mild-downhill exposure, active zero moved `-0.10..0` response error from approximately zero to
`+0.074 m/s2` median and moved the `-0.20..-0.10` hold band from `+0.098` to `+0.153 m/s2`.
That first divergence belongs to Honda's response to the changed domain state in that exposure.
This result does not write off every narrower domain or response mechanism; the current negative-
live bridge is separately owned by the coast-to-gas response gap and does not restore active zero.
Its first road route exposed a narrower lifecycle error: two valid recovery entries reversed toward
stronger deceleration, but bridge-originated gas inherited ordinary active-gas hysteresis and held
`-60` down to about `-0.20 m/s2`. That nested candidate bounded only that bridge-originated
state to `-0.101..0 m/s2`; ordinary active gas remains unchanged. This revision is software-gated
and awaiting its second supervised road example, not yet retained or promoted.

A separate event-level rescreen of the same source-equivalent brake path found 21 achieved-jerk
peaks across three routes about `0.34..0.73 s` after brake-domain entry, with approximately `2.9x`
median amplification over the strongest causal wire jerk. Planner, `carControl`, and wire remained
close, all 21 followed coast-to-brake activation, and 19 had no nearby gear change. Received
`VSA_STATUS.COMPUTER_BRAKING` rose for all 21 after a median `0.061 s`, while the achieved-jerk peak
followed that state edge by a median `0.494 s`. Exact onset-limiter routes retained the same split.
The Bosch logs contain no `0x1E7` pressure frame, so this locates the symptom after command packing
and brake-state activation without distinguishing Honda's internal pressure loop from physical
actuator/vehicle response. The earlier onset limiter did not improve its adequately exposed road
examples, so this repeated downstream symptom alone does not justify restoring that exact arm. Keep
raw `ACCEL_COMMAND` as the comparison baseline while allowing a distinct onset or response
mechanism to be tested when its first divergence is isolated.

Brake-state dwell does not supply that mechanism. Across the same 21 events, longer coast and
received-computer-braking-off dwell did not precede larger jerk; a conditioned subset remained
inverse but was confounded by wire-command slope, and the 11 exact onset-limiter events supplied no
independent positive dwell trend. The selector already holds braking through every negative request,
while historical time-release and width arms did not establish a benefit in their road exposures.
This screen alone does not justify extending the brake hold, but it does not make a fresh,
separately attributable hold hypothesis inadmissible.

The same four-route pool supplies no current reason to change lateral authority. Routes 02, 03, and 05 supplied
1.46, 8.72, and 3.31 seconds at the stock 2560 cap with zero steering faults; conditioned response
ranged from close tracking to strong under-response and did not repeat consistently across matched
speed and demand bins. The controller reached the exact stock wire cap, so this is physical-
authority context rather than a DBC loss. At that point stock 2560 remained the comparison;
the later 3840 trial is described in the current-focus and evidence sections. The prior 3840
decision was not a permanent write-off.

Keep the stopped-lead planner arm and any uphill/model behavior separate from Honda response work.
Before changing production behavior, show the first divergence, run the focused tests and replay
checks, and obtain an isolated controlled or ordinary-road comparison against `ody-op`.

## Historical decisions

Detailed route measurements, failed experiments, and retired-arm provenance live in
[`.agents/tune-evidence.md`](.agents/tune-evidence.md). Keep this file focused on
cold-start rules and current invariants; do not duplicate route history here.
