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

## Known Gotchas by Platform
- **Honda Bosch (A/C, radar-equipped)**: the car's own ECU already runs an internal closed-loop brake PID on top of whatever `ACC_CONTROL.ACCEL_COMMAND` (real m/s², see DBC) openpilot sends. Stock `longitudinalTuning.kp/ki = 0` in `interface.py` is intentional, not a gap to fill in - adding openpilot's own closed-loop gain on top of that stacks two PID loops and is a documented cause of oscillating braking/acceleration (opendbc PR #2347, github.com/commaai/opendbc/pull/2347). If a Bosch car pulses or overshoots, suspect this before adding kp/ki.
- **Honda Bosch A `GAS_COMMAND`**: unlike `ACCEL_COMMAND`, this signal is opaque/unitless in the DBC (not a real torque or accel value) and there is no writable torque CAN signal on this platform at all - the car only exposes read-only torque telemetry (`GAS_PEDAL_2.ENGINE_TORQUE_ESTIMATE/REQUEST`). Don't assume `GAS_COMMAND` scales linearly with accel across speed/load without checking; a torque-based gas mapping is feasible in principle but requires reverse-engineering that calibration from logged drives, not a protocol-level change (see `honda/interface.py`'s `HONDA_ODYSSEY_5G_MMR` "CUSTOM TUNE JOURNAL" comment for the full writeup).

## The "Readies" (Mandatory Evaluation Checkpoints)
Before finalizing any code modification, you must satisfy these validation parameters:
1. **Linter Compliance**: Force-verify Python modifications using the modern environment tool (e.g., `uv run ruff check . --fix`).
2. **Hook Verification**: Instruct or run `lefthook run lint` (or standard `pre-commit`) to prevent build log failures.
3. **Safety Model Isolation**: Any logic touching C-based panda firmware must conform to MISRA C:2012 guidelines and support strict compiler flags (`-Wall -Wextra -Wstrict-prototypes -Werror`).
4. **Car Interface Tests**: Run the car interfaces test suite (e.g., `uv run pytest opendbc_repo/opendbc/car/tests/test_car_interfaces.py` or equivalent in the active repository) to rapidly validate that car port modifications didn't break system definitions.
5. **Local Integration Check**: Execute the primary testing script (like `test.sh`) to trigger parallel unittests and cross-compile with `scons`.