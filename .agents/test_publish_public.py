"""Exercise the public Git tree independently of the working checkout and private tools."""
import subprocess
import re
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

import publish_public as mirror


def test_release_checks_are_independent_of_public_caller_branch():
  workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/odyssey.yaml').read_text()
  step = workflow.split('- name: Test development tools and Odyssey interface\n', 1)[1]
  assert 'github.ref' not in step, 'The public caller must not skip checked-out development tooling'
  group = re.search(r'^  group: (.+)$', workflow, re.MULTILINE).group(1)
  public = group.replace('${{ github.workflow }}', 'Odyssey software checks').replace('${{ github.ref }}', 'refs/heads/ody-op')
  release = group.replace('${{ github.workflow }}', 'Odyssey weekly release').replace('${{ github.ref }}', 'refs/heads/ody-op')
  assert public != release, 'A public-branch push must not cancel release validation'


class TestPublicRelease(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.repo = Path(self.tmp.name)
    self.git('init', '-q', '-b', 'ody-op-test')
    self.git('config', 'user.name', 'Mirror Test')
    self.git('config', 'user.email', 'mirror@example.invalid')
    self.write('.github/workflows/tests.yml', 'public CI\n')
    self.scheduler = (Path(__file__).resolve().parents[1] / '.github/workflows/odyssey-release.yaml').read_text()
    self.write('.github/workflows/odyssey-release.yaml', self.scheduler)
    self.write('car.py', 'baseline\n')
    self.git('add', '.')
    self.git('commit', '-qm', 'upstream')
    self.parent = self.git('rev-parse', 'HEAD')
    self.write('car.py', 'vehicle behavior\n')
    self.write('tests/test_car.py', 'vehicle tests\n')
    self.write('tools/op.sh', 'installation tool\n')
    self.write('tools/README.md', '# tools\n\n## Private Odyssey workflow\nprivate workflow\n')
    self.write('.gitignore', '*.pyc\n/.agents/tune-evidence.md\n# Project guidance lives in AGENTS.md and .agents/.\n')
    self.write('pyproject.toml', '[project]\nname = "openpilot"\n[project.optional-dependencies]\ntesting = [\n  "pytest",\n  "lefthook", # hooks\n]\n')
    self.write('uv.lock', 'version = 1\n\n[[package]]\nname = "lefthook"\nversion = "1"\n\n'
               '[[package]]\nname = "openpilot"\nversion = "1"\n[package.optional-dependencies]\ntesting = [\n'
               '    { name = "lefthook" },\n    { name = "pytest" },\n]\n[package.metadata]\nrequires-dist = [\n'
               '    { name = "lefthook", marker = "extra == \'testing\'" },\n]\n\n'
               '[[package]]\nname = "pytest"\nversion = "1"\n')
    for path in ('AGENTS.md', 'lefthook.yml', 'tools/check_offroad.py', 'tools/deploy_ody_op.sh',
                 'tools/deploy_staging.sh', 'tools/sync_ody_op.sh',
                 'openpilot/tools/jotpluggler/layouts/brikowski.json', '.agents/analysis.py',
                 '.vscode/tasks.json', '.codex/local.json', '.claude/local.json'):
      self.write(path, 'development tooling\n')
    self.write('.github/workflows/tests.yml', 'shared vehicle CI\n')
    self.write('.github/workflows/odyssey-release.yaml', 'unpublished scheduler edit\n')
    self.git('add', '.')
    (self.repo / 'opendbc_repo').mkdir()
    self.git('update-index', '--add', '--cacheinfo', f'160000,{self.parent},opendbc_repo')
    self.git('commit', '-qm', 'development')
    self.source = self.git('rev-parse', 'HEAD')

  def git(self, *args):
    return mirror.git(self.repo, *args)

  def write(self, path, content):
    target = self.repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)

  def public(self, source=None, parent=None):
    return mirror.build_public(self.repo, source or self.source, parent or self.parent)

  def test_vehicle_code_tests_and_pins_are_identical(self):
    public = self.public()
    for path in ('car.py', 'tests/test_car.py', 'tools/op.sh', 'opendbc_repo'):
      self.assertEqual(self.git('ls-tree', self.source, path), self.git('ls-tree', public, path))
    self.assertEqual(self.git('rev-parse', f'{public}^'), self.parent)
    self.assertIn(self.source, self.git('show', '-s', '--format=%B', public))
    self.assertEqual(self.git('rev-parse', 'HEAD'), self.source)
    self.assertEqual(self.git('status', '--porcelain'), '')

  def test_custom_tooling_is_absent_and_public_ci_is_preserved(self):
    public = self.public()
    paths = self.git('ls-tree', '-r', '--name-only', public).splitlines()
    # Explicit names deliberately independent of the implementation's exclusion list.
    for path in ('AGENTS.md', 'lefthook.yml', '.agents/analysis.py', '.vscode/tasks.json',
                 '.codex/local.json', '.claude/local.json', 'tools/check_offroad.py',
                 'tools/deploy_ody_op.sh', 'tools/deploy_staging.sh', 'tools/sync_ody_op.sh',
                 'openpilot/tools/jotpluggler/layouts/brikowski.json'):
      self.assertNotIn(path, paths)
    self.assertEqual(self.git('show', f'{public}:.github/workflows/tests.yml'), 'public CI')
    self.assertEqual(self.git('show', f'{public}:tools/README.md'), '# tools')
    self.assertEqual(self.git('show', f'{public}:.gitignore'), '*.pyc')

  def test_weekly_scheduler_survives_vehicle_releases(self):
    public = self.public()
    self.assertEqual(self.git('show', f'{public}:.github/workflows/odyssey-release.yaml') + '\n', self.scheduler)
    self.write('car.py', 'next vehicle change\n')
    self.git('add', 'car.py')
    self.git('commit', '-qm', 'vehicle update')
    updated = self.public(source='HEAD', parent=public)
    self.assertNotEqual(updated, public)
    self.assertEqual(self.git('show', f'{updated}:.github/workflows/odyssey-release.yaml') + '\n', self.scheduler)

  def test_dependencies_keep_vehicle_tests_without_custom_hooks(self):
    public = self.public()
    project = tomllib.loads(self.git('show', f'{public}:pyproject.toml'))
    self.assertEqual(project['project']['optional-dependencies']['testing'], ['pytest'])
    packages = tomllib.loads(self.git('show', f'{public}:uv.lock'))['package']
    self.assertEqual([p['name'] for p in packages], ['openpilot', 'pytest'])
    self.assertEqual(packages[0]['optional-dependencies']['testing'], [{'name': 'pytest'}])
    self.assertEqual(packages[0]['metadata']['requires-dist'], [])

  def test_tooling_only_changes_do_not_publish_but_vehicle_updates_do(self):
    public = self.public()
    self.assertEqual(self.public(parent=public), public)
    self.write('.agents/analysis.py', 'new analysis\n')
    self.git('add', '.')
    self.git('commit', '-qm', 'tooling only')
    self.assertEqual(self.public(source='HEAD', parent=public), public)
    self.write('car.py', 'next vehicle change\n')
    self.git('add', '.')
    self.git('commit', '-qm', 'vehicle update')
    updated = self.public(source='HEAD', parent=public)
    self.assertNotEqual(updated, public)
    self.assertEqual(self.git('rev-parse', f'{updated}^'), public)
    self.assertEqual(self.git('show', f'{updated}:car.py'), 'next vehicle change')

  def test_publication_preserves_upstream_lfs_pointers_without_uploading(self):
    pointer = ('version https://git-lfs.github.com/spec/v1\n'
               'oid sha256:' + 'a' * 64 + '\nsize 12345\n')
    self.write('models/driving.pkl', pointer)
    self.git('add', 'models/driving.pkl')
    self.git('commit', '-qm', 'upstream model pointer')
    source = self.git('rev-parse', 'HEAD')
    with tempfile.TemporaryDirectory() as remote:
      subprocess.run(['git', 'init', '--bare', '-q', remote], check=True)
      self.git('remote', 'add', 'origin', remote)
      self.git('push', '-q', 'origin', f'{source}:refs/heads/ody-op-test', f'{self.parent}:refs/heads/ody-op')
      self.git('config', 'core.hooksPath', '.git/hooks')
      hook = self.repo / '.git/hooks/pre-push'
      hook.write_text('#!/bin/sh\n'
                      'echo visited >> .git/publish-hook-visits\n'
                      'test "$GIT_LFS_SKIP_PUSH" = 1 || { echo "upstream LFS upload needs credentials" >&2; exit 1; }\n')
      hook.chmod(0o755)
      actual_git = mirror.git

      def local_git(repo, *args, **kwargs):
        if args[:2] == ('remote', 'get-url'):
          return 'https://github.com/brikowski/openpilot.git'
        return actual_git(repo, *args, **kwargs)

      with patch.object(mirror, '__file__', str(self.repo / '.agents/publish_public.py')), \
           patch.object(mirror, 'git', side_effect=local_git), \
           patch.dict(mirror.os.environ, {'GIT_LFS_SKIP_PUSH': '0'}):
        mirror.main(['--publish'])
        self.assertEqual(mirror.os.environ['GIT_LFS_SKIP_PUSH'], '0')
      public = self.git('ls-remote', 'origin', 'refs/heads/ody-op').split()[0]
      self.assertNotEqual(public, self.parent)
      self.assertEqual((self.repo / '.git/publish-hook-visits').read_text(), 'visited\n')
      self.assertEqual(self.git('show', f'{public}:models/driving.pkl') + '\n', pointer)
      self.assertEqual(self.git('rev-parse', f'{public}:opendbc_repo'), self.parent)
      self.assertEqual(self.git('rev-parse', 'HEAD'), source)
      self.assertEqual(self.git('status', '--porcelain'), '')

  def test_unpublished_development_source_cannot_release(self):
    with tempfile.TemporaryDirectory() as remote:
      subprocess.run(['git', 'init', '--bare', '-q', remote], check=True)
      self.git('remote', 'add', 'origin', remote)
      self.git('push', '-q', 'origin', f'{self.source}:refs/heads/ody-op-test', f'{self.parent}:refs/heads/ody-op')
      advanced = self.git('commit-tree', f'{self.source}^{{tree}}', '-p', self.source, '-m', 'development advanced during checks')
      self.git('push', '-q', 'origin', f'{advanced}:refs/heads/ody-op-test')
      actual_git = mirror.git

      def local_git(repo, *args, **kwargs):
        if args[:2] == ('remote', 'get-url'):
          return 'https://github.com/brikowski/openpilot.git'
        return actual_git(repo, *args, **kwargs)

      with patch.object(mirror, '__file__', str(self.repo / '.agents/publish_public.py')), \
           patch.object(mirror, 'git', side_effect=local_git), self.assertRaises(SystemExit):
        mirror.main(['--publish'])
      self.assertEqual(self.git('ls-remote', 'origin', 'refs/heads/ody-op').split()[0], self.parent)
      self.assertEqual(self.git('rev-parse', 'HEAD'), self.source)

  def test_checkout_remote_with_or_without_git_suffix_can_publish(self):
    for remote in ('https://github.com/brikowski/openpilot', 'https://github.com/brikowski/openpilot.git'):
      calls = []

      def fake_git(repo, *args, calls=calls, remote=remote, **kwargs):
        calls.append(args)
        if args[:2] == ('remote', 'get-url'):
          return remote
        if args == ('branch', '--show-current'):
          return 'ody-op-test'
        if args in (('rev-parse', 'HEAD'), ('rev-parse', 'origin/ody-op-test')):
          return 'source'
        if args == ('rev-parse', 'origin/ody-op'):
          return 'public-parent'
        if args[0] == 'push':
          self.fail('Tooling-only update attempted publication')
        return ''

      with self.subTest(remote=remote), patch.object(mirror, 'git', side_effect=fake_git), \
           patch.object(mirror, 'build_public', return_value='public-parent') as build:
        mirror.main(['--publish'])
        build.assert_called_once()
        self.assertFalse(any(c[0] == 'push' for c in calls))

  def test_publication_rejects_an_unexpected_destination(self):
    with patch.object(mirror, 'git', return_value='https://github.com/other/openpilot.git'), \
         self.assertRaises(SystemExit):
      mirror.main([])

  def test_publication_never_forces_a_concurrent_public_update(self):
    calls = []

    def fake_git(repo, *args, **kwargs):
      calls.append(args)
      if args[:2] == ('remote', 'get-url'):
        return 'https://github.com/brikowski/openpilot.git'
      if args in (('rev-parse', 'HEAD'), ('rev-parse', 'origin/ody-op-test')):
        return 'source'
      if args == ('branch', '--show-current'):
        return 'ody-op-test'
      if args == ('rev-parse', 'origin/ody-op'):
        return 'public-parent'
      if args[0] == 'push':
        raise subprocess.CalledProcessError(1, args)
      return ''

    with patch.object(mirror, 'git', side_effect=fake_git), patch.object(mirror, 'build_public', return_value='candidate'), \
         self.assertRaises(subprocess.CalledProcessError):
      mirror.main(['--publish'])
    self.assertEqual(calls[-1], ('push', 'origin', 'candidate:refs/heads/ody-op'))

  def test_only_explicit_publication_pushes(self):
    pushes = []

    def fake_git(repo, *args, **kwargs):
      if args[:2] == ('remote', 'get-url'):
        return 'https://github.com/brikowski/openpilot.git'
      if args == ('branch', '--show-current'):
        return 'ody-op-test'
      if args in (('rev-parse', 'HEAD'), ('rev-parse', 'origin/ody-op-test')):
        return 'source'
      if args == ('rev-parse', 'origin/ody-op'):
        return 'public-parent'
      if args[0] == 'push':
        pushes.append(args)
      return ''

    for argv, expected in (([], []), (['--publish'], [('push', 'origin', 'candidate:refs/heads/ody-op')])):
      with self.subTest(argv=argv), patch.object(mirror, 'git', side_effect=fake_git), \
           patch.object(mirror, 'build_public', return_value='candidate'):
        pushes.clear()
        mirror.main(argv)
        self.assertEqual(pushes, expected)


if __name__ == '__main__':
  unittest.main()
