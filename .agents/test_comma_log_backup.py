import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comma_log_backup as backup

DESTINATION = '/my-files/Documents/openpilot/rlogs'


@pytest.fixture
def setup(tmp_path):
  root, logs = tmp_path / 'private', tmp_path / 'logs'
  root.mkdir()
  logs.mkdir()
  backup.write_config(root, {'enabled': True, 'destination': DESTINATION})
  session = root / 'password-store' / backup.SESSION
  session.parent.mkdir(parents=True)
  session.write_bytes(b'fake encrypted session')
  job = backup.Backup(root, logs, lambda: True)
  calls = []

  class Client:
    namespace = 'volume~destination'
    remote = {}

    def info(self, path):
      calls.append(('info', path))
      if path == DESTINATION:
        return {'uid': self.namespace}
      return {'uid': path, 'activeRevision': {'claimedDigests': {'sha1': self.remote.get(path)}, 'claimedSize': len(b'full-rate evidence')}}

    def upload(self, source, destination):
      calls.append(('upload', source.parent.name))
      assert source.name == 'rlog.zst' and source.is_file()
      assert source.parent.parent == logs  # Original source, never a staged copy/link.
      self.remote.setdefault(f'{destination}/{source.parent.name}/rlog.zst',
                             hashlib.sha1(source.read_bytes()).hexdigest())

  job.client = Client()
  return SimpleNamespace(root=root, logs=logs, job=job, calls=calls, session=session)


def segment(setup, index=0):
  directory = setup.logs / f'000000aa--aabbccdd--{index}'
  directory.mkdir()
  (directory / 'rlog.zst').write_bytes(b'full-rate evidence')
  (directory / 'fcamera.hevc').write_bytes(b'video must not be uploaded')
  return directory


@pytest.mark.parametrize('condition', [
  'disabled', 'missing-config', 'invalid-config', 'missing-session', 'empty-session', 'symlink-session', 'no-wifi',
])
def test_no_cloud_calls_without_opt_in_login_and_wifi(setup, condition):
  segment(setup)
  if condition == 'disabled':
    backup.write_config(setup.root, {'enabled': False, 'destination': DESTINATION})
  elif condition == 'missing-config':
    (setup.root / 'config.json').unlink()
  elif condition == 'invalid-config':
    (setup.root / 'config.json').write_text('{')
  elif condition == 'missing-session':
    setup.session.unlink()
  elif condition == 'empty-session':
    setup.session.write_bytes(b'')
  elif condition == 'symlink-session':
    setup.session.unlink()
    setup.session.symlink_to('/etc/passwd')
  else:
    setup.job.state = lambda: False
  assert setup.job.once() == 0
  assert setup.calls == []
  assert not (setup.root / 'receipts.sqlite').exists()


@pytest.mark.parametrize('destination', ['', '/', '/my-files/', '/shared-with-me/logs', '/my-files/../logs'])
def test_invalid_destination_cannot_enable_cloud_access(setup, destination):
  backup.write_config(setup.root, {'enabled': True, 'destination': destination})
  assert setup.job.once() == 0
  assert setup.calls == []


def test_closed_rlogs_only_and_verified_receipts_skip_repeat_uploads(setup):
  closed = segment(setup)
  opened = segment(setup, 1)
  (opened / 'rlog.lock').touch()
  link = setup.logs / '000000aa--aabbccdd--2'
  link.symlink_to(closed, target_is_directory=True)
  assert setup.job.once() == 1
  assert [call for call in setup.calls if call[0] == 'upload'] == [('upload', closed.name)]
  assert setup.job.once() == 0
  assert closed.exists() and opened.exists()
  assert not list(setup.root.glob('transfer-*'))
  with sqlite3.connect(setup.root / 'receipts.sqlite') as db:
    assert db.execute('SELECT sha256 FROM receipts').fetchone()[0] == hashlib.sha256(b'full-rate evidence').hexdigest()


def test_expired_login_cannot_reach_upload(setup):
  segment(setup)

  def expired(_):
    raise backup.BackupError('not signed in')

  setup.job.client.info = expired
  with pytest.raises(backup.BackupError, match='not signed in'):
    setup.job.once()
  assert setup.calls == []


def test_mismatched_remote_content_never_receipted_or_overwritten(setup):
  directory = segment(setup)
  path = f'{DESTINATION}/{directory.name}/rlog.zst'
  setup.job.client.remote[path] = 'wrong-digest'
  with pytest.raises(backup.BackupError, match='digest differs'):
    setup.job.once()
  with sqlite3.connect(setup.root / 'receipts.sqlite') as db:
    assert db.execute('SELECT COUNT(*) FROM receipts').fetchone() == (0,)
  assert setup.job.client.remote[path] == 'wrong-digest'
  assert (directory / 'rlog.zst').read_bytes() == b'full-rate evidence'


def test_interrupted_upload_retries_even_after_remote_commit(setup):
  segment(setup)
  upload = setup.job.client.upload

  def interrupted(*args):
    upload(*args)
    raise backup.BackupError('connection lost after upload')

  setup.job.client.upload = interrupted
  with pytest.raises(backup.BackupError):
    setup.job.once()
  setup.job.client.upload = upload
  assert setup.job.once() == 1
  assert setup.job.once() == 0


def test_other_account_or_folder_does_not_reuse_receipts(setup):
  segment(setup)
  assert setup.job.once() == 1
  setup.job.client.namespace = 'another-account~another-folder'
  assert setup.job.once() == 1


def test_progress_counts_only_confirmed_backups_and_finishes_at_total(setup):
  segment(setup)
  segment(setup, 1)
  snapshots = []
  upload = setup.job.client.upload

  def observe(source, destination):
    snapshots.append(json.loads((setup.root / 'status.json').read_text()))
    upload(source, destination)

  setup.job.client.upload = observe
  assert setup.job.once() == 2
  assert [(row['state'], row['completed'], row['total']) for row in snapshots] == [('uploading', 0, 2), ('uploading', 1, 2)]
  final = json.loads((setup.root / 'status.json').read_text())
  assert (final['state'], final['completed'], final['total']) == ('complete', 2, 2)
  assert set(final) == {'version', 'updated_at', 'state', 'completed', 'total'}
  assert setup.job.once() == 0
  assert json.loads((setup.root / 'status.json').read_text())['state'] == 'complete'


def test_failed_transfer_reports_retrying_without_claiming_completion(setup, monkeypatch):
  segment(setup)

  def failed(*_):
    raise backup.BackupError('connection failed')

  setup.job.client.upload = failed
  monkeypatch.setattr(backup, 'ROOT', setup.root)
  monkeypatch.setattr(backup, 'LiveState', lambda: None)
  monkeypatch.setattr(backup, 'Backup', lambda *args: setup.job)
  monkeypatch.setattr(sys, 'argv', ['backup', 'once'])
  with pytest.raises(SystemExit) as error:
    backup.main()
  assert error.value.code == 1
  final = json.loads((setup.root / 'status.json').read_text())
  assert (final['state'], final['completed'], final['total']) == ('retrying', 0, 1)


@pytest.mark.parametrize('reason', ['disabled', 'sign_in', 'waiting_wifi'])
def test_waiting_reason_is_reported_without_cloud_activity(setup, reason):
  if reason == 'disabled':
    backup.write_config(setup.root, {'enabled': False, 'destination': DESTINATION})
  elif reason == 'sign_in':
    setup.session.unlink()
  else:
    setup.job.state = lambda: False
  assert setup.job.once() == 0
  assert json.loads((setup.root / 'status.json').read_text())['state'] == reason
  assert setup.calls == []


def test_status_write_failure_does_not_stop_backups(setup, monkeypatch):
  segment(setup)

  def unwritable(*_):
    raise OSError('status storage unavailable')

  monkeypatch.setattr(backup, 'write_json', unwritable)
  assert setup.job.once() == 1


def test_progress_heartbeat_stays_fresh_during_long_transfers(setup, monkeypatch):
  now = [0.]
  monkeypatch.setattr(backup.time, 'monotonic', lambda: now[0])
  progress = backup.UploadProgress(setup.root)
  progress.update('uploading', completed=1, total=2)
  now[0] = 600.
  progress.update()
  final = json.loads((setup.root / 'status.json').read_text())
  assert final['updated_at'] == 600.
  assert (final['state'], final['completed'], final['total']) == ('uploading', 1, 2)


def test_source_deletion_during_backup_is_not_prevented_or_reversed(setup):
  directory = segment(setup)

  def deleted(source, destination):
    assert source.stat().st_nlink == 1
    shutil.rmtree(directory)
    raise FileNotFoundError('stock deleter removed the segment')

  setup.job.client.upload = deleted
  assert setup.job.once() == 0
  assert not directory.exists()
  assert not list(setup.root.rglob('rlog.zst'))
  with sqlite3.connect(setup.root / 'receipts.sqlite') as db:
    assert db.execute('SELECT COUNT(*) FROM receipts').fetchone() == (0,)


def test_upload_passes_only_original_rlog_and_skips_conflicts(setup, monkeypatch):
  source = segment(setup) / 'rlog.zst'
  proton = backup.Proton(setup.root, lambda: True)
  calls = []
  monkeypatch.setattr(proton, 'info', lambda _: {'uid': 'existing-folder'})
  monkeypatch.setattr(proton, 'call', lambda *args: calls.append(args))
  proton.upload(source, DESTINATION)
  assert calls == [('filesystem', 'upload', str(source), f'{DESTINATION}/{source.parent.name}',
                    '--file-conflict-strategy', 'skip', '--skip-thumbnails')]


def test_new_remote_segment_folder_is_created_before_direct_file_upload(setup, monkeypatch):
  source = segment(setup) / 'rlog.zst'
  proton = backup.Proton(setup.root, lambda: True)
  calls = []

  def missing(_):
    raise backup.BackupError('not found')

  monkeypatch.setattr(proton, 'info', missing)
  monkeypatch.setattr(proton, 'call', lambda *args: calls.append(args))
  proton.upload(source, DESTINATION)
  assert calls[0] == ('filesystem', 'create-folder', DESTINATION, source.parent.name)
  assert calls[1][0:3] == ('filesystem', 'upload', str(source))


@pytest.mark.parametrize('operation', ['download', 'delete', 'trash', 'move'])
def test_worker_cannot_download_or_delete_cloud_files(setup, monkeypatch, operation):
  proton = backup.Proton(setup.root, lambda: True)
  monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: pytest.fail('client must not start'))
  with pytest.raises(backup.BackupError, match='only upload'):
    proton.call('filesystem', operation, DESTINATION)


def test_opt_out_during_transfer_cancels_child_process(tmp_path):
  root = tmp_path
  (root / 'bin').mkdir()
  client = root / 'bin/proton-drive'
  client.write_text(f'#!{sys.executable}\nimport time, os\nfrom pathlib import Path\n'
                    f'Path({str(root / "child.pid")!r}).write_text(str(os.getpid()))\ntime.sleep(30)\n')
  client.chmod(0o700)
  started = time.monotonic()
  beats = []

  def allowed():
    try:
      ready = int((root / 'child.pid').read_text()) > 0
    except (FileNotFoundError, ValueError):
      ready = False
    return (not ready or not beats) and time.monotonic() - started < 5

  proton = backup.Proton(root, allowed, heartbeat=lambda: beats.append(True))
  with pytest.raises(backup.Paused):
    proton.call('filesystem', 'info', DESTINATION)
  assert time.monotonic() - started < 7
  assert beats
  with pytest.raises(ProcessLookupError):
    os.kill(int((root / 'child.pid').read_text()), 0)


@pytest.mark.parametrize('started,network,age,valid,alive,expected', [
  (False, 'wifi', 0, True, True, True),
  (True, 'wifi', 0, True, True, True),
  (True, 'cell4G', 0, True, True, False),
  (True, 'none', 0, True, True, False),
  (True, 'wifi', 4_000_000_000, True, True, False),
  (True, 'wifi', 0, False, True, False),
  (True, 'wifi', 0, True, False, False),
])
def test_live_gate_requires_fresh_wifi_including_while_driving(monkeypatch, started, network, age, valid, alive, expected):
  gate = backup.LiveState.__new__(backup.LiveState)

  class Messages:
    def update(self, _):
      pass

    def __getitem__(self, _):
      return SimpleNamespace(started=started, networkType=network)

  gate.sm = Messages()
  gate.sm.valid = {'deviceState': valid}
  gate.sm.alive = {'deviceState': alive}
  gate.sm.logMonoTime = {'deviceState': 10_000_000_000 - age}
  monkeypatch.setattr(backup.time, 'monotonic_ns', lambda: 10_000_000_000)
  assert gate() is expected


def test_enable_requires_saved_login_before_any_client_call(setup, monkeypatch):
  setup.session.unlink()
  monkeypatch.setattr(backup, 'ROOT', setup.root)
  monkeypatch.setattr(sys, 'argv', ['backup', 'enable'])
  monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: pytest.fail('client must not start'))
  with pytest.raises(backup.BackupError, match='sign in'):
    backup.main()
