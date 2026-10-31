"""Reject private archives in staged files or outgoing commit history."""
import argparse
from pathlib import Path, PurePosixPath
import subprocess


def private_file(path):
  return (path == '.private' or path.startswith('.private/') or
          PurePosixPath(path).name in ('rlog.zst', 'rlog.bz2', 'qlog.zst', 'qlog.bz2') or path.endswith('.rlog'))


def check(repo, committed=False):
  def git(*args):
    return subprocess.check_output(['git', *args], cwd=repo).decode()
  paths = git('diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z').split('\0')
  if committed:
    for revision in git('rev-list', 'HEAD', '--not', '--remotes').splitlines():
      paths.extend(git('ls-tree', '-r', '--name-only', '-z', revision).split('\0'))
  return sorted({path for path in paths if private_file(path)})


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--committed', action='store_true', help='also inspect commits not yet on a remote')
  args = parser.parse_args()
  blocked = check(Path(__file__).resolve().parents[1], args.committed)
  if blocked:
    raise SystemExit('Private logs/evidence must not be committed or pushed:\n' + '\n'.join(blocked))


if __name__ == '__main__':
  main()
