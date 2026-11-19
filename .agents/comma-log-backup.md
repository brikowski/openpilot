# Optional comma-to-Proton rlog backup

This private tool uploads completed `rlog.zst` files directly from the comma to the existing
`Documents/openpilot/rlogs` folder in the owner's Proton account. Any Wi-Fi connection can be
used while parked or driving, including a phone hotspot. Hotspots use the phone's data.
The Mac does not participate in uploads. It still needs Proton synchronization to download files
for local analysis, and each newly available route still needs `validate_log.py` validation.

Installation of the fork does not install or start this service. The service, client, explicit
enable flag, destination, encrypted account session, encryption key and receipts live under
`/data/proton-log-backup`, outside the checkout. The public publisher excludes `.agents` and
`lefthook.yml`; no uploader, credentials or automatic enablement is added to the public tree.

## Privacy and operation

- Configuration is disabled by default. Only the explicit `enable` command opts in, after
  checking that an existing destination is accessible with the saved Proton session.
- Missing, invalid or disabled configuration, or a missing session, produces no Proton calls.
  The service never initiates sign-in. An expired/revoked session cannot authorize uploads;
  failed commands leave files pending for retry without prompting or falling back to credentials.
- Every upload requires fresh valid `deviceState` and Wi-Fi, regardless of driving state. Active client
  processes are terminated when those conditions or opt-in/session availability change. This
  follows hardwared's network classification; cancellation follows its detection of a change.
  The service and its children retain low CPU and idle I/O priority while driving. Closed
  segments are reconsidered every 30 seconds; the active logger-owned segment waits until closed.
- Only closed full-rate rlogs are selected. Qlogs, video, account information and evidence ledgers
  are not uploaded. Logger locks and source changes are checked before transfer.
- The worker's command allowlist permits only upload, folder creation and node metadata reads.
  It rejects Drive file downloads, deletion and movement before starting the client. It runs no
  bidirectional synchronization. Client/account metadata caches are not downloaded rlog copies.
- Transfers read the original rlog directly. They create no log copies, hard links, preservation
  flags, upload xattrs or changes inside `realdata`. The stock space deleter and power-down
  behavior remain authoritative. Source deletion may interrupt a transfer; the worker never
  restores a removed segment or retains a private copy. Ordinary open-file lifetime applies
  while a transfer reads a file, without adding a persistent reference.
- Existing remote files are skipped, never replaced. The client handles encryption and upload
  integrity. A local receipt is written only after the remote revision's claimed SHA-1 and byte
  count match the original file. This metadata check is not an independent download/readback.
  Failed, interrupted or mismatched uploads remain pending; retries are idempotent.
- Receipts bind the destination UID and source fingerprint, and retain the source SHA-256.
  They do not periodically re-audit later cloud deletions. Cloud synchronization is not an
  independent archival backup. This tool never deletes source logs or cloud data.
- `status.json` atomically publishes version 1 aggregate progress: `state`, `completed`,
  `total`, `pending_bytes`, `last_success_at`, `error` and monotonic `updated_at`. Counts refer to completed, retained rlog files in the
  current scan; only matching receipts count as complete. Pending bytes describe unconfirmed
  local rlogs, including existing cloud files still needing verification, not remaining network
  traffic. Last-success wall time is retained across restarts and advances only after a verified
  receipt commits. Error categories distinguish timeouts, unavailable Proton access, metadata,
  content mismatch and local/receipt storage; raw client errors never reach the status file.
  No account details, destinations,
  filenames or route IDs are exposed. Long client operations refresh the heartbeat every five
  seconds, and display-status write failures never block backup. Disabled/sign-out operations
  immediately publish a hidden state.
- Sign-in uses Proton's browser flow. Only its session is saved, encrypted using Proton's
  supported `pass` backend. The unattended GPG key stays on this device in a private directory;
  encryption does not protect against someone who controls the device/account.

The Mac intake command is `.venv/bin/python .agents/pull_logs.py --all-new`
(`--list` enforces retention/capacity before previewing; it is not a read-only cleanup preview).
It checks Proton first, validates the available snapshot and makes no device connection by default.
Newly available segments reopen previously partial ledger coverage. Its age filter uses file mtimes;
Proton arrival times can differ from drive times. Do not treat available segments as a whole drive.

If an expected drive or segment is absent, check Mac Proton synchronization first. Then use
`--route ROUTE_ID --device-fallback` (with `COMMA_SSH` configured) to inspect the uploader and retrieve
missing device data. The probe reads service/progress state, opt-in/session presence, closed/active
segments, matching historical receipts and fixed sanitized error messages. It saves a private
`evidence/log-acquisition-ledger.jsonl` entry before transfer, even if diagnosis is unavailable. It
never signs in, modifies uploader configuration or starts a cloud transfer. A receipt proves a past
upload verification and can also belong to an older destination; it does not prove current cloud
presence. Distinguish incomplete uploads from Mac sync lag, changed destinations or later deletions;
record unknown causes as unknown. `--list` never connects, even with `--device-fallback`.

Fallback transfer/hash checks overlap closed-file and byte-fidelity coverage; this service adds
device-side opt-in, login, live network gates, remote conflict handling and receipts. Neither changes
a lateral/longitudinal command path or provides road-performance evidence.

The main UI passively reads this optional file at most once per second while visible, offroad
or in confirmed stationary Park. It shows checking, progress, completion, Wi-Fi wait, sign-in,
retry and unavailable states; stale status cannot claim completion. It hides while driving,
under the screensaver/settings/dialogs, and for devices without the optional uploader. This
indicator registers no alert, input, navigation or display-wake events. Upload start, progress
and completion do not reset the ten-second screensaver or sixty-second display deadline.

## Client and dependencies

The official Proton CLI 0.9.0 ARM64 binary fails on the comma in Sentry's `os.cpus()` call before
sign-in. Build the unmodified CLI source without the optional `SENTRY_DSN` build variable:

- Source: `ProtonDriveApps/sdk`, tag `cli/v0.9.0`, commit
  `df3a717bb8123791abf115a1dd171cb66813e9f4`.
- Bun: `1.4.2`, with the CLI's frozen lockfile.
- In `cli`, run `bun install --frozen-lockfile`. Make the CLI's dependencies available to
  sibling source packages with `client/js/node_modules -> ../../cli/node_modules` and
  `incubating/account/js/node_modules -> ../../../cli/node_modules`.
- From `cli`, build with `CLI_APP_VERSION_NAME=external-drive-odyssey CLI_VERSION=0.9.0
  JS_VERSION=source-df3a717b bun run build bun-linux-arm64`. Keep `SENTRY_DSN` unset. This uses
  Proton's external application identity and omits optional error/operational reporting.
- Copy `cli/release/linux-arm64/proton-drive` to `/data/proton-log-backup/bin/proton-drive`.
  Compare its SHA-256 before and after transfer, make it executable, and check `version` and
  `filesystem upload --help` on the device. No binary is committed.

The comma has the GnuPG runtime libraries but lacks `gpg`, `gpg-agent`, `gpgconf` and `pass`.
Download those ARM64/all packages using Ubuntu Noble's signed apt indexes with apt's lists/cache
redirected into `/data/proton-log-backup/apt`, and extract them with `dpkg-deb --extract` into
`/data/proton-log-backup/gnupg-runtime`. Do not install packages into or remount the AGNOS root.
The installer supplies the explicit `gpg-agent` path and initializes a private password store.

## Install and operate

With the device confirmed offroad, copy the reviewed `comma_log_backup.py`,
`proton-log-backup.service` and `install_comma_log_backup.sh` into `/data/proton-log-backup`,
then run `bash /data/proton-log-backup/install_comma_log_backup.sh` as `comma`.
The installer uses the current checkout interpreter (native fallback when absent), checks fresh
offroad state, verifies an encryption round trip, starts a disabled
service, and preserves the existing `/data/continue.sh` hook while adding runtime service
link/start commands. The separate `/data` files survive OpenPilot updates; verify again after
an AGNOS replacement or factory reset. The installer does not switch branches or reboot.

Run these commands on the comma:

```sh
cd /data/proton-log-backup
./run_backup.sh status
./run_backup.sh login
# Open the printed Proton URL on your own browser. No password goes through chat.
# Successful login still leaves uploads disabled. Explicitly opt in:
./run_backup.sh enable
sudo journalctl -u proton-log-backup.service -n 20 --no-pager
```

The default destination must already exist. An alternative can be supplied with
`enable --destination /my-files/your-folder`. Opt out immediately with
`./run_backup.sh disable`; `logout` disables and removes the
saved session. To stop the worker as well, use `sudo systemctl stop proton-log-backup.service`.
The next boot may restart the disabled worker, which makes no cloud calls. To remove its
startup registration, remove only the marked optional Proton block in `/data/continue.sh`.

## Validation and decision

Focused tests cover disabled/signed-out/expired states, closed-file selection, live Wi-Fi while
parked or driving, cancellation, remote mismatches, retry after an interrupted acknowledgment,
destination-specific receipts, rejected download/delete commands and source deletion during
transfer. Deliberate mutations removing opt-out, login, cellular exclusion, digest rejection,
download rejection or source-deletion freedom must each fail the relevant test. These are separate checks
from car-port/preflash coverage; no vehicle runtime source or nested gitlink changes.

Keep as opt-in diagnostic tooling. Activation requires a real owner sign-in and explicit
enablement. A successful live upload and independent Proton download/hash comparison on an
analysis computer are required before claiming end-to-end backup operation; the comma must
not download Drive file payloads for verification. Software tests alone do not establish it.

## Agent handoff

When available, read `evidence/proton-uploader-handoff.md` through `private_paths.evidence_root()`
for the owner's installed revision pair, archive move receipt, live observations and pending checks.
Without that private handoff, use this runbook and live device evidence; do not infer opt-in or credentials.
Keep changing counts, account/machine details, verification filenames and route evidence in
Proton, not this repository. These are snapshots, not a continuously refreshed health monitor.
The owner chose Proton as the sole logs/evidence archive. Do not recreate `.private/rlogs`,
`.private/evidence`, a second working copy or a symlink to the archive. The ignored `.private/`
directory retains operational migration receipts only. Historical sealed evidence remains
byte-identical; relocate old path prefixes instead of editing historical manifests.

The archive move and any owner-approved removal before server synchronization are recorded
privately; they do not grant permission to repeat that exception for another move. Do not infer that
filesystem verification means server synchronization is complete, and do not reset/uninstall
Proton or clear its File Provider storage while it contains the only not-yet-uploaded copy.
For a future move, retain originals until sync finishes unless the owner explicitly authorizes
removing verified copies earlier with that limitation understood.

Start with read-only checks on the comma:

```sh
cd /data/proton-log-backup
./run_backup.sh status
cat status.json
sudo systemctl show proton-log-backup.service -p ActiveState -p SubState -p NRestarts -p MemoryCurrent
sudo journalctl -u proton-log-backup.service -n 20 --no-pager -o cat
```

`status` reports opt-in and saved-session presence; it does not prove the session is still valid.
Compare `status.json.updated_at` with `time.monotonic()` **on the device**, not the Mac.
The UI rejects status older than 90 seconds. `last_success_at` is wall time; queue counters
cover the current retained closed-log snapshot. They can shrink when stock cleanup removes
logs. Matching receipts prove past cloud metadata verification, not present cloud existence,
whole-drive coverage, Mac synchronization or independent payload readback.

Check the exact parent, gitlink and nested checkout separately from service health:

```sh
cd /data/openpilot
git rev-parse HEAD HEAD:opendbc_repo
git -C opendbc_repo rev-parse HEAD
git status --short
```

The standalone service, worker, generated `run_backup.sh`, client, session and receipts live
outside the checkout. A Git update alone does not replace them. For a reviewed worker update,
stop only `proton-log-backup.service`, transfer a `.next` file, compare SHA-256, atomically
replace the worker and restart that service. Preserve config, credentials, receipts and the
marked startup block. Initial installation and main checkout deployment require the fresh
offroad guard; use `tools/deploy_ody_op.sh deploy` for tracked UI changes rather than copying
tracked UI files onto the device. Documentation-only commits need no device rebuild/reboot.
Do not log out, regenerate keys, rerun login or remove the installation to diagnose a queue wait.

Missing cloud folders can be Mac restore lag: verify the signed-in account and existing parent
before creating the exact missing destination. Do not create a second archive or move/overwrite
cloud data to bypass that check. Diagnose Mac File Provider startup/sync separately from the
comma worker; an active Mac process alone does not prove its provider is syncing.

Keep these invariants when changing the feature:

- Wi-Fi is required while parked **or driving**; do not restore a `started == false` gate.
- Missing opt-in/session means no background cloud calls; expired access cannot authorize uploads.
- The comma uploads only: metadata reads, folder creation and upload are allowed; payload downloads,
  cloud deletion/movement and bidirectional synchronization remain forbidden.
- Stock source deletion and power-down win. Do not add copies, hard links, xattrs or preservation flags.
- The passive UI uses the shared `get_alert`, hides while driving and under other navigation layers,
  and must not touch display-wake, interaction, screensaver, navigation or power deadlines.
- Archive cleanup belongs to the analysis host; the uploader continues past the analysis budget.

Re-run focused worker/UI/intake/retention checks for relevant changes. Deliberately break opt-in,
session/Wi-Fi, command allowlist, digest, source deletion, driving visibility, timer isolation,
combined-cap accounting, transfer reservation and archive discovery to see the checks fail.
Integration tests exercise a real child process against a simulated cloud; do not label that a
live account test. Independent server readback must occur on an analysis host, never the comma.
Use the private pending verification marker and expected digest if it has not yet arrived on the
Mac; do not claim that check passed simply because a pre-existing cached rlog has matching bytes.

## Archive budget and retention

The analysis storage budget is **50 GB (50,000,000,000 bytes)** across `rlogs/` and `evidence/`,
including partial transfers, ledgers and caches. The Mac intake takes an archive lock, cleans eligible
whole routes at every log check and reserves headroom before explicit SSH transfers. File Provider
metadata checks do not hydrate payloads. Analysis reads Proton directly, without a second archive.

The comma uploads closed rlogs on fresh Wi-Fi without checking aggregate archive size. Cloud uploads
and synchronization can temporarily grow the archive beyond the analysis budget. Retention runs when
analyzing logs; the uploader never deletes files or purges Trash. It still verifies remote content and
keeps destination-bound receipts so confirmed files are skipped on later passes.

Cleanup preserves evidence, active baselines, unresolved faults, unvalidated/partial routes and linked
files. A contiguous route is eligible only after validation confirms both route sentinels and checks
for reported steering faults, even with steering disengaged. Revalidate a reviewed older route with
`validate_log.py` before retiring it if its ledger row lacks those checks.
Explicit SSH transfers that cannot fit still wait for safe cleanup. Preview with `archive_retention.py --preview`; `--apply`
rechecks the plan. Removal from the mirror propagates to Proton and other Macs. Private policies,
plans and receipts stay outside Git.

The restored UI uses the current shared `get_alert` function. Focused integration checks run the
worker through a real child process with an isolated simulated cloud, verify persisted receipts,
stock-source deletion and opt-out, continued uploads beyond the analysis budget, and fault rejection. These
checks do not establish a live account session or device health: after installation, require a
real upload and independent verification on the analysis host before claiming end-to-end operation.
