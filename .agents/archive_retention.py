#!/usr/bin/env python3
"""Keep the local rlog archive within 30 GB while preserving required evidence."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import re
import shutil
import time
from collections import defaultdict
from pathlib import Path

from private_paths import evidence_root, rlog_root

SEGMENT = re.compile(r"([0-9a-f]{8}--[0-9a-f]+)--([0-9]+)")
MAX_ARCHIVE_BYTES = 30_000_000_000


class ArchiveFull(RuntimeError):
  pass


def read_json(path):
  return json.loads(path.read_text())


def read_policy(evidence):
  path = evidence / 'rlog-retention-policy.json'
  if path.exists():
    return read_json(path)
  return {'budget_bytes': MAX_ARCHIVE_BYTES, 'retention_days': 30, 'protected_routes': {}}


@contextmanager
def archive_lock(evidence):
  with (evidence / '.archive.lock').open('a') as lock:
    try:
      fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
      raise RuntimeError('another archive check or download is running') from error
    try:
      yield
    finally:
      fcntl.flock(lock, fcntl.LOCK_UN)


def route_files(root, route):
  result = []
  for directory in sorted(root.glob(route + "--*")):
    match = SEGMENT.fullmatch(directory.name)
    if not match or directory.is_symlink() or not directory.is_dir():
      raise ValueError("unrecognized or linked route directory")
    children = list(directory.iterdir())
    if len(children) != 1 or children[0].name != "rlog.zst" or children[0].is_symlink():
      raise ValueError("route has an active, partial or unrecognized file")
    stat = children[0].stat()
    result.append({"segment": directory.name, "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns})
  return result


def budget_status(root, policy):
  budget = policy['budget_bytes']
  if type(budget) is not int or budget < 1:
    raise ValueError('invalid archive budget')
  budget = min(budget, MAX_ARCHIVE_BYTES)
  # Count temporary/partial files as well as completed rlogs. Metadata only.
  usage = sum(p.stat().st_size for p in root.rglob('*') if p.is_file() and not p.is_symlink())
  return {'archive_bytes': usage, 'budget_bytes': budget, 'budget_exceeded': usage > budget}


def preview(root, ledger_path, policy, now, incoming_bytes=0, keep=()):
  if root.is_symlink():
    raise ValueError('refusing cleanup through a linked archive root')
  if type(incoming_bytes) is not int or incoming_bytes < 0:
    raise ValueError('invalid incoming byte reservation')
  protected = policy['protected_routes']
  days = policy['retention_days']
  if not isinstance(protected, dict) or type(days) is not int or days < 1:
    raise ValueError('invalid retention policy')
  storage = budget_status(root, policy)
  usage, budget = storage['archive_bytes'], storage['budget_bytes']
  rows = {}
  if ledger_path.exists():
    for line in ledger_path.read_text().splitlines():
      if line.strip():
        row = json.loads(line)
        rows[row['route']] = row
  groups = defaultdict(list)
  for directory in root.iterdir():
    if match := SEGMENT.fullmatch(directory.name):
      groups[match[1]].append(int(match[2]))
  candidates, recent, kept = [], [], {}
  for route, indices in sorted(groups.items()):
    row = rows.get(route)
    if route in protected or route in keep:
      kept[route] = protected.get(route, 'selected for this check')
      continue
    if row is None or not row.get('provenance_exact') or row.get('git_dirty') is not False or row.get('qlog_fallback'):
      kept[route] = 'unvalidated or uncertain source'
      continue
    findings = row.get('verdicts', [])
    if isinstance(findings, dict):
      findings = findings.values()
    if any(check.get('ok') is not True if isinstance(check, dict) else check != 'PASS' for check in findings):
      kept[route] = 'unresolved validation finding'
      continue
    coverage = row.get('local_segment_coverage', {})
    if (sorted(indices) != list(range(len(indices))) or coverage.get('first') != 0 or coverage.get('last') != len(indices) - 1 or
        coverage.get('count') != len(indices) or coverage.get('missing_between')):
      kept[route] = 'partial or changed coverage'
      continue
    start, minutes = row.get('start_wall'), row.get('log_min')
    if (type(start) not in (float, int) or type(minutes) not in (float, int) or
        not math.isfinite(start) or not math.isfinite(minutes) or start <= 0 or minutes < 0 or start + minutes * 60 > now):
      kept[route] = 'uncertain drive date'
      continue
    try:
      files = route_files(root, route)
    except (OSError, ValueError):
      kept[route] = 'active, partial or changed files'
      continue
    item = {'route': route, 'drive_end': start + minutes * 60,
            'validation_sha256': hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest(),
            'files': files, 'bytes': sum(p['bytes'] for p in files)}
    (candidates if item['drive_end'] < now - days * 86400 else recent).append(item)
  candidates.sort(key=lambda row: (row['drive_end'], row['route']))
  remaining = usage + incoming_bytes - sum(row['bytes'] for row in candidates)
  for row in sorted(recent, key=lambda row: (row['drive_end'], row['route'])):
    if remaining > budget:
      candidates.append(row)
      remaining -= row['bytes']
    else:
      kept[row['route']] = 'inside retention window'
  return {'version': 1, 'as_of': now, 'root': str(root.resolve()), 'policy': policy,
          **storage, 'incoming_bytes': incoming_bytes, 'keep': sorted(keep),
          'candidate_bytes': sum(r['bytes'] for r in candidates), 'projected_bytes': remaining,
          'candidates': candidates, 'kept': kept, 'scope': 'Local logs including partials; analysis/evidence caches are separate.'}


def apply_plan(root, ledger_path, policy, plan, record_removed=lambda route: None):
  if plan.get('version') != 1 or plan.get('root') != str(root.resolve()) or plan.get('policy') != policy:
    raise ValueError('plan root or policy changed')
  current = preview(root, ledger_path, policy, plan['as_of'], plan.get('incoming_bytes', 0), plan.get('keep', ()))
  if current['candidates'] != plan.get('candidates'):
    raise ValueError('candidate files or evidence changed; generate another preview')
  removed = []
  for row in plan['candidates']:
    if route_files(root, row['route']) != row['files']:
      raise ValueError('candidate changed during cleanup')
    for item in row['files']:
      shutil.rmtree(root / item['segment'])
    removed.append(row['route'])
    record_removed(row['route'])
  return removed


def enforce(root, evidence, incoming_bytes=0, keep=(), now=None):
  policy = read_policy(evidence)
  ledger = evidence / 'log-validation-ledger.jsonl'
  report = preview(root, ledger, policy, time.time() if now is None else now, incoming_bytes, keep)  # noqa: TID251
  if report['projected_bytes'] > report['budget_bytes']:
    raise ArchiveFull(f"30 GB log cap: need {report['projected_bytes'] / 1e9:.3f} GB after eligible cleanup; "
                      'protected, unvalidated or partial logs prevent this transfer. Review protections or resume/remove partials.')
  plan_sha = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
  with (evidence / 'rlog-retention-ledger.jsonl').open('a') as stream:
    def record_removed(route):
      stream.write(json.dumps({'at': report['as_of'], 'removed': route, 'plan_sha256': plan_sha, 'reason': 'age or capacity'}) + '\n')
      stream.flush()
    removed = apply_plan(root, ledger, policy, report, record_removed)
  storage = budget_status(root, policy)
  if storage['archive_bytes'] + incoming_bytes > storage['budget_bytes']:
    raise ArchiveFull('archive changed during capacity reservation; download refused')
  print(f"Local logs: {storage['archive_bytes'] / 1e9:.3f} / {storage['budget_bytes'] / 1e9:g} GB; "
        f"removed {len(removed)} expired/capacity route(s)")
  return {**storage, 'removed': removed}


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  action = parser.add_mutually_exclusive_group()
  action.add_argument('--preview', type=Path, help='write a reviewable plan without deleting')
  action.add_argument('--apply', type=Path, help='apply an unchanged preview')
  action.add_argument('--enforce', action='store_true', help='clean expired routes and enforce the local cap now')
  args = parser.parse_args()
  root, evidence = rlog_root(), evidence_root()
  with archive_lock(evidence):
    if args.enforce:
      enforce(root, evidence)
      return
    policy = read_policy(evidence)
    ledger = evidence / 'log-validation-ledger.jsonl'
    report = preview(root, ledger, policy, time.time())  # noqa: TID251
    print(f"Local logs: {report['archive_bytes'] / 1e9:.3f} / {report['budget_bytes'] / 1e9:g} GB")
    print(f"Preview: {len(report['candidates'])} eligible route(s); {len(report['kept'])} kept")
    if args.preview:
      if args.preview.resolve().is_relative_to(Path(__file__).resolve().parents[1]) and not args.preview.resolve().is_relative_to(evidence):
        parser.error('save retention plans in private evidence or outside the checkout')
      args.preview.write_text(json.dumps(report, indent=2) + '\n')
    if args.apply:
      plan = read_json(args.apply)
      with (evidence / 'rlog-retention-ledger.jsonl').open('a') as stream:
        def record_removed(route):
          stream.write(json.dumps({'at': report['as_of'], 'removed': route,
                                   'plan_sha256': hashlib.sha256(args.apply.read_bytes()).hexdigest()}) + '\n')
          stream.flush()
        removed = apply_plan(root, ledger, policy, plan, record_removed)
      print(f'Removed {len(removed)} local route(s).')


if __name__ == '__main__':
  try:
    main()
  except (RuntimeError, ValueError) as error:
    raise SystemExit(str(error)) from error
