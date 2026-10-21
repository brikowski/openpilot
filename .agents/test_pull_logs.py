import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pull_logs


def test_select_all_new_includes_older_unvalidated_routes():
  routes = [("00000001--old", 1.0, 2), ("00000002--new", 2.0, 3)]

  targets, skipped, scope = pull_logs._select_routes(routes, {"00000001--done"}, all_new=True)

  assert targets == routes
  assert skipped == []
  assert scope == "retained"


def test_select_all_new_skips_every_ledgered_route():
  routes = [("00000001--old", 1.0, 2), ("00000002--new", 2.0, 3)]

  targets, skipped, scope = pull_logs._select_routes(routes, {"00000001--old"}, all_new=True)

  assert targets == [routes[1]]
  assert skipped == ["00000001--old"]
  assert scope == "retained"


def test_selection_summary_distinguishes_validated_routes_from_no_recorded_routes():
  summary = pull_logs._selection_summary(24, 24, "retained", [], ["00000061--aaaaaaaaaa"] * 24)

  assert "0 not yet validated" in summary
  assert "24 already validated" in summary
  assert "device has 24 route(s)" in summary


def test_pull_retries_broken_pipe_with_partial_files_and_keepalives(monkeypatch, tmp_path):
  calls = []

  def fake_run(cmd, **kwargs):
    calls.append((cmd, kwargs))
    if len(calls) == 1:
      return subprocess.CompletedProcess(cmd, 12, "", "rsync: connection unexpectedly closed (Broken pipe)")

    for segment in range(2):
      segment_dir = tmp_path / f"0000004c--bbbbbbbbbb--{segment}"
      segment_dir.mkdir(exist_ok=True)
      (segment_dir / "rlog.zst").write_bytes(b"complete")
    return subprocess.CompletedProcess(cmd, 0, "", "")

  monkeypatch.setattr(pull_logs, "LOCAL_ROOT", tmp_path)
  monkeypatch.setattr(pull_logs, "PULL_RETRY_DELAYS", (0, 0))
  monkeypatch.setattr(pull_logs.subprocess, "run", fake_run)
  monkeypatch.setattr(pull_logs, "_ssh", lambda _: subprocess.CompletedProcess(
    [], 0, "\n".join(f"{pull_logs.REMOTE_ROOT}/0000004c--bbbbbbbbbb--{i}" for i in range(2)), ""))
  monkeypatch.setattr(pull_logs.time, "sleep", lambda _: None)

  assert pull_logs.pull("0000004c--bbbbbbbbbb", expected_segments=2)
  assert len(calls) == 2
  command, kwargs = calls[0]
  assert "--partial" in command
  assert "--partial-dir=.rsync-partial" in command
  assert "--timeout=60" in command
  assert "ServerAliveInterval=10" in command[command.index("-e") + 1]
  assert kwargs == {"capture_output": True, "text": True}

  errors = [json.loads(line) for line in pull_logs._pull_error_log().read_text().splitlines()]
  assert len(errors) == 1
  assert errors[0]["route"] == "0000004c--bbbbbbbbbb"
  assert errors[0]["returncode"] == 12
  assert "Broken pipe" in errors[0]["detail"]
  assert errors[0]["completed_segments"] == 0
  assert errors[0]["expected_segments"] == 2


@pytest.mark.parametrize("retained", [(0, 1, 2), (0, 2)])
def test_pull_rejects_noncontiguous_local_segments(monkeypatch, tmp_path, retained):
  route = "0000004c--bbbbbbbbbb"
  for segment in (0, 2):
    segment_dir = tmp_path / f"{route}--{segment}"
    segment_dir.mkdir()
    (segment_dir / "rlog.zst").write_bytes(b"complete")

  monkeypatch.setattr(pull_logs, "LOCAL_ROOT", tmp_path)
  monkeypatch.setattr(pull_logs, "PULL_ATTEMPTS", 1)
  monkeypatch.setattr(pull_logs.subprocess, "run",
                      lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, "", ""))
  monkeypatch.setattr(pull_logs, "_ssh", lambda _: subprocess.CompletedProcess(
    [], 0, "\n".join(f"{pull_logs.REMOTE_ROOT}/{route}--{i}" for i in retained), ""))

  assert not pull_logs.pull(route)
  errors = [json.loads(line) for line in pull_logs._pull_error_log().read_text().splitlines()]
  assert errors[-1]["completed_segments"] == 2
  assert "non-contiguous local segments" in errors[-1]["detail"]


def test_pull_accepts_retained_suffix_only_after_matching_remote_files(monkeypatch, tmp_path, capsys):
  route = "0000004c--bbbbbbbbbb"
  for i in (4, 5, 6):
    path = tmp_path / f"{route}--{i}"
    path.mkdir()
    (path / "rlog.zst").write_bytes(b"complete")
  monkeypatch.setattr(pull_logs, "LOCAL_ROOT", tmp_path)
  monkeypatch.setattr(pull_logs, "PULL_ATTEMPTS", 1)
  monkeypatch.setattr(pull_logs.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, "", ""))
  monkeypatch.setattr(pull_logs, "_ssh", lambda _: subprocess.CompletedProcess(
    [], 0, "\n".join(f"{pull_logs.REMOTE_ROOT}/{route}--{i}" for i in (4, 5, 6)), ""))

  assert pull_logs.pull(route, expected_segments=3)
  assert "partial" in capsys.readouterr().out.lower()


def test_pull_rejects_missing_retained_tail_even_when_the_count_matches(monkeypatch, tmp_path):
  route = "0000004c--bbbbbbbbbb"
  for i in (0, 1, 2):
    path = tmp_path / f"{route}--{i}"
    path.mkdir()
    (path / "rlog.zst").write_bytes(b"complete")
  monkeypatch.setattr(pull_logs, "LOCAL_ROOT", tmp_path)
  monkeypatch.setattr(pull_logs, "PULL_ATTEMPTS", 1)
  monkeypatch.setattr(pull_logs.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, "", ""))
  monkeypatch.setattr(pull_logs, "_ssh", lambda _: subprocess.CompletedProcess(
    [], 0, "\n".join(f"{pull_logs.REMOTE_ROOT}/{route}--{i}" for i in (1, 2, 3)), ""))

  assert not pull_logs.pull(route, expected_segments=3)


@pytest.mark.parametrize("first", [0, 4])
@pytest.mark.parametrize("returncode", [0, 255])
def test_pull_cannot_accept_local_files_without_remote_inventory(monkeypatch, tmp_path, first, returncode):
  route = "0000004c--bbbbbbbbbb"
  path = tmp_path / f"{route}--{first}"
  path.mkdir()
  (path / "rlog.zst").write_bytes(b"complete")
  monkeypatch.setattr(pull_logs, "LOCAL_ROOT", tmp_path)
  monkeypatch.setattr(pull_logs, "PULL_ATTEMPTS", 1)
  monkeypatch.setattr(pull_logs.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, "", ""))
  monkeypatch.setattr(pull_logs, "_ssh", lambda _: subprocess.CompletedProcess(
    [], returncode, "", "unreachable" if returncode else ""))

  assert not pull_logs.pull(route, expected_segments=1)


def test_pull_preserves_older_local_prefix_when_device_retains_a_suffix(monkeypatch, tmp_path, capsys):
  route = "0000004c--bbbbbbbbbb"
  for i in range(7):
    path = tmp_path / f"{route}--{i}"
    path.mkdir()
    (path / "rlog.zst").write_bytes(b"complete")
  monkeypatch.setattr(pull_logs, "LOCAL_ROOT", tmp_path)
  monkeypatch.setattr(pull_logs, "PULL_ATTEMPTS", 1)
  monkeypatch.setattr(pull_logs.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, "", ""))
  monkeypatch.setattr(pull_logs, "_ssh", lambda _: subprocess.CompletedProcess(
    [], 0, "\n".join(f"{pull_logs.REMOTE_ROOT}/{route}--{i}" for i in (4, 5, 6)), ""))

  assert pull_logs.pull(route, expected_segments=3)
  assert len(pull_logs._local_segment_indices(route)) == 7
  assert "partial" not in capsys.readouterr().out.lower()


def test_validate_uses_current_interpreter_without_refreshing_lock(monkeypatch):
  calls = []

  def fake_run(cmd, **kwargs):
    calls.append((cmd, kwargs))
    return subprocess.CompletedProcess(cmd, 0)

  monkeypatch.setattr(pull_logs.subprocess, "run", fake_run)

  assert pull_logs.validate("0000002b--cccccccccc", "diagnostic") == 0
  assert calls == [([sys.executable, ".agents/validate_log.py", "0000002b--cccccccccc", "diagnostic"],
                   {"cwd": pull_logs.REPO})]
