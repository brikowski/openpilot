# Honda car-port and safety guidance

This is the repository-owned guidance for edits under `opendbc_repo/opendbc/car/` and the Honda
panda-safety layer. Keep route IDs, measurements, and experiment history in
[`tune-evidence.md`](tune-evidence.md); this file describes the current invariants only.

## Keep the upstream boundaries

- `values.py` owns platform declarations, buses, flags, static limits, and controller parameters.
- `carstate.py` parses incoming CAN into normalized vehicle state.
- `carcontroller.py` owns control state and outgoing actuation decisions.
- `hondacan.py` remains a thin DBC-backed message builder.
- `interface.py` owns high-level capabilities, tuning, limits, and delays.

Do not move behavior between these layers just to shorten a diff. Review the active DBC and panda
safety hook before quoting a signal scale or limit; an outgoing message must remain inside the
active safety rails.

## Honda Bosch longitudinal facts

- `ACC_CONTROL.ACCEL_COMMAND` is the acceleration request in m/s².
- `GAS_COMMAND` is opaque/unitless. Do not infer acceleration or torque linearity from its raw value.
- The Honda Bosch ECU closes its own acceleration/brake loop. Do not stack a generic OpenPilot PID
  around `ACCEL_COMMAND` or use CAN shaping to hide an upstream planner/controller mismatch.
- On the current `ody-op` Odyssey port, `carcontroller.py` keeps the clipped raw controller request
  as `ACCEL_COMMAND`; `odyssey_command_domains` chooses mutually exclusive gas/brake domains. Its
  active behavior is low-speed non-positive → brake below 5 m/s, road-speed brake entry at -0.30
  m/s², and active-gas continuity above Honda's upstream -0.20 m/s² split. It does not add a
  gasfactor, windfactor, low-speed PID, compensated-force map, or onset shaper.
- Read `values.py`, `hondacan.py`, the DBC, and `safety/modes/honda.h` together before changing a
  rail or signal. Numeric command fidelity is incomplete if the active domain bits disagree.

## Attribute before changing

Trace longitudinal behavior as:

`longitudinalPlan` → `carControl.actuators.accel` → `ACCEL_COMMAND` plus `GAS_COMMAND`/`BRAKE_REQUEST`
→ Honda ECU → vehicle response.

For lateral behavior, trace the upstream lateral plan/controller → `carControl` steering → Honda
steering CAN → ECU → vehicle response. Change the layer where the first repeatable divergence
appears; do not retune a faithful wire command without a separate actuator-response symptom.

Replay validates command shape on frozen inputs only. It does not establish closed-loop timing,
ride quality, lead selection, or stop behavior. Use focused mutation-tested checks, then controlled
and ordinary-road evidence with comparable command, speed, domain, authority, and terrain exposure.

## Required checks for a port change

1. Inspect the diff against the OpenPilot-pinned `opendbc` commit and keep production comments
   focused on invariants.
2. Run `lefthook run pre-commit`, the focused Odyssey rail/lifecycle tests, and `opendbc_repo/test.sh`
   as appropriate to the touched layer. Safety changes also require the complete safety suite and
   MISRA-compatible C checks.
3. For actuation changes, run replay for command shape and record the ordinary-road or controlled
   evidence separately. A clean validator result is software evidence, not a ride-quality claim.
4. Publish the nested `opendbc_repo` commit before the parent gitlink, verify exact remote SHAs and
   clean trees, and only then deploy through the guarded task.

The `CLAUDE.md` symlink remains only as a compatibility alias to `AGENTS.md`; project guidance and
agent tooling live in `AGENTS.md` and `.agents/`.
