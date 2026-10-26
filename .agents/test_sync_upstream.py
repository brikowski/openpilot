"""Exercise paired sync and publication on isolated local Git repositories."""
import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest

import sync_upstream as sync


def git(repo, *args):
  return subprocess.check_output(['git', '-C', str(repo), *args], text=True, stderr=subprocess.PIPE).strip()


def init(repo, bare=False):
  repo.mkdir(parents=True)
  git(repo, 'init', '--quiet', '--bare' if bare else '--initial-branch=master')
  if not bare:
    git(repo, 'config', 'user.name', 'Sync Test')
    git(repo, 'config', 'user.email', 'sync@example.invalid')
    git(repo, 'config', 'core.hooksPath', '/dev/null')
    git(repo, 'config', 'submodule.recurse', 'false')


def write_commit(repo, path, value, message):
  (repo / path).write_text(value)
  git(repo, 'add', path)
  git(repo, 'commit', '--quiet', '-m', message)
  return git(repo, 'rev-parse', 'HEAD')


@pytest.fixture
def repositories(tmp_path, monkeypatch):
  def create(conflict=False, lock_conflict=False):
    parent = tmp_path / 'checkout'
    child = parent / 'opendbc_repo'
    remotes = {key: tmp_path / key for key in ('official-parent', 'official-child', 'fork-parent', 'fork-child')}
    for remote in remotes.values():
      init(remote, bare=True)
    init(parent)
    init(child)
    base_child = write_commit(child, 'honda', 'Honda baseline\n', 'upstream baseline')
    pin = write_commit(child, 'parser', 'official pinned parser\n', 'official parser')
    unpinned = write_commit(child, 'next', 'must not import yet\n', 'unmatched master')
    git(child, 'remote', 'add', 'upstream', str(remotes['official-child']))
    git(child, 'push', '--quiet', 'upstream', 'master')
    git(child, 'fetch', '--quiet', 'upstream', 'master')
    git(child, 'switch', '--quiet', '--create', 'ody-op-test', base_child)
    old_child = write_commit(child, 'honda', 'Honda tune\n', 'retain Honda tuning')
    git(child, 'remote', 'add', 'origin', str(remotes['fork-child']))
    git(child, 'push', '--quiet', 'origin', 'ody-op-test')
    (parent / '.gitmodules').write_text('[submodule "opendbc"]\n  path = opendbc_repo\n  url = ' + str(remotes['fork-child']) + '\n')
    (parent / 'app').write_text('base\n')
    (parent / '.github/workflows').mkdir(parents=True)
    (parent / '.github/workflows/check.yaml').write_text('fork manual and weekly CI\n')
    git(parent, 'add', '.github/workflows')
    git(parent, 'add', '.gitmodules', 'app')
    if lock_conflict:
      (parent / 'uv.lock').write_text('base metadata\n')
      git(parent, 'add', 'uv.lock')
    git(parent, 'update-index', '--add', '--cacheinfo', f'160000,{base_child},opendbc_repo')
    git(parent, 'commit', '--quiet', '-m', 'upstream baseline')
    base_parent = git(parent, 'rev-parse', 'HEAD')
    (parent / 'official').write_text('official update\n')
    git(parent, 'add', 'official')
    (parent / '.github/workflows/check.yaml').write_text('upstream push CI\n')
    (parent / '.github/workflows/new.yaml').write_text('new upstream push CI\n')
    git(parent, 'add', '.github/workflows')
    if lock_conflict:
      (parent / 'uv.lock').write_text('official metadata\n')
      git(parent, 'add', 'uv.lock')
    if conflict:
      (parent / 'app').write_text('official app\n')
      git(parent, 'add', 'app')
    git(parent, 'update-index', '--cacheinfo', f'160000,{pin},opendbc_repo')
    git(parent, 'commit', '--quiet', '-m', 'official update')
    official_parent = git(parent, 'rev-parse', 'HEAD')
    git(parent, 'remote', 'add', 'upstream', str(remotes['official-parent']))
    git(parent, 'push', '--quiet', 'upstream', 'master')
    git(parent, 'switch', '--quiet', '--create', 'ody-op-test', base_parent)
    (parent / 'fork').write_text('retain fork behavior\n')
    git(parent, 'add', 'fork')
    (parent / '.github/workflows/check.yaml').write_text('fork manual and weekly CI\n')
    git(parent, 'add', '.github/workflows')
    if lock_conflict:
      (parent / 'uv.lock').write_text('fork testing metadata\n')
      git(parent, 'add', 'uv.lock')
    if conflict:
      (parent / 'app').write_text('fork app\n')
      git(parent, 'add', 'app')
    git(parent, 'update-index', '--cacheinfo', f'160000,{old_child},opendbc_repo')
    git(parent, 'commit', '--quiet', '-m', 'retain fork behavior')
    old_parent = git(parent, 'rev-parse', 'HEAD')
    git(parent, 'remote', 'add', 'origin', str(remotes['fork-parent']))
    git(parent, 'push', '--quiet', 'origin', 'ody-op-test')
    monkeypatch.setattr(sync, 'REPO', parent)
    monkeypatch.setattr(sync, 'OPENDBC', child)
    monkeypatch.setattr(sync, 'REMOTES', {parent: str(remotes['fork-parent']), child: str(remotes['fork-child'])})
    return parent, child, old_parent, old_child, official_parent, pin, unpinned, remotes
  return create


def test_sync_preserves_both_histories_and_exact_compatible_pin(repositories):
  parent, child, old_parent, old_child, official, pin, unpinned, _ = repositories()
  sync.main([])
  for repo, old, upstream in ((parent, old_parent, official), (child, old_child, pin)):
    assert git(repo, 'show', '-s', '--format=%P', 'HEAD').split() == [old, upstream]
    assert git(repo, 'status', '--porcelain') == ''
    message = git(repo, 'show', '-s', '--format=%B', 'HEAD')
    assert '#' not in message and 'github.com/' not in message
  assert (parent / '.github/workflows/check.yaml').read_text() == 'fork manual and weekly CI\n'
  assert not (parent / '.github/workflows/new.yaml').exists()
  assert not sync.contains(child, unpinned)
  assert git(parent, 'rev-parse', 'HEAD:opendbc_repo') == git(child, 'rev-parse', 'HEAD')
  assert (parent / 'fork').read_text() == 'retain fork behavior\n'
  assert (parent / 'official').read_text() == 'official update\n'
  assert (child / 'honda').read_text() == 'Honda tune\n'
  assert (child / 'parser').read_text() == 'official pinned parser\n'
  assert git(parent, 'ls-remote', 'origin', 'refs/heads/ody-op-test').split()[0] == old_parent
  assert git(child, 'ls-remote', 'origin', 'refs/heads/ody-op-test').split()[0] == old_child
  heads = [git(repo, 'rev-parse', 'HEAD') for repo in (parent, child)]
  sync.main([])
  assert heads == [git(repo, 'rev-parse', 'HEAD') for repo in (parent, child)]


def test_source_conflict_aborts_without_discarding_work(repositories):
  parent, child, old_parent, old_child, *_ = repositories(conflict=True)
  with pytest.raises(SystemExit, match='source conflicts'):
    sync.main([])
  assert git(parent, 'rev-parse', 'HEAD') == old_parent
  assert git(child, 'rev-parse', 'HEAD') == old_child
  assert git(parent, 'status', '--porcelain') == ''
  assert not sync.merging(parent) and not sync.merging(child)


def test_public_branch_cannot_sync(repositories):
  parent, *_ = repositories()
  git(parent, 'switch', '--quiet', 'master')
  with pytest.raises(SystemExit, match='ody-op-test'):
    sync.main([])


def test_dirty_work_cannot_sync(repositories):
  parent, *_ = repositories()
  (parent / 'fork').write_text('unsaved work\n')
  with pytest.raises(SystemExit, match='clean'):
    sync.main([])
  assert (parent / 'fork').read_text() == 'unsaved work\n'


def test_validated_pair_publishes_without_rewriting_history(repositories):
  parent, child, old_parent, old_child, *_ = repositories()
  sync.main([])
  sync.main(['--publish', '--expected-parent', old_parent, '--expected-child', old_child])
  for repo in (parent, child):
    assert git(repo, 'ls-remote', 'origin', 'refs/heads/ody-op-test').split()[0] == git(repo, 'rev-parse', 'HEAD')


@pytest.mark.parametrize('advance_child', (False, True))
def test_development_advance_prevents_all_publication(repositories, advance_child):
  parent, child, old_parent, old_child, *_, remotes = repositories()
  sync.main([])
  remote = remotes['fork-child' if advance_child else 'fork-parent']
  old = old_child if advance_child else old_parent
  tree = git(remote, 'rev-parse', old + '^{tree}')
  newer = subprocess.check_output(['git', '-C', str(remote), '-c', 'user.name=Concurrent', '-c',
                                   'user.email=concurrent@example.invalid', 'commit-tree', tree, '-p', old, '-m',
                                   'development advanced'], text=True).strip()
  git(remote, 'update-ref', 'refs/heads/ody-op-test', newer, old)
  with pytest.raises(SystemExit, match='advanced'):
    sync.main(['--publish', '--expected-parent', old_parent, '--expected-child', old_child])
  assert git(parent, 'ls-remote', 'origin', 'refs/heads/ody-op-test').split()[0] == (old_parent if advance_child else newer)
  assert git(child, 'ls-remote', 'origin', 'refs/heads/ody-op-test').split()[0] == (newer if advance_child else old_child)


def test_publication_requires_explicit_remote_tips():
  with pytest.raises(SystemExit):
    sync.main(['--publish'])


def test_child_push_failure_does_not_publish_parent(repositories):
  parent, child, old_parent, old_child, *_, remotes = repositories()
  sync.main([])
  hook = remotes['fork-child'] / 'hooks/pre-receive'
  hook.write_text('#!/bin/sh\nexit 1\n')
  hook.chmod(0o755)
  with pytest.raises(subprocess.CalledProcessError):
    sync.main(['--publish', '--expected-parent', old_parent, '--expected-child', old_child])
  assert git(parent, 'ls-remote', 'origin', 'refs/heads/ody-op-test').split()[0] == old_parent
  assert git(child, 'ls-remote', 'origin', 'refs/heads/ody-op-test').split()[0] == old_child


def test_generated_lock_uses_the_completed_submodule_merge(repositories, tmp_path, monkeypatch):
  parent, _, _, _, _, pin, *_ = repositories(lock_conflict=True)
  binary = tmp_path / 'bin'
  binary.mkdir()
  uv = binary / 'uv'
  # A fixture resolver rejects invocation before the new dependency source is present.
  uv.write_text('#!/usr/bin/env python3\nimport pathlib,subprocess\n'
                f'assert subprocess.run(["git","-C","opendbc_repo","merge-base","--is-ancestor","{pin}","HEAD"]).returncode==0\n'
                'assert pathlib.Path("opendbc_repo/parser").read_text()=="official pinned parser\\n"\n'
                'pathlib.Path("uv.lock").write_text("resolved from merged manifests\\n")\n')
  uv.chmod(0o755)
  import os
  monkeypatch.setenv('PATH', str(binary) + os.pathsep + os.environ['PATH'])
  sync.main([])
  assert git(parent, 'show', 'HEAD:uv.lock') == 'resolved from merged manifests'
  assert git(parent, 'status', '--porcelain') == ''


def test_sync_key_uses_ssh_despite_checkout_https_rewrites(repositories):
  _, child, *_ = repositories()
  workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/odyssey-upstream.yaml').read_text()
  push_url = re.search(r'config remote.origin.pushurl (\S+)', workflow).group(1)
  git(child, 'config', 'url.https://github.com/.insteadOf', 'git@github.com:')
  git(child, 'config', 'remote.origin.pushurl', push_url)
  assert git(child, 'remote', 'get-url', '--push', 'origin') == 'ssh://git@github.com/brikowski/opendbc.git'


def test_host_key_download_authenticates_with_the_job_token(tmp_path):
  workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/odyssey-upstream.yaml').read_text()
  step = workflow.split('      - name: Publish checked development pair\n', 1)[1]
  binary = tmp_path / 'bin'
  binary.mkdir()
  curl = binary / 'curl'
  curl.write_text('#!/usr/bin/env python3\nimport json,sys\n'
                  'args=sys.argv[1:]\n'
                  'if "--header" not in args or args[args.index("--header")+1] != "Authorization: Bearer test-actions-token":\n'
                  '  raise SystemExit(22)\n'
                  'assert args[-1] == "https://api.github.com/meta"\n'
                  'print(json.dumps({"ssh_keys":["ssh-rsa ignored", "ssh-ed25519 test-host-key"]}))\n')
  curl.chmod(0o755)
  hosts = tmp_path / 'known_hosts'
  command = step[step.index('curl '):step.index('eval ')]
  command = command.replace('~/.ssh/known_hosts', shlex.quote(str(hosts)))
  result = subprocess.run(['bash', '-eo', 'pipefail', '-c', command], text=True, capture_output=True,
                          env={**os.environ, 'PATH': str(binary) + os.pathsep + os.environ['PATH'],
                               'GITHUB_TOKEN': 'test-actions-token'})
  assert result.returncode == 0, result.stderr
  assert '          GITHUB_TOKEN: ${{ github.token }}\n' in step
  assert hosts.read_text() == 'github.com ssh-ed25519 test-host-key\n'
