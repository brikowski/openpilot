import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive_retention as retention

NOW = 1800000000.
OLD = "000000aa--aabbccdd"
BASE = "000000bb--bbccddee"


@pytest.fixture
def archive(tmp_path):
  root = tmp_path / "rlogs"
  root.mkdir()
  ledger = tmp_path / "ledger.jsonl"
  rows = []
  for route in (OLD, BASE):
    path = root / (route + "--0")
    path.mkdir()
    (path / "rlog.zst").write_bytes(b"full-rate route")
    rows.append({"route": route, "provenance_exact": True, "git_dirty": False, "qlog_fallback": False,
                 "start_wall": NOW - 60 * 86400, "log_min": 1.,
                 "local_segment_coverage": {"first": 0, "last": 0, "count": 1, "missing_between": []}})
  ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))
  policy = {"budget_bytes": 20, "retention_days": 30, "protected_routes": {BASE: "active baseline"}}
  return root, ledger, policy


def test_preview_warns_without_deleting_and_protects_baseline(archive):
  root, ledger, policy = archive
  report = retention.preview(root, ledger, policy, NOW)
  assert report["archive_bytes"] == 30 and report["budget_exceeded"]
  assert report["candidate_bytes"] == 15
  assert [r["route"] for r in report["candidates"]] == [OLD]
  assert report["kept"][BASE] == "active baseline"
  assert len(list(root.glob("*/rlog.zst"))) == 2


@pytest.mark.parametrize("condition", ["unvalidated", "uncertain", "recent", "clock", "coverage", "lock", "partial", "symlink"])
def test_uncertain_active_and_unreviewed_routes_are_kept(archive, condition):
  root, ledger, policy = archive
  rows = [json.loads(x) for x in ledger.read_text().splitlines()]
  if condition == "unvalidated":
    rows = rows[1:]
  elif condition == "uncertain":
    rows[0]["provenance_exact"] = False
  elif condition == "recent":
    rows[0]["start_wall"] = NOW - 86400
  elif condition == "clock":
    rows[0]["start_wall"] = None
  elif condition == "coverage":
    rows[0]["local_segment_coverage"]["count"] = 2
  elif condition == "lock":
    (root / (OLD + "--0/rlog.lock")).touch()
  elif condition == "partial":
    (root / (OLD + "--0/.rsync-partial")).mkdir()
  else:
    path = root / (OLD + "--0/rlog.zst")
    path.unlink()
    path.symlink_to(root / (BASE + "--0/rlog.zst"))
  ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))
  report = retention.preview(root, ledger, policy, NOW)
  assert report["candidates"] == [] and OLD in report["kept"]


@pytest.mark.parametrize("change", ["file", "policy", "ledger", "finding", "root"])
def test_changed_plan_rejects_all_deletion(archive, change, tmp_path):
  root, ledger, policy = archive
  plan = retention.preview(root, ledger, policy, NOW)
  if change == "file":
    (root / (OLD + "--0/rlog.zst")).write_bytes(b"new evidence")
  elif change == "policy":
    policy = {**policy, "protected_routes": {BASE: "baseline", OLD: "newly unresolved"}}
  elif change == "ledger":
    ledger.write_text("\n".join(x for x in ledger.read_text().splitlines() if OLD not in x) + "\n")
  elif change == "finding":
    rows = [json.loads(x) for x in ledger.read_text().splitlines()]
    rows[0]["verdicts"] = {"newly_unresolved_fault": "FAIL"}
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))
  else:
    plan["root"] = str(tmp_path)
  with pytest.raises(ValueError):
    retention.apply_plan(root, ledger, policy, plan)
  assert len(list(root.glob("*/rlog.zst"))) == 2


def test_apply_removes_only_the_inspected_whole_route_and_records_it(archive):
  root, ledger, policy = archive
  plan = retention.preview(root, ledger, policy, NOW)
  recorded = []
  assert retention.apply_plan(root, ledger, policy, plan, recorded.append) == [OLD]
  assert recorded == [OLD]
  assert not (root / (OLD + "--0")).exists()
  assert (root / (BASE + "--0/rlog.zst")).exists()


def test_budget_includes_resumable_partials_without_reading_payloads(archive, monkeypatch):
  root, _, policy = archive
  partial = root / (OLD + "--0/.rsync-partial")
  partial.mkdir()
  (partial / "rlog.zst").write_bytes(b"inflight")
  monkeypatch.setattr(Path, "open", lambda *args, **kwargs: pytest.fail("budget checks must not hydrate or read rlogs"))
  assert retention.budget_status(root, policy)["archive_bytes"] == 38
