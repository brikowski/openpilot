# Odyssey command-following — cold-start rules

Read this before changing lateral or longitudinal behavior or its tooling. This file holds decisions
and invariants; private route history and derivations belong in the Proton Drive evidence folder.

## Project objective

Make the Odyssey follow `carControl`'s lateral and longitudinal commands as accurately and
smoothly as its Honda actuators allow. Preserve `ody-op` as the known-good rollback baseline and keep
production changes minimal relative to current `commaai/openpilot` and `commaai/opendbc`.

Prefer behavior that responds dynamically to the commanded state. Use reliable live or learned
vehicle state when it directly represents the behavior being controlled; use fixed values only
when a suitable signal is unavailable, unreliable, or needed as a constraint or fallback. Use the
simplest implementation that works, without duplicate logic or new learning solely to remove a
constant. Remove unnecessary tuning, documentation, abstractions, and code.

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
fidelity and physical response as separate outcomes: replay validates command shape, while
full-rate road evidence validates closed-loop behavior. Every candidate needs proportionate
mutation-verified tests, an attributable baseline comparison, and an explicit keep/change/retire
decision.
Historical keep/change/retire labels are evidence receipts, not permanent exclusions. New
full-rate logs may reopen any mechanism when they supply a repeatable first-divergence hypothesis;
re-audit the cited exposure instead of treating an absence of proof as proof of failure. Preserve
the verified safety, provenance, and ownership boundaries below.

Runtime changes in both OpenPilot and nested `opendbc` are in scope for this objective. Use pinned
upstream behavior as the comparison baseline. Fix command generation, controller state, timing, or
publication in OpenPilot when the first repeatable divergence belongs there; fix CAN translation,
domains, safety translation, and actuator response in the Honda layer when it belongs there. Do not
mask an upstream error in the car port or change the planner/model's intended motion to compensate
for Honda actuator limitations. Keep vehicle-specific changes as narrow as practical and put each
behavior in the simplest appropriate layer.

## What this branch is

`ody-op` is the recovery baseline and shared tooling/evidence branch for Honda Bosch command following on
`HONDA_ODYSSEY_5G_MMR`. All mechanism changes, validator updates, evidence, and directly related
tests are integrated linearly on this branch. Do not create branches or worktrees. Keep the parent
and nested opendbc SHAs paired; use `git revert` to change or retire a candidate, and keep the prior
road-known-good pair reachable.

Old experiment branches and their mechanisms are historical evidence, not active targets or
accepted knowledge. Their private measurements remain in Proton Drive's `evidence/tune-evidence.md`;
they do not prohibit a new source-compatible hypothesis owned by current logs.

Alpha Long has a separate safety boundary on this Bosch Odyssey: enabling
`openpilotLongitudinalControl` disables the Bosch radar ECU through the Honda UDS
communication-control path, and the controller keeps it disabled with tester-present messages.
Treat Honda CMBS, including stock AEB and FCW, as unavailable during Alpha Long road tests.
This is independent of the Panda `alternativeExperience` AEB-forwarding flag and of safety
guards that reject OpenPilot AEB bits; neither mechanism restores CMBS while the radar ECU is
disabled.

The current Odyssey lateral baseline uses the stock `[0, 2560]` LKA map, `latAccelFactor 0.9`, and
`steerActuatorDelay 0.15`. Prior 3840 screens are historical comparisons, not a permanent exclusion.

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
- At very low speed, correct failure to achieve the requested acceleration, not failure to stop
  by itself. If the vehicle follows `carControl` but upstream does not request a complete stop,
  leave that upstream behavior unchanged. Do not add a stop-until-zero latch or retain braking
  against a released upstream request merely to complete a stop.
- Apply the same boundary to lateral behavior: do not use Honda steering shaping to compensate for an
  upstream lateral-plan or controller error, and do not retune a correct command path without a
  repeatable vehicle-response symptom.

## Evidence rules

1. **Replay checks command shape, not closed-loop timing.** It freezes the recorded inputs; only a
   drive measures when the controller changes domains.
2. **Pool on resolved behavior revisions, not branch names.** Resolve both parent and nested
   `opendbc` commits. Matching `opendbc` hashes do not establish comparable OpenPilot behavior.
   Pool different hashes only after a source diff proves the measured command path and response
   mechanism behavior-identical. Private evidence records any excluded routes.
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
   wire fidelity and domain bits to locate the first divergence. Exact-route A/B is useful when
   available, but source-compatible matched intervals or pooled events are sufficient when their
   conditioning, exposure, and sensitivity checks make the direction attributable. Unmatched
   whole-route averages are not evidence.
8. There is no fixed route-count gate. One decisive safety regression may retire a candidate, while
   noisy evidence may remain inconclusive regardless of drive count. Do not wait for a specially
   shaped second or third route when existing exact-provenance evidence resolves the hypothesis.
9. Every candidate must have an explicit keep, change, or retire decision after checking the relevant
   lateral or longitudinal exposure. Do not retain tuning merely because it is historical or already
   present.

## Workflow

- Private rlogs are not stored in GitHub. On macOS analysis hosts, read
  `Proton Drive/Documents/openpilot/README.md`. Analysis tools find the active
  `ProtonDrive-*-folder/Documents/openpilot` under `~/Library/CloudStorage` and read `rlogs/`
  directly. `LOG_ROOT` or `OPENPILOT_PRIVATE_ROOT` can override discovery. The Proton account name
  and absolute File Provider mount are machine-local and must not be committed. The comma device
  does not have Proton Drive access.
- Private ledgers and route-specific tuning notes are stored in the same Proton Drive folder under
  `evidence/`. Analysis tools read that folder directly; `ODYSSEY_EVIDENCE_ROOT` can override it.
  Do not commit route IDs, event times, or route-specific conclusions to GitHub.
- Pull private full-rate rlogs with `.agents/pull_logs.py`; qlogs are too decimated for the
  transition metrics. Use `.agents/extract.py` for repeat exploratory analysis.
- Run every drive through `.agents/validate_log.py`, which writes one row per route to Proton Drive's
  `evidence/log-validation-ledger.jsonl` (authoritative) and `.md` (human view).
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

Commit subsequent changes separately. Squash or amend existing history only when the user explicitly asks.

Commit at a stable evidence boundary, not merely because tests pass or a worktree is dirty. Before
committing, classify every diff as production behavior, diagnostic tooling, evidence/docs, or
unrelated user work; never mix unrelated work.

A diagnostic/tooling commit is ready when its semantics and ownership are documented, deliberate
mutation makes the relevant check fail, focused tests and `git diff --check` pass, and no vehicle
runtime behavior changes. Evidence or ledger updates may be a separate commit when they are useful
for reproducibility, but they must not be mixed with unrelated changes.

Promotion of production behavior additionally requires exact route, parent, and nested `opendbc`
provenance; first-divergence ownership; a coherent, attributable design; source-compatible full-rate comparison with
adequate exposure; an attributable improvement or required safety fix without unacceptable
regression; and an explicit keep/change/retire decision. Resolve DBC signal meaning from the exact
nested revision; do not infer alignment from matching signal names across `ody-op`,
`sunnypilot/staging`, or another branch.

Gas response, brake response, and their transitions may be changed together as a coordinated
design. There is no one-change-at-a-time requirement. Validate each affected domain and their
interactions, and use component-level tests or offline ablations when needed for attribution;
separate road deployments are not mandatory for each component. Retain overlapping corrections
only with a stated role and supporting evidence, not merely because they were already deployed.

Commit each software-validated candidate and its tests directly to `ody-op` for supervised car
testing before road benefit is established; a commit is not a promotion. After the source,
mutation, focused-test, preflash, and provenance gates pass, deployment
is the default next step for a supervised road test when the user authorizes it; do not defer it
merely because the candidate is unpromoted. Verify the root SHA, nested `opendbc` gitlink SHA, remote
refs, and clean state separately from device health and road behavior. Keep the `ody-op` and nested
`opendbc` rollback SHAs reachable throughout.

Device availability is not an implementation gate. Continue in-scope analysis, OpenPilot and Honda changes,
tests, commits, and publication on `ody-op` when the evidence and software gates pass, even if the
device is offline or onroad. A published commit or queued updater download is not an installation:
defer the guarded switch and exact device readback until the device is reachable and offroad, then
assess road response separately. An unmeasured installed candidate also does not block an
independent, evidence-backed change, but retain both source pairs for attribution and rollback.

## Current focus

The latest route exposure, trial decisions, and exact rollback pair are in the private Proton Drive
evidence. Keep Alpha Long enabled for these trials unless the user changes it. Honda CMBS is
unavailable while it is active. Command-path fidelity alone does not establish closed-loop benefit.
