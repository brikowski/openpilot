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
    policy = {**policy, "budget_bytes": 100}
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


def configured(archive):
  root, ledger, policy = archive
  evidence = ledger.parent / "evidence"
  evidence.mkdir()
  (evidence / "log-validation-ledger.jsonl").write_bytes(ledger.read_bytes())
  (evidence / "rlog-retention-policy.json").write_text(json.dumps(policy))
  return root, evidence, policy


def test_capacity_can_retire_a_recent_disposable_route(archive):
  root, evidence, _ = configured(archive)
  ledger = evidence / "log-validation-ledger.jsonl"
  rows = [json.loads(x) for x in ledger.read_text().splitlines()]
  rows[0]["start_wall"] = NOW - 86400
  ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))
  result = retention.enforce(root, evidence, incoming_bytes=5, now=NOW)
  assert result["removed"] == [OLD]
  assert result["archive_bytes"] + 5 == 20
  assert (root / (BASE + "--0/rlog.zst")).exists()
  receipt = json.loads((evidence / "rlog-retention-ledger.jsonl").read_text())
  assert receipt["removed"] == OLD


def test_expired_disposable_routes_are_removed_even_with_free_space(archive):
  root, evidence, policy = configured(archive)
  policy["budget_bytes"] = 100
  (evidence / "rlog-retention-policy.json").write_text(json.dumps(policy))
  assert retention.enforce(root, evidence, now=NOW)["removed"] == [OLD]


def test_capacity_refuses_before_any_deletion_if_required_evidence_will_not_fit(archive):
  root, evidence, _ = configured(archive)
  before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
  with pytest.raises(retention.ArchiveFull, match="protected"):
    retention.enforce(root, evidence, incoming_bytes=6, now=NOW)
  assert {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_selected_route_is_kept_and_cap_still_applies(archive):
  root, evidence, _ = configured(archive)
  with pytest.raises(retention.ArchiveFull):
    retention.enforce(root, evidence, keep={OLD}, now=NOW)
  assert (root / (OLD + "--0/rlog.zst")).exists()


def test_capacity_removes_oldest_recent_route_first(archive):
  root, ledger, policy = archive
  newer = "000000cc--ccddeeff"
  segment = root / (newer + "--0")
  segment.mkdir()
  (segment / "rlog.zst").write_bytes(b"recent")
  rows = [json.loads(x) for x in ledger.read_text().splitlines()]
  rows[0]["start_wall"] = NOW - 2 * 86400
  rows.append({**rows[0], "route": newer, "start_wall": NOW - 86400})
  ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))
  report = retention.preview(root, ledger, {**policy, "budget_bytes": 25}, NOW)
  assert [r["route"] for r in report["candidates"]] == [OLD]
  assert newer in report["kept"]


def test_single_archive_lock_prevents_overlapping_download_reservations(tmp_path):
  with retention.archive_lock(tmp_path):
    with pytest.raises(RuntimeError, match="another archive"):
      with retention.archive_lock(tmp_path):
        pytest.fail("concurrent archive writer admitted")
  with retention.archive_lock(tmp_path):
    pass


def test_config_cannot_raise_the_hard_cap(tmp_path):
  assert retention.budget_status(tmp_path, {"budget_bytes": 50_000_000_000})["budget_bytes"] == 30_000_000_000


@pytest.mark.parametrize("findings", [[{"check": "unresolved", "ok": False, "status": None}], {"unresolved": "FAIL"}])
def test_failed_validation_is_kept_even_under_capacity_pressure(archive, findings):
  root, ledger, policy = archive
  rows = [json.loads(x) for x in ledger.read_text().splitlines()]
  rows[0]["verdicts"] = findings
  ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))
  report = retention.preview(root, ledger, policy, NOW)
  assert report["candidates"] == []
  assert report["kept"][OLD] == "unresolved validation finding"
