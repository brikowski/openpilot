#!/usr/bin/env python3
"""Opt-in Wi-Fi backup of closed rlogs using an independently installed Proton CLI.

Install outside the checkout in /data/proton-log-backup. Nothing in OpenPilot starts this tool.
Account sessions, configuration and receipts are device-local and never belong in Git.
"""
import argparse
import fcntl
import hashlib
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path('/data/proton-log-backup')
LOGS = Path('/data/media/0/realdata')
SEGMENT = re.compile(r'[0-9a-f]{8}--[0-9a-f]+--\d+')
SESSION = 'ch.proton.drive/drive-sdk-cli/auth-session.gpg'
OPERATIONS = {('filesystem', 'info'), ('filesystem', 'create-folder'), ('filesystem', 'upload')}


class BackupError(Exception):
  pass


class Paused(BackupError):
  pass


def read_config(root):
  try:
    config = json.loads((root / 'config.json').read_text())
    destination = config.get('destination', '')
    if (config.get('enabled') is not True or not isinstance(destination, str) or
        not destination.startswith('/my-files/') or
        any(part in ('', '.', '..') for part in destination.split('/')[1:])):
      return None
    return config
  except (OSError, ValueError, AttributeError):
    return None


def write_config(root, config):
  write_json(root / 'config.json', config)


def write_json(path, value):
  path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
  with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
    json.dump(value, stream)
    stream.flush()
    os.fsync(stream.fileno())
    temporary = Path(stream.name)
  temporary.replace(path)


class UploadProgress:
  """Publish only aggregate queue state; UI updates must never become display-wake events."""
  def __init__(self, root):
    self.path = root / 'status.json'
    self.values = {'state': 'checking', 'completed': 0, 'total': 0}
    self._published = None
    self._last_write = float('-inf')

  def update(self, state=None, **counts):
    if state is not None:
      self.values['state'] = state
    self.values.update(counts)
    now = time.monotonic()
    if self.values == self._published and now - self._last_write < 5:
      return
    try:
      write_json(self.path, {'version': 1, 'updated_at': now, **self.values})
      self._published = self.values.copy()
      self._last_write = now
    except OSError:
      pass  # A status-display failure must not interrupt backups.


def has_session(root):
  path = root / 'password-store' / SESSION
  return path.is_file() and not path.is_symlink() and path.stat().st_size > 0


def environment(root):
  return {**os.environ,
          'PATH': f'{root}/bin:/usr/bin:/bin',
          'GNUPGHOME': str(root / 'gnupg'),
          'PASSWORD_STORE_DIR': str(root / 'password-store'),
          'PASSWORD_STORE_ENABLE_EXTENSIONS': 'false',
          'PROTON_DRIVE_CREDENTIALS_STORE': 'pass',
          'PROTON_DRIVE_CACHE_DIR': str(root / 'client'),
          'PROTON_DRIVE_LOG_LEVEL': 'ERROR'}


class LiveState:
  """Require current hardwared Wi-Fi state, whether parked or driving."""
  def __init__(self):
    sys.path.insert(0, '/data/openpilot')
    from openpilot.cereal import messaging
    self.sm = messaging.SubMaster(['deviceState'])

  def __call__(self):
    self.sm.update(0)
    ds = self.sm['deviceState']
    age = time.monotonic_ns() - self.sm.logMonoTime['deviceState']
    return (self.sm.valid['deviceState'] and self.sm.alive['deviceState'] and
            0 <= age < 3_000_000_000 and ds.networkType == 'wifi')


def stop_process(process):
  try:
    os.killpg(process.pid, signal.SIGTERM)
    process.wait(timeout=3)
  except subprocess.TimeoutExpired:
    os.killpg(process.pid, signal.SIGKILL)
    process.wait()
  except ProcessLookupError:
    process.wait()


class Proton:
  def __init__(self, root, allowed, heartbeat=lambda: None):
    self.root, self.allowed = root, allowed
    self.heartbeat = heartbeat

  def call(self, *args):
    if tuple(args[:2]) not in OPERATIONS:
      raise BackupError('the backup worker permits only upload and destination metadata operations')
    if not self.allowed():
      raise Paused('waiting for opt-in, login and Wi-Fi')
    # File-backed output avoids deadlock on verbose CLI errors. Never print client output,
    # which could contain account details. No stdin means a background job cannot prompt.
    with tempfile.TemporaryFile() as output:
      process = subprocess.Popen([str(self.root / 'bin/proton-drive'), *args, '--json'],
                                 env=environment(self.root), stdin=subprocess.DEVNULL,
                                 stdout=output, stderr=subprocess.DEVNULL, start_new_session=True)
      deadline = time.monotonic() + 600
      try:
        while process.poll() is None:
          if not self.allowed():
            raise Paused('upload paused: opt-in, login or Wi-Fi changed')
          if time.monotonic() > deadline:
            raise BackupError('Proton command timed out; will retry')
          self.heartbeat()
          time.sleep(0.5)
        if process.returncode:
          raise BackupError('Proton unavailable: check sign-in, connection and quota; will retry')
        output.seek(0)
        return output.read()
      finally:
        if process.poll() is None:
          stop_process(process)

  def info(self, path):
    try:
      node = json.loads(self.call('filesystem', 'info', path))
      if not isinstance(node, dict) or not node.get('uid'):
        raise ValueError('missing node identity')
      return node
    except (ValueError, TypeError) as error:
      raise BackupError('unrecognized Proton metadata; leaving backup unconfirmed') from error

  def upload(self, source, destination):
    parent = f'{destination}/{source.parent.name}'
    try:
      self.info(parent)
    except Paused:
      raise
    except BackupError:
      self.call('filesystem', 'create-folder', destination, source.parent.name)
    self.call('filesystem', 'upload', str(source), parent,
              '--file-conflict-strategy', 'skip', '--skip-thumbnails')


def fingerprint(path):
  stat = path.stat()
  return json.dumps([stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns])


def closed_rlogs(logs):
  if not logs.is_dir():
    return
  for directory in sorted(logs.iterdir()):
    if directory.is_symlink() or not SEGMENT.fullmatch(directory.name) or not directory.is_dir():
      continue
    path = directory / 'rlog.zst'
    if path.is_file() and not path.is_symlink() and not (directory / 'rlog.lock').exists():
      yield path


class Backup:
  def __init__(self, root, logs, state):
    self.root, self.logs, self.state = root, logs, state
    self.progress = UploadProgress(root)
    self.client = Proton(root, self.allowed, self.progress.update)

  def allowed(self):
    return read_config(self.root) is not None and has_session(self.root) and self.state()

  def report_waiting(self):
    state = 'disabled' if read_config(self.root) is None else 'waiting_wifi' if has_session(self.root) else 'sign_in'
    self.progress.update(state)

  def once(self):
    if not self.allowed():
      self.report_waiting()
      return 0
    config = read_config(self.root)
    destination = config['destination']
    self.client.allowed = lambda: self.allowed() and read_config(self.root)['destination'] == destination
    self.progress.update('checking')
    # An existing destination must be accessible with the currently signed-in account.
    # Its UID also prevents receipts for one account/folder from skipping another's backup.
    namespace = self.client.info(destination)['uid']
    completed = 0
    with sqlite3.connect(self.root / 'receipts.sqlite') as receipts:
      receipts.execute('CREATE TABLE IF NOT EXISTS receipts '
                       '(namespace TEXT, segment TEXT, fingerprint TEXT, sha256 TEXT, '
                       'PRIMARY KEY(namespace, segment))')
      sources = []
      verified = 0
      total = 0
      for source in closed_rlogs(self.logs):
        try:
          before = fingerprint(source)
          row = receipts.execute('SELECT fingerprint FROM receipts WHERE namespace=? AND segment=?',
                                 (namespace, source.parent.name)).fetchone()
          total += 1
          if row and row[0] == before:
            verified += 1
          else:
            sources.append(source)
        except FileNotFoundError:
          continue
      self.progress.update('uploading' if verified < total else 'complete', completed=verified, total=total)
      for source in sources:
        if not self.allowed() or read_config(self.root)['destination'] != destination:
          self.report_waiting()
          break
        segment = source.parent.name
        try:
          before = fingerprint(source)
          with source.open('rb') as stream:
            sha1 = hashlib.file_digest(stream, 'sha1').hexdigest()
            stream.seek(0)
            sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
          if (source.parent / 'rlog.lock').exists() or fingerprint(source) != before:
            continue
          # Read the original file directly. Never copy, link, restore, or preserve source logs;
          # the stock deleter owns their lifetime, even if that interrupts a backup.
          self.client.upload(source, destination)
          remote = self.client.info(f'{destination}/{segment}/rlog.zst')
          revision = remote.get('activeRevision') or {}
          digest = (revision.get('claimedDigests') or {}).get('sha1')
          if digest != sha1 or revision.get('claimedSize') != source.stat().st_size:
            raise BackupError('remote rlog digest differs; leaving backup unconfirmed')
          after = fingerprint(source)
          if after != before:
            continue
          receipts.execute('INSERT OR REPLACE INTO receipts VALUES (?, ?, ?, ?)',
                           (namespace, segment, after, sha256))
          receipts.commit()
          completed += 1
          verified += 1
          self.progress.update('uploading' if verified < total else 'complete', completed=verified)
        except FileNotFoundError:
          total -= 1
          self.progress.update(total=total)
          continue  # Source deletion is authoritative, including during a transfer.
      else:
        self.progress.update('complete' if verified == total else 'pending')
    return completed


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('command', choices=('run', 'once', 'status', 'enable', 'disable', 'login', 'logout'))
  parser.add_argument('--destination', default='/my-files/Documents/openpilot/rlogs')
  args = parser.parse_args()
  os.umask(0o077)
  if args.command == 'status':
    print(json.dumps({'enabled': read_config(ROOT) is not None, 'saved_session': has_session(ROOT)}))
    return
  if args.command in ('disable', 'login', 'logout'):
    write_config(ROOT, {'enabled': False, 'destination': args.destination})
    UploadProgress(ROOT).update('disabled')
    if args.command != 'disable':
      subprocess.run([str(ROOT / 'bin/proton-drive'), 'auth', args.command], env=environment(ROOT), check=True)
    return
  if args.command == 'enable':
    if not has_session(ROOT):
      raise BackupError('sign in using the login command before enabling backups')
    config = {'enabled': True, 'destination': args.destination}
    # Validate configuration locally before making any cloud call.
    with tempfile.TemporaryDirectory() as temp:
      write_config(Path(temp), config)
      if read_config(Path(temp)) is None:
        raise BackupError('destination must be an explicit folder under /my-files/')
    Proton(ROOT, lambda: has_session(ROOT)).info(args.destination)
    write_config(ROOT, config)
    UploadProgress(ROOT).update('checking')
    print('backup enabled; waiting for fresh Wi-Fi state')
    return
  backup = Backup(ROOT, LOGS, LiveState())
  with (ROOT / 'run.lock').open('w') as lock:
    try:
      fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
      raise BackupError('another backup process is running') from error
    while True:
      try:
        completed = backup.once()
        if completed:
          print(f'verified {completed} rlog backup(s)', flush=True)
      except (BackupError, OSError, sqlite3.Error) as error:
        if isinstance(error, Paused):
          backup.report_waiting()
        else:
          backup.progress.update('retrying')
        print(str(error), flush=True)
        if args.command == 'once':
          raise SystemExit(1) from error
      if args.command == 'once':
        return
      time.sleep(30)


if __name__ == '__main__':
  try:
    main()
  except BackupError as error:
    sys.exit(str(error))
