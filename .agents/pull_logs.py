#!/usr/bin/env python3
"""Pull route rlogs off the comma over SSH and validate them.

Two modes:
    uv run python .agents/pull_logs.py --route 0000001f--765ef47daf ["note"]
    uv run python .agents/pull_logs.py --since-hours 48 ["note"]     # everything new

Why SSH rather than the comma API (verified 2026-07-27):
  * rlogs NEVER auto-upload. uploader's next_file_to_upload() only ever returns crash/boot files
    plus qlog/qlog.zst/qcamera.ts, and returns None for anything else - rlog included.
  * The tools cannot ask for one either: auto_source() only reads what is already on comma's
    servers and raises LogsUnavailable ("please ensure all logs are uploaded") otherwise.
  * So without clicking upload per route in connect, SSH is the ONLY way to get full-rate logs.
    It also needs no comma auth and costs no cellular data.
  * qlogs are not a substitute: at 1-in-10 decimation they suppress the jerk, domain-chatter and
    kickdown metrics entirely (see validate_log's qlog_fallback handling).

Device host comes from $COMMA_SSH (default comma@192.168.1.200); local store from $LOG_ROOT
(default ~/.comma/media/0/realdata), matching Paths.log_root() so validate_log finds them.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

AGENTS = Path(__file__).resolve().parent
REPO = AGENTS.parent
LEDGER = AGENTS / "log-validation-ledger.jsonl"
DEVICE = os.environ.get("COMMA_SSH", "comma@192.168.1.200")
REMOTE_ROOT = "/data/media/0/realdata"
LOCAL_ROOT = Path(os.environ.get("LOG_ROOT", Path.home() / ".comma/media/0/realdata"))
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
            "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=3",
            "-o", "LogLevel=ERROR"]
LOGID_RE = re.compile(r"[0-9a-f]{8}--[0-9a-f]+")
PULL_ATTEMPTS = 3
PULL_RETRY_DELAYS = (2, 5)


def _ssh(cmd):
  return subprocess.run(["ssh", *SSH_OPTS, DEVICE, cmd], capture_output=True, text=True, timeout=120)


def remote_routes():
  """[(logid, newest_mtime, n_segments)] on the device, newest first."""
  # Group locally rather than with awk over ssh - far less quoting to get wrong.
  r = _ssh(f"find {REMOTE_ROOT} -maxdepth 1 -mindepth 1 -type d -printf '%T@ %f\\n'")
  if r.returncode != 0:
    sys.exit(f"cannot reach {DEVICE}: {r.stderr.strip() or 'ssh failed'}\n"
             f"Is the device powered and on wifi? Override with COMMA_SSH=user@ip")
  newest, count = {}, {}
  for line in r.stdout.splitlines():
    parts = line.split()
    if len(parts) != 2:
      continue
    ts, name = float(parts[0]), parts[1]
    m = LOGID_RE.match(name)
    if not m:
      continue   # 'boot', 'crash', etc
    rid = m.group(0)
    newest[rid] = max(newest.get(rid, 0), ts)
    count[rid] = count.get(rid, 0) + 1
  return sorted(((r, newest[r], count[r]) for r in newest), key=lambda x: -x[1])


def ledger_routes():
  """Log ids already validated, keyed the same way validate_log dedups them."""
  if not LEDGER.exists():
    return set()
  out = set()
  for line in LEDGER.read_text().splitlines():
    if not line.strip():
      continue
    m = LOGID_RE.search(json.loads(line).get("route", ""))
    if m:
      out.add(m.group(0))
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


def _local_rlog_count(rid):
  return sum(1 for f in LOCAL_ROOT.glob(f"{rid}--*/rlog.zst") if f.is_file())


def _pull_command(rid):
  return ["rsync", "-a", "--partial", "--partial-dir=.rsync-partial", "--timeout=60", "--prune-empty-dirs",
          "--include=*/", "--include=rlog.zst", "--exclude=*",
          "-e", "ssh " + " ".join(SSH_OPTS),
          f"{DEVICE}:{REMOTE_ROOT}/{rid}--*", str(LOCAL_ROOT) + "/"]


def pull(rid, expected_segments=None):
  """Rsync one route's rlogs with bounded, resumable retries."""
  LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
  # CUSTOM TOOLING: keep interrupted rlogs outside their final path, retry the Wi-Fi/SSH stalls
  # observed on 2026-08-02, and retain the exact rsync failure for the next diagnosis.
  cmd = _pull_command(rid)
  for attempt in range(1, PULL_ATTEMPTS + 1):
    result = subprocess.run(cmd, capture_output=True, text=True)
    completed = _local_rlog_count(rid)
    enough = completed > 0 and (expected_segments is None or completed >= expected_segments)
    if result.returncode == 0 and enough:
      if attempt > 1:
        print(f"  pull recovered on attempt {attempt}/{PULL_ATTEMPTS}")
      return True

    detail = (result.stderr.strip() or result.stdout.strip()
              or (f"rsync exited successfully but only {completed}/{expected_segments} segments completed"
                  if expected_segments is not None else "rsync completed without an rlog"))
    failure = f"  pull attempt {attempt}/{PULL_ATTEMPTS} failed (rsync exit {result.returncode}, {completed} local segment(s)): {detail}"
    print(failure)
    _record_pull_error(rid, attempt, result.returncode, detail, completed, expected_segments)
    if attempt < PULL_ATTEMPTS:
      delay = PULL_RETRY_DELAYS[min(attempt - 1, len(PULL_RETRY_DELAYS) - 1)]
      print(f"  retrying in {delay}s; partial data retained")
      time.sleep(delay)

  print(f"  failure details saved to {_pull_error_log()}")
  return False


def validate(rid, desc):
  return subprocess.run(["uv", "run", "python", ".agents/validate_log.py", rid, desc],
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
    print(f"\npruned {sum(victims.values())} segment(s) from {len(victims)} validated route(s) "
          f"older than {hours:g}h, freed {freed/1e6:.0f} MB")
    for rid, n in sorted(victims.items()):
      print(f"    {rid}  {n} segs")
  if kept_unvalidated:
    print(f"  kept {len(kept_unvalidated)} old route(s) that are NOT in the ledger yet: "
          f"{', '.join(sorted(kept_unvalidated))}")


def main():
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  g = ap.add_mutually_exclusive_group(required=True)
  g.add_argument("--route", help="one route: bare log id or dongle/logid")
  g.add_argument("--since-hours", type=float, help="every route newer than N hours not yet in the ledger")
  ap.add_argument("description", nargs="?", default="", help="note for the ledger row(s)")
  ap.add_argument("--redo", action="store_true", help="with --since-hours, include already-validated routes")
  ap.add_argument("--list", action="store_true", help="show what would be pulled, then stop")
  # CUSTOM TOOLING: retain private rlogs by default. Metric backfills repeatedly needed routes
  # older than the device's ~2-day window, so implicit seven-day deletion discarded irreplaceable
  # evidence. Cleanup remains available only as an explicit, reviewable action.
  ap.add_argument("--prune-hours", type=float,
                  help="OPT IN: after validation, delete ledgered local routes older than this")
  args = ap.parse_args()

  if args.route:
    m = LOGID_RE.search(args.route)
    if not m:
      sys.exit(f"could not parse a log id out of '{args.route}'")
    targets = [(m.group(0), None, None)]
  else:
    cutoff = datetime.now().timestamp() - args.since_hours * 3600
    done = set() if args.redo else ledger_routes()
    routes = remote_routes()
    targets = [(r, ts, n) for r, ts, n in routes if ts >= cutoff and r not in done]
    skipped = [r for r, ts, _ in routes if ts >= cutoff and r in done]
    print(f"device has {len(routes)} route(s); {len(targets)} new within {args.since_hours:g}h"
          f"{f', {len(skipped)} already validated' if skipped else ''}")
    if not targets:
      print("nothing to do.")
      return
    est = sum(n for _, _, n in targets) * 9.5
    print(f"  to pull: {sum(n for _, _, n in targets)} segments, ~{est:.0f} MB")
    for r, ts, n in targets:
      print(f"    {r}  {n:>3} segs  {(datetime.now().timestamp()-ts)/3600:>5.1f}h ago")

  if args.list:
    return

  failed = []
  for i, (rid, _, expected_segments) in enumerate(targets, 1):
    print(f"\n===== [{i}/{len(targets)}] {rid} =====")
    if not pull(rid, expected_segments=expected_segments):
      print(f"  pull FAILED for {rid}")
      failed.append(rid)
      continue
    if validate(rid, args.description) != 0:
      print(f"  validate FAILED for {rid}")
      failed.append(rid)
  # Prune only when explicitly requested, after validating and re-reading the ledger so anything
  # just validated counts as safe.
  if args.prune_hours is not None:
    prune(args.prune_hours, ledger_routes())

  if failed:
    print(f"\n{len(failed)} route(s) failed: {', '.join(failed)}")
    sys.exit(1)


if __name__ == "__main__":
  main()
