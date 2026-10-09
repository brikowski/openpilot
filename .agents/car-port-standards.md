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
  domains from the raw request, with response-qualified gas entry from settled coast, brake entry
  from observed coast with a prior forecast, and early release of an already-active road-speed brake domain. Its
  active behavior is low-speed non-positive → brake below 5 m/s, fallback road-speed brake entry at -0.30
  m/s², and active-gas continuity above Honda's upstream -0.20 m/s² split. It does not add a
  gasfactor, windfactor, low-speed PID, compensated-force map, or onset shaper. The current
  passive-response candidate uses the existing same-gear forecast at 8–35 m/s. Both forecast
  and measured acceleration must fall below a negative request by the response margin before
  settled coast or a held, physically inactive brake domain can enter gas. Fresh valid CAN,
  received gear and braking state qualify this additional authority. A new brake selection must
  settle over the existing response-delay interval before inactive feedback can qualify that override.
  It bypasses pre-activation
  and permits existing bounded feedback at the gas-map floor, preserving raw gas-domain
  `ACCEL_COMMAND`. Gas remains available at the floor while passive deceleration still requires
  assistance and measured response does not exceed the request by the margin. A prior coast forecast
  and measured acceleration above a negative request select mutually exclusive braking when fresh
  valid CAN confirms inactive gas and braking. Brake selection need not wait for the coast learner
  to settle; learning and gas entry retain their response interval.
  Low-speed authority, braking beyond passive response and unreliable-state fallbacks remain.
  The Odyssey-only uphill trial changes the opaque `GAS_COMMAND` mapping through a
  request-ramped, bounded pitch load. Its grade-proportional gas term rises
  from the brake boundary, remains request-sensitive through zero, and blends
  into the positive-request grade term. A fresh negative gas bridge retains
  `-60` at level/downhill grade and blends toward mapped gas on an uphill;
  response feedback remains inactive during the bridge. An already-active
  gas domain may still release into coast earlier on shallow climbs. At road
  speed in PID control, the brake-domain
  `ACCEL_COMMAND` adds an Odyssey-calibrated grade term, limiting extra downhill deceleration
  to the requested deceleration's magnitude as a gentle request approaches zero. The creep-speed brake trial adds
  at most 0.25 m/s² of request-sensitive deceleration below 2 m/s, tapering to zero at zero request
  and at -0.80 m/s². It requires active control with neither pedal pressed and remains continuous
  across control-state transitions. This feedforward calibration does not accumulate acceleration error or
  retain a released request. Physical benefit remains unmeasured. At road speed, level-road,
  stopping and missing-pose behavior retain the raw-request rules. Early brake release requires
  fresh received braking state, an easing negative request, current overdeceleration, and a
  same-gear coast forecast that can supply the request. Without a qualified forecast, an active
  brake follows the easing negative command. At 8–35 m/s in PID control with qualified CAN and
  pose, an active brake remains available through zero and positive net-acceleration requests
  below the learned coast acceleration. It releases when the request reaches that forecast.
  Gas and brake remain mutually exclusive; nonnegative brake targets retain raw `ACCEL_COMMAND`.
  Missing or unreliable state retains the raw-sign fallback for nonnegative requests. This does
  not create positive-request brake entry or extend low-speed stopping authority.
  Replay does not prove road benefit.
- The unpromoted Odyssey gas-response candidate replaces the prior fixed steep-climb
  near-zero lookup term. During startup, measured excess acceleration may reduce gas;
  positive feedback still waits for the delayed observer. After 0.5 s of continuous active gas, it compares the earlier
  `carControl` request with measured `aEgo` within the same received target gear and applies a bounded,
  slewed correction to `GAS_COMMAND` only. Received target-gear or transmission-activity changes
  clear the delayed observer while the existing correction retains its slew limit. The activity
  byte is compared as reported state, without assuming a gear ratio or a shift-complete encoding. Missing,
  stale or invalid gear state disables feedback while preserving the feedforward map. A request
  change does not by itself veto feedback: the filtered delayed error is limited to the sign and
  magnitude of the latest acceleration error. Existing correction still unwinds under its slew limit.
  Domain rules, raw gas-domain `ACCEL_COMMAND`, the negative bridge,
  and brake translation remain unchanged; feedback can affect the exhausted-gas coast fallback. Replay
  establishes command shape, not that the resulting vehicle acceleration is improved.
- The downhill gas-to-coast trial learns passive acceleration only from previously issued,
  settled, pedal-free coast or a settled brake selection with inactive actuators in the same target
  gear with valid CAN and fresh received gear, gas and braking state, using the existing recent five-sample median
  throughout eligible coast. Held brake observations also require `USER_BRAKE` within one DBC
  quantization step of zero; the shared VSA reception timestamp qualifies that signal.
  The first five settled observations use consecutive ACC cycles;
  established estimates retain their 100 ms update cadence. It selects or retains coast when
  measured and learned passive acceleration exceed the request, including positive requests, with agreeing downhill pitch
  signs and fresh valid received state. Gas resumes when measured or predicted coast no longer
  exceeds the request. Without a learned estimate, release still requires falling mild negative
  demand and exhausted bounded gas feedback; request trend uses elapsed control time. No new
  learner or gas-map gain is added. This selection does not activate friction braking, alter
  `ACCEL_COMMAND`, or change non-Odyssey Honda behavior.
  Replay does not establish road benefit.
- The Odyssey steering trial preserves the ordinary physical 2560-count map by
  rescaling the torque normalization and slew together. Extra counts are limited to persistent,
  same-direction 15–33 m/s curvature under-response while lateral control is active and
  unoverridden. Persistence follows the upstream torque request; issued torque retains its physical
  slew limit. `carOutput` reports the bounded controller command. The gate is not evidence
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

OpenPilot runtime fixes are in scope under `AGENTS.md` when the first divergence belongs there;
implement them there instead of adding Honda compensation. In the port, prefer reliable live or
learned vehicle state over fixed tuning when it directly represents the controlled behavior. Keep
constraints and fallbacks where needed, and do not add a learner solely to remove a constant.

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
