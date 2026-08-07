# Odyssey longitudinal tune — rules that must survive a cold start

Read this before touching the tune or its tooling. Detail and evidence live in
[`.agents/tune-evidence.md`](.agents/tune-evidence.md); this file is only the part that is expensive to
re-derive and dangerous to get wrong. Every rule below was paid for by a failed drive, a wrong
number, or a wasted session.

## What this branch is

`ody-op-long` is a **lateral-and-longitudinal** Honda Bosch A tune for `HONDA_ODYSSEY_5G_MMR`.
The longitudinal tune is **CONVERGED — we are validating, not tuning.** Do not propose a tuning
change without a specific logged symptom.

Lateral is **settled and closed**: stock-LKA 2560, `latAccelFactor 0.9`, `steerActuatorDelay 0.20`.
Honda pairs the 3840 RDM range with one-sided brake drag we cannot command, so asking for it buys
authority the car will not deliver. `validate_log` deliberately has no lateral checks.

## The one question the car port answers

**"Did we put on the wire what CarController was asked for?"**

- The input is `carControl.actuators.accel`. **Not** `longitudinalPlan.aTarget` — that is one stage
  upstream and `longcontrol` legitimately overrides it.
- Anything upstream of that input is openpilot's planner/model. Anything downstream of
  `ACCEL_COMMAND` is Honda's ECU.
- If `aEgo` tracks the request, control is fine and the symptom is the planner's. Late lead braking,
  jumpy `aTarget`, set-speed-change braking, and stop-line behavior are **all upstream — not ours**.
  The lever for those is driving personality or `experimentalMode`, not code.

## Rules that have each cost a failure

1. **Never promote a change from replay alone.** `replay_carcontroller.py` freezes `aTarget`, so it
   has no feedback path and its domain-transition counts are fiction. Three confident replay
   predictions, three on-road failures. Open-loop crossing rates underpredict ~2.7x. Replay checks
   command *shape*; only a drive measures *when* we brake.
2. **Pool on `opendbc_commit`, never on branch or parent commit.** The tune lives in the submodule.
   Grouping by parent made the 0.50 analysis wrong. Route `00000005` is excluded from every pooled
   comparison.
3. **Mutation-verify a check when you write it.** A check you have never seen fail is not evidence.
   If it cannot be made to fail, that is the finding.
4. **Before adding a check, measure its overlap with the checks you already have.** A 2026-08-05
   proposal turned out to be a 100% duplicate of `sign disagreement`.
5. **Check the mask before believing a metric moved.** A 0.325 "divergence" that day was an artifact
   of computing over engaged frames instead of `pid` frames.
6. **A near-zero error is not evidence of fidelity** when the other half of the command makes the
   request undeliverable. `ACCEL_COMMAND` can carry the request perfectly while `GAS_COMMAND` sits
   at its inactive constant.
7. **Name checks after the symptom, not the fix.** A metric tied to a proposed fix dies with it.
8. **Comments are a lead to verify, not a fact to cite.** Correct stale ones as part of your change.

## Workflow

- **Logs come off the device over SSH** (`.agents/pull_logs.py`); rlogs never auto-upload and qlogs
  are too decimated for the jerk/domain metrics. `.agents/extract.py` caches the decoded signals so
  repeat analysis of one route does not re-read every segment.
- **Every drive goes through `.agents/validate_log.py`**, which appends one row per route to
  `.agents/log-validation-ledger.jsonl` (authoritative) and `.md` (human view).
- **A threshold flag identifies an event to inspect. By itself it is not permission to tune.**
- Car-port edits must follow `.claude/skills/comma-standards/SKILL.md` — actuation must never exceed
  the panda safety limits, and file boundaries (`values.py` / `carstate.py` / `carcontroller.py` /
  `interface.py`) are load-bearing.
- Custom edits carry an inline comment explaining *why*, ending
  `TODO: delete excessive comments before trying to submit a PR.`
- **Never sync opendbc to its own master** — pin it to the commit openpilot master pins, or
  `controlsd` crashes on-road from a `car.capnp` schema mismatch.
- `git commit` runs lefthook: ruff over `.agents` and the Honda tune, plus the tooling tests. It is
  tool-agnostic; do not bypass it.

## Open item

Entry `-0.20` with `DOMAIN_HYST_EXIT = 0.50` withholds `GAS_COMMAND` against a positive request for
~50 s per 15 engaged minutes. Fidelity and descent chatter trade roughly 1:1 across every
configuration tested, so there is no free setting. Route `00000003--f670928197` is the clean 0.50
baseline.

**What withheld gas actually costs (measured 2026-08-06, driver-reported):** it is not coasting. On
descent holds the throttle is shut in an unchanged gear, engine torque runs **-103/-164** against
**+311** in the gas domain on the same descents, and the car lands **0.14-0.26 m/s² short of a
positive request**. Not the friction brakes (`COMPUTER_BRAKING` 5-19%), not `brake_pid` (-0.006),
not a downshift (gear unchanged). Because the decision input carries `hill_brake`, a -1.5° descent
enters the brake domain at request **+0.03** and does not release until **+0.53** — flat ground is
-0.22/+0.28, which is why the symptom is grade-only.

**Band POSITION and band WIDTH are different axes — do not conflate them.** Every prior sweep moved
the *width* (`DOMAIN_HYST_EXIT`), which trades ~1:1 against descent chatter and failed on road three
times. `BRAKE_DOMAIN_ENTRY` moves the band's *position* and had never been swept. Open-loop over
`0000000d`+`00000003`, with the domain state machine first validated at **99.8%/98.9%** against the
logged wire, entry `-0.20 -> -0.30` gives descent hold **74.3 s -> 29.8 s (-60%)**, brake duty
**7.2% -> 4.5%**, and descent toggles **6.1 -> 6.5/min (flat)** — it does *not* buy the hold
reduction with chatter. **`BRAKE_DOMAIN_ENTRY = -0.30` is now on the branch as the road candidate.**
Cost to watch: 132.5 s (2.74% of engaged time) moves brake->gas domain; the request there averages
~0 but p10 is **-0.37**, and gas has no braking authority below ~-0.2, so **late brake onset and
longer stops are the failure mode**. Revert to `-0.20` if that appears. Open-loop underpredicts
~2.7x and cannot model feedback: this is a candidate, not a result.

**Two dead ends, recorded so they are not retried.** (1) "Latch `BRAKE_REQUEST` but command neutral
gas" is *not implementable* — `gas_dom = not brake_domain` makes them mutually exclusive by
construction and `BRAKE_REQUEST` is the same bit as `BRAKE_LIGHTS`. (2) `GAS_COMMAND = 0` while
braking passes panda, but `test_odyssey_long_rails` asserts `brake domain => GAS_INACTIVE` in two
places, and since **panda has no gas/brake mutual-exclusion check** that test is the only guard
there is. Do not weaken it to ship an unmeasured state. Detail in
[`.agents/tune-evidence.md`](.agents/tune-evidence.md).

**Gate, restated 2026-08-06 — the old ">=3 descent minutes in one drive" was unreachable.** Zero of
46 routes ever hit it; the max ever is 2.10, and the gate's own reference routes `0000002f`/`00000030`
are 0.57 and 1.42 (1.99 combined). It also contradicted rule 2 above. The gate is now **>=20 descent
hold-episodes pooled at one `opendbc_commit`**, terrain-matched, at both the incumbent and candidate
setting — not another replay sweep. **The incumbent 0.50 arm is satisfied** (26 episodes / 76.9 s).
What blocks a change is the candidate arm: the same roads driven at the new value.
