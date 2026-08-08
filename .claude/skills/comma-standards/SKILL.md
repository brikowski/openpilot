---
name: comma-standards
description: Use when writing, refactoring, or auditing code inside an opendbc car port or safety layer - carcontroller.py, carstate.py, values.py, interface.py, or anything emitting CAN. Enforces comma's architecture boundaries and the panda safety model, which silently drops out-of-range actuation while driving.
---

## Goal
Ensure any proposed modification safely aligns with the architecture, guidelines, and definitions specified by Comma's engineering practices. All fork modifications must comply with Openpilot's [safety framework](file:///Users/travisbadgley/openpilot/docs/SAFETY.md) and the [panda safety model](https://github.com/commaai/panda#safety-model).

## Code Architecture Alignment
When modifying vehicle platform controls, target the correct execution boundaries:
- `values.py`: Managing vehicle fingerprinting, CAN bus configurations, and static car parameters.
- `carstate.py`: Extracting and parsing incoming CAN stream variables.
- `carcontroller.py`: Constructing and executing out-bound CAN actuation signals. **CRITICAL:** Any actuation values (gas, brake, steer torque) must NEVER exceed the hardware safety limits defined in the Panda safety model, or the Panda will immediately fault and kill the drive.
- `interface.py`: Exposing high-level car interface classes (like PID tuning, bounds, and delays) to the core system.

## Dual-Branch Strategy
- **`ody-op`**: lateral-tuning-only. No longitudinal changes - `carcontroller.py`'s gas/brake logic and `interface.py`'s longitudinal fields (`longitudinalTuning`, `longitudinalActuatorDelay`, `BOSCH_GAS_LOOKUP_V`, etc.) stay stock there.
- **`ody-op-long`** (this branch): lateral **and** longitudinal tuning are both in scope. You're explicitly authorized to implement custom longitudinal logic (feedforward terms, gas-only PID, etc.) directly in `carcontroller.py`. The current implementation is a live-learning gas feedforward (speed-scheduled `gasfactor` baseline + trim, `windfactor`, grade/drag terms) plus a gated supplemental `brake_pid` - see tune-evidence.md "Current longitudinal design on this branch" (under "Custom Tuning & Development Guidelines") before changing it. Panda safety hardware limits (steer torque, max gas/brake) must still never be exceeded.

## Known Gotchas by Platform
- **Honda Bosch (A/C, radar-equipped)**: the car's own ECU already runs an internal closed-loop brake PID on top of whatever `ACC_CONTROL.ACCEL_COMMAND` (real m/s², see DBC) openpilot sends. Stock `longitudinalTuning.kp/ki = 0` in `interface.py` is intentional, not a gap to fill in - adding openpilot's own closed-loop gain on top of that stacks two PID loops and is a documented cause of oscillating braking/acceleration (opendbc PR #2347, github.com/commaai/opendbc/pull/2347). If a Bosch car pulses or overshoots, suspect this before adding kp/ki.
- **Honda Bosch A `GAS_COMMAND`**: unlike `ACCEL_COMMAND`, this signal is opaque/unitless in the DBC (not a real torque or accel value) and there is no writable torque CAN signal on this platform at all - the car only exposes read-only torque telemetry (`GAS_PEDAL_2.ENGINE_TORQUE_ESTIMATE/REQUEST`). Don't assume `GAS_COMMAND` scales linearly with accel across speed/load without checking; a torque-based gas mapping is feasible in principle but requires reverse-engineering that calibration from logged drives, not a protocol-level change.
- **Alpha long disables CMBS/AEB (fundamental, not a bug)**: enabling openpilot longitudinal on a Bosch radar car requires silencing the stock radar (`ret.radarUnavailable = True`; the `interface.py` comment literally reads "WARNING: THIS DISABLES AEB!"). That radar runs Honda's CMBS collision braking, so CMBS is off whenever alpha long is on - you cannot have both on the same bus. openpilot is Level 2 and does **not** implement AEB (panda safety caps braking near `BOSCH_ACCEL_MIN` -3.5 m/s², far short of AEB's ~-8 to -10), so the driver is the emergency-braking fallback. The only way to keep CMBS is to not use openpilot long (stock ACC + openpilot lateral only, i.e. the `ody-op` approach). Do not try to make openpilot command emergency braking - it's outside the safety model by design.
- **Grade compensation biases the gas/brake domain switch**: the `hill_brake = sin(pitch)*g` feedforward is folded into `gas_pedal_force`, which decides the gas-vs-brake domain. On a real grade - or a pitch *offset* - it can push the switch the wrong way (e.g. release the brake near a stop), which is why the low-speed switch is gated on planner accel instead of `gas_pedal_force`. **Standing pitch bias - SETTLED 2026-08-08**: `orientationNED[1]` carries a constant ~+0.02 rad offset (speed- and accel-invariant, present on every drive with usable data since 2026-07-29; ~+0.21 m/s² of phantom `hill_brake`). It is a mount/calibration offset, not dynamics. The gasfactor learner absorbs it and every empirical band number was measured against the biased signal - do NOT zero it out without redoing the band analysis, and never read `orientationNED[1]` as true grade (true grade ~= pitch - 0.02). Measurement in tune-evidence.md "Standing pitch bias".

## Trust But Verify: Custom-Tune Comments
Comments left by prior sessions (including "CUSTOM TUNE" blocks and journal-style writeups) capture reasoning *at the time they were written*. Treat them as a starting point for investigation, not as verified fact - upstream PRs move, DBC signals get re-checked, and code gets reverted or reworked out from under a comment that still references it. Before relying on a claim in one of these comments, spot-check it against the current code/DBC/PR state. If you find a comment that's stale, wrong, or refers to code that no longer exists, correct or remove it as part of your change rather than leaving it to mislead the next session.

## The "Readies" (Mandatory Evaluation Checkpoints)
Before finalizing any code modification, you must satisfy these validation parameters:
1. **Linter Compliance**: Force-verify Python modifications using `uv run ruff check opendbc_repo --fix`.
2. **Hook Verification**: Instruct or run `lefthook run lint` (or standard `pre-commit`) to prevent build log failures.
3. **Safety Model Isolation**: Any logic touching C-based panda firmware must conform to MISRA C:2012 guidelines and support strict compiler flags (`-Wall -Wextra -Wstrict-prototypes -Werror`).
4. **Car Interface Tests**: Run the car interfaces test suite (e.g., `uv run pytest opendbc_repo/opendbc/car/tests/test_car_interfaces.py` or equivalent in the active repository) to rapidly validate that car port modifications didn't break system definitions.
5. **Local Integration Check**: Execute the primary testing script (like `test.sh`) to trigger parallel unittests and cross-compile with `scons`.
