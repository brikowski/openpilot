import contextlib
import io
import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from openpilot.cereal import log, messaging
from openpilot.common.params import Params
from openpilot.system.manager import manager
from openpilot.system.updated import updated


@pytest.fixture
def params(monkeypatch, tmp_path):
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path / 'params'))
  params = Params()
  params.put_bool('UpdateAvailable', True, block=True)
  params.put_bool('IsOffroad', True, block=True)
  params.put('UpdaterState', 'idle', block=True)
  params.put('UpdaterTargetBranch', 'ody-op-test', block=True)
  return params


@pytest.fixture
def sm():
  sm = messaging.SubMaster(['deviceState', 'pandaStates', 'carParams'])
  sm.data['deviceState'] = messaging.new_message('deviceState').deviceState
  pandas = messaging.new_message('pandaStates', 1)
  pandas.pandaStates[0].pandaType = log.PandaState.PandaType.uno
  sm.data['pandaStates'] = pandas.pandaStates
  for name in sm.services:
    sm.updated[name] = sm.valid[name] = sm.alive[name] = sm.freq_ok[name] = True
  return sm


@pytest.fixture
def staging(monkeypatch, tmp_path):
  base = tmp_path / 'openpilot'
  git_dir = base / '.git'
  git_dir.mkdir(parents=True)
  (git_dir / 'HEAD').write_text('installed revision')
  for path in (git_dir, git_dir / 'HEAD'):
    os.utime(path, (1, 1))
  overlay_init = base / '.overlay_init'
  overlay_init.touch()
  os.utime(overlay_init, (2, 2))
  staging = tmp_path / 'staging'
  finalized = staging / 'finalized'
  finalized.mkdir(parents=True)
  (finalized / '.overlay_consistent').touch()
  monkeypatch.setattr(updated, 'BASEDIR', str(base))
  monkeypatch.setattr(updated, 'OVERLAY_INIT', overlay_init)
  monkeypatch.setattr(updated, 'STAGING_ROOT', str(staging))
  monkeypatch.setattr(updated, 'FINALIZED', str(finalized))
  monkeypatch.setattr(updated, 'cloudlog', Mock())
  run = updated.run

  def staged_command(cmd, cwd=None):
    if cmd == ['git', 'rev-parse', '--abbrev-ref', 'HEAD'] and cwd == str(finalized):
      return 'ody-op-test\n'
    return run(cmd, cwd)

  monkeypatch.setattr(updated, 'run', staged_command)
  return base, staging, finalized


def test_finalized_update_qualifies_with_fresh_offroad_ignition_off_state(params, sm, staging):
  assert manager.should_reboot_for_update(params, sm)


@pytest.mark.parametrize('key,value', [
  ('UpdateAvailable', False), ('IsOffroad', False), ('DisableUpdates', True),
  ('DoShutdown', True), ('DoUninstall', True), ('DoReboot', True),
])
def test_update_policy_and_pending_power_actions_prevent_automatic_reboot(params, sm, staging, key, value):
  params.put_bool(key, value, block=True)
  assert not manager.should_reboot_for_update(params, sm)


@pytest.mark.parametrize('state', [None, 'checking...', 'downloading...', 'finalizing update...'])
def test_updater_must_finish_staging_before_automatic_reboot(params, sm, staging, state):
  if state is None:
    params.remove('UpdaterState')
  else:
    params.put('UpdaterState', state, block=True)
  assert not manager.should_reboot_for_update(params, sm)


def test_started_device_prevents_automatic_reboot(params, sm, staging):
  sm['deviceState'].started = True
  assert not manager.should_reboot_for_update(params, sm)


@pytest.mark.parametrize('service', ['deviceState', 'pandaStates'])
@pytest.mark.parametrize('condition', ['updated', 'valid', 'alive', 'freq_ok'])
def test_missing_invalid_or_stale_vehicle_state_prevents_automatic_reboot(params, sm, staging, service, condition):
  getattr(sm, condition)[service] = False
  assert not manager.should_reboot_for_update(params, sm)


@pytest.mark.parametrize('ignition_field', ['ignitionLine', 'ignitionCan'])
def test_ignition_on_prevents_reboot_even_when_openpilot_is_offroad(params, sm, staging, ignition_field):
  setattr(sm['pandaStates'][0], ignition_field, True)
  assert not manager.should_reboot_for_update(params, sm)


@pytest.mark.parametrize('states', [[], ['unknown'], ['uno', 'unknown'], ['uno', 'uno']])
def test_every_connected_panda_must_confirm_ignition_off(params, sm, staging, states):
  message = messaging.new_message('pandaStates', len(states))
  for panda, kind in zip(message.pandaStates, states, strict=True):
    panda.pandaType = kind
  if states == ['uno', 'uno']:
    message.pandaStates[1].ignitionCan = True
  sm.data['pandaStates'] = message.pandaStates
  assert not manager.should_reboot_for_update(params, sm)


@pytest.mark.parametrize('missing', ['.overlay_init', '.overlay_consistent'])
def test_missing_staging_markers_prevent_reboot(params, sm, staging, missing):
  base, _, finalized = staging
  (base / missing if missing == '.overlay_init' else finalized / missing).unlink()
  assert not manager.should_reboot_for_update(params, sm)


def test_existing_install_backup_prevents_an_update_reboot_loop(params, sm, staging):
  _, stage, _ = staging
  (stage / 'old_openpilot').mkdir()
  assert not manager.should_reboot_for_update(params, sm)


def test_local_checkout_changes_prevent_overwriting_development_work(params, sm, staging):
  base, _, _ = staging
  os.utime(base / '.git' / 'HEAD', (3, 3))
  assert not manager.should_reboot_for_update(params, sm)


@pytest.mark.parametrize('branch', [None, 'ody-op'])
def test_a_staged_update_must_match_the_current_target_branch(params, sm, staging, branch):
  if branch is None:
    params.remove('UpdaterTargetBranch')
  else:
    params.put('UpdaterTargetBranch', branch, block=True)
  assert not manager.should_reboot_for_update(params, sm)


@pytest.mark.parametrize('error', [OSError('read failed'), subprocess.CalledProcessError(1, 'git')])
def test_staging_inspection_failures_defer_the_update_instead_of_crashing(params, sm, staging, monkeypatch, error):
  monkeypatch.setattr(updated, 'run', Mock(side_effect=error))
  assert not manager.should_reboot_for_update(params, sm)


def test_unreadable_staging_marker_defers_the_update(params, sm, staging, monkeypatch):
  monkeypatch.setattr(Path, 'is_file', Mock(side_effect=OSError('read failed')))
  assert not manager.should_reboot_for_update(params, sm)


def mock_manager(monkeypatch, params, sm):
  monkeypatch.setattr(manager, 'Params', lambda: params)
  monkeypatch.setattr(manager, 'managed_processes', {})
  monkeypatch.setattr(manager, 'ensure_running', Mock())
  monkeypatch.setattr(manager, 'cloudlog', Mock())
  monkeypatch.setattr(manager.messaging, 'SubMaster', lambda *args, **kwargs: sm)
  monkeypatch.setattr(manager.messaging, 'PubMaster', Mock())
  monkeypatch.setattr(manager, 'atomic_write', lambda *args, **kwargs: contextlib.nullcontext(io.StringIO()))


def test_manager_uses_graceful_reboot_as_soon_as_the_update_is_ready(params, sm, staging, monkeypatch):
  mock_manager(monkeypatch, params, sm)
  params.put_bool('UpdateAvailable', False, block=True)

  def update(_timeout):
    if sm.update.call_count == 2:
      params.put_bool('UpdateAvailable', True, block=True)
    elif sm.update.call_count > 2:
      pytest.fail('manager did not request the ready update on its next iteration')

  sm.update = Mock(side_effect=update)
  monkeypatch.setattr(manager, 'manager_init', Mock())
  monkeypatch.setattr(manager.signal, 'signal', Mock())
  actions = []
  monkeypatch.setattr(manager, 'manager_cleanup', lambda: actions.append('cleanup'))
  monkeypatch.setattr(manager.HARDWARE, 'reboot', lambda: actions.append('reboot'))
  manager.main()

  assert sm.update.call_count == 2
  assert params.get_bool('DoReboot')
  assert params.get('LastManagerExitReason').startswith('DoReboot ')
  assert actions == ['cleanup', 'reboot']


def test_manager_keeps_running_if_ignition_returns_before_installation(params, sm, staging, monkeypatch):
  mock_manager(monkeypatch, params, sm)
  sm['pandaStates'][0].ignitionLine = True
  sm.update = Mock(side_effect=[None, StopIteration])
  with pytest.raises(StopIteration):
    manager.manager_thread()
  assert not params.get_bool('DoReboot')
