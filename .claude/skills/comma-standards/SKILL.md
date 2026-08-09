---
name: comma-standards
description: Use when writing, refactoring, or auditing code inside an opendbc car port or safety layer - carcontroller.py, carstate.py, values.py, interface.py, or anything emitting CAN. Enforces comma's architecture boundaries and the panda safety bounds on outgoing actuation.
---

## Goal
Keep fork changes within openpilot's [safety framework](../../../docs/SAFETY.md), the current
[opendbc port structure](../../../opendbc_repo/README.md), and the panda safety model. Verify the
local checkout rather than relying on a historical comment or PR summary.

## Code Architecture Alignment
Use the existing boundaries:
- `values.py`: platforms, flags, bus configuration, and static controller parameters.
- `carstate.py`: incoming CAN parsing and normalized vehicle state.
- `carcontroller.py`: control state and outgoing actuation.
- `hondacan.py`: thin DBC-backed message construction.
- `interface.py`: high-level capabilities, tuning, limits, and delays.

Do not move logic across these files merely to shorten a diff. Outgoing values must remain within
the active panda safety limits; an out-of-range message is rejected by the TX hook.

## Known Gotchas by Platform
- Bosch `ACC_CONTROL.ACCEL_COMMAND` is scaled in m/s² in the DBC. `GAS_COMMAND` is unitless;
  do not infer torque or acceleration linearity from its raw value.
- Honda's ECU closes the brake loop. Preserve the stock zero high-level longitudinal gains and do
  not add a second ordinary `kp/ki` loop around `ACCEL_COMMAND`.
- Enabling Bosch openpilot longitudinal disables the radar/AEB path, as warned in `interface.py`.
- Current Honda Bosch safety limits are `ACCEL_COMMAND` -3.5 to +2.0 m/s² and `GAS_COMMAND`
  -30000 inactive to 2000 maximum. Read both the DBC and `safety/modes/honda.h` before citing them.
- Odyssey grade compensation also participates in the gas/brake domain decision. Preserve the
  low-speed raw-controller-request path and re-verify pitch assumptions from logs before changing it.

## Trust But Verify: Custom-Tune Comments
Production comments should explain a non-obvious invariant or why the code differs from upstream.
Keep route IDs, dates, measured tables, and experiment narratives in `.agents/tune-evidence.md`.
Correct a stale comment in the same focused change.

## Verification

Review the diff against the openpilot-pinned upstream opendbc commit. Run focused Ruff and tests
proportional to the change. Any actuation or parameter change also requires the Odyssey rail tests,
car-interface coverage, and ordinary-road validation; software tests do not prove ride quality.
Changes under `opendbc/safety/` additionally require the complete safety suite and MISRA-compatible C.
