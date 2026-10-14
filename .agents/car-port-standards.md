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
- Received `KINEMATICS.LONG_ACCEL` has unqualified scale and reference frame on this Odyssey.
  Keep it diagnostic until qualified; it is not interchangeable with net `aEgo`.
- The Honda Bosch ECU closes its own acceleration/brake loop. Do not stack a generic OpenPilot PID
  around `ACCEL_COMMAND` or use CAN shaping to hide an upstream planner/controller mismatch.
- On the current `ody-op-test` Odyssey port, the controller chooses mutually exclusive gas/brake
  domains from the raw request, with response-qualified gas entry from settled coast, brake entry
  from observed coast with a prior forecast, and response-qualified road-speed brake release. Its
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
  `ACCEL_COMMAND`. Gas remains available at the floor while passive deceleration requires assistance.
  During active gas control, a qualified coast forecast below the negative request retains gas
  through transient measured excess acceleration. Sustained excess in the existing same-drivetrain
  delayed-response observer restores fallback selection; a request beyond coast releases this authority. A prior coast forecast
  and measured acceleration above the request, including a nonnegative request, select mutually exclusive braking when fresh
  valid CAN confirms inactive gas and braking. Brake selection need not wait for the coast learner
  to settle; learning and gas entry retain their response interval.
  Excess road-speed braking may release when fresh active brake feedback and the qualified coast
  estimate show that coast supplies the current negative request. Qualified coast overrides the fixed
  fallback entry while measured response remains within the existing response margin. A stronger request
  than predicted coast, a measured shortfall beyond that margin, or unreliable state restores fallback
  braking. Release does not require a request trend.
  Low-speed authority, braking beyond passive response and unreliable-state fallbacks remain.
  The Odyssey-only uphill trial changes the opaque `GAS_COMMAND` mapping through a
  request-ramped, bounded pitch load. Its grade-proportional gas term rises
  from the brake boundary, remains request-sensitive through zero, and blends
  into the positive-request grade term. A fresh negative gas bridge retains
  `-60` at level/downhill grade and blends toward mapped gas on an uphill;
  it does not enter when the compensated map is at its zero-gas floor.
  Downhill gas compensation uses the existing grade term through zero net demand;
  it does not fade with the request. Raw gas-domain `ACCEL_COMMAND` is preserved.
  Response feedback remains inactive during the bridge. An already-active
  gas domain may still release into coast earlier on shallow climbs. At road
  speed, brake-domain `ACCEL_COMMAND` preserves the bounded raw acceleration request.
  The raw-request trial isolates Honda's response from the prior brake-grade correction;
  internal grade compensation and physical benefit remain unestablished. The creep-speed brake trial adds
  at most 0.25 m/s² of request-sensitive deceleration below 2 m/s, tapering to zero at zero request
  and at -0.80 m/s². It requires active control with neither pedal pressed and remains continuous
  across control-state transitions. This feedforward calibration does not accumulate acceleration error or
  retain a released request. Physical benefit remains unmeasured. At road speed, level-road,
  stopping and missing-pose behavior retain the raw-request rules. Early brake release requires
  fresh received braking state, a negative request, current overdeceleration, and a
  same-gear coast forecast that can supply the request. Release and gas handoff share active
  feedback: `COMPUTER_BRAKING` or finite `USER_BRAKE` above one DBC step. Without a qualified forecast, an active
  brake follows the easing negative command. At 8–35 m/s in PID control with qualified CAN and
  pose, an active brake remains available through zero and positive net-acceleration requests
  below the learned coast acceleration. It releases when the request reaches that forecast.
  A settled hold also yields to a positive-request acceleration shortfall when fresh received
  gas and brake feedback are idle. The existing response margin applies; the held forecast
  is not updated from that controlled response.
  Gas and brake remain mutually exclusive; nonnegative brake targets retain raw `ACCEL_COMMAND`.
  Missing or unreliable state retains the raw-sign fallback for nonnegative requests. This does
  not extend low-speed stopping authority.
  New gas entry at 8–35 m/s in PID control waits in coast while fresh received computer-braking
  or positive `USER_BRAKE` feedback remains active. It releases `BRAKE_REQUEST` immediately,
  preserves numeric `ACCEL_COMMAND`, and uses no fixed delay. A qualified handoff keeps its
  settled brake history through qualified coast and while feedback blocks gas, so early release does
  not discard an established handoff. A new brake selection restarts brake settling; a gear change
  restarts settling for coast observations while retaining any prior estimate for the received gear.
  Existing gas continuity and unreliable-state fallbacks remain available.
  Replay does not prove road benefit.
- The unpromoted Odyssey gas-response candidate replaces the prior fixed steep-climb
  near-zero lookup term. During startup, measured excess acceleration may reduce gas;
  positive feedback still waits for the delayed observer. After 0.5 s of continuous active gas, it compares the earlier
  `carControl` request with measured `aEgo` within the same received target gear and applies a bounded,
  slewed correction to `GAS_COMMAND` only. Received target-gear or transmission-activity changes
  clear delayed history. During warmup, already-issued positive correction may remain while current
  acceleration still needs it, subject to headroom and slew. This hold seeds the new integral within
  its retained-offset bound. New positive feedback still waits for
  the delayed observer. The activity
  byte is compared as reported state, without assuming a gear ratio or a shift-complete encoding. Missing,
  stale or invalid gear state disables feedback while preserving the feedforward map. Falling grade
  restarts feedback with a positive learned offset while retaining feedback already reducing gas. With zero offset,
  grade changes alone do not restart the observer. A request change does not by itself veto feedback:
  the filtered delayed error is limited to the sign and
  magnitude of the latest acceleration error. Qualified feedback retains a bounded integral offset
  at zero error; ineligible feedback clears it. Output uses the mapped command's available headroom
  in both directions, including the low-speed trim. Fresh delayed feedback uses that headroom for
  its integral offset; warmup seeds positive memory to at most 100 counts.
  Accumulation respects these constraints, and output retains its slew limit. Mapped headroom also bounds
  feedback during high-demand launches.
  Domain rules, raw gas-domain `ACCEL_COMMAND`, the negative bridge,
  and brake translation remain unchanged; feedback can affect the exhausted-gas coast fallback. Replay
  establishes command shape, not that the resulting vehicle acceleration is improved.
- The downhill gas-to-coast trial learns passive acceleration only from previously issued,
  settled, pedal-free coast or a settled negative-request brake selection with inactive actuators in the same target
  gear with valid CAN and fresh received gear, gas and braking state, using the existing recent five-sample median
  throughout eligible coast. Learning and prediction use live calibrated pitch as their shared gravity
  reference; gas feedforward and response feedback retain their separate filtered pitch.
  All coast observations require `USER_BRAKE` within one DBC
  quantization step of zero, including after the brake command releases; the shared VSA reception
  timestamp qualifies that signal.
  Nonnegative brake holding uses the prior coast estimate without learning its controlled response as coast.
  At 8–35 m/s, qualified pedal-free manual coast can initialize the same learner before engagement.
  Manual observations also require idle received gas/braking and pressure within one DBC step of zero;
  physical-state qualification owns resets, while active control keeps its existing PID gates.
  The first five settled observations use consecutive ACC cycles;
  established estimates retain their 100 ms update cadence. It selects or retains coast when
  measured and learned passive acceleration exceed the request, including positive requests, with agreeing downhill pitch
  signs and fresh valid received state. Gas resumes when measured or predicted coast no longer
  exceeds the request. Without a learned estimate, release still requires falling mild negative
  demand and an already-issued zero gas command; request trend uses elapsed control time. No new
  learner or gas-map gain is added. This selection does not activate friction braking, alter
  `ACCEL_COMMAND`, or change non-Odyssey Honda behavior.
  Replay does not establish road benefit.
- The Odyssey steering trial preserves the ordinary physical seed feedforward by
  rescaling the torque tune and slew together. The torque learner fits normalized output;
  changing its scale can change fitted gains, friction and physical bucket coverage. Compare the
  actually consumed parameters rather than assuming the learned map is unchanged.
  Torque-cache identity includes Honda's steering route. Discard incompatible or unassociated
  caches so they cannot return after the previous-route metadata advances.
  Extra counts are limited to persistent,
  same-direction 15–33 m/s curvature under-response while lateral control is active and
  unoverridden. Once qualified, authority follows the continuing upstream torque request through
  tracking convergence. Falling demand, a direction change, or ineligible vehicle state closes the
  gate. The existing 3840-count limit and physical slew limit remain.
  `carOutput` reports the bounded controller command. The gate is not evidence
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
