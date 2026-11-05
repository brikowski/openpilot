#!/usr/bin/env python3
"""Pull closed full-rate rlogs over Tailscale SSH into the capped local private archive.

Usage modes:
    .venv/bin/python .agents/pull_logs.py --route ROUTE_ID ["note"]
    .venv/bin/python .agents/pull_logs.py --since-hours 48 ["note"]     # everything new
    .venv/bin/python .agents/pull_logs.py --all-new ["note"]             # every available route not in ledger

The default checks the device; --local uses saved logs without SSH. Each check removes
expired, unprotected validated routes and makes room for downloads within the 30 GB cap.
If protected or unvalidated logs prevent fitting a transfer, it is refused before rsync.
Only closed rlogs are copied at low CPU/I/O priority, with resumable partial files and
source SHA-256 verification. No background uploader or cloud synchronization is used.
Retained contiguous suffixes are usable when their transfer matches the device inventory;
validation records their available segment extent rather than implying a whole drive.

Device host comes from $COMMA_SSH or $ODYSSEY_DEVICE. Private rlogs and the
ledger are stored in the Git-excluded .private/ folder by default.
"""
import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from private_paths import evidence_path, evidence_root, rlog_root
from archive_retention import ArchiveFull, archive_lock, enforce, read_policy

AGENTS = Path(__file__).resolve().parent
REPO = AGENTS.parent
LEDGER = evidence_path("log-validation-ledger.jsonl")
DEVICE = os.environ.get("COMMA_SSH") or (f"comma@{os.environ['ODYSSEY_DEVICE']}" if os.environ.get("ODYSSEY_DEVICE") else "")
REMOTE_ROOT = "/data/media/0/realdata"
try:
  LOCAL_ROOT = rlog_root()
except FileNotFoundError:
  LOCAL_ROOT = REPO / ".private/rlogs"  # pure tests can import without an archive
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
  r = _ssh(f"find {REMOTE_ROOT} -mindepth 2 -maxdepth 2 -type f -name rlog.zst {CLOSED_RLOG_FILTER} -printf '%T@ %h\\n'")
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
  """Catalog closed local rlogs without admitting locked or partial segments."""
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
  return evidence_root() / "log-pull-errors.jsonl"


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
  result = _ssh(f"nice -n 19 ionice -c 3 find {REMOTE_ROOT} -mindepth 2 -maxdepth 2 "
                f"-type f -path {pattern} {CLOSED_RLOG_FILTER} -exec sha256sum {{}} +")
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
          "--rsync-path=nice -n 19 ionice -c 3 rsync",
          "-e", "ssh " + " ".join(SSH_OPTS),
          f"{DEVICE}:{REMOTE_ROOT}/", str(LOCAL_ROOT) + "/"]


def _reserve_download(rid, retained):
  pattern = shlex.quote(f"{REMOTE_ROOT}/{rid}--*/rlog.zst")
  result = _ssh(f"find {REMOTE_ROOT} -mindepth 2 -maxdepth 2 -type f -path {pattern} "
                f"{CLOSED_RLOG_FILTER} -printf '%s %h\\n'")
  if result.returncode:
    raise RuntimeError("cannot reserve space without closed-source file sizes")
  sizes = {}
  for line in result.stdout.splitlines():
    size, path = line.split(maxsplit=1)
    match = re.fullmatch(re.escape(rid) + r"--(\d+)", Path(path).name)
    if not match or not size.isdecimal():
      raise RuntimeError("invalid closed-source size inventory")
    index = int(match[1])
    if index in sizes:
      raise RuntimeError("duplicate closed-source size")
    sizes[index] = int(size)
  if not set(retained) <= sizes.keys():
    raise RuntimeError("closed-source size inventory changed")
  evidence = evidence_root()
  # Reserve every source byte, including replacement/temp-file headroom. Existing local
  # and resumable bytes still count until rsync actually reuses or replaces them.
  enforce(LOCAL_ROOT, evidence, incoming_bytes=sum(sizes[i] for i in retained), keep={rid})


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
      _reserve_download(rid, retained)
      files = "".join(f"{rid}--{index}/rlog.zst\n" for index in retained)
      result = subprocess.run(cmd, input=files, capture_output=True, text=True)
      contiguous, completeness_detail = _local_segments_contiguous(rid, expected_indices=retained)
      if result.returncode == 0 and contiguous:
        contiguous, completeness_detail = _verify_rlog_hashes(rid, retained)
    except ArchiveFull as error:
      print(f"  download refused: {error}")
      return False
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


def main():
  global LEDGER, LOCAL_ROOT
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  g = ap.add_mutually_exclusive_group(required=True)
  g.add_argument("--route", help="one route: bare log id or dongle/logid")
  g.add_argument("--since-hours", type=float, help="routes newer than N hours not yet fully validated")
  g.add_argument("--all-new", action="store_true", help="all retained routes not yet fully validated")
  ap.add_argument("description", nargs="?", default="", help="note for the ledger row(s)")
  ap.add_argument("--redo", action="store_true", help="include already-validated routes")
  ap.add_argument("--list", action="store_true", help="apply retention, then list without downloading or validating")
  ap.add_argument("--local", action="store_true", help="check existing local logs without SSH")
  args = ap.parse_args()
  evidence = evidence_root()
  LEDGER = evidence / "log-validation-ledger.jsonl"
  LOCAL_ROOT = rlog_root()
  route_id = None
  if args.route:
    match = LOGID_RE.search(args.route)
    if not match:
      ap.error(f"could not parse a log id out of '{args.route}'")
    route_id = match[0]

  with archive_lock(evidence):
    enforce(LOCAL_ROOT, evidence, keep={route_id} if route_id else set())
    routes, retained = local_routes() if args.local else remote_routes()
    done = set() if args.redo else ledger_routes(retained)
    if route_id:
      targets = [row for row in routes if row[0] == route_id]
      skipped, scope = [], "selected"
    else:
      targets, skipped, scope = _select_routes(routes, done, since_hours=args.since_hours, all_new=args.all_new)
    print(_selection_summary(len(routes), len(targets) + len(skipped), scope, targets, skipped,
                             redo=args.redo, source="Local archive" if args.local else "Device"))
    for rid, _, count in targets:
      print(f"  {rid}: {count} closed segment(s)")
    if args.list:
      return
    if route_id and not targets:
      raise SystemExit(f"{route_id} is not available in the selected inventory")
    failed = []
    for rid, _, count in targets:
      print(f"\n===== {rid} =====")
      if not args.local and not pull(rid, expected_segments=count):
        failed.append(rid)
        continue
      # New acquisitions remain protected until their tuning review retires them.
      policy_path = evidence / "rlog-retention-policy.json"
      policy = read_policy(evidence)
      policy['protected_routes'].setdefault(rid, "New acquisition or revalidation; review before retirement")
      policy_path.write_text(json.dumps(policy, indent=2) + "\n")
      if validate(rid, args.description) != 0:
        failed.append(rid)
    enforce(LOCAL_ROOT, evidence)
    if failed:
      raise SystemExit(f"{len(failed)} route(s) failed: {', '.join(failed)}")


if __name__ == '__main__':
  try:
    main()
  except (RuntimeError, ValueError) as error:
    raise SystemExit(str(error)) from error
