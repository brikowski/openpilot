#!/usr/bin/env python3
"""Preview reviewed-rlog retention in the Proton mirror; apply only an inspected plan."""
import argparse
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


def read_json(path):
  return json.loads(path.read_text())


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
  usage = sum(p.stat().st_size for p in root.rglob("rlog.zst") if p.is_file() and not p.is_symlink())
  budget = policy["budget_bytes"]
  if type(budget) is not int or budget < 1:
    raise ValueError("invalid archive budget")
  return {"archive_bytes": usage, "budget_exceeded": usage >= budget}


def preview(root, ledger_path, policy, now):
  rows = {}
  for line in ledger_path.read_text().splitlines():
    row = json.loads(line)
    rows[row["route"]] = row
  groups = defaultdict(list)
  for directory in root.iterdir():
    if match := SEGMENT.fullmatch(directory.name):
      groups[match[1]].append(int(match[2]))
  usage = budget_status(root, policy)["archive_bytes"]
  protected = policy["protected_routes"]
  days, budget = policy["retention_days"], policy["budget_bytes"]
  if not isinstance(protected, dict) or type(days) is not int or days < 1 or type(budget) is not int or budget < 1:
    raise ValueError("invalid retention policy")
  candidates, kept = [], {}
  for route, indices in sorted(groups.items()):
    row = rows.get(route)
    if route in protected:
      kept[route] = protected[route]
      continue
    if row is None or not row.get("provenance_exact") or row.get("git_dirty") is not False or row.get("qlog_fallback"):
      kept[route] = "unvalidated or uncertain source"
      continue
    coverage = row.get("local_segment_coverage", {})
    if (sorted(indices) != list(range(len(indices))) or coverage.get("first") != 0 or coverage.get("last") != len(indices) - 1 or
        coverage.get("count") != len(indices) or coverage.get("missing_between")):
      kept[route] = "partial or changed coverage"
      continue
    start, minutes = row.get("start_wall"), row.get("log_min")
    if (type(start) not in (float, int) or type(minutes) not in (float, int) or
        not math.isfinite(start) or not math.isfinite(minutes) or start <= 0 or minutes < 0 or start + minutes * 60 > now):
      kept[route] = "uncertain drive date"
      continue
    end = start + minutes * 60
    if end >= now - days * 86400:
      kept[route] = "inside retention window"
      continue
    try:
      files = route_files(root, route)
    except (OSError, ValueError):
      kept[route] = "active, partial or changed files"
      continue
    validation = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
    candidates.append({"route": route, "drive_end": end, "validation_sha256": validation,
                       "files": files, "bytes": sum(p["bytes"] for p in files)})
  return {"version": 1, "as_of": now, "root": str(root.resolve()), "policy": policy,
          "archive_bytes": usage, "budget_exceeded": usage >= budget,
          "candidate_bytes": sum(r["bytes"] for r in candidates), "candidates": candidates, "kept": kept,
          "scope": "Mac mirror metadata only, not Proton account quota. Deletion here synchronizes to Proton and other Macs."}


def apply_plan(root, ledger_path, policy, plan, record_removed=lambda route: None):
  if plan.get("version") != 1 or plan.get("root") != str(root.resolve()) or plan.get("policy") != policy:
    raise ValueError("plan root or policy changed")
  current = preview(root, ledger_path, policy, plan["as_of"])
  if current["candidates"] != plan.get("candidates"):
    raise ValueError("candidate files or evidence changed; generate another preview")
  removed = []
  for row in plan["candidates"]:
    if route_files(root, row["route"]) != row["files"]:
      raise ValueError("candidate changed during cleanup")
    for item in row["files"]:
      shutil.rmtree(root / item["segment"])
    removed.append(row["route"])
    record_removed(row["route"])
  return removed


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  action = parser.add_mutually_exclusive_group()
  action.add_argument("--preview", type=Path, help="write a reviewable plan; never deletes")
  action.add_argument("--apply", type=Path, help="apply an inspected unchanged preview")
  args = parser.parse_args()
  root, evidence = rlog_root(), evidence_root()
  policy_path = evidence / "rlog-retention-policy.json"
  if not policy_path.exists():
    parser.error("configure private evidence/rlog-retention-policy.json with budget_bytes, retention_days and protected_routes first")
  policy = read_json(policy_path)
  ledger = evidence / "log-validation-ledger.jsonl"
  report = preview(root, ledger, policy, time.time())  # noqa: TID251 -- compare recorded drive dates, not scheduling.
  print(f"Archive: {report['archive_bytes'] / 2**30:.1f} / {policy['budget_bytes'] / 2**30:.1f} GiB in the Mac mirror")
  if report["budget_exceeded"]:
    print("WARNING: archive budget reached; review retention without removing protected evidence.")
  print(f"Preview: {len(report['candidates'])} old validated route(s), {report['candidate_bytes'] / 2**30:.1f} GiB; "
        f"{len(report['kept'])} protected or ineligible")
  if args.preview:
    if args.preview.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
      parser.error("save retention plans outside the source checkout")
    args.preview.write_text(json.dumps(report, indent=2) + "\n")
    digest = hashlib.sha256(args.preview.read_bytes()).hexdigest()
    print(f"Plan SHA-256: {digest}")
  if args.apply:
    digest = hashlib.sha256(args.apply.read_bytes()).hexdigest()
    with (evidence / "rlog-retention-ledger.jsonl").open("a") as stream:
      def record_removed(route):
        stream.write(json.dumps({"at": report["as_of"], "removed": route, "plan_sha256": digest}) + "\n")
        stream.flush()
      removed = apply_plan(root, ledger, policy, read_json(args.apply), record_removed)
    print(f"Removed {len(removed)} reviewed route(s); Proton synchronization propagates these deletions.")


if __name__ == "__main__":
  main()
