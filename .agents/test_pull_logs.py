import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pull_logs


def test_pull_retries_broken_pipe_with_partial_files_and_keepalives(monkeypatch, tmp_path):
  calls = []

  def fake_run(cmd, **kwargs):
    calls.append((cmd, kwargs))
    if len(calls) == 1:
      return subprocess.CompletedProcess(cmd, 12, "", "rsync: connection unexpectedly closed (Broken pipe)")

    for segment in range(2):
      segment_dir = tmp_path / f"0000004c--c66974e5d7--{segment}"
      segment_dir.mkdir(exist_ok=True)
      (segment_dir / "rlog.zst").write_bytes(b"complete")
    return subprocess.CompletedProcess(cmd, 0, "", "")

  monkeypatch.setattr(pull_logs, "LOCAL_ROOT", tmp_path)
  monkeypatch.setattr(pull_logs, "PULL_RETRY_DELAYS", (0, 0))
  monkeypatch.setattr(pull_logs.subprocess, "run", fake_run)
  monkeypatch.setattr(pull_logs.time, "sleep", lambda _: None)

  assert pull_logs.pull("0000004c--c66974e5d7", expected_segments=2)
  assert len(calls) == 2
  command, kwargs = calls[0]
  assert "--partial" in command
  assert "--partial-dir=.rsync-partial" in command
  assert "--timeout=60" in command
  assert "ServerAliveInterval=10" in command[command.index("-e") + 1]
  assert kwargs == {"capture_output": True, "text": True}

  errors = [json.loads(line) for line in pull_logs._pull_error_log().read_text().splitlines()]
  assert len(errors) == 1
  assert errors[0]["route"] == "0000004c--c66974e5d7"
  assert errors[0]["returncode"] == 12
  assert "Broken pipe" in errors[0]["detail"]
  assert errors[0]["completed_segments"] == 0
  assert errors[0]["expected_segments"] == 2
