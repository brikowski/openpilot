#!/usr/bin/env python3
"""Merge official master and its exact opendbc pin without rewriting history.

The default is local only. --publish sends an already-validated pair with explicit remote-tip guards.

Fork workflow definitions are retained. Only the paired gitlink and a generated uv.lock conflict
are otherwise resolved automatically. Other source conflicts abort the merge for manual review. Validate the resulting pair before publishing it.
"""
import argparse
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OPENDBC = REPO / 'opendbc_repo'
BRANCH = 'ody-op-test'
REMOTES = {REPO: 'https://github.com/brikowski/openpilot.git', OPENDBC: 'https://github.com/brikowski/opendbc.git'}


def run(args, *, cwd=None, check=True, capture=False, env=None):
  return subprocess.run(args, cwd=cwd or REPO, check=check, text=True, capture_output=capture, env=env)


def output(args, *, cwd=None):
  return run(args, cwd=cwd, capture=True).stdout.strip()


def contains(repo, base):
  return run(['git', 'merge-base', '--is-ancestor', base, 'HEAD'], cwd=repo, check=False).returncode == 0


def merging(repo):
  return run(['git', 'rev-parse', '-q', '--verify', 'MERGE_HEAD'], cwd=repo, check=False, capture=True).returncode == 0


def start_merge(repo, base):
  result = run(['git', 'merge', '--no-ff', '--no-commit', '--no-log', base], cwd=repo, check=False)
  conflicts = output(['git', 'diff', '--name-only', '--diff-filter=U'], cwd=repo).splitlines()
  if result.returncode and not conflicts:
    raise SystemExit('merge failed before conflict resolution; nothing was pushed')
  return conflicts


def check_pair():
  for repo in (REPO, OPENDBC):
    if output(['git', 'branch', '--show-current'], cwd=repo) != BRANCH:
      raise SystemExit('sync requires ody-op-test in both repositories')
    if output(['git', 'status', '--porcelain'], cwd=repo):
      raise SystemExit('sync requires clean parent and opendbc checkouts')
  old_parent = output(['git', 'rev-parse', 'HEAD'])
  old_child = output(['git', 'rev-parse', 'HEAD'], cwd=OPENDBC)
  if output(['git', 'rev-parse', 'HEAD:opendbc_repo']) != old_child:
    raise SystemExit('parent and opendbc must be paired before sync')

  return old_parent, old_child


def publish(expected_parent, expected_child):
  parent, child = check_pair()
  for repo, expected in ((REPO, expected_parent), (OPENDBC, expected_child)):
    remote = output(['git', 'remote', 'get-url', 'origin'], cwd=repo)
    if remote.removesuffix('.git') != REMOTES[repo].removesuffix('.git'):
      raise SystemExit('refusing an unexpected publication destination')
    if output(['git', 'ls-remote', 'origin', f'refs/heads/{BRANCH}'], cwd=repo).split()[0] != expected:
      raise SystemExit('development advanced during sync/checks; nothing was pushed')
    if not contains(repo, expected):
      raise SystemExit('sync must preserve the previous development history')
  env = {**os.environ, 'GIT_LFS_SKIP_PUSH': '1'}
  for repo, sha in ((OPENDBC, child), (REPO, parent)):
    run(['git', 'push', 'origin', f'{sha}:refs/heads/{BRANCH}'], cwd=repo, env=env)
    assert output(['git', 'ls-remote', 'origin', f'refs/heads/{BRANCH}'], cwd=repo).split()[0] == sha
  print('Published exact paired development revisions; no device deployment.')


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--publish', action='store_true', help='publish an already-validated local pair instead of syncing')
  parser.add_argument('--expected-parent')
  parser.add_argument('--expected-child')
  args = parser.parse_args(argv)
  if args.publish:
    if not args.expected_parent or not args.expected_child:
      parser.error('publication requires both expected remote tips')
    publish(args.expected_parent, args.expected_child)
    return
  old_parent, old_child = check_pair()
  run(['git', 'fetch', '--no-tags', '--no-recurse-submodules', 'upstream', 'master'])
  base = output(['git', 'rev-parse', 'upstream/master'])
  pin = output(['git', 'rev-parse', f'{base}:opendbc_repo'])
  run(['git', 'fetch', '--no-tags', '--no-recurse-submodules', 'upstream', pin], cwd=OPENDBC)
  if contains(REPO, base):
    if not contains(OPENDBC, pin):
      raise SystemExit('existing parent does not contain its compatible opendbc base')
    print('Already synced; existing commits preserved.')
    return

  try:
    conflicts = start_merge(REPO, base)
    if output(['git', 'ls-tree', old_parent, '.github/workflows']):
      run(['git', 'restore', f'--source={old_parent}', '--staged', '--worktree', '--', '.github/workflows'])
      conflicts = [p for p in conflicts if not p.startswith('.github/workflows/')]
    if set(conflicts) - {'opendbc_repo', 'uv.lock'}:
      raise SystemExit('upstream source conflicts require manual review: ' + ', '.join(conflicts))
    if 'uv.lock' in conflicts:
      # Regenerate from the merged manifests; do not choose either side's dependency metadata.
      lock = run(['git', 'show', f'{base}:uv.lock'], capture=True).stdout
      (REPO / 'uv.lock').write_text(lock)
    if not contains(OPENDBC, pin):
      if start_merge(OPENDBC, pin):
        raise SystemExit('opendbc source conflicts require manual review')
      run(['git', 'commit', '-m', 'Sync OpenPilot-pinned opendbc'], cwd=OPENDBC)
    child = output(['git', 'rev-parse', 'HEAD'], cwd=OPENDBC)
    run(['git', 'add', 'opendbc_repo'])
    paths = [line.split(maxsplit=1)[1] for line in output(
      ['git', 'config', '-f', '.gitmodules', '--get-regexp', 'path']).splitlines()]
    other_paths = [p for p in paths if p != 'opendbc_repo']
    if other_paths:
      run(['git', 'submodule', 'update', '--init', '--recursive', '--', *other_paths])
    if (REPO / 'uv.lock').is_file():
      run(['uv', 'lock'])
      run(['git', 'add', 'uv.lock'])
    run(['git', 'diff', '--cached', '--check'])
    run(['git', 'commit', '-m', 'Sync official OpenPilot master'])
  except (subprocess.CalledProcessError, SystemExit):
    for repo in (OPENDBC, REPO):
      if merging(repo):
        run(['git', 'merge', '--abort'], cwd=repo)
    raise

  assert contains(REPO, old_parent) and contains(REPO, base)
  assert contains(OPENDBC, old_child) and contains(OPENDBC, pin)
  assert output(['git', 'rev-parse', 'HEAD:opendbc_repo']) == child
  print('Local sync complete; history preserved. Nothing was pushed.')


if __name__ == '__main__':
  main()
