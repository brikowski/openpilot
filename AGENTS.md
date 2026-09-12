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
Retired mechanisms remain historical and are not reopened without new first-divergence evidence.

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
The unproven asymmetric onset limiter is fully retired: `ACCEL_COMMAND` delivers raw clipped
acceleration while the three-domain selector, direct gas mapping, and low-speed stop authority remain
active. New model or radar experiments must be one hypothesis committed directly to `ody-op`, then
deployed only after the software gate for a supervised road test.

Alpha Long has a separate safety boundary on this Bosch Odyssey: enabling
`openpilotLongitudinalControl` disables the Bosch radar ECU through the Honda UDS
communication-control path, and the controller keeps it disabled with tester-present messages.
Treat Honda CMBS, including stock AEB and FCW, as unavailable during Alpha Long road tests.
This is independent of the Panda `alternativeExperience` AEB-forwarding flag and of safety
guards that reject OpenPilot AEB bits; neither mechanism restores CMBS while the radar ECU is
disabled.

The former `ody-op-radar` arm is closed after its first engaged route, and both implementation
branches are deleted. It changed radar availability and published a camera-side object/fusion bank;
it did not change the retained Honda longitudinal CAN translation. On route
`00000043--a13083ebb4`, radar-marked lead selection and the planner command changed abruptly while
physical brake-domain cycling and driver-felt gas/brake behavior worsened. Do not compensate for
this perception/planner regression with gas or brake tuning. Preserve its route/source findings as
historical evidence and use the vision-only `ody-op` baseline for future comparisons.

Lateral uses the stock 2560 LKA command map with `latAccelFactor 0.9` and
`steerActuatorDelay 0.15`. The isolated nonlinear 3840 arm is retired after its bounded three-route
screen failed to establish an attributable improvement. Route `0000005d--ed7df97035` was mixed and
only favored the arm in a thin unmatched comparison; route `00000061--b8f07e1ca7` supplied 15.61
high-authority seconds but still had `0.245 m/s2` actual-desired RMS and three steering-fault events;
route `00000064--898a884741` was clean for 5.09 seconds at 3840 but its `+0.009 m/s2` median
under-response was effectively the same as the comparable stock-2560 readout. Clean operation is not
proof of benefit, and the custom range no longer meets the PR-minimal retention burden. The former
linear 3840 RDM map and 0.20 s delay fallback remain retired. Reopen steering authority only for a
repeatable logged lateral symptom and an isolated matched-road comparison. Passive route
`00000069--eab494ffc4` independently captured the stock camera source with no OpenPilot steering
frames: every nonzero steering request stayed within 2560, including 216 full-rate frames exactly at
the cap, while the DBC-labeled RDM/haptic state carried zero torque. This confirms the stock LKA wire
range; it does not establish a separate 3840 RDM range or prove lane-tracking quality.

`extract.py` and `validate_log.py` retain controller-side lateral command/output, saturation,
steering response, overrides, and fault diagnostics. For full-rate Odyssey stock-radar routes,
`validate_log.py` also counter-matches bus-0 `sendcan` to the physical bus-1 steering frame, so radar
forwarding or attenuation is measured separately from the stock 2560 controller cap. These
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

The retained `ody-op` baseline is the default comparison: raw clipped longitudinal command,
evidence-supported Odyssey command domains, direct upstream gas mapping, and stock lateral authority.
The retired gasfactor, windfactor, low-speed PID, onset-shaping, gas re-entry deadband, and 3840-steering
mechanisms remain historical; reopen one only when a new route locates a repeatable first divergence
that it could own.

The latest full-rate diagnostic route carried the planner request through `carControl` and Honda CAN
with small command-path residuals, while `aEgo` still differed materially from the request. This
makes vehicle-response characterization the next diagnostic priority, not permission to reshape the
command. Follow the dated [response-attribution entry](.agents/tune-evidence.md#current-response-attribution-focus-2026-09-07)
for the required timing alignment, gas/brake/coast separation, and speed, grade, gear, and lead
conditioning.

Keep the stopped-lead planner arm and any uphill/model behavior separate from Honda response work.
Before changing production behavior, show the first divergence, run the focused tests and replay
checks, and obtain an isolated controlled or ordinary-road comparison against `ody-op`.

## Historical decisions

Detailed route measurements, failed experiments, and retired-arm provenance live in
[`.agents/tune-evidence.md`](.agents/tune-evidence.md). Keep this file focused on
cold-start rules and current invariants; do not duplicate route history here.
