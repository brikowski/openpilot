# name: comma-standards
# description: Triggers when writing, refactoring, or auditing code inside car ports or safety layers to ensure strict compliance with Comma's standards.

## Goal
Ensure any proposed modification safely aligns with the architecture, guidelines, and definitions specified by Comma's engineering practices.

## Code Architecture Alignment
When modifying vehicle platform controls, target the correct execution boundaries:
- `values.py`: Managing vehicle fingerprinting, CAN bus configurations, and static car parameters.
- `carstate.py`: Extracting and parsing incoming CAN stream variables.
- `carcontroller.py`: Constructing and executing out-bound CAN actuation signals. **CRITICAL:** Any actuation values (gas, brake, steer torque) must NEVER exceed the hardware safety limits defined in the Panda safety model, or the Panda will immediately fault and kill the drive.
- `interface.py`: Exposing high-level car interface classes (like PID tuning, bounds, and delays) to the core system.

## Branch Scope
- **`ody-op` (this branch) is lateral-tuning-only.** Longitudinal control must stay stock - no custom `carcontroller.py` gas/brake logic, no `longitudinalTuning`/`longitudinalActuatorDelay`/`BOSCH_GAS_LOOKUP_V` overrides. If a task calls for longitudinal changes, that work belongs on `ody-op-long`, not here.

## Trust But Verify: Custom-Tune Comments
Comments left by prior sessions (including "CUSTOM TUNE" blocks and journal-style writeups) capture reasoning *at the time they were written*. Treat them as a starting point for investigation, not as verified fact - upstream PRs move, DBC signals get re-checked, and code gets reverted or reworked out from under a comment that still references it. Before relying on a claim in one of these comments, spot-check it against the current code/DBC/PR state. If you find a comment that's stale, wrong, or refers to code that no longer exists, correct or remove it as part of your change rather than leaving it to mislead the next session.

## The "Readies" (Mandatory Evaluation Checkpoints)
Before finalizing any code modification, you must satisfy these validation parameters:
1. **Linter Compliance**: Force-verify Python modifications using the modern environment tool (e.g., `uv run ruff check . --fix`).
2. **Hook Verification**: Instruct or run `lefthook run lint` (or standard `pre-commit`) to prevent build log failures.
3. **Safety Model Isolation**: Any logic touching C-based panda firmware must conform to MISRA C:2012 guidelines and support strict compiler flags (`-Wall -Wextra -Wstrict-prototypes -Werror`).
4. **Car Interface Tests**: Run the car interfaces test suite (e.g., `uv run pytest opendbc_repo/opendbc/car/tests/test_car_interfaces.py` or equivalent in the active repository) to rapidly validate that car port modifications didn't break system definitions.
5. **Local Integration Check**: Execute the primary testing script (like `test.sh`) to trigger parallel unittests and cross-compile with `scons`.
