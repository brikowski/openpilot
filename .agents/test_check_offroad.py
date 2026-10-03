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
git() { if [[ "$*" == *ls-remote* ]]; then echo 'x refs/heads/ody-op'; fi; }
.venv/bin/python() { return 0; }
remote() { printf '%s\\n' "${1//ODY_OP_DEPLOY_COMPLETE/CAPTURED_MARKER}"; return 1; }
'''
  result = subprocess.run(["bash", "-c", script + mocks + command], capture_output=True, text=True)
  assert result.returncode == 1
  code = (root / "tools/check_offroad.py").read_text().strip()
  assert result.stdout.count(code) == (2 if command == "deploy_device" else 1)
  if command == "deploy_device":
    assert result.stdout.index(code) < result.stdout.index("tools/op.sh switch")
    assert result.stdout.rindex(code) < result.stdout.index("sudo reboot")
