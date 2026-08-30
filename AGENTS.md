# Odyssey command-following — cold-start rules

Read this before changing lateral or longitudinal behavior or its tooling. This file holds decisions
and invariants; route history and derivations belong in [`.agents/tune-evidence.md`](.agents/tune-evidence.md).

## Project objective

Make the Odyssey follow the commands produced by OpenPilot as smoothly and accurately as the vehicle
allows, independently for lateral and longitudinal control, while keeping the smallest practical delta
from current `commaai/openpilot` and `commaai/opendbc` master.

- Use every comparable private full-rate log, controlled maneuver, and ordinary-road result to find the
  first repeatable divergence from the upstream plan/controller command through CAN to vehicle response.
  Make only the smallest change supported by that evidence, then verify the result against a baseline
  with comparable command, speed, domain, and terrain exposure. An exact route match is stronger but
  is not required to determine whether command following improved.
- Treat the upstream OpenPilot command path as the primary functional reference. For longitudinal,
  stock-radar traces remain a benchmark for actuator transitions, episode shape, and achieved ride
  response, not for proprietary target selection. Lateral and longitudinal quality must be assessed
  separately.
- Prefer mechanisms already used on current upstream master. A fork-only mechanism needs a concise,
  PR-quality physical rationale, focused regression coverage, and an isolated road arm.
- Minimize production code and change one mechanism per comparison. Replay establishes command shape
  only; promotion requires controlled maneuvers and ordinary-road evidence.
- Retire or remove tuning that is redundant, irrelevant, unproven, or no longer shows an attributable
  improvement. Preserve rejected mechanisms as historical evidence, not as active behavior.
- Preserve honest command attribution. If the vehicle cannot smoothly achieve a request, prefer the
  narrowest upstream-style limit before `carControl` over hiding the mismatch in Honda CAN shaping.

## What this branch is

`ody-op` is the recovery baseline and shared tooling/evidence branch for Honda Bosch command following on
`HONDA_ODYSSEY_5G_MMR`. Experimental children inherit their validator, private-log tools, evidence,
and standards from here; mechanism-specific controller code and rail assertions are tested on
temporary child branches and promoted here only after the evidence supports them. Keep parent and
nested opendbc branches paired.

`ody-op-test` is a frozen failed experiment. Do not add commits to it or treat its coast interlock,
raw `-0.40` entry, zero brake integral, onset shaper, or direct brake release as accepted knowledge.
The former `ody-op-test2` final candidate is now the `ody-op` baseline: it changes only Odyssey
command-domain selection around the raw `ACCEL_COMMAND` (road-speed brake/coast separation,
low-speed stop authority, and an OEM-aligned active-gas hold). It does not restore the retired brake
PID, compensated input, coast interlock, raw-split reference, or onset shaping. New model or radar
experiments must start from a temporary child of `ody-op` and be deleted or promoted deliberately.

The former `ody-op-radar` arm is closed after its first engaged route, and both implementation
branches are deleted. It changed radar availability and published a camera-side object/fusion bank;
it did not change the retained Honda longitudinal CAN translation. On route
`00000043--a13083ebb4`, radar-marked lead selection and the planner command changed abruptly while
physical brake-domain cycling and driver-felt gas/brake behavior worsened. Do not compensate for
this perception/planner regression with gas or brake tuning. Preserve its route/source findings as
historical evidence and use the vision-only `ody-op` baseline for future comparisons.

Lateral uses the stock 2560 LKA command map with `latAccelFactor 0.9` and
`steerActuatorDelay 0.15`. The isolated nonlinear 3840 arm is retired after its bounded three-route
screen failed to establish an attributable improvement. Route `0000005d--ed7df97035` was mixed and
only favored the arm in a thin unmatched comparison; route `00000061--b8f07e1ca7` supplied 15.61
high-authority seconds but still had `0.245 m/s2` actual-desired RMS and three steering-fault events;
route `00000064--898a884741` was clean for 5.09 seconds at 3840 but its `+0.009 m/s2` median
under-response was effectively the same as the comparable stock-2560 readout. Clean operation is not
proof of benefit, and the custom range no longer meets the PR-minimal retention burden. The former
linear 3840 RDM map and 0.20 s delay fallback remain retired. Reopen steering authority only for a
repeatable logged lateral symptom and an isolated matched-road comparison. Passive route
`00000069--eab494ffc4` independently captured the stock camera source with no OpenPilot steering
frames: every nonzero steering request stayed within 2560, including 216 full-rate frames exactly at
the cap, while the DBC-labeled RDM/haptic state carried zero torque. This confirms the stock LKA wire
range; it does not establish a separate 3840 RDM range or prove lane-tracking quality.

`extract.py` and `validate_log.py` retain controller-side lateral command/output, saturation,
steering response, overrides, and fault diagnostics. For full-rate Odyssey stock-radar routes,
`validate_log.py` also counter-matches bus-0 `sendcan` to the physical bus-1 steering frame, so radar
forwarding or attenuation is measured separately from the stock 2560 controller cap. These
diagnostics do not by themselves prove lane tracking or closed-loop road behavior.

## Attribution boundary

Trace questionable lateral and longitudinal behavior independently in this order:

`longitudinalPlan` → `carControl.actuators.accel` → `ACCEL_COMMAND` plus
`GAS_COMMAND`/`BRAKE_REQUEST` → Honda ECU/vehicle response.

For lateral behavior, trace the upstream lateral plan/controller command → `carControl` steering
actuator output → Honda steering CAN → Honda ECU/vehicle response.

`carControl.actuators.accel` is the controller input; `longitudinalPlan.aTarget` is upstream and
`longcontrol` may legitimately override it. Numeric `ACCEL_COMMAND` fidelity is not sufficient if
the domain bits leave gas inactive. Locate the first divergence before assigning the symptom.

Use that first divergence to choose the work:

- If the model/planner command pulses or fails to stop, investigate Experimental/model/planner
  behavior; do not compensate for it in the car port.
- If the planner is smooth but `carControl` is not, investigate `longcontrol`.
- If `carControl` is correct but numeric CAN or the active gas/brake domain differs, investigate the
  Honda translation.
- If numeric CAN and its domain are correct but `aEgo` bites or lags, calibrate Honda actuator
  response without reshaping the model command.
- Apply the same boundary to lateral behavior: do not use Honda steering shaping to compensate for an
  upstream lateral-plan or controller error, and do not retune a correct command path without a
  repeatable vehicle-response symptom.

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
7. Compare the outcome OpenPilot requested, not merely whether two drives used the same road. For
   lateral, compare actual versus desired lateral acceleration in comparable speed, demand, and
   authority bins. For longitudinal, compare `aEgo` versus `carControl.actuators.accel` separately in
   gas and brake domains, conditioned on comparable speed, request, and terrain. Use controller-to-
   wire fidelity and domain bits to locate the first divergence. Exact-route A/B is preferred when
   available, but unmatched whole-route averages are not evidence.
8. Every unpromoted custom arm gets at most three independent, adequately exposed road examples of
   the same mechanism. If three fail to show an attributable improvement in OpenPilot-command
   following, retire it. Do not count multiple thresholds, metrics, or transitions from one episode
   as independent examples; a safety regression can retire an arm sooner.
9. Every candidate must have an explicit keep, change, or retire decision after checking the relevant
   lateral or longitudinal exposure. Do not retain tuning merely because it is historical or already
   present.

## Workflow

- Pull private full-rate rlogs with `.agents/pull_logs.py`; qlogs are too decimated for the
  transition metrics. Use `.agents/extract.py` for repeat exploratory analysis.
- Run every drive through `.agents/validate_log.py`, which writes one row per route to
  `.agents/log-validation-ledger.jsonl` (authoritative) and `.md` (human view).
- Use `.agents/inspect_following.py` plus cached upstream signals to locate the first divergence.
- Review lateral and longitudinal behavior as separate evidence streams; a result on one axis does
  not authorize a change on the other.
- Car-port edits follow `.claude/skills/comma-standards/SKILL.md`. Keep production comments PR-lean:
  explain the invariant or reason; keep route numbers, dates, and experiment history in evidence.
- `carOutput.actuatorsOutput` must describe actuator output, not internal learner state. The
  historical deployed child used its `gas`/`brake` fields for learned-factor telemetry; the
  upstream-rooted port restores actuator semantics. Any future learner telemetry must be
  reconstructed offline or moved to an explicitly named diagnostic event accepted by the
  corresponding schema owner.
- **Never sync opendbc to its own master.** Rebase it to the commit openpilot master pins, or
  `controlsd` crashes on-road from a `car.capnp` schema mismatch.
- `lefthook run pre-commit` covers focused lint and pure metric tests. `.agents/preflash.py` adds
  Odyssey interface and panda-safety coverage; neither substitutes for a road drive.

## Active road question

The two-state release-width work is closed without promotion. Entry `-0.30`, width `0.50` reduced
descent transitions but held braking through positive requests; width `0.20` released sooner but
returned driver-felt tapping on split routes `00000027`/`00000028` (12 physical descent edges over
0.734 min, 16.4/min). Do not continue that two-state width/threshold architecture.

The first `ody-op-test` architecture failed its road screen on route
`00000029--4c9b612e7c`: it produced 24 direct gas-to-brake and 23 direct brake-to-gas handoffs in
9.7 engaged minutes, including the driver-reported pulsing. Useful compensated gas was allowed to
reactivate immediately above brake entry, so the coast state did not separate those transitions.

The completed direct-release arm disproved two later claims. Routes `0000003f--cf7b94c588` and
`00000040--ff2868cffe` had zero direct gas-to-brake handoffs yet still measured 33.1 and 13.1
downhill brake edges/min. Their typical downhill applications lasted about 1.0-1.1 s; the wire
reached 80% command depth in 0.19-0.20 s and the standardized achieved-accel metric reached 80%
in 0.64-0.66 s. Stock-radar route `0000003b--08f77bc5c3` measured 3.0 downhill edges/min; its two
downhill applications had a median duration of 10.86 s and median achieved-accel 80% time of
8.08 s. The gap is both episode frequency and onset shape. A one-command coast interlock is not
a pulse-braking fix, and the `ody-op-test` stack is closed without promotion.

The fresh raw-split `ody-op-test2` reference failed on both first drives. Route
`00000042--990be22fe1` measured 167 physical brake edges (30.3/min overall, peak 28/10 s,
119.4/min downhill); route `00000041--91a6b6745b` measured 69 (11.2/min, peak 26/10 s,
121.0/min downhill). Around 39 mph the raw request crossed `-0.20` repeatedly and Honda's
`COMPUTER_BRAKING` followed every `BRAKE_REQUEST`. During the route-42 lead stop, the request
relaxed from `-0.21` to `-0.18` below 2 mph, the raw split selected gas, speed rose, and the driver
took over. The planner also withheld `shouldStop` until near zero; a car-port domain change cannot
repair that upstream stop decision.

The three-domain arm keeps `ACCEL_COMMAND` as the clipped raw request and uses state only to choose
Honda's binary command domains. At road speed, brake remains selected while the request is negative
and a positive request releases it immediately. An active gas command remains live down to Honda's
upstream `-0.20` split, but after coast it re-enters only for a positive request. Below 5 m/s,
non-positive requests select brake and any positive start request selects gas immediately.

The retained `-0.50` entry passed an earlier ordinary-road screen without the raw-split burst
pattern, but route `00000044--1f70122a52` now rejects its late physical onset. It withheld the brake
domain for 10.05 s and 2.45 s beyond a `-0.30` entry during the two reported lead approaches, then
activated Honda at about `-0.50 m/s2`. The same mechanism delayed the six reported downhill entries
by 0.44-2.85 s versus `-0.30`; achieved acceleration changed from positive to as low as
`-1.26 m/s2` in the following second. The current isolated arm therefore changes only road-speed
entry back to `-0.30`. Frozen-input analysis predicts 40 route-wide physical edges versus 28 at
`-0.50`, while the reported downhill burst peak remains 6/10 s, so this is a road-unproven tradeoff,
not a comfort fix. Reject it for renewed tapping, excess braking, or incomplete stops.

The retained custom longitudinal behavior outside brake authority is the road-supported Odyssey
gasfactor calibration. The unproven 60-count handoff ramp is retired: eligible gas now receives the
calculated command immediately. Gas and brake remain mutually exclusive, disengagement emits no
longitudinal command, Panda bounds command magnitude, and positive stop-release requests select gas
immediately. The new route-43 gas arm leaves that gasfactor calibration and the three-domain brake
candidate unchanged, but removes unverified wind/grade feedforward from the actual `GAS_COMMAND`.
The unidentifiable production windfactor learner is retired as dead state: it was not published as
telemetry and could not choose a domain or affect either wire command. The read-only offline shadow
remains available for future drag identification. The latest full non-Experimental route still had
13 sub-second gas episodes beginning at tiny positive cruise requests before crossing the `-0.20`
release boundary. That is a separate gas-domain re-entry arm; the current brake arm does not
claim to resolve it. This is a command-path isolation experiment, not a road-proven comfort
improvement.

The first post-`b472c9afe` ordinary-road uploads were thin: route `00000052--5550e053e9` had 5.7
engaged minutes and route `00000053--360703793d` had 5.5; route `00000051--f714a28f5f` was
offroad-only. Both driving routes carried `carControl` to CAN correctly and had no direct gas-to-
brake handoff. Route 53 still contains one true sub-second coast-to-gas pulse at a tiny positive
request; route 52 contains no sub-second in-control pulse under the corrected diagnostic, though it
has shorter gas intervals. A frozen `+0.02 m/s²` re-entry threshold screens those tiny entries but
does not remove route 53's strong-request transient, so no production gas deadband is promoted from
these routes alone. Treat route 52's short downhill brake window and both routes' stop-lurch readings
as thin context, not a brake retune authorization.

The isolated `+0.02 m/s²` Odyssey road-speed gas re-entry arm is retired after its bounded road
screen. Exact-arm routes `00000030--d288c988eb`, `00000031--781e1d39f2`, and
`00000032--3526ec7811` supplied 20/14/10 coast re-entries and independently exposed 13/8/9 intervals
where the gate withheld a positive OpenPilot request. Gas-domain jerk was mixed at
`0.291/0.349/0.262 m/s3` versus `0.299/0.349` on the two pre-arm routes, and the arm still produced
2/1/1 short re-entries. Across those routes plus `61`-`64`, the gate withheld 67 intervals for
10.29 s; 55 entered gas within 0.25 s anyway. Eliminating the tiny-request classification by
forbidding those entries is not an attributable ride or tracking improvement. Fresh positive
road-speed requests therefore select gas again. Active-gas continuity to `-0.20`, the `-0.30` brake
entry, low-speed domains, raw `ACCEL_COMMAND`, and gasfactor are unchanged.

The failed raw-split reference and direct-handoff architectures remain historical evidence only.
The promoted command-domain candidate has current ordinary-road screening, but it does not claim to
fix Experimental model behavior or provide radar tracks. Full-rate master
route `00000024--5c888c605c` measured 108.2 downhill edges/min and peak 25/10 s, versus 1.9/min and
peak 3/10 s on `ody-op` route `00000026--bfe3fd933b`. The current upstream-pinned Honda path still
uses the same raw request and fixed -0.20 split, so that comparison remains behaviorally relevant.

The supplemental low-speed brake PID is retired. Corrected exact-source metrics proved that the old
zero-exposure ledger values were caused by an impossible above-3/below-3 m/s mask; exposed routes
showed small real command additions but no matched road A/B establishing benefit. Their measured
stop lurches were predominantly downstream of `ACCEL_COMMAND`, and Honda Bosch already closes its
own acceleration loop. Keep low-speed non-positive requests in the brake domain, but send the raw
clipped `carControl.actuators.accel` command. Reopen command shaping only for a repeatable first
divergence at the wire and an isolated controlled-road result.

Keep the 8 m/s gasfactor seed at `0.54` until the corrected narrow-window, exposure-qualified,
per-`opendbc_commit` report accumulates enough evidence. Legacy broad-bin suggestions are invalid.

The former production windfactor learner was not independently identified from gasfactor and grade,
never affected commands after wind/grade feedforward was removed, and is now retired. Do not restore
it merely as diagnostic state. Any future drag replacement must first remain offline and must freeze
or partition gasfactor during identification because both estimates otherwise use the same tracking
error; promotion would require its own isolated road arm.

Vision-only route `00000044--1f70122a52` separates two contributors. At the 11:57:35 and 12:00:58
brake takeovers, the planner kept `shouldStop` false and selected a close lead while planner-to-
`carControl` and numeric request-to-wire RMS stayed within 0.014 m/s2 and 0.011 m/s2; that stop-
spacing decision remains upstream. However, numeric `ACCEL_COMMAND` fidelity was incomplete
actuation fidelity: the `-0.50` port threshold left both gas and brake inactive through earlier mild
negative requests. At 12:17, 12:24, and 12:25, non-Experimental `cruise` also pulsed the request
from roughly `-0.53..-0.66` to zero or positive, while the late binary brake entry and Honda's
achieved-response amplification made those pulses harder. Keep the new `-0.30` entry isolated; do
not add brake supplement or command shaping unless its road comparison still locates the first
divergence there.

Route `00000064--898a884741` resolves the reported no-lead drop from 39 to 31 mph without a Honda
change. Driver-monitoring/soft-disable `forceDecel` was false. The upstream model instead held
`allowThrottle=false`; `get_cruise_accel()` capped the no-lead `cruise` candidate at the grade-based
coast estimate, which became increasingly negative to about `-0.47 m/s2` even after speed fell below
set. `carControl` and CAN followed that request, and Honda amplified the achieved response to about
`-0.78 m/s2`. Across comparable Alpha Long routes `44`, `45`, `61`, `62`, `63`, and `64` using the
same planner source, only route `64` had a sustained no-lead, throttle-disallowed braking episode
while more than 1 mph below set. Treat this as an isolated upstream model/planner coast-limit event;
do not hide it with Honda thresholds or command shaping. Reopen the port only for a repeatable first
divergence after `carControl`.
