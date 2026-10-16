"""The deployment guard must fail closed on missing, stale or onroad state."""
import importlib.util
import shlex
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

spec = importlib.util.spec_from_file_location("check_offroad", Path(__file__).parents[1] / "tools/check_offroad.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


@pytest.mark.parametrize("offroad,started,updated,valid,alive,timestamp", [
  (False, False, True, True, True, 20),
  (True, True, True, True, True, 20),
  (True, False, False, True, True, 20),
  (True, False, True, False, True, 20),
  (True, False, True, True, False, 20),
  (True, False, True, True, True, 5),
])
def test_deployment_rejects_unconfirmed_offroad_state(offroad, started, updated, valid, alive, timestamp):
  sm = MagicMock()
  sm.updated, sm.valid, sm.alive = ({"deviceState": value} for value in (updated, valid, alive))
  sm.logMonoTime = {"deviceState": timestamp}
  sm.__getitem__.return_value = SimpleNamespace(started=started)
  params = MagicMock()
  params.get_bool.return_value = offroad
  with patch.object(guard.messaging, "SubMaster", return_value=sm), patch.object(guard, "Params", return_value=params), \
       patch.object(guard.time, "monotonic_ns", return_value=10), pytest.raises(SystemExit, match="refusing:"):
    guard.main()


def test_deployment_accepts_new_valid_offroad_state():
  sm = MagicMock()
  sm.updated = sm.valid = sm.alive = {"deviceState": True}
  sm.logMonoTime = {"deviceState": 20}
  sm.__getitem__.return_value = SimpleNamespace(started=False)
  params = MagicMock()
  params.get_bool.return_value = True
  with patch.object(guard.messaging, "SubMaster", return_value=sm), patch.object(guard, "Params", return_value=params), \
       patch.object(guard.time, "monotonic_ns", return_value=10):
    guard.main()
  params.get_bool.assert_called_once_with("IsOffroad")


def test_deployment_rejects_a_parked_capture_hold():
  sm = MagicMock()
  sm.updated = sm.valid = sm.alive = {"deviceState": True}
  sm.logMonoTime = {"deviceState": 20}
  sm.__getitem__.return_value = SimpleNamespace(started=False)
  params = MagicMock()
  params.get_bool.return_value = True
  params.all_keys.return_value = ["IsOffroad", "OdysseyRadarTest"]
  with patch.object(guard.messaging, "SubMaster", return_value=sm), patch.object(guard, "Params", return_value=params), \
       patch.object(guard.time, "monotonic_ns", return_value=10), pytest.raises(SystemExit, match="parked radar capture"):
    guard.main()


@pytest.mark.parametrize("command", ["verify_device", "deploy_device"])
def test_remote_recipes_check_offroad_before_switch_and_reboot(command):
  root = Path(__file__).parents[1]
  script = (root / "tools/deploy_ody_op.sh").read_text().rsplit('\nmain "$@"', 1)[0]
  script = '\n'.join(f"ROOT_DIR={shlex.quote(str(root))}" if line.startswith("ROOT_DIR=") else line
                     for line in script.splitlines())
  # Execute the recipe builder with all external operations replaced. remote
  # captures its argument and terminates; no switch, build, SSH or reboot runs.
  mocks = '''
local_pair() { PARENT_SHA=x; OPENDBC_SHA=x; }
git() { if [[ "$*" == *ls-remote* ]]; then echo 'x refs/heads/ody-op-test'; fi; }
.venv/bin/python() { return 0; }
remote() { printf '%s\\n' "${1//ODY_OP_DEPLOY_COMPLETE/CAPTURED_MARKER}"; return 1; }
'''
  result = subprocess.run(["bash", "-c", script + mocks + command], capture_output=True, text=True)
  assert result.returncode == 1
  code = (root / "tools/check_offroad.py").read_text().strip()
  assert result.stdout.count(code) == (2 if command == "deploy_device" else 1)
  if command == "deploy_device":
    assert "tools/op.sh switch origin 'ody-op-test'" in result.stdout
  else:
    assert "test \"$branch\" = 'ody-op-test'" in result.stdout
  if command == "deploy_device":
    target = "Params().put('UpdaterTargetBranch', 'ody-op-test')"
    assert result.stdout.index(code) < result.stdout.index(target) < result.stdout.index("tools/op.sh switch")
    assert result.stdout.rindex(code) < result.stdout.index("sudo reboot")


@pytest.mark.parametrize("project,global_env,guard_status,expected", [
  (True, True, 0, "project"),
  (False, True, 0, "global"),
  (False, False, 0, None),
  (False, True, 2, "global"),
])
def test_offroad_recipe_selects_available_environment_and_propagates_failure(tmp_path, project, global_env, guard_status, expected):
  root = Path(__file__).parents[1]
  script = (root / "tools/deploy_ody_op.sh").read_text().split("\nusage()", 1)[0]
  script = '\n'.join(f"ROOT_DIR={shlex.quote(str(root))}" if line.startswith("ROOT_DIR=") else line
                     for line in script.splitlines())
  global_python = tmp_path / "global/python3"
  # Relocate the device's global environment into this test's private directory.
  script = script.replace("/usr/local/venv/bin/python3", str(global_python))
  recipe = subprocess.run(["bash", "-c", script + '\nprintf "%s" "$OFFROAD_CHECK"'],
                          capture_output=True, text=True, check=True).stdout
  received = tmp_path / "guard.py"
  for present, path, name in ((project, tmp_path / ".venv/bin/python", "project"),
                              (global_env, global_python, "global")):
    if present:
      path.parent.mkdir(parents=True)
      path.write_text(f"#!/bin/sh\ncat > {shlex.quote(str(received))}\necho {name}\nexit {guard_status}\n")
      path.chmod(0o755)
  result = subprocess.run(["bash", "-c", "set -e\n" + recipe + '\necho guard-passed'],
                          cwd=tmp_path, capture_output=True, text=True)
  if expected is None:
    assert result.returncode != 0
    assert not received.exists()
  else:
    assert result.returncode == guard_status
    assert result.stdout.splitlines()[0] == expected
    assert received.read_text().strip() == (root / "tools/check_offroad.py").read_text().strip()
  assert ("guard-passed" in result.stdout) == (expected is not None and guard_status == 0)


@pytest.mark.parametrize("failure", [
  "none", "parent_branch", "parent_dirty", "child_dirty", "child_branch", "gitlink",
  "read_directory", "read_parent_branch", "read_parent_status", "read_child_status", "read_child_branch",
  "read_parent_revision", "read_child_revision", "read_gitlink",
])
def test_conditional_verification_rejects_invalid_local_source(failure):
  root = Path(__file__).parents[1]
  script = (root / "tools/deploy_ody_op.sh").read_text().rsplit('\nmain "$@"', 1)[0]
  script = '\n'.join(f"ROOT_DIR={shlex.quote(str(root))}" if line.startswith("ROOT_DIR=") else line
                     for line in script.splitlines())
  # Exercise real local_pair guards in the exact conditional/substitution context
  # used by reboot verification. Git and remote calls have no external effects.
  mocks = r'''
cd() { [[ "$failure" != read_directory ]] || return 73; builtin cd "$@"; }
git() {
  case "$*" in
    'branch --show-current') [[ "$failure" == parent_branch ]] && echo ody-op || echo ody-op-test ;;
    'status --porcelain') [[ "$failure" != parent_dirty ]] || echo ' M changed' ;;
    '-C opendbc_repo status --porcelain') [[ "$failure" != child_dirty ]] || echo ' M changed' ;;
    '-C opendbc_repo branch --show-current') [[ "$failure" == child_branch ]] && echo ody-op || echo ody-op-test ;;
    'rev-parse HEAD') echo parent ;;
    '-C opendbc_repo rev-parse HEAD') echo child ;;
    'ls-tree HEAD opendbc_repo')
      if [[ "$failure" == gitlink ]]; then echo '160000 commit other opendbc_repo'; else echo '160000 commit child opendbc_repo'; fi ;;
    'rev-parse HEAD:opendbc_repo') [[ "$failure" == gitlink ]] && echo other || echo child ;;
    *) return 97 ;;
  esac
  case "$failure:$*" in
    'read_parent_branch:branch --show-current'|'read_parent_status:status --porcelain'|\
    'read_child_status:-C opendbc_repo status --porcelain'|'read_child_branch:-C opendbc_repo branch --show-current'|\
    'read_parent_revision:rev-parse HEAD'|'read_child_revision:-C opendbc_repo rev-parse HEAD'|\
    'read_gitlink:ls-tree HEAD opendbc_repo'|'read_gitlink:rev-parse HEAD:opendbc_repo') return 73 ;;
  esac
}
remote() { echo REMOTE_CALLED; }
PARENT_SHA=parent
OPENDBC_SHA=child
if output=$(verify_device 2>&1); then result=accepted; else result=refused; fi
printf '%s\n%s\n' "$result" "$output"
'''
  result = subprocess.run(["bash", "-c", script + "\nfailure=" + shlex.quote(failure) + "\n" + mocks],
                          capture_output=True, text=True, check=True)
  lines = result.stdout.splitlines()
  valid = failure == "none"
  assert lines[0] == ("accepted" if valid else "refused")
  assert ("REMOTE_CALLED" in lines) == valid
