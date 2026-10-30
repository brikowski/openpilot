import hashlib
import os
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

    def upload(self, directory, destination):
      calls.append(('upload', directory.name))
      assert list(directory.iterdir()) == [directory / 'rlog.zst']
      self.remote.setdefault(f'{destination}/{directory.name}/rlog.zst',
                             hashlib.sha1((directory / 'rlog.zst').read_bytes()).hexdigest())

  job.client = Client()
  return SimpleNamespace(root=root, logs=logs, job=job, calls=calls, session=session)


def segment(setup, index=0):
  directory = setup.logs / f'000000aa--aabbccdd--{index}'
  directory.mkdir()
  (directory / 'rlog.zst').write_bytes(b'full-rate evidence')
  (directory / 'fcamera.hevc').write_bytes(b'video must not be uploaded')
  return directory


@pytest.mark.parametrize('condition', [
  'disabled', 'missing-config', 'invalid-config', 'missing-session', 'empty-session', 'symlink-session', 'onroad-or-no-wifi',
])
def test_no_cloud_calls_without_opt_in_login_and_offroad_wifi(setup, condition):
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


def test_opt_out_during_transfer_cancels_child_process(tmp_path):
  root = tmp_path
  (root / 'bin').mkdir()
  client = root / 'bin/proton-drive'
  client.write_text(f'#!{sys.executable}\nimport time, os\nfrom pathlib import Path\n'
                    f'Path({str(root / "child.pid")!r}).write_text(str(os.getpid()))\ntime.sleep(30)\n')
  client.chmod(0o700)
  started = time.monotonic()
  proton = backup.Proton(root, lambda: time.monotonic() - started < 0.2)
  with pytest.raises(backup.Paused):
    proton.call('filesystem', 'info', DESTINATION)
  assert time.monotonic() - started < 4
  with pytest.raises(ProcessLookupError):
    os.kill(int((root / 'child.pid').read_text()), 0)


@pytest.mark.parametrize('started,offroad,network,age,valid,alive,expected', [
  (False, True, 'wifi', 0, True, True, True),
  (True, True, 'wifi', 0, True, True, False),
  (False, False, 'wifi', 0, True, True, False),
  (False, True, 'cell4G', 0, True, True, False),
  (False, True, 'wifi', 4_000_000_000, True, True, False),
  (False, True, 'wifi', 0, False, True, False),
  (False, True, 'wifi', 0, True, False, False),
])
def test_live_gate_requires_fresh_offroad_wifi(monkeypatch, started, offroad, network, age, valid, alive, expected):
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
  gate.params = SimpleNamespace(get_bool=lambda _: offroad)
  monkeypatch.setattr(backup.time, 'monotonic_ns', lambda: 10_000_000_000)
  assert gate() is expected


def test_enable_requires_saved_login_before_any_client_call(setup, monkeypatch):
  setup.session.unlink()
  monkeypatch.setattr(backup, 'ROOT', setup.root)
  monkeypatch.setattr(sys, 'argv', ['backup', 'enable'])
  monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: pytest.fail('client must not start'))
  with pytest.raises(backup.BackupError, match='sign in'):
    backup.main()
