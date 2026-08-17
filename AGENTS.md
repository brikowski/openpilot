# Odyssey longitudinal tune — cold-start rules

Read this before changing the tune or its tooling. This file holds decisions and invariants;
route history and derivations belong in [`.agents/tune-evidence.md`](.agents/tune-evidence.md).

## Project objective

Make the Odyssey track `carControl.actuators.accel` as smoothly as Honda's stock radar commands the
vehicle, while keeping the smallest practical delta from current `commaai/openpilot` and
`commaai/opendbc` master.

- Treat stock radar as the benchmark for actuator transitions, episode shape, and achieved ride
  response, not for its proprietary target selection.
- Prefer mechanisms already used on current upstream master. A fork-only mechanism needs a concise,
  PR-quality physical rationale, focused regression coverage, and an isolated road arm.
- Minimize production code and change one mechanism per road comparison. Replay establishes command
  shape only; promotion requires controlled maneuvers and ordinary-road evidence.
- Preserve honest command attribution. If the vehicle cannot smoothly achieve a request, prefer the
  narrowest upstream-style limit before `carControl` over hiding the mismatch in Honda CAN shaping.

## What this branch is

`ody-op` is the recovery baseline and shared tooling/evidence branch for the Honda Bosch A tune on
`HONDA_ODYSSEY_5G_MMR`. Experimental children inherit their validator, private-log tools, evidence,
and standards from here; only mechanism-specific controller code and rail assertions belong on a
test branch. Keep parent and nested opendbc branches paired.

`ody-op-test` is a frozen failed experiment. Do not add commits to it or treat its coast interlock,
raw `-0.40` entry, zero brake integral, onset shaper, or direct brake release as accepted knowledge.
`ody-op-test2` is the active child. Its upstream raw-split reference failed its road screen; the
current candidate changes only Odyssey command-domain selection around the raw `ACCEL_COMMAND`:
road-speed brake/coast separation, low-speed stop authority, and an OEM-aligned active-gas hold. It
does not restore the retired brake PID, compensated input, coast interlock, or onset shaping.

Lateral is currently an isolated **3840 command-range arm** with the stock
`latAccelFactor 0.9` and `steerActuatorDelay 0.15`; it is not yet road-proven. Keep 3840 unless a
logged or road-tested symptom gives a reason to reduce it. The former 0.20 s fallback had no
isolated road benefit and remains retired. `extract.py` and `validate_log.py` record lateral
command/output, torque-controller saturation, steering response, overrides, and faults; these are
diagnostics and not lane-tracking proof.

## Attribution boundary

Trace questionable behavior in this order:

`longitudinalPlan` → `carControl.actuators.accel` → `ACCEL_COMMAND` plus
`GAS_COMMAND`/`BRAKE_REQUEST` → Honda ECU/vehicle response.

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

## Workflow

- Pull private full-rate rlogs with `.agents/pull_logs.py`; qlogs are too decimated for the
  transition metrics. Use `.agents/extract.py` for repeat exploratory analysis.
- Run every drive through `.agents/validate_log.py`, which writes one row per route to
  `.agents/log-validation-ledger.jsonl` (authoritative) and `.md` (human view).
- Use `.agents/inspect_following.py` plus cached upstream signals to locate the first divergence.
- Car-port edits follow `.claude/skills/comma-standards/SKILL.md`. Keep production comments PR-lean:
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

## Active road question

The two-state release-width work is closed without promotion. Entry `-0.30`, width `0.50` reduced
descent transitions but held braking through positive requests; width `0.20` released sooner but
returned driver-felt tapping on split routes `00000027`/`00000028` (12 physical descent edges over
0.734 min, 16.4/min). Do not continue that two-state width/threshold architecture.

The first `ody-op-test` architecture failed its road screen on route
`00000029--4c9b612e7c`: it produced 24 direct gas-to-brake and 23 direct brake-to-gas handoffs in
9.7 engaged minutes, including the driver-reported pulsing. Useful compensated gas was allowed to
reactivate immediately above brake entry, so the coast state did not separate those transitions.

The completed direct-release arm disproved two later claims. Routes `0000003f--cf7b94c588` and
`00000040--ff2868cffe` had zero direct gas-to-brake handoffs yet still measured 33.1 and 13.1
downhill brake edges/min. Their typical downhill applications lasted about 1.0-1.1 s; the wire
reached 80% command depth in 0.19-0.20 s and the standardized achieved-accel metric reached 80%
in 0.64-0.66 s. Stock-radar route `0000003b--08f77bc5c3` measured 3.0 downhill edges/min; its two
downhill applications had a median duration of 10.86 s and median achieved-accel 80% time of
8.08 s. The gap is both episode frequency and onset shape. A one-command coast interlock is not
a pulse-braking fix, and the `ody-op-test` stack is closed without promotion.

The fresh raw-split `ody-op-test2` reference failed on both first drives. Route
`00000042--990be22fe1` measured 167 physical brake edges (30.3/min overall, peak 28/10 s,
119.4/min downhill); route `00000041--91a6b6745b` measured 69 (11.2/min, peak 26/10 s,
121.0/min downhill). Around 39 mph the raw request crossed `-0.20` repeatedly and Honda's
`COMPUTER_BRAKING` followed every `BRAKE_REQUEST`. During the route-42 lead stop, the request
relaxed from `-0.21` to `-0.18` below 2 mph, the raw split selected gas, speed rose, and the driver
took over. The planner also withheld `shouldStop` until near zero; a car-port domain change cannot
repair that upstream stop decision.

The current `-0.50` brake-entry arm keeps `ACCEL_COMMAND` as the clipped raw request and uses state
only to choose Honda's binary command domains. At road speed, brake enters below `-0.50` and remains
selected while the request is negative; a positive request releases it immediately. An active gas
command remains live down to Honda's upstream `-0.20` split, but after coast it re-enters only for a
positive request. Below 5 m/s, non-positive requests select brake and any positive start request
selects gas immediately. The earlier `-0.30` replay results on routes 41/42 are retained as command-
shape evidence for that predecessor, not as validation of this arm. Controlled and ordinary-road
drives must reject late onset, excess overspeed, renewed tapping, gas pulsing, or incomplete stops.

The `-0.50` arm changes one road-speed entry constant only; it does not change the gasfactor, gas
handoff semantics, low-speed stop authority, or numeric `ACCEL_COMMAND`. It is software-validated
and road-unvalidated until the official controlled maneuvers and a terrain-matched ordinary-road
drive are complete.

The retained custom longitudinal behavior outside brake authority is the road-supported Odyssey
gasfactor calibration. The unproven 60-count handoff ramp is retired: eligible gas now receives the
calculated command immediately. Gas and brake remain mutually exclusive, disengagement emits no
longitudinal command, Panda bounds command magnitude, and positive stop-release requests select gas
immediately. The new route-43 gas arm leaves that gasfactor calibration and the three-domain brake
candidate unchanged, but removes unverified wind/grade feedforward from the actual `GAS_COMMAND`.
Windfactor remains logged as diagnostic-only learner state; it cannot choose the brake domain or add
wire force. The latest full non-Experimental route still had 13 sub-second gas episodes beginning at
tiny positive cruise requests before crossing the `-0.20` release boundary. That is a separate
gas-domain re-entry arm; the current `-0.50` brake arm does not claim to resolve it. This is a
command-path isolation experiment, not a road-proven comfort improvement.

Do not substitute the failed raw-split reference or the unvalidated command-domain candidate for the
`ody-op` recovery branch. Full-rate master
route `00000024--5c888c605c` measured 108.2 downhill edges/min and peak 25/10 s, versus 1.9/min and
peak 3/10 s on `ody-op` route `00000026--bfe3fd933b`. The current upstream-pinned Honda path still
uses the same raw request and fixed -0.20 split, so that comparison remains behaviorally relevant.

Keep the 8 m/s gasfactor seed at `0.54` until the corrected narrow-window, exposure-qualified,
per-`opendbc_commit` report accumulates enough evidence. Legacy broad-bin suggestions are invalid.

The production windfactor learner is not independently identified from the gasfactor learner and
grade compensation. Do not call it validated or include it among the known-good behavior. It is
carried unchanged only so the brake-domain candidate does not also become a gas-powertrain
experiment. Any removal or replacement must be its own arm, with gasfactor frozen or partitioned
during identification because both learners use the same tracking error.
