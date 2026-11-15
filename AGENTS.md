# Odyssey development guidance

This file holds durable project boundaries. Read linked guides when relevant to the task;
keep route history, changing measurements and experiment decisions in Proton's private evidence archive.

## Objective and judgment

Make the Odyssey's actual lateral and longitudinal response follow `carControl` accurately and
smoothly in Standard and factory ECON modes, within Honda hardware limits.

Locate the first reproducible command-to-response error and fix it in the responsible layer,
including OpenPilot or `opendbc`. Do not mask upstream faults with Honda-specific compensation.

Treat ECON as native behavior. Share calibration unless measured response requires otherwise,
and keep ECON-specific adaptation out of Standard.

Choose the simplest reliable solution. Reuse, simplify, or remove existing logic before adding
complexity. Use live state, learning, or fixed values according to what is simplest and supported
by evidence. Follow upstream architecture and keep vehicle-specific logic narrow. Write production
changes as if they could be upstreamed, minimizing differences from current `commaai/openpilot`
and its pinned `commaai/opendbc`.

Use engineering judgment to resolve routine ambiguities, define acceptance criteria and choose
proportionate validation within the authorization, safety and privacy boundaries below.
Revisit earlier decisions when new evidence warrants; historical keep/change/retire labels and
experiment branches are evidence receipts, not permanent design restrictions.

Before extensive analysis, identify the question and the decision its answer could change.
Reuse verified results when inputs and relevant behavior are unchanged. Stop an analysis when it
answers that question; more logs, artifacts or passing checks do not themselves establish progress.
Keep documentation and tooling useful and proportional to the decision.

Missing logs, an unavailable device or an unmeasured installed candidate can block a particular
road-performance claim. Continue independent analysis, justified implementation and software
validation. When no justified action remains, explain the blocker and what would unlock progress;
do not repeatedly poll unchanged state without a reason to expect new information.

## Find the responsible layer

Apply attribution independently to lateral and longitudinal behavior:

| First reproducible divergence | Owner |
| --- | --- |
| Wrong intended motion | OpenPilot model or planner |
| Sound plan, wrong `carControl` | OpenPilot controller, state machine, timing or publication |
| Correct `carControl`, wrong numeric CAN or command domain | Honda translation, DBC or safety boundary |
| Correct commands and domains, wrong vehicle response | Honda ECU or actuator response |

For longitudinal work, trace `longitudinalPlan` → `carControl.actuators.accel` →
`ACCEL_COMMAND` plus `GAS_COMMAND`/`BRAKE_REQUEST` → vehicle response. `longcontrol` may
legitimately override `longitudinalPlan.aTarget`. Trace the analogous lateral command path.
Fix upstream errors at their owner; preserve intended motion when calibrating actuators.

Correct failure to achieve the requested low-speed acceleration, rather than adding a car-port
stop-until-zero latch or retaining braking after the upstream request releases. Judge stopped
brake holding separately from moving acceleration tracking.

For car-port or safety changes, use [car-port standards](.agents/car-port-standards.md).
Resolve signal meaning and rails from the exact pinned DBC/safety source, not matching names on
another fork. `GAS_COMMAND` and engine effort reports have no qualified physical torque units.
`carOutput.actuatorsOutput` describes emitted actuators, never internal learner telemetry.

## Evidence and validation

- Resolve exact parent and nested `opendbc` revisions for evidence used in a behavior claim.
  Pool different revisions only after a source diff establishes compatibility of the relevant paths;
  matching child hashes alone do not establish parent compatibility. Use pinned upstream as the baseline.
- Reconstruct the relevant controller and zero-order-held CAN history for translation, timing or
  state hypotheses. Preserve enough continuous history for the mechanism being tested. Reuse
  qualified captures and existing diagnostics rather than rebuilding unrelated analyses.
- Separate command fidelity from physical response. Replay on frozen inputs proves command shape,
  not an alternative closed-loop trajectory, ride quality or ECU acceptance. Qlogs are too
  decimated for transition measurements. Passing software checks do not prove road benefit.
- Compare actual and requested motion under comparable speed, demand, terrain, drivetrain, mode,
  authority and driver state. Separate gas/brake domains and lateral/longitudinal conclusions.
  Use suitable timing and uncertainty checks. Source-compatible matched intervals or pooled events
  can suffice; exact-route A/B and fixed route counts are not mandatory.
- Reuse existing checks. Verify new behavioral or metric checks reject the defect they are meant
  to detect, using a known regression or deliberate fault. Check selection against known exposure;
  report empty or inapplicable cohorts explicitly. A threshold flag starts investigation, not tuning.
- For each candidate, record its hypothesis, source pair, relevant validation and keep/change/retire
  decision. Keep software-validated candidates, measured improvements and unresolved questions
  distinct. Do not retain a mechanism merely because it is already present.
- Gas, braking and their transitions may change together as a coherent design. Validate affected
  domains and interactions, using component tests or offline ablations where useful. Separate
  road deployments for each component are not required.

Choose checks for the changed layer. Documentation generally needs review, link checks and
`git diff --check`; diagnostic code needs focused tests and meaningful fault rejection; actuation
changes additionally need source-matched replay, interface/rail/safety checks and supervised road
assessment. `lefthook run pre-commit` provides focused local checks; `.agents/preflash.py` adds
Odyssey interface and Panda coverage. Follow the car-port guide for safety-suite/MISRA obligations.
Broaden testing when a failure, new change or unresolved concern warrants it.

## Branches, commits and publication

- Work directly on `ody-op-test` in both repositories, including tests and development tooling.
  Target development PRs there. `ody-op` is the clean public install/default branch. Create no
  additional branches or worktrees. `master` is inactive history; use `upstream/master` for deliberate syncs.
- Keep commits focused: separate production behavior, tooling, evidence/docs and unrelated user work.
  Commit at a useful validated boundary, not merely because the tree is dirty. Do not squash or
  amend history unless requested; use `git revert` to retire committed candidates and keep the
  prior road-known-good parent/child pair reachable.
- Publish nested development source before its parent gitlink. Verify exact root/child SHAs,
  remote refs and clean state. **Never sync `opendbc` to its own master**: merge only OpenPilot's
  exact upstream pin, or a `car.capnp` mismatch can crash `controlsd` on-road.
- Sunday at 12:01 AM America/Chicago, Actions checks and publishes the exact tested `ody-op-test`
  revision to `ody-op`. Monday at 12:01 AM, a separate job merges official OpenPilot master and
  its exact `opendbc` pin into development, checks it, then publishes child before parent.
  Syncs use merge commits; conflicts or concurrent development stop publication. Sunday does not
  sync upstream, and neither job deploys to the device.
- Keep inherited workflows disabled and retain reviewed fork definitions during sync. Checks run
  manually or through the weekly jobs, not on pushes/PRs. Reviewed scheduler source lives on both
  branches; default-branch schedulers dispatch the jobs. Nested sync uses its repository deploy key.
- Push development only to `ody-op-test`. **Never manually push `ody-op` or run
  `.agents/publish_public.py --publish` here.** Preview with `.venv/bin/python .agents/publish_public.py`.
  Publication must preserve identical vehicle source, tests and submodule pins while excluding
  private data and agent/analysis/editor/deployment tooling, refreshing reviewed schedulers and
  retaining independent public CI configuration. Publication is not road-validated promotion.

Commit justified, software-validated candidates and tests for supervised testing before road
benefit is established. Promotion requires attributable physical improvement or a required safety
fix, adequate comparable exposure and no unacceptable regression. Do not require road proof before
a candidate can be implemented and tested, or let an independent unmeasured trial stop other work.

## Private data and uploads

- The sole archive is Proton Drive's `Documents/openpilot/{rlogs,evidence}`. For analysis, read its
  `README.md`. Tools discover the active `ProtonDrive-*-folder/Documents/openpilot` under
  `~/Library/CloudStorage`; `OPENPILOT_PRIVATE_ROOT`, `LOG_ROOT` and `ODYSSEY_EVIDENCE_ROOT` override
  discovery. Keep account names and absolute mounts machine-local. Never commit private data.
  `.private/` holds ignored operational migration receipts only: no second archive or symlink.
- Check Proton before connecting to the comma. `.agents/pull_logs.py --all-new` validates available
  files without SSH; `--list` applies retention and previews availability. Before explicit
  `--device-fallback`, check Mac sync and uploader health. Fallback records sanitized acquisition
  diagnostics and copies only closed rlogs, resumably and with source SHA-256 verification.
  Low-priority SSH fallback is allowed while driving, over cellular or a hotspot.
- Enforce **50 GB (50,000,000,000 bytes) combined** across rlogs, partials, evidence and analysis
  caches. Use the retention policy and archive lock to reserve headroom. Remove only eligible
  whole log routes; never evidence or protected, unvalidated, unresolved-fault, linked or partial
  routes. Refuse a transfer that cannot fit. Mirror deletion propagates to Proton and other computers.
- Validate each new or extended drive with `.agents/validate_log.py`; its private ledger is
  authoritative. Newly arriving segments reopen coverage. Keep prefixes/suffixes explicitly partial.
  Upload receipts establish past verification, not current cloud presence or whole-drive coverage.
- The optional uploader requires owner sign-in and explicit enablement. Installing the fork does
  not enable it. It uploads closed rlogs on fresh Wi-Fi while parked or driving. Credentials,
  configuration and the standalone worker stay outside the checkout. It never downloads Drive
  payloads, deletes cloud data, retains source logs or changes stock log deletion, display,
  screensaver or power-down behavior. Updating checkout source does not update the worker.
- Before uploader, sync or migration work, read the [runbook/handoff](.agents/comma-log-backup.md#agent-handoff)
  and private `evidence/proton-uploader-handoff.md`. Read the device before claiming current health;
  counts and installed revisions in receipts are snapshots. Preserve owner opt-in and the only
  unsynchronized copy; an approved past migration exception does not authorize another one.
- Before uploading, the worker checks parent-archive size metadata, including evidence, against
  the same cap. Proton counts trashed descendants, so this can pause conservatively early. The
  worker never purges Trash; do not bypass the cap. Reconcile concurrent writers through intake checks.

Use `.agents/inspect_following.py`, `.agents/inspect_response.py` and `.agents/extract.py` as
appropriate. Keep route numbers, measurements and experiment history in Proton evidence; production
comments should explain the invariant or reason. Never rewrite sealed historical receipts during a move.

## Vehicle and deployment boundaries

Current trials target `HONDA_ODYSSEY_5G_MMR`. Keep Alpha Long enabled unless the owner changes it.
On this Bosch Odyssey, `openpilotLongitudinalControl` disables the radar ECU through UDS communication control and
tester-present keeps it disabled. Honda CMBS, including stock AEB and FCW, is unavailable.
Panda AEB-forwarding flags or rejection of OpenPilot AEB bits do not restore it.

The current steering trial uses `[0, 3840]`, `latAccelFactor 1.35`, `friction 0.2 / 1.5`,
`steerActuatorDelay 0.15` and the ordinary `7680` counts/s limiter in both stock ACC and Alpha Long.
These are a supervised configuration, not a proven physical optimum. Factory 3840 requests occur with idle reported
braking; do not gate this range on braking. Preserve stock physical learner coordinates/buckets,
active output normalization (zero when inactive) and cache compatibility; never restore an
incompatible or unassociated torque-configuration/steering-route cache. Details live in the car-port guide.

In stock-radar routes, compare bus-0 TX with physical bus-1 steering; the radar can hold payloads
while advancing its counter. Alpha Long sends steering directly on bus 1: compare TX with
same-cycle `carOutput`. Neither comparison proves EPS acceptance or extra-count tracking benefit.

After source, focused/fault-rejection, preflash and provenance checks pass, use the guarded
deployment path for an authorized supervised test. Verify fresh offroad state before switching or
restarting the device. An offline or onroad device defers installation, not independent development.
Verify installed root/child SHAs separately from process health and road behavior; a pushed commit
or queued updater download is not installation. Keep rollback pairs reachable throughout.

The current exposure, decisions and exact rollback pair belong in Proton evidence, not this file.
