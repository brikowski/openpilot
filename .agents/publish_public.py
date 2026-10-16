#!/usr/bin/env python3
"""Prepare or publish a software-validated ody-op release without custom development tooling.

Build through a temporary Git index: leave the checkout untouched, keep vehicle tests and exact
submodule pins, and inherit the public branch's independent CI configuration. Publication only fast-forwards;
a stale checkout or concurrent public update cannot overwrite newer source. The Monday workflow
runs --publish after software checks; the same command is available manually. The default is a local preview.
"""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

EXCLUDED = {
  'AGENTS.md', 'lefthook.yml', 'tools/check_offroad.py', 'tools/deploy_ody_op.sh',
  'tools/deploy_staging.sh', 'tools/sync_ody_op.sh',
  'openpilot/tools/jotpluggler/layouts/brikowski.json',
  'openpilot/selfdrive/ui/layouts/settings/odyssey_radar.py',
  'openpilot/selfdrive/pandad/odyssey_radar_test.h',
}
PREFIXES = ('.agents/', '.vscode/', '.codex/', '.claude/', 'openpilot/tools/odyssey/')
DIAGNOSTIC_INTEGRATIONS = (
  'openpilot/common/params_keys.h', 'openpilot/system/hardware/hardwared.py',
  'openpilot/system/manager/manager.py', 'openpilot/system/manager/process_config.py',
  'openpilot/selfdrive/pandad/pandad.cc', 'openpilot/selfdrive/ui/layouts/settings/developer.py',
  'openpilot/selfdrive/ui/ui_state.py',
)


def git(repo, *args, env=None, data=None):
  return subprocess.run(['git', *args], cwd=repo, env=env, input=data,
                        stdout=subprocess.PIPE, check=True).stdout.decode().strip()


def public_text(path, text):
  if path in DIAGNOSTIC_INTEGRATIONS:
    text = re.sub(r'^[ \t]*(?://|#) BEGIN ODYSSEY PARKED DIAGNOSTICS\n.*?^[ \t]*(?://|#) END ODYSSEY PARKED DIAGNOSTICS\n',
                  '', text, flags=re.MULTILINE | re.DOTALL)
    if 'ODYSSEY PARKED DIAGNOSTICS' in text or 'OdysseyRadarTest' in text or 'odyssey_radar' in text:
      raise ValueError(f'Unremoved parked diagnostic integration in {path}')
    return text
  if path == 'tools/README.md':
    return text.split('\n## Private Odyssey workflow\n', 1)[0].rstrip() + '\n'
  if path == '.gitignore':
    return ''.join(line for line in text.splitlines(keepends=True)
                   if not line.startswith(('/.agents/', '# Project guidance lives in AGENTS.md')))
  if path == 'pyproject.toml':
    return re.sub(r'^  "lefthook"[^\n]*\n', '', text, flags=re.MULTILINE)
  if path == 'uv.lock':
    # Only the root's hook dependency is custom. Nested projects' unselected extra metadata stays.
    chunks = text.split('[[package]]\n')
    for i, chunk in enumerate(chunks):
      if chunk.startswith('name = "lefthook"\n'):
        chunks[i] = ''
      elif chunk.startswith('name = "openpilot"\n'):
        chunks[i] = re.sub(r'^    \{ name = "lefthook"[^\n]*\n', '', chunk, flags=re.MULTILINE)
    return '[[package]]\n'.join(chunk for chunk in chunks if chunk)
  return text


def build_public(repo, source, parent):
  source, parent = (git(repo, 'rev-parse', f'{ref}^{{commit}}') for ref in (source, parent))
  with tempfile.TemporaryDirectory() as tmp:
    env = {**os.environ, 'GIT_INDEX_FILE': str(Path(tmp) / 'index')}
    git(repo, 'read-tree', source, env=env)
    paths = git(repo, 'ls-files', '-z', env=env).split('\0')
    removed = [p for p in paths if p in EXCLUDED or p.startswith(PREFIXES)]
    if removed:
      git(repo, 'update-index', '--force-remove', '--', *removed, env=env)
    git(repo, 'restore', f'--source={parent}', '--staged', '--', '.github', env=env)
    for path in ('tools/README.md', '.gitignore', 'pyproject.toml', 'uv.lock', *DIAGNOSTIC_INTEGRATIONS):
      if path in paths:
        original = subprocess.run(['git', 'show', f'{source}:{path}'], cwd=repo,
                                  stdout=subprocess.PIPE, check=True).stdout
        cleaned = public_text(path, original.decode()).encode()
        if cleaned != original:
          mode = git(repo, 'ls-files', '-s', '--', path, env=env).split()[0]
          blob = git(repo, 'hash-object', '-w', '--stdin', data=cleaned)
          git(repo, 'update-index', '--cacheinfo', f'{mode},{blob},{path}', env=env)
    tree = git(repo, 'write-tree', env=env)
  if tree == git(repo, 'rev-parse', f'{parent}^{{tree}}'):
    return parent
  message = f'Odyssey stable release from ody-op-test\n\nSource-Commit: {source}\n'
  return git(repo, 'commit-tree', tree, '-p', parent, '-m', message)


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--publish', action='store_true', help='publish this reviewed stable release')
  args = parser.parse_args(argv)
  repo = Path(__file__).resolve().parents[1]
  if git(repo, 'remote', 'get-url', 'origin') not in (
      'https://github.com/brikowski/openpilot', 'https://github.com/brikowski/openpilot.git'):
    raise SystemExit('refusing publication to an unexpected repository')
  git(repo, 'fetch', 'origin', '+refs/heads/ody-op-test:refs/remotes/origin/ody-op-test',
      '+refs/heads/ody-op:refs/remotes/origin/ody-op')
  if git(repo, 'branch', '--show-current') != 'ody-op-test' or git(repo, 'status', '--porcelain'):
    raise SystemExit('release requires a clean ody-op-test checkout and pinned submodules')
  source = git(repo, 'rev-parse', 'HEAD')
  if source != git(repo, 'rev-parse', 'origin/ody-op-test'):
    raise SystemExit('publish development source before preparing its public release')
  parent = git(repo, 'rev-parse', 'origin/ody-op')
  public = build_public(repo, source, parent)
  if public == parent:
    print('No public vehicle changes.')
  else:
    print(git(repo, 'diff', '--stat', parent, public))
    print(f'Public candidate {public} from {source}.')
    if args.publish:
      git(repo, 'push', 'origin', f'{public}:refs/heads/ody-op')
      print(f'Published {public}.')
    else:
      print('Preview only. Use --publish after reviewing this stable release.')


if __name__ == '__main__':
  main()
