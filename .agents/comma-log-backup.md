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
  `total` and monotonic `updated_at`. Counts refer to completed, retained rlog files in the
  current scan; only matching receipts count as complete. No account details, destinations,
  filenames or route IDs are exposed. Long client operations refresh the heartbeat every five
  seconds, and display-status write failures never block backup. Disabled/sign-out operations
  immediately publish a hidden state.
- Sign-in uses Proton's browser flow. Only its session is saved, encrypted using Proton's
  supported `pass` backend. The unattended GPG key stays on this device in a private directory;
  encryption does not protect against someone who controls the device/account.

The Mac intake command is `.venv/bin/python .agents/pull_logs.py --all-new` (`--list` previews).
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
The installer checks fresh offroad state, verifies an encryption round trip, starts a disabled
service, and preserves the existing `/data/continue.sh` hook while adding runtime service
link/start commands. The separate `/data` files survive OpenPilot updates; verify again after
an AGNOS replacement or factory reset. The installer does not switch branches or reboot.

Run these commands on the comma:

```sh
cd /data/proton-log-backup
/usr/local/venv/bin/python3 comma_log_backup.py status
/usr/local/venv/bin/python3 comma_log_backup.py login
# Open the printed Proton URL on your own browser. No password goes through chat.
# Successful login still leaves uploads disabled. Explicitly opt in:
/usr/local/venv/bin/python3 comma_log_backup.py enable
sudo journalctl -u proton-log-backup.service -n 20 --no-pager
```

The default destination must already exist. An alternative can be supplied with
`enable --destination /my-files/your-folder`. Opt out immediately with
`/usr/local/venv/bin/python3 comma_log_backup.py disable`; `logout` disables and removes the
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
