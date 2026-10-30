#!/usr/bin/env python3
"""Validate private full-rate rlogs from Proton first; use SSH only for explicit fallback.

Usage modes:
    .venv/bin/python .agents/pull_logs.py --route ROUTE_ID ["note"]
    .venv/bin/python .agents/pull_logs.py --since-hours 48 ["note"]     # everything new
    .venv/bin/python .agents/pull_logs.py --all-new ["note"]             # every available route not in ledger

The default reads the Proton-synchronized archive without connecting to the car.
If an expected drive or segment is unavailable, check Mac synchronization, then add
--device-fallback to inspect the uploader and retrieve missing device logs. A missing
local file alone does not prove that it is missing from the cloud. Qlogs are too
decimated for transition and jerk metrics.
Only segments without the logger-owned rlog.lock are selected. Transfers and hash checks
use that fixed snapshot; newly closed segments wait for the next pull.
Retained contiguous suffixes are usable when their transfer matches the device inventory;
validation records their available segment extent rather than implying a whole drive.

Device host comes from $COMMA_SSH or $ODYSSEY_DEVICE. Private rlogs and the
ledger are found under the active Proton Drive folder in ~/Library/CloudStorage.
"""
import argparse
import hashlib
import inspect
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from private_paths import evidence_path, evidence_root, rlog_root

AGENTS = Path(__file__).resolve().parent
REPO = AGENTS.parent
LEDGER = evidence_path("log-validation-ledger.jsonl")
DEVICE = os.environ.get("COMMA_SSH") or (f"comma@{os.environ['ODYSSEY_DEVICE']}" if os.environ.get("ODYSSEY_DEVICE") else "")
REMOTE_ROOT = "/data/media/0/realdata"
try:
  LOCAL_ROOT = rlog_root()
except FileNotFoundError:
  LOCAL_ROOT = Path.home() / ".comma/media/0/realdata"  # pure tests can import without Proton Drive
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
            "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=3",
            "-o", "LogLevel=ERROR"]
LOGID_RE = re.compile(r"[0-9a-f]{8}--[0-9a-f]+")
PULL_ATTEMPTS = 3
PULL_RETRY_DELAYS = (2, 5)
CLOSED_RLOG_FILTER = r"-execdir /bin/test ! -e ./rlog.lock \;"


def _ssh(cmd):
  if not DEVICE:
    sys.exit("Set COMMA_SSH=comma@<device-address> or ODYSSEY_DEVICE=<device-address> before pulling logs")
  return subprocess.run(["ssh", *SSH_OPTS, DEVICE, cmd], capture_output=True, text=True, timeout=120)


def remote_routes():
  """Retained route catalog, including unclosed segments that are not yet validated."""
  r = _ssh(f"find {REMOTE_ROOT} -mindepth 2 -maxdepth 2 -type f -name rlog.zst -printf '%T@ %h\\n'")
  if r.returncode != 0:
    sys.exit(f"cannot reach {DEVICE}: {r.stderr.strip() or 'ssh failed'}\n" +
             "Is the device powered and on wifi? Override with COMMA_SSH=user@ip")
  newest, retained = {}, {}
  for line in r.stdout.splitlines():
    parts = line.split()
    if len(parts) != 2:
      continue
    ts, name = float(parts[0]), Path(parts[1]).name
    m = LOGID_RE.match(name)
    if not m:
      continue
    try:
      index = int(name.rsplit("--", 1)[-1])
    except ValueError:
      continue
    rid = m.group(0)
    newest[rid] = max(newest.get(rid, 0), ts)
    retained.setdefault(rid, set()).add(index)
  routes = sorted(((rid, newest[rid], len(indices)) for rid, indices in retained.items()), key=lambda x: -x[1])
  return routes, retained


def local_routes():
  """Catalog the Proton mirror, including files that File Provider must hydrate on read."""
  newest, available, locked = {}, {}, set()
  for path in LOCAL_ROOT.glob("*/rlog.zst"):
    match = re.fullmatch(r"([0-9a-f]{8}--[0-9a-f]+)--(\d+)", path.parent.name)
    if not match or not path.is_file():
      continue
    rid, index = match[1], int(match[2])
    if (path.parent / "rlog.lock").exists():
      locked.add(rid)
      continue
    newest[rid] = max(newest.get(rid, 0), path.stat().st_mtime)
    available.setdefault(rid, set()).add(index)
  # Validation reads a route's files together; never include a locked tail via a closed prefix.
  for rid in locked:
    available.pop(rid, None)
  routes = sorted(((rid, newest[rid], len(indices)) for rid, indices in available.items()), key=lambda row: -row[1])
  return routes, available


def _uploader_snapshot(rid, root="/data/proton-log-backup"):
  """Read-only device probe, sent over stdin; return no credentials or raw client output."""
  import runpy
  import types
  import json
  import sqlite3
  import subprocess
  import time
  from pathlib import Path

  root = Path(root)
  script = root / "comma_log_backup.py"
  if not script.is_file():
    return {"installed": False}
  backup = types.SimpleNamespace(**runpy.run_path(str(script)))
  result = {"installed": True, "enabled": backup.read_config(root) is not None,
            "saved_session": backup.has_session(root)}
  service = subprocess.run(["systemctl", "is-active", "proton-log-backup.service"], capture_output=True, text=True, timeout=10)
  result["service_active"] = service.returncode == 0
  try:
    status = json.loads((root / "status.json").read_text())
    states = {"checking", "uploading", "complete", "pending", "disabled", "waiting_wifi", "sign_in", "retrying"}
    result["state"] = status.get("state") if status.get("state") in states else "unknown"
    for key in ("completed", "total"):
      if type(status.get(key)) is int:
        result[key] = status[key]
    if type(status.get("updated_at")) in (int, float):
      result["heartbeat_age_s"] = round(time.monotonic() - status["updated_at"], 1)
  except (OSError, ValueError, AttributeError):
    result["state"] = "unavailable"
  result["closed_segments"], result["open_segments"], result["receipted_segments"] = [], [], []
  receipts = None
  try:
    if (root / "receipts.sqlite").is_file():
      receipts = sqlite3.connect(f"file:{root}/receipts.sqlite?mode=ro", uri=True)
    for source in root.parent.joinpath("media/0/realdata").glob(f"{rid}--*/rlog.zst"):
      index = int(source.parent.name.rsplit("--", 1)[1])
      if (source.parent / "rlog.lock").exists():
        result["open_segments"].append(index)
        continue
      result["closed_segments"].append(index)
      # A matching receipt proves a past upload check, not current cloud presence or Mac sync.
      if receipts and receipts.execute("SELECT 1 FROM receipts WHERE segment=? AND fingerprint=?",
                                       (source.parent.name, backup.fingerprint(source))).fetchone():
        result["receipted_segments"].append(index)
  except (OSError, ValueError, sqlite3.Error):
    result["receipt_check"] = "unavailable"
  finally:
    if receipts:
      receipts.close()
  journal = subprocess.run(["journalctl", "-u", "proton-log-backup.service", "-n", "40", "--no-pager", "-o", "cat"],
                           capture_output=True, text=True, timeout=10)
  # Never save raw CLI/journal text. These are the worker's fixed, credential-free errors.
  errors = ("Proton command timed out; will retry", "Proton unavailable: check sign-in, connection and quota; will retry",
            "unrecognized Proton metadata; leaving backup unconfirmed", "remote rlog digest differs; leaving backup unconfirmed")
  result["recent_errors"] = [message for message in errors if message in journal.stdout]
  result["journal_available"] = journal.returncode == 0
  return result


def diagnose_upload(rid, local_indices):
  """Keep a private receipt before fallback, including unavailable/ambiguous diagnoses."""
  script = inspect.getsource(_uploader_snapshot) + f"\nprint(__import__('json').dumps(_uploader_snapshot({rid!r})))\n"
  try:
    result = _ssh("python3 - <<'PROTON_DIAGNOSTIC'\n" + script + "PROTON_DIAGNOSTIC")
    status = json.loads(result.stdout) if result.returncode == 0 else {"probe": "unavailable"}
  except (OSError, ValueError, subprocess.TimeoutExpired):
    status = {"probe": "unavailable"}
  row = {"date": datetime.now().astimezone().isoformat(), "route": rid,
         "proton_local_segments": sorted(local_indices), "uploader": status}
  path = evidence_root() / "log-acquisition-ledger.jsonl"
  with path.open("a") as stream:
    stream.write(json.dumps(row) + "\n")
  print(f"  uploader diagnostic: {json.dumps(status, sort_keys=True)}")
  print("  A device receipt is a past cloud verification; missing Mac files can also mean sync lag or later cloud deletion.")
  return row


def ledger_routes(retained=None):
  """Validated route ids, optionally requiring coverage of every currently retained segment."""
  if not LEDGER.exists():
    return set()
  out = set()
  for line in LEDGER.read_text().splitlines():
    if not line.strip():
      continue
    row = json.loads(line)
    m = LOGID_RE.search(row.get("route", ""))
    if m:
      rid = m.group(0)
      if retained is not None and rid in retained:
        coverage = row.get("local_segment_coverage")
        if not coverage:
          continue
        validated = set(range(coverage["first"], coverage["last"] + 1)) - set(coverage["missing_between"])
        if not retained[rid] <= validated:
          continue
      out.add(rid)
  return out


def _pull_error_log():
  return LOCAL_ROOT / ".pull_logs-errors.jsonl"


def _record_pull_error(rid, attempt, returncode, detail, completed, expected):
  row = {
    "date": datetime.now().astimezone().isoformat(),
    "route": rid,
    "attempt": attempt,
    "returncode": returncode,
    "detail": detail,
    "completed_segments": completed,
    "expected_segments": expected,
  }
  with _pull_error_log().open("a") as f:
    f.write(json.dumps(row) + "\n")


def _local_segment_indices(rid):
  """Return complete local segment numbers, excluding interrupted partial directories."""
  indices = set()
  for rlog in LOCAL_ROOT.glob(f"{rid}--*/rlog.zst"):
    if not rlog.is_file():
      continue
    try:
      indices.add(int(rlog.parent.name.rsplit("--", 1)[-1]))
    except ValueError:
      continue
  return sorted(indices)


def _local_rlog_count(rid):
  return len(_local_segment_indices(rid))


def _remote_segment_indices(rid):
  """Read currently retained rlogs, rather than assuming every route still starts at zero."""
  pattern = shlex.quote(f"{REMOTE_ROOT}/{rid}--*/rlog.zst")
  result = _ssh(f"find {REMOTE_ROOT} -mindepth 2 -maxdepth 2 -type f -path {pattern} {CLOSED_RLOG_FILTER} -printf '%h\\n'")
  if result.returncode:
    raise RuntimeError(result.stderr.strip() or "cannot read retained rlog inventory")
  names = (Path(line).name for line in result.stdout.splitlines())
  indices = sorted({int(name.rsplit("--", 1)[1]) for name in names
                    if re.fullmatch(re.escape(rid) + r"--\d+", name)})
  if not indices:
    raise RuntimeError("no closed rlogs in remote inventory")
  return indices


def _verify_rlog_hashes(rid, retained):
  """Verify retained source bytes; older local-only segments are not requalified."""
  pattern = shlex.quote(f"{REMOTE_ROOT}/{rid}--*/rlog.zst")
  result = _ssh(f"find {REMOTE_ROOT} -mindepth 2 -maxdepth 2 -type f -path {pattern} {CLOSED_RLOG_FILTER} -exec sha256sum {{}} +")
  if result.returncode:
    raise RuntimeError(result.stderr.strip() or "cannot read retained rlog checksums")
  verified = set()
  for line in result.stdout.splitlines():
    parts = line.split(maxsplit=1)
    if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
      raise RuntimeError("invalid retained rlog checksum inventory")
    source = Path(parts[1].strip())
    if source.name != "rlog.zst" or not re.fullmatch(re.escape(rid) + r"--\d+", source.parent.name):
      raise RuntimeError("unexpected file in retained rlog checksum inventory")
    index = int(source.parent.name.rsplit("--", 1)[1])
    if index not in retained:
      continue  # The route may have closed another segment after this snapshot.
    if index in verified:
      raise RuntimeError("duplicate retained rlog checksum")
    path = LOCAL_ROOT / source.parent.name / "rlog.zst"
    try:
      with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError as e:
      raise RuntimeError(f"cannot checksum local rlog {index}: {e}") from e
    if digest != parts[0]:
      return False, f"rlog checksum mismatch in segment {index}"
    verified.add(index)
  if verified != set(retained):
    raise RuntimeError("retained rlog checksum inventory changed or is incomplete")
  return True, ""


def _local_segments_contiguous(rid, expected_indices=None):
  """Reject transfer omissions and interior gaps; allow a verified retained suffix."""
  indices = _local_segment_indices(rid)
  if not indices:
    return False, "no complete rlog"
  if expected_indices is None and indices[0] != 0:
    return False, f"segment sequence starts at {indices[0]}, expected 0"
  expected = list(range(indices[0], indices[-1] + 1))
  if indices != expected:
    missing = [str(i) for i in expected if i not in set(indices)]
    preview = ",".join(missing[:8]) + (",..." if len(missing) > 8 else "")
    return False, f"non-contiguous local segments; missing {preview}"
  if expected_indices is not None:
    missing = sorted(set(expected_indices) - set(indices))
    if missing:
      return False, f"missing retained segment(s): {','.join(map(str, missing[:8]))}"
    if expected_indices and indices[-1] > max(expected_indices):
      return False, "unverified local tail extends beyond the closed source snapshot"
  return True, ""


def _select_routes(routes, done, *, since_hours=None, all_new=False):
  """Select unvalidated device routes, either by age or across the full retained inventory."""
  if all_new:
    targets = [(rid, timestamp, segments) for rid, timestamp, segments in routes if rid not in done]
    skipped = [rid for rid, _, _ in routes if rid in done]
    return targets, skipped, "retained"

  assert since_hours is not None
  cutoff = datetime.now().timestamp() - since_hours * 3600
  targets = [(rid, timestamp, segments) for rid, timestamp, segments in routes
             if timestamp >= cutoff and rid not in done]
  skipped = [rid for rid, timestamp, _ in routes if timestamp >= cutoff and rid in done]
  return targets, skipped, f"within {since_hours:g}h"


def _selection_summary(route_count, recent, scope, targets, skipped, *, redo=False, source="device"):
  """Describe selected versus already-validated routes without implying no routes were recorded."""
  selected_label = "selected" if redo else "not yet validated"
  return (f"{source} has {route_count} route(s); {recent} {scope}: "
          f"{len(targets)} {selected_label}, {len(skipped)} already validated")


def _pull_command():
  return ["rsync", "-a", "-R", "--files-from=-", "--checksum", "--partial", "--partial-dir=.rsync-partial", "--timeout=60",
          "-e", "ssh " + " ".join(SSH_OPTS),
          f"{DEVICE}:{REMOTE_ROOT}/", str(LOCAL_ROOT) + "/"]


def pull(rid, expected_segments=None):
  """Rsync one route's rlogs with bounded, resumable retries."""
  LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
  # CUSTOM TOOLING: keep interrupted rlogs outside their final path, retry the Wi-Fi/SSH stalls
  # observed on 2026-08-02, and retain the exact rsync failure for the next diagnosis.
  cmd = _pull_command()
  for attempt in range(1, PULL_ATTEMPTS + 1):
    result = None
    try:
      retained = _remote_segment_indices(rid)
      print(f"  closed source snapshot: segments {retained[0]}–{retained[-1]} ({len(retained)} files)", flush=True)
      files = "".join(f"{rid}--{index}/rlog.zst\n" for index in retained)
      result = subprocess.run(cmd, input=files, capture_output=True, text=True)
      contiguous, completeness_detail = _local_segments_contiguous(rid, expected_indices=retained)
      if result.returncode == 0 and contiguous:
        contiguous, completeness_detail = _verify_rlog_hashes(rid, retained)
    except (RuntimeError, subprocess.TimeoutExpired) as e:
      contiguous, completeness_detail = False, str(e)
    completed = _local_rlog_count(rid)
    enough = contiguous and completed > 0
    if result is not None and result.returncode == 0 and enough:
      indices = _local_segment_indices(rid)
      if indices[0] != 0:
        print(f"  partial route: retained segments {indices[0]}–{indices[-1]}; initial segments unavailable")
      if attempt > 1:
        print(f"  pull recovered on attempt {attempt}/{PULL_ATTEMPTS}")
      return True

    detail = (result.stderr.strip() or result.stdout.strip()) if result is not None else ""
    detail = detail or completeness_detail or "rsync completed without an rlog"
    returncode = result.returncode if result is not None else None
    failure = f"  pull attempt {attempt}/{PULL_ATTEMPTS} failed (rsync exit {returncode}, {completed} local segment(s)): {detail}"
    print(failure)
    _record_pull_error(rid, attempt, returncode, detail, completed, expected_segments)
    if attempt < PULL_ATTEMPTS:
      delay = PULL_RETRY_DELAYS[min(attempt - 1, len(PULL_RETRY_DELAYS) - 1)]
      print(f"  retrying in {delay}s; partial data retained")
      time.sleep(delay)

  print(f"  failure details saved to {_pull_error_log()}")
  return False


def validate(rid, desc):
  return subprocess.run([sys.executable, ".agents/validate_log.py", rid, desc],
                        cwd=REPO).returncode


def prune(hours, validated):
  """Explicitly delete local segments older than ``hours``.

  ONE HARD RULE: only prune routes that are already in the ledger. A route we have not validated
  has never had its metrics extracted, so deleting it would lose the drive outright.

  Even so, understand what this costs. The device itself only retains ~2 days (its deleter starts
  at 5GB free), so once a route ages out of BOTH places it is gone for good. Every time a new
  metric is added to validate_log, old routes have to be re-run to backfill it - that happened six
  times in the session this was written. Pruning at 48h means backfills only reach back ~2 days.
  Pruning is opt-in because historical full-rate logs are the ground truth needed whenever a new
  metric must be backfilled. Use --prune-hours only after deliberately archiving or accepting the
  loss of those routes.

  rsync -a preserves the device's mtime, so age here is when the drive happened, not when it was
  downloaded - which is what we want.
  """
  if not LOCAL_ROOT.exists():
    return
  cutoff = datetime.now().timestamp() - hours * 3600
  # Age a ROUTE by its NEWEST segment, and delete whole routes only.
  # Per-segment mtime is a trap: the device boots with an unsynced RTC, and the final segment of a
  # drive is touched during shutdown/next boot before NTP corrects it, so it carries a stale
  # 2026-06-05 timestamp. Checking each segment individually therefore saw the last minute of a
  # 20-hour-old drive as 52 days old and deleted it - which is exactly what happened to routes
  # 00000017/00000019/0000001b the first time this ran. Same unsynced-clock trap as
  # initData.wallTimeNanos (see validate_log._wall_start).
  segs_by_route = {}
  for d in sorted(LOCAL_ROOT.iterdir()):
    if not d.is_dir():
      continue
    m = LOGID_RE.match(d.name)
    if m:
      segs_by_route.setdefault(m.group(0), []).append(d)

  freed, victims, kept_unvalidated = 0, {}, set()
  for rid, dirs in segs_by_route.items():
    if max(d.stat().st_mtime for d in dirs) >= cutoff:
      continue
    if rid not in validated:
      kept_unvalidated.add(rid)
      continue
    for d in dirs:
      freed += sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
      shutil.rmtree(d)
    victims[rid] = len(dirs)
  if victims:
    print(f"\npruned {sum(victims.values())} segment(s) from {len(victims)} validated route(s) " +
          f"older than {hours:g}h, freed {freed/1e6:.0f} MB")
    for rid, n in sorted(victims.items()):
      print(f"    {rid}  {n} segs")
  if kept_unvalidated:
    print(f"  kept {len(kept_unvalidated)} old route(s) that are NOT in the ledger yet: " +
          f"{', '.join(sorted(kept_unvalidated))}")


def main():
  global LEDGER, LOCAL_ROOT
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  g = ap.add_mutually_exclusive_group(required=True)
  g.add_argument("--route", help="one route: bare log id or dongle/logid")
  g.add_argument("--since-hours", type=float, help="every route newer than N hours not yet in the ledger")
  g.add_argument("--all-new", action="store_true", help="every available route not yet fully covered by the ledger")
  ap.add_argument("description", nargs="?", default="", help="note for the ledger row(s)")
  ap.add_argument("--redo", action="store_true", help="include already-validated routes")
  ap.add_argument("--list", action="store_true", help="list Proton availability without validation or device contact")
  ap.add_argument("--device-fallback", action="store_true",
                  help="after Proton, inspect device uploads and fetch additional/missing logs over SSH")
  # CUSTOM TOOLING: retain private rlogs by default. Metric backfills repeatedly needed routes
  # older than the device's ~2-day window, so implicit seven-day deletion discarded irreplaceable
  # evidence. Cleanup remains available only as an explicit, reviewable action.
  ap.add_argument("--prune-hours", type=float,
                  help="OPT IN: after validation, delete ledgered local routes older than this")
  args = ap.parse_args()
  LEDGER = evidence_root() / "log-validation-ledger.jsonl"
  LOCAL_ROOT = rlog_root()

  route_id = None
  if args.route:
    match = LOGID_RE.search(args.route)
    if not match:
      sys.exit(f"could not parse a log id out of '{args.route}'")
    route_id = match[0]

  routes, available = local_routes()
  done = set() if args.redo else ledger_routes(available)
  if route_id:
    targets = [row for row in routes if row[0] == route_id]
    skipped, scope = [], "selected"
  else:
    targets, skipped, scope = _select_routes(routes, done, since_hours=args.since_hours, all_new=args.all_new)
  print(_selection_summary(len(routes), len(targets) + len(skipped), scope, targets, skipped,
                           redo=args.redo, source="Proton archive"))
  for rid, _, count in targets:
    contiguous, detail = _local_segments_contiguous(rid)
    print(f"  {rid}: {count} available segment(s)" + (f"; {detail}" if not contiguous else ""))
  print("  Archive availability is a snapshot, not proof of a whole drive or completed uploads.")
  if args.list:
    return

  failed, processed = set(), set()
  for rid, _, _ in targets:
    print(f"\n===== Proton: {rid} =====")
    if validate(rid, args.description) != 0:
      failed.add(rid)
    else:
      processed.add(rid)

  if args.device_fallback:
    print("\nChecking device only after the Proton archive; diagnosing any fallback before transfer.")
    routes, retained = remote_routes()
    done = set() if args.redo else ledger_routes(retained)
    if route_id:
      targets = [row for row in routes if row[0] == route_id]
      if not targets and route_id not in processed:
        print(f"  {route_id} is unavailable in Proton and the device catalog")
        failed.add(route_id)
    else:
      targets, _, _ = _select_routes(routes, done, since_hours=args.since_hours, all_new=args.all_new)
    for rid, _, expected_segments in targets:
      local = set(_local_segment_indices(rid))
      if retained[rid] <= local:
        if rid not in processed and rid not in failed and validate(rid, args.description) != 0:
          failed.add(rid)
        continue  # The available archive covers this device inventory; no transfer is needed.
      print(f"\n===== Device fallback: {rid} =====")
      diagnose_upload(rid, local)
      if not pull(rid, expected_segments=expected_segments) or validate(rid, args.description) != 0:
        failed.add(rid)
      else:
        failed.discard(rid)
  elif route_id and not targets:
    print(f"  {route_id} is not available in the Proton mirror")
    failed.add(route_id)

  if not args.device_fallback:
    print("\nNo device connection made. If expected logs are absent, check Proton synchronization; "
          "use --device-fallback to investigate uploads and retrieve device logs.")
  # Prune only when explicitly requested, after validating and re-reading the ledger so anything
  # just validated counts as safe.
  if args.prune_hours is not None:
    prune(args.prune_hours, ledger_routes())

  if failed:
    print(f"\n{len(failed)} route(s) failed: {', '.join(failed)}")
    sys.exit(1)


if __name__ == "__main__":
  main()
