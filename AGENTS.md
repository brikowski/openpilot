# Odyssey longitudinal tune — cold-start rules

Read this before changing the tune or its tooling. This file holds decisions and invariants;
route history and derivations belong in [`.agents/tune-evidence.md`](.agents/tune-evidence.md).

## What this branch is

`ody-op` is a Honda Bosch A longitudinal tune for `HONDA_ODYSSEY_5G_MMR`.
The longitudinal tune is in maintenance/validation mode. Require a specific full-rate logged
symptom before opening another behavior change.

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

The `BRAKE_DOMAIN_ENTRY=-0.30`, `DOMAIN_HYST_EXIT=0.50` arm is closed without promotion. It sharply
reduced physical descent toggles versus stock on the GPS-matched 2026-08-11 routes, but held the
brake domain through positive requests and produced sustained underspeed. The next isolated road
candidate keeps entry at `-0.30` and narrows `DOMAIN_HYST_EXIT` to `0.20`. This exact combination is
untested. A prior `0.20` width with `-0.20` entry measured 15.1 corrected descent toggles/min versus
3.6-4.8 at `0.50`, so reject the candidate immediately if downhill tapping returns. Also revert for
stable-lead late brake onset or longer stops. Do not change brake PID, gasfactor, or windfactor in
this arm.

Keep gas and brake domains mutually exclusive. Panda bounds `ACCEL_COMMAND` and `GAS_COMMAND` but
does not enforce that invariant; `.agents/test_odyssey_long_rails.py` does.

Keep the 8 m/s gasfactor seed at `0.54` until the corrected narrow-window, exposure-qualified,
per-`opendbc_commit` report accumulates enough evidence. Legacy broad-bin suggestions are invalid.

The production windfactor learner is not independently identified from the gasfactor learner and
grade compensation. Do not call it validated or change it while the release-width arm is open. Once
that arm closes, compare an evidence-derived fixed drag factor with a shadow learner restricted to
live gas, no pedals, no saturation, and steady high-speed/grade windows. Because both learners use
the same tracking error, freeze or partition gasfactor learning during windfactor identification.
