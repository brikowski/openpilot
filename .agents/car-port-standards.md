# Honda car-port and safety guidance

This is the repository-owned guidance for edits under `opendbc_repo/opendbc/car/` and the Honda
panda-safety layer. Keep route IDs, measurements, and experiment history in Proton Drive's
`evidence/tune-evidence.md`; this file describes the current invariants only.

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
- On the current `ody-op` Odyssey port, the controller chooses mutually exclusive gas/brake
  domains from the raw request, with response-qualified gas entry from settled coast and
  early release of an already-active road-speed brake domain. Its
  active behavior is low-speed non-positive → brake below 5 m/s, road-speed brake entry at -0.30
  m/s², and active-gas continuity above Honda's upstream -0.20 m/s² split. It does not add a
  gasfactor, windfactor, low-speed PID, compensated-force map, or onset shaper. The current
  coast-entry trial uses settled, eligible coast at 8–35 m/s. The existing same-gear forecast
  and measured acceleration must both fall below the mild negative request by the response margin.
  Entry requires positive mapped gas and bypasses bridge pre-activation while preserving raw
  gas-domain `ACCEL_COMMAND`, stronger braking, low-speed authority, and unreliable-state fallbacks.
  The Odyssey-only uphill trial changes the opaque `GAS_COMMAND` mapping through a
  request-ramped, bounded pitch load. Its grade-proportional gas term rises
  from the brake boundary, remains request-sensitive through zero, and blends
  into the positive-request grade term. A fresh negative gas bridge retains
  `-60` at level/downhill grade and blends toward mapped gas on an uphill;
  response feedback remains inactive during the bridge. An already-active
  gas domain may still release into coast earlier on shallow climbs. At road
  speed in PID control, the brake-domain
  `ACCEL_COMMAND` adds a bounded Odyssey-calibrated grade term so Honda's grade-relative brake
  request follows the controller's net-acceleration target. Level road, low speed, stopping,
  and missing-pose behavior retain the raw-request rules. The early-release trial requires
  fresh received engine-torque and current overdeceleration evidence; it never overrides
  stronger raw braking or low-speed stop authority. Replay does not prove road benefit.
- The deployed unpromoted Odyssey gas-response candidate replaces the prior fixed steep-climb
  near-zero lookup term. After 0.5 s of continuous active gas, it compares the earlier
  `carControl` request with measured `aEgo` and applies a bounded, slewed correction to
  `GAS_COMMAND` only. A request decrease relative to the delayed request vetoes a positive
  correction target (and an increase vetoes a negative target), but existing correction unwinds
  under its slew limit; this is not an immediate sign veto on the transmitted correction.
  Request direction alone does not establish whether residual correction opposes the current
  acceleration-tracking error. Gas/brake domain selection, raw gas-domain
  `ACCEL_COMMAND`, the negative bridge, and brake translation remain unchanged. Replay
  establishes command shape, not that the resulting vehicle acceleration is improved.
- The downhill gas-to-coast trial learns passive acceleration only from previously issued,
  settled, pedal-free coast in the same target gear. It releases an already-active gas domain
  only when the request is mildly negative and falling, both measured and passive acceleration
  exceed that request, the downhill pitch signs agree, and the state is fresh. Without a learned
  coast estimate, it may instead release when bounded gas feedback has exhausted the zero gas
  command under those same request, downhill, and measured-response conditions. It does not
  activate friction braking, alter `ACCEL_COMMAND`, or change non-Odyssey Honda behavior.
  Replay does not establish road benefit.
- The Odyssey high-speed steering trial preserves the ordinary physical 2560-count map by
  rescaling the torque normalization and slew together. Extra counts are limited to persistent,
  same-direction 20–33 m/s curvature under-response while lateral control is active and
  unoverridden. `carOutput` reports the bounded controller command. The gate is not evidence
  that the EPS accepts extra torque or that road tracking improves.
- Read `values.py`, `hondacan.py`, the DBC, and `safety/modes/honda.h` together before changing a
  rail or signal. Numeric command fidelity is incomplete if the active domain bits disagree.

## Attribute before changing

Trace longitudinal behavior as:

`longitudinalPlan` → `carControl.actuators.accel` → `ACCEL_COMMAND` plus `GAS_COMMAND`/`BRAKE_REQUEST`
→ Honda ECU → vehicle response.

For lateral behavior, trace the upstream lateral plan/controller → `carControl` steering → Honda
steering CAN → ECU → vehicle response. Change the layer where the first repeatable divergence
appears; do not retune a faithful wire command without a separate actuator-response symptom.

Use that trace as the ownership decision, not merely as a list of signals:

- Wrong upstream request: investigate the OpenPilot planner, model, or controller.
- Correct request but wrong `carControl`: investigate `longcontrol` or lateral control.
- Correct `carControl` but wrong CAN value or domain: investigate the Honda port, DBC, or safety
  boundary.
- Correct command and domain but wrong response: investigate Honda ECU/actuator behavior and preserve
  the OpenPilot command shape.

A large `aEgo` or lateral-response residual alone does not identify a port bug. Align response timing,
separate domains and authority states, and condition on the relevant speed, request, grade, gear,
lead, and driver-input exposure before changing Honda code.

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

Project guidance and agent tooling live in `AGENTS.md` and `.agents/`.
