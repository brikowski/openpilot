#!/usr/bin/env python3
"""Download private full-rate rlogs over Tailscale SSH and validate the local archive.

    .venv/bin/python .agents/pull_logs.py --all-new ["note"]
    .venv/bin/python .agents/pull_logs.py --since-hours 48 ["note"]
    .venv/bin/python .agents/pull_logs.py --route ROUTE_ID ["note"]

The default checks the device and downloads new closed rlogs. --list previews the
inventory without downloading; --local reads only the existing archive without SSH.
Use COMMA_SSH=comma@<tailnet-host> or ODYSSEY_DEVICE=<tailnet-host>. The Mac's SSH
configuration owns authentication and the Tailscale hostname.

Only logger-unlocked files in a fixed source snapshot are transferred. Downloads
resume after interruption and must match source SHA-256 hashes. Available contiguous
suffixes remain partial routes. Qlogs are too decimated for transition metrics.
Private logs and evidence default to the Git-excluded .private/ folder in this repo.
"""
import argparse
import hashlib
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
  LOCAL_ROOT = REPO / ".private/rlogs"  # Pure tests can import before archive creation.
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
             "Is the device powered and connected to Tailscale? Set COMMA_SSH=comma@<tailnet-host>")
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
  """Catalog the local archive without contacting the device."""
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
  result = _ssh(f"nice -n 19 ionice -c 3 find {REMOTE_ROOT} -mindepth 2 -maxdepth 2 -type f -path {pattern} "
                f"{CLOSED_RLOG_FILTER} -exec sha256sum {{}} +")
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
  g.add_argument("--since-hours", type=float, help="routes newer than N hours not yet fully validated")
  g.add_argument("--all-new", action="store_true", help="all retained routes not yet fully validated")
  ap.add_argument("description", nargs="?", default="", help="note for the ledger row(s)")
  ap.add_argument("--redo", action="store_true", help="include already-validated routes")
  ap.add_argument("--list", action="store_true", help="preview the selected inventory without downloading or validating")
  ap.add_argument("--local", action="store_true", help="validate existing local files without SSH")
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

  routes, retained = local_routes() if args.local else remote_routes()
  done = set() if args.redo else ledger_routes(retained)
  if route_id:
    targets = [row for row in routes if row[0] == route_id]
    skipped, scope = [], "selected"
  else:
    targets, skipped, scope = _select_routes(routes, done, since_hours=args.since_hours, all_new=args.all_new)
  print(_selection_summary(len(routes), len(targets) + len(skipped), scope, targets, skipped,
                           redo=args.redo, source="Local archive" if args.local else "Tailscale device"))
  for rid, _, count in targets:
    print(f"  {rid}: {count} retained segment(s)")
  if args.list:
    return

  failed = set()
  for rid, _, count in targets:
    print(f"\n===== {rid} =====")
    if not args.local and not retained[rid] <= set(_local_segment_indices(rid)):
      if not pull(rid, expected_segments=count):
        failed.add(rid)
        continue
    if validate(rid, args.description) != 0:
      failed.add(rid)
  if route_id and not targets:
    print(f"  {route_id} is unavailable in the selected inventory")
    failed.add(route_id)
  if args.prune_hours is not None:
    prune(args.prune_hours, ledger_routes())
  if failed:
    print(f"\n{len(failed)} route(s) failed: {', '.join(sorted(failed))}")
    sys.exit(1)


if __name__ == "__main__":
  main()
