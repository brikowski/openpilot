# Odyssey longitudinal tune — cold-start rules

Read this before changing the tune or its tooling. This file holds decisions and invariants;
route history and derivations belong in [`.agents/tune-evidence.md`](.agents/tune-evidence.md).

## What this branch is

`ody-op` is the recovery baseline and shared tooling/evidence branch for the Honda Bosch A tune on
`HONDA_ODYSSEY_5G_MMR`. Experimental children inherit their validator, private-log tools, evidence,
and standards from here; only mechanism-specific controller code and rail assertions belong on a
test branch. Keep parent and nested opendbc branches paired.

`ody-op-test` is a frozen failed experiment. Do not add commits to it or treat its coast interlock,
raw `-0.40` entry, zero brake integral, onset shaper, or direct brake release as accepted knowledge.
`ody-op-test2` is the active child and resets the complete brake-command path to upstream Honda
source semantics while leaving the existing gas path unchanged for clean attribution.

Lateral is **stock and closed**: LKA 2560, `latAccelFactor 0.9`, `steerActuatorDelay 0.15`.
The former 0.20 s fallback had no isolated road benefit, so it was retired rather than kept as an
unproven tune. Honda pairs the 3840 RDM range with one-sided brake drag we cannot command. Reopen
lateral only for a logged symptom. `validate_log` deliberately has no lateral checks.

## Attribution boundary

Trace questionable behavior in this order:

`longitudinalPlan` → `carControl.actuators.accel` → `ACCEL_COMMAND` plus
`GAS_COMMAND`/`BRAKE_REQUEST` → Honda ECU/vehicle response.

`carControl.actuators.accel` is the controller input; `longitudinalPlan.aTarget` is upstream and
`longcontrol` may legitimately override it. Numeric `ACCEL_COMMAND` fidelity is not sufficient if
the domain bits leave gas inactive. Locate the first divergence before assigning the symptom.

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
- `carOutput.actuatorsOutput` must describe actuator output, not internal learner state. The current
  Odyssey use of its `gas`/`brake` fields for learned-factor telemetry is fork-only instrumentation.
  Before an upstream PR, restore actuator semantics and either reconstruct the learners offline or
  move them to an explicitly named diagnostic event accepted by the corresponding schema owner.
- **Never sync opendbc to its own master.** Rebase it to the commit openpilot master pins, or
  `controlsd` crashes on-road from a `car.capnp` schema mismatch.
- `lefthook run pre-commit` covers focused lint and pure metric tests. `.agents/preflash.py` adds
  Odyssey interface and panda-safety coverage; neither substitutes for a road drive.

## Active road question

The two-state release-width work is closed without promotion. Entry `-0.30`, width `0.50` reduced
descent transitions but held braking through positive requests; width `0.20` released sooner but
returned driver-felt tapping on split routes `00000027`/`00000028` (12 physical descent edges over
0.734 min, 16.4/min). Do not continue width or threshold tuning from that result.

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

`ody-op-test2` is now the fresh brake-source baseline. It removes every unproven custom brake
calibration: supplemental integral braking, compensated entry, stateful release hysteresis, and
onset shaping. `ACCEL_COMMAND` is the clipped controller request, and Honda's upstream raw-request
split at the live gas-lookup floor chooses the command domain. This is a source reference, not a
claim that stock braking is comfortable: master route `00000024--5c888c605c` measured 108.2
downhill edges/min. Do not deploy it as an improvement without an explicit controlled-reference
test plan.

The retained custom longitudinal behavior is outside brake authority: the road-supported Odyssey
gasfactor calibration and the validated `<=60` inactive-to-live gas ramp. Gas and brake remain
mutually exclusive, disengagement emits no longitudinal command, Panda bounds command magnitude,
and positive stop-release requests select gas immediately. Windfactor remains an explicitly
unproven gas-side learner and is not allowed to choose the brake domain; audit it separately rather
than coupling a powertrain rewrite to this brake reset.

Do not substitute this stock-semantics reset for the `ody-op` recovery branch. Full-rate master
route `00000024--5c888c605c` measured 108.2 downhill edges/min and peak 25/10 s, versus 1.9/min and
peak 3/10 s on `ody-op` route `00000026--bfe3fd933b`. The current upstream-pinned Honda path still
uses the same raw request and fixed -0.20 split, so that comparison remains behaviorally relevant.

Keep the 8 m/s gasfactor seed at `0.54` until the corrected narrow-window, exposure-qualified,
per-`opendbc_commit` report accumulates enough evidence. Legacy broad-bin suggestions are invalid.

The production windfactor learner is not independently identified from the gasfactor learner and
grade compensation. Do not call it validated or include it among the known-good behavior. It is
carried unchanged only so the fresh brake-source reference does not also become a gas-powertrain
experiment. Any removal or replacement must be its own arm, with gasfactor frozen or partitioned
during identification because both learners use the same tracking error.
