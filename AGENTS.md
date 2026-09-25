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
fidelity and physical response as separate outcomes: replay validates command shape, while
full-rate road evidence validates closed-loop behavior. Every candidate needs proportionate
mutation-verified tests, an attributable baseline comparison, and an explicit keep/change/retire
decision.
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
tests are integrated linearly on this branch. Do not create branches or worktrees. Keep the parent
and nested opendbc SHAs paired; use `git revert` to change or retire a candidate, and keep the prior
road-known-good pair reachable.

Old experiment branches and their mechanisms are historical evidence, not active targets or
accepted knowledge. Their measurements remain in `.agents/tune-evidence.md`; they do not prohibit a
new source-compatible hypothesis owned by current logs.

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
provenance; first-divergence ownership; one hypothesis; source-compatible full-rate comparison with
adequate exposure; an attributable improvement or required safety fix without unacceptable
regression; and an explicit keep/change/retire decision. Resolve DBC signal meaning from the exact
nested revision; do not infer alignment from matching signal names across `ody-op`,
`sunnypilot/staging`, or another branch.

A candidate is committed directly to `ody-op` to preserve reproducibility, but the commit is not a
promotion. After the source, mutation, focused-test, preflash, and provenance gates pass, deployment
is the default next step for a supervised road test when the user authorizes it; do not defer it
merely because the candidate is unpromoted. Verify the root SHA, nested `opendbc` gitlink SHA, remote
refs, and clean state separately from device health and road behavior. Keep the `ody-op` and nested
`opendbc` rollback SHAs reachable throughout.

## Current focus

At the latest successful 2026-09-25 verification, the device ran root
`4ef98509ea` / nested `1ff3bb131` on the single `ody-op` line. The immediately
prior deployed pair was root `652e169280` / nested `47196b9a4`; the previous
road baseline before that was behavioral root `0bd9816712b1` / nested `6915be202bb7`;
root `3269deef3d7c` added only its deployment receipt. The nested candidate
retains raw `ACCEL_COMMAND`, the request-ramped positive
`GAS_COMMAND` mapping, the smooth capped correction through an already-active uphill negative gas
request, the `0.3` filtered-pitch brake translation, fresh `-60` bridge entry, and stock 2560
lateral authority. It changes positive-request gas translation to use signed grade with gain `0.6`
and requires raw and filtered pitch signs to agree before applying it, preventing stale uphill
compensation across a crest.

Route `0000001f--3c3caa3f64` locates the reported lead-following cycles after accurate planner to
`carControl` and controller-to-wire translation: the planner issues real catch/deceleration cycles,
while Odyssey lag and over-response amplify them. Three low-speed accelerations averaged
approximately `+0.15..+0.32 m/s2` achieved acceleration beyond the request. During the 12:07
Experimental hill, the uphill slowdown starts in the upstream command, but the former one-sided
gas translation amplified the subsequent downhill surge. Source-compatible uphill matching favors
gain `0.6` over deployed `0.7`; removing grade compensation entirely is worse. The signed-grade
candidate has three post-deployment routes, but none exercises its downhill positive-gas branch;
that branch remains road-unmeasured and the candidate is not promoted. Route
`00000022--1326e023d1` places the 16:42–16:43 lead cycle on an uphill. Raw vision lead
range/speed estimates jump despite continuous high lead-presence probability, and the planner
issues the catch/brake requests that `carControl` and Honda CAN largely follow. Road video shows
the same in-lane lead through the jumps; Honda brake overdeceleration adds to the cycle but was
also present before this candidate. The retained negative-request
uphill behavior improved comparable lead-present under-response but over-corrected steady no-lead
exposure and also remains unpromoted. Do not make translation planner-source-specific or mask the
upstream cycle; continue isolating Honda-owned positive-gas overshoot and delayed response decay.
On current-source sustained brake entries at 10–20 m/s, active-wire tracking initially
under-brakes, then may over-brake; 30–40 m/s entries track much closer. A fixed weaker
brake command would worsen the lower-speed early phase. Keep the brake-grade gain
separate from this speed- and demand-conditioned transient response target:
firm lower-speed brake requests may remain under-braked at one second.
Near-level mild-negative coast/brake samples have opposite tracking errors at lower speeds,
while highway coast already overdecelerates; a global earlier brake-entry threshold is not
supported by current road evidence.

A bounded Odyssey-only positive-gas trial is deployed as root `652e169280` /
nested `47196b9a4`: it trims at most 200 opaque gas counts for positive PID
requests around 12–20 m/s and +0.8–+1.6 m/s2, with smooth
ramps and no change to raw `ACCEL_COMMAND` or brake/negative-gas domains. Two historical
source-different matched episodes give its direction and trial size; they do not establish a
closed-loop gain. The guarded offroad switch, build, reboot, and exact-pair
health checks passed; that is not road validation. Keep or retire this
unpromoted trial from source-compatible road response.

The 2026-09-25 full-rate routes `00000025--65f310df96`,
`00000026--a324cbacbc`, and `00000027--543105a0ab` identify a separate
steep-climb near-zero gas-response gap despite close planner/request/wire
agreement. Route 26's 12:05 override also includes legitimate planner
braking and a distinct late vehicle-response transient; do not treat either
as cured by added uphill gas. Nested `1ff3bb131` is an unpromoted,
speed-gated, bounded, bridge-slewed gas-only candidate on `ody-op`.
Its exact-input replay leaves `ACCEL_COMMAND` and brake domains unchanged
and avoids enlarging the incumbent maximum live-gas step. This is software
evidence, not road improvement. Judge steep lead and no-lead response,
bridge exits, and overshoot from source-compatible post-deployment logs.

Alpha Long remained enabled at the latest device verification. Do not disable it for this trial;
Honda CMBS is unavailable while it is active. The guarded deployment verified
clean exact SHAs, an idle updater with no
exception, active manager/Panda services, and no failed services; this is deployment health, not
road proof. Seven-route settled-brake evidence independently fits a positive grade term on every
route and retains the rounded `0.3` brake gain. Judge physical response from source-compatible
full-rate evidence without waiting for an arbitrary drive count. Detailed measurements and prior
experiment provenance remain in `.agents/tune-evidence.md`; dated directives there do not override
this file.
