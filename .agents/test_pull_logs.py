import hashlib
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

  monkeypatch.setattr(pull_logs, "_verify_rlog_hashes", lambda *_: (True, ""))

  assert pull_logs.pull("0000004c--bbbbbbbbbb", expected_segments=2)
  assert len(calls) == 2
  command, kwargs = calls[0]
  assert "--partial" in command
  assert "--checksum" in command
  assert "--partial-dir=.rsync-partial" in command
  assert "--timeout=60" in command
  assert "ServerAliveInterval=10" in command[command.index("-e") + 1]
  assert kwargs == {"input": "0000004c--bbbbbbbbbb--0/rlog.zst\n0000004c--bbbbbbbbbb--1/rlog.zst\n",
                    "capture_output": True, "text": True}

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

  monkeypatch.setattr(pull_logs, "_verify_rlog_hashes", lambda *_: (True, ""))

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

  monkeypatch.setattr(pull_logs, "_verify_rlog_hashes", lambda *_: (True, ""))

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


@pytest.mark.parametrize("selection", [["--all-new"], ["--since-hours", "24"]])
@pytest.mark.parametrize("coverage,retained,complete", [
  ({"first": 0, "last": 2, "missing_between": [1]}, [0, 1, 2], False),
  ({"first": 0, "last": 1, "missing_between": []}, [0, 1, 2], False),
  ({"first": 0, "last": 2, "missing_between": []}, [1, 2, 3], False),
  ({"first": 4, "last": 6, "missing_between": []}, [4, 5, 6], True),
  ({"first": 0, "last": 6, "missing_between": []}, [4, 5, 6], True),
  ({"first": 0, "last": 2, "missing_between": [1]}, [0, 2], True),
  (None, [0, 1], False),
])
def test_partial_validation_does_not_hide_newly_available_segments(monkeypatch, tmp_path, capsys,
                                                                  coverage, retained, complete, selection):
  route = "0000004c--bbbbbbbbbb"
  ledger = tmp_path / "log-validation-ledger.jsonl"
  ledger.write_text(json.dumps({"route": route, "local_segment_coverage": coverage}) + "\n")
  monkeypatch.setattr(pull_logs, "LEDGER", ledger)
  monkeypatch.setattr(pull_logs, "LOCAL_ROOT", tmp_path)

  monkeypatch.setattr(pull_logs, "evidence_root", lambda: tmp_path)
  monkeypatch.setattr(pull_logs, "rlog_root", lambda: tmp_path)
  monkeypatch.setattr(pull_logs, "local_routes", lambda: ([(route, pull_logs.datetime.now().timestamp(), len(retained))], {route: set(retained)}))
  monkeypatch.setattr(sys, "argv", ["pull_logs.py", *selection, "--local", "--list"])
  pull_logs.main()
  assert f"{int(not complete)} not yet validated" in capsys.readouterr().out
  # Pruning still uses the explicit validation ledger, independently of device retention.
  assert pull_logs.ledger_routes() == {route}


def test_remote_inventory_counts_rlogs_and_retains_exact_indices(monkeypatch):
  route = "0000004c--bbbbbbbbbb"
  commands = []

  def ssh(command):
    commands.append(command)
    return subprocess.CompletedProcess([], 0, "\n".join(
      f"{i}.0 {pull_logs.REMOTE_ROOT}/{route}--{i}" for i in (4, 5, 6)), "")

  monkeypatch.setattr(pull_logs, "_ssh", ssh)
  routes, retained = pull_logs.remote_routes()
  assert routes == [(route, 6., 3)]
  assert retained == {route: {4, 5, 6}}
  assert "-name rlog.zst" in commands[0]


@pytest.mark.parametrize("local_bytes", [b"comp", b"corrupt!"])
def test_pull_rejects_a_local_byte_mismatch_after_successful_rsync(monkeypatch, tmp_path, local_bytes):
  route = "0000004c--bbbbbbbbbb"
  path = tmp_path / f"{route}--0"
  path.mkdir()
  (path / "rlog.zst").write_bytes(local_bytes)
  source_hash = hashlib.sha256(b"complete").hexdigest()

  def ssh(command):
    name = f"{pull_logs.REMOTE_ROOT}/{route}--0"
    output = f"{source_hash}  {name}/rlog.zst\n" if "sha256sum" in command else name + "\n"
    return subprocess.CompletedProcess([], 0, output, "")

  monkeypatch.setattr(pull_logs, "LOCAL_ROOT", tmp_path)
  monkeypatch.setattr(pull_logs, "PULL_ATTEMPTS", 1)
  monkeypatch.setattr(pull_logs, "_ssh", ssh)
  monkeypatch.setattr(pull_logs.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, "", ""))

  assert not pull_logs.pull(route, expected_segments=1)
  errors = [json.loads(line) for line in pull_logs._pull_error_log().read_text().splitlines()]
  assert "checksum" in errors[-1]["detail"]


def test_retained_rlog_checksums_preserve_an_older_local_prefix(monkeypatch, tmp_path):
  route = "0000004c--bbbbbbbbbb"
  for index in range(7):
    path = tmp_path / f"{route}--{index}"
    path.mkdir()
    (path / "rlog.zst").write_bytes(b"complete")
  digest = hashlib.sha256(b"complete").hexdigest()
  monkeypatch.setattr(pull_logs, "LOCAL_ROOT", tmp_path)
  monkeypatch.setattr(pull_logs, "_ssh", lambda _: subprocess.CompletedProcess(
    [], 0, "\n".join(f"{digest}  {pull_logs.REMOTE_ROOT}/{route}--{i}/rlog.zst" for i in (4, 5, 6)), ""))

  assert pull_logs._verify_rlog_hashes(route, [4, 5, 6]) == (True, "")
  assert pull_logs._local_segment_indices(route) == list(range(7))


@pytest.mark.parametrize("output,returncode", [("", 0), ("invalid checksum", 0), ("", 255)])
def test_pull_cannot_accept_unavailable_source_checksums(monkeypatch, tmp_path, output, returncode):
  route = "0000004c--bbbbbbbbbb"
  path = tmp_path / f"{route}--0"
  path.mkdir()
  (path / "rlog.zst").write_bytes(b"complete")

  def ssh(command):
    if "sha256sum" in command:
      return subprocess.CompletedProcess([], returncode, output, "unreachable" if returncode else "")
    return subprocess.CompletedProcess([], 0, f"{pull_logs.REMOTE_ROOT}/{route}--0\n", "")

  monkeypatch.setattr(pull_logs, "LOCAL_ROOT", tmp_path)
  monkeypatch.setattr(pull_logs, "PULL_ATTEMPTS", 1)
  monkeypatch.setattr(pull_logs, "_ssh", ssh)
  monkeypatch.setattr(pull_logs.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, "", ""))
  assert not pull_logs.pull(route, expected_segments=1)


@pytest.mark.parametrize("catalog_count", [2, 3])
def test_pull_pins_closed_source_snapshot_when_next_segment_finishes(monkeypatch, tmp_path, catalog_count):
  route = "0000004c--bbbbbbbbbb"
  digest = hashlib.sha256(b"complete").hexdigest()
  calls = []

  def ssh(command):
    if "sha256sum" in command:
      # Segment 2 finishes while the selected 0/1 snapshot is being copied.
      output = "\n".join(f"{digest}  {pull_logs.REMOTE_ROOT}/{route}--{i}/rlog.zst" for i in (0, 1, 2))
    else:
      output = "\n".join(f"{pull_logs.REMOTE_ROOT}/{route}--{i}" for i in (0, 1))
    return subprocess.CompletedProcess([], 0, output, "")

  def transfer(command, **kwargs):
    calls.append((command, kwargs))
    for name in kwargs["input"].splitlines():
      path = tmp_path / name
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_bytes(b"complete")
    return subprocess.CompletedProcess(command, 0, "", "")

  monkeypatch.setattr(pull_logs, "LOCAL_ROOT", tmp_path)
  monkeypatch.setattr(pull_logs, "_ssh", ssh)
  monkeypatch.setattr(pull_logs.subprocess, "run", transfer)
  monkeypatch.setattr(pull_logs, "PULL_ATTEMPTS", 1)
  assert pull_logs.pull(route, expected_segments=catalog_count)
  assert len(calls) == 1
  assert calls[0][1]["input"].splitlines() == [f"{route}--0/rlog.zst", f"{route}--1/rlog.zst"]
  assert pull_logs._local_segment_indices(route) == [0, 1]


def test_pull_rejects_existing_unverified_tail_outside_closed_snapshot(monkeypatch, tmp_path):
  route = "0000004c--bbbbbbbbbb"
  for i in (0, 1):
    path = tmp_path / f"{route}--{i}"
    path.mkdir()
    (path / "rlog.zst").write_bytes(b"partial" if i else b"complete")
  digest = hashlib.sha256(b"complete").hexdigest()

  def ssh(command):
    path = f"{pull_logs.REMOTE_ROOT}/{route}--0"
    output = f"{digest}  {path}/rlog.zst\n" if "sha256sum" in command else path + "\n"
    return subprocess.CompletedProcess([], 0, output, "")

  monkeypatch.setattr(pull_logs, "LOCAL_ROOT", tmp_path)
  monkeypatch.setattr(pull_logs, "_ssh", ssh)
  monkeypatch.setattr(pull_logs.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, "", ""))
  monkeypatch.setattr(pull_logs, "PULL_ATTEMPTS", 1)
  assert not pull_logs.pull(route, expected_segments=1)
  assert (tmp_path / f"{route}--1/rlog.zst").read_bytes() == b"partial"


def test_transfer_and_checksum_inventory_require_logger_lock_absence(monkeypatch, tmp_path):
  route = "0000004c--bbbbbbbbbb"
  digest = hashlib.sha256(b"complete").hexdigest()
  path = tmp_path / f"{route}--0"
  path.mkdir()
  (path / "rlog.zst").write_bytes(b"complete")
  commands = []

  def ssh(command):
    commands.append(command)
    source = f"{pull_logs.REMOTE_ROOT}/{route}--0"
    output = (f"{digest}  {source}/rlog.zst\n" if "sha256sum" in command else
              f"1.0 {source}\n" if "%T@" in command else source + "\n")
    return subprocess.CompletedProcess([], 0, output, "")

  monkeypatch.setattr(pull_logs, "LOCAL_ROOT", tmp_path)
  monkeypatch.setattr(pull_logs, "_ssh", ssh)
  pull_logs.remote_routes()
  pull_logs._remote_segment_indices(route)
  assert pull_logs._verify_rlog_hashes(route, [0]) == (True, "")
  assert len(commands) == 3
  assert "rlog.lock" not in commands[0]  # The retained catalog must not hide an unfinished tail.
  for command in commands[1:]:
    assert "-execdir /bin/test ! -e ./rlog.lock" in command
  # Exercise the same logger-owned condition on real directories, without GNU find on this host.
  (path / "rlog.lock").touch()
  assert subprocess.run(["/bin/test", "!", "-e", "./rlog.lock"], cwd=path).returncode == 1
  (path / "rlog.lock").unlink()
  assert subprocess.run(["/bin/test", "!", "-e", "./rlog.lock"], cwd=path).returncode == 0


def test_rsync_does_not_copy_newly_closed_files_outside_snapshot(monkeypatch, tmp_path):
  import shutil

  if not shutil.which("rsync"):
    pytest.skip("rsync is required for the transfer integration check")
  route = "0000004c--bbbbbbbbbb"
  remote, local = tmp_path / "remote", tmp_path / "local"
  remote.mkdir()
  local.mkdir()
  for i in (0, 1):
    path = remote / f"{route}--{i}"
    path.mkdir()
    (path / "rlog.zst").write_bytes(b"complete")
  monkeypatch.setattr(pull_logs, "LOCAL_ROOT", local)
  command = pull_logs._pull_command()
  command = [arg for arg in command if not arg.startswith('--rsync-path=')]  # Linux priority wrapper is verified separately.
  command[-2] = str(remote) + "/"  # Local source exercises rsync; no SSH or device access.
  result = subprocess.run(command, input=f"{route}--0/rlog.zst\n", text=True, capture_output=True)
  assert result.returncode == 0, result.stderr
  assert (local / f"{route}--0/rlog.zst").read_bytes() == b"complete"
  assert not (local / f"{route}--1/rlog.zst").exists()


@pytest.mark.parametrize("options", [["--all-new"], ["--route", "0000004c--bbbbbbbbbb"], ["--since-hours", "24"]])
def test_local_mode_never_connects_to_the_device(monkeypatch, tmp_path, options):
  route = "0000004c--bbbbbbbbbb"
  segment = tmp_path / f"{route}--0"
  segment.mkdir()
  (segment / "rlog.zst").write_bytes(b"closed")
  monkeypatch.setattr(pull_logs, "evidence_root", lambda: tmp_path)
  monkeypatch.setattr(pull_logs, "rlog_root", lambda: tmp_path)
  monkeypatch.setattr(pull_logs, "_ssh", lambda *_: pytest.fail("local mode must not connect"))
  calls = []
  monkeypatch.setattr(pull_logs, "validate", lambda rid, desc: calls.append(rid) or 0)
  monkeypatch.setattr(sys, "argv", ["pull_logs.py", *options, "--local"])
  pull_logs.main()
  assert calls == [route]


@pytest.mark.parametrize("local_indices", [[0], [0, 1]])
def test_default_download_checks_device_before_validation(monkeypatch, tmp_path, local_indices):
  route = "0000004c--bbbbbbbbbb"
  for index in local_indices:
    segment = tmp_path / f"{route}--{index}"
    segment.mkdir()
    (segment / "rlog.zst").write_bytes(b"closed")
  monkeypatch.setattr(pull_logs, "evidence_root", lambda: tmp_path)
  monkeypatch.setattr(pull_logs, "rlog_root", lambda: tmp_path)
  calls = []
  monkeypatch.setattr(pull_logs, "validate", lambda rid, desc: calls.append(("validate", rid)) or 0)
  def device():
    calls.append(("device", route))
    return [(route, pull_logs.datetime.now().timestamp(), 2)], {route: {0, 1}}
  monkeypatch.setattr(pull_logs, "remote_routes", device)
  monkeypatch.setattr(pull_logs, "pull", lambda rid, **kw: calls.append(("pull", rid)) or True)
  monkeypatch.setattr(sys, "argv", ["pull_logs.py", "--route", route])
  pull_logs.main()
  expected = [("device", route)]
  if local_indices == [0]:
    expected.append(("pull", route))
  expected.append(("validate", route))
  assert calls == expected


def test_device_list_does_not_download_or_validate(monkeypatch, tmp_path):
  route = "0000004c--bbbbbbbbbb"
  monkeypatch.setattr(pull_logs, "evidence_root", lambda: tmp_path)
  monkeypatch.setattr(pull_logs, "rlog_root", lambda: tmp_path)
  monkeypatch.setattr(pull_logs, "remote_routes", lambda: ([(route, 1., 1)], {route: {0}}))
  monkeypatch.setattr(pull_logs, "pull", lambda *a, **kw: pytest.fail("list must not download"))
  monkeypatch.setattr(pull_logs, "validate", lambda *a: pytest.fail("list must not validate"))
  monkeypatch.setattr(sys, "argv", ["pull_logs.py", "--all-new", "--list"])
  pull_logs.main()


def test_failed_download_is_not_validated(monkeypatch, tmp_path):
  route = "0000004c--bbbbbbbbbb"
  monkeypatch.setattr(pull_logs, "evidence_root", lambda: tmp_path)
  monkeypatch.setattr(pull_logs, "rlog_root", lambda: tmp_path)
  monkeypatch.setattr(pull_logs, "remote_routes", lambda: ([(route, 1., 1)], {route: {0}}))
  monkeypatch.setattr(pull_logs, "pull", lambda *a, **kw: False)
  monkeypatch.setattr(pull_logs, "validate", lambda *a: pytest.fail("failed transfer must not validate"))
  monkeypatch.setattr(sys, "argv", ["pull_logs.py", "--all-new"])
  with pytest.raises(SystemExit) as result:
    pull_logs.main()
  assert result.value.code == 1


def test_remote_transfer_and_checksum_work_run_at_idle_priority(monkeypatch, tmp_path):
  route = "0000004c--bbbbbbbbbb"
  path = tmp_path / f"{route}--0" / "rlog.zst"
  path.parent.mkdir()
  path.write_bytes(b"closed")
  monkeypatch.setattr(pull_logs, "LOCAL_ROOT", tmp_path)
  digest = hashlib.sha256(b"closed").hexdigest()
  commands = []
  def ssh(command):
    commands.append(command)
    return subprocess.CompletedProcess([], 0, f"{digest}  {pull_logs.REMOTE_ROOT}/{route}--0/rlog.zst\n", "")
  monkeypatch.setattr(pull_logs, "_ssh", ssh)
  assert pull_logs._verify_rlog_hashes(route, [0]) == (True, "")
  assert commands[0].startswith("nice -n 19 ionice -c 3 ")
  assert "--rsync-path=nice -n 19 ionice -c 3 rsync" in pull_logs._pull_command()


def test_local_catalog_does_not_validate_an_open_tail_via_its_closed_prefix(monkeypatch, tmp_path):
  route, other = "0000004c--bbbbbbbbbb", "0000004d--cccccccccc"
  for name in (f"{route}--0", f"{route}--1", f"{other}--0", "invalid--0", f"{other}--1.partial"):
    directory = tmp_path / name
    directory.mkdir()
    (directory / "rlog.zst").write_bytes(b"rlog")
  (tmp_path / f"{route}--1/rlog.lock").touch()
  monkeypatch.setattr(pull_logs, "LOCAL_ROOT", tmp_path)
  routes, available = pull_logs.local_routes()
  assert available == {other: {0}}
  assert [(rid, count) for rid, _, count in routes] == [(other, 1)]
