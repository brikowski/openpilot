import subprocess

import pytest

from check_private_files import check


@pytest.fixture
def repo(tmp_path):
  def git(*args):
    return subprocess.check_output(['git', *args], cwd=tmp_path).decode()
  git('init', '-q')
  git('config', 'user.name', 'Privacy test')
  git('config', 'user.email', 'privacy@example.invalid')
  (tmp_path / 'source.py').write_text('vehicle source\n')
  git('add', '.')
  git('commit', '-qm', 'baseline')
  return tmp_path, git


@pytest.mark.parametrize('name', ['.private/evidence/receipt.json', '.private/rlogs/segment/rlog.zst', 'elsewhere/rlog.zst'])
def test_private_archive_and_raw_logs_cannot_be_staged(repo, name):
  root, git = repo
  path = root / name
  path.parent.mkdir(parents=True)
  path.write_bytes(b'synthetic private data')
  git('add', '-f', name)
  assert check(root) == [name]


def test_removing_private_file_does_not_hide_it_from_outgoing_history(repo):
  root, git = repo
  path = root / '.private/receipt.json'
  path.parent.mkdir()
  path.write_text('synthetic receipt')
  git('add', '-f', '.private')
  git('commit', '-qm', 'synthetic private commit')
  git('rm', '-qr', '.private')
  git('commit', '-qm', 'remove synthetic private file')
  assert check(root) == []
  assert check(root, committed=True) == ['.private/receipt.json']


def test_source_and_diagnostic_tools_remain_publishable(repo):
  root, git = repo
  (root / 'source.py').write_text('changed source\n')
  (root / '.agents').mkdir()
  (root / '.agents/analysis.py').write_text('diagnostic source\n')
  git('add', '.')
  assert check(root) == []
  assert check(root, committed=True) == []
