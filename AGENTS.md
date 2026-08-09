# Odyssey longitudinal tune — cold-start rules

Read this before changing the tune or its tooling. This file holds decisions and invariants;
route history and derivations belong in [`.agents/tune-evidence.md`](.agents/tune-evidence.md).

## What this branch is

`ody-op-long` is a **lateral-and-longitudinal** Honda Bosch A tune for `HONDA_ODYSSEY_5G_MMR`.
The longitudinal tune is in maintenance/validation mode. Require a specific full-rate logged
symptom before opening another behavior change.

Lateral is **settled and closed**: stock-LKA 2560, `latAccelFactor 0.9`, `steerActuatorDelay 0.20`.
Honda pairs the 3840 RDM range with one-sided brake drag we cannot command. `validate_log`
deliberately has no lateral checks.

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
- **Never sync opendbc to its own master.** Rebase it to the commit openpilot master pins, or
  `controlsd` crashes on-road from a `car.capnp` schema mismatch.
- `lefthook run pre-commit` covers focused lint and pure metric tests. `.agents/preflash.py` adds
  Odyssey interface and panda-safety coverage; neither substitutes for a road drive.

## Active road question

`BRAKE_DOMAIN_ENTRY=-0.30` is a road candidate intended to reduce descent engine-braking holds;
`DOMAIN_HYST_EXIT=0.50` remains the validated width. Behavior-equivalent candidate hashes
`c1ce76fa857a`, `14677d814cb2`, and `2cc9d0df854d` have **19/20** required terrain-matched hold
episodes through 2026-08-09. The newest routes removed the early apparent severity advantage:
hold exposure is not lower than the incumbent, while no late brake onset or longer-stop trigger
has appeared. Finish the gate on the same version before promotion, reversion, or another entry
position experiment.

Keep gas and brake domains mutually exclusive. Panda bounds `ACCEL_COMMAND` and `GAS_COMMAND` but
does not enforce that invariant; `.agents/test_odyssey_long_rails.py` does.

Keep the 8 m/s gasfactor seed at `0.54` until the corrected narrow-window, exposure-qualified,
per-`opendbc_commit` report accumulates enough evidence. Legacy broad-bin suggestions are invalid.
