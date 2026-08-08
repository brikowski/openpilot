#!/usr/bin/env python3
"""Rebase both tuning repositories locally onto openpilot's compatible upstream pair.

This script deliberately never pushes. It resolves only opendbc_repo gitlink conflicts; any source
conflict is left for a human to inspect. Run the full validation task after it completes, then use
the separate publish task if the result should replace the remote rebased branch.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OPENDBC = REPO / "opendbc_repo"
ALLOWED_BRANCHES = {"ody-op", "ody-op-long"}


def run(args, *, cwd=REPO, check=True, capture=False, env=None):
  result = subprocess.run(args, cwd=cwd, check=False, text=True,
                          capture_output=capture, env=env)
  if check and result.returncode:
    if capture:
      print(result.stdout, end="")
      print(result.stderr, end="", file=sys.stderr)
    raise subprocess.CalledProcessError(result.returncode, args)
  return result


def output(args, *, cwd=REPO):
  return run(args, cwd=cwd, capture=True).stdout.strip()


def clean_or_exit():
  parent = output(["git", "status", "--porcelain"])
  child = output(["git", "status", "--porcelain"], cwd=OPENDBC)
  if parent or child:
    sys.exit("refusing local rebase: both openpilot and opendbc_repo must be clean")


def rebase_in_progress():
  git_dir = Path(output(["git", "rev-parse", "--git-dir"]))
  if not git_dir.is_absolute():
    git_dir = REPO / git_dir
  return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()


def resolve_parent_gitlinks(new_opendbc):
  env = {**os.environ, "GIT_EDITOR": "true"}
  while rebase_in_progress():
    unresolved = output(["git", "diff", "--name-only", "--diff-filter=U"]).splitlines()
    if unresolved == ["opendbc_repo"]:
      run(["git", "update-index", "--cacheinfo", f"160000,{new_opendbc},opendbc_repo"])
    elif unresolved:
      sys.exit("parent rebase stopped for source conflict(s):\n  " + "\n  ".join(unresolved) +
               "\nResolve them normally, then continue the rebase. Nothing was pushed.")

    continued = run(["git", "rebase", "--continue"], check=False, capture=True, env=env)
    if continued.returncode == 0:
      continue

    # --continue exits nonzero when it lands this commit but the NEXT one conflicts. Fresh
    # conflicts belong to the loop head, which classifies them (gitlink -> auto-resolve, source
    # -> stop with instructions). Bailing here instead left the 2026-08-08 rebase stopped at
    # commit 2 of 13 over a plain gitlink conflict that the loop itself knew how to resolve.
    if output(["git", "diff", "--name-only", "--diff-filter=U"]):
      continue

    # A parent commit that only moved the old opendbc pointer can become empty after every gitlink
    # conflict is deliberately resolved to the final rebased opendbc SHA. Skip only that proven
    # pointer-only commit; never discard a source change.
    names = output(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "REBASE_HEAD"]).splitlines()
    if names == ["opendbc_repo"]:
      run(["git", "rebase", "--skip"], env=env)
      continue
    print(continued.stdout, end="")
    print(continued.stderr, end="", file=sys.stderr)
    sys.exit("parent rebase needs manual attention. Nothing was pushed.")


def main():
  branch = output(["git", "branch", "--show-current"])
  if branch not in ALLOWED_BRANCHES:
    sys.exit(f"refusing local rebase on {branch!r}; expected one of {sorted(ALLOWED_BRANCHES)}")
  if output(["git", "branch", "--show-current"], cwd=OPENDBC) != branch:
    sys.exit("parent and opendbc_repo must be on the same tuning branch")
  clean_or_exit()

  print("Fetching openpilot upstream and opendbc upstream...")
  run(["git", "fetch", "upstream"])
  run(["git", "fetch", "upstream"], cwd=OPENDBC)
  pinned = output(["git", "ls-tree", "upstream/master", "opendbc_repo"]).split()
  if len(pinned) < 3:
    sys.exit("could not resolve the opendbc commit pinned by openpilot upstream/master")
  pinned_sha = pinned[2]

  print(f"Rebasing opendbc_repo onto openpilot's pinned {pinned_sha[:12]}...")
  child_rebase = run(["git", "rebase", pinned_sha], cwd=OPENDBC, check=False)
  if child_rebase.returncode:
    run(["git", "rebase", "--abort"], cwd=OPENDBC, check=False)
    sys.exit("opendbc source conflict; rebase aborted and nothing was pushed")
  new_opendbc = output(["git", "rev-parse", "HEAD"], cwd=OPENDBC)

  # Temporarily detach the submodule worktree at the pointer recorded by the parent. The rebased
  # branch ref remains at new_opendbc, while the parent rebase gets the clean tree git requires.
  run(["git", "submodule", "update", "--checkout", "opendbc_repo"])
  print("Rebasing openpilot; only the opendbc_repo pointer is auto-resolved...")
  parent_rebase = run(["git", "rebase", "upstream/master"], check=False)
  if parent_rebase.returncode:
    resolve_parent_gitlinks(new_opendbc)

  # Update every upstream-owned submodule, then reattach the tuned opendbc worktree to its branch.
  paths = output(["git", "config", "-f", ".gitmodules", "--get-regexp", "path"]).splitlines()
  for line in paths:
    path = line.split(maxsplit=1)[1]
    if path != "opendbc_repo":
      run(["git", "submodule", "update", "--init", "--recursive", path])
  run(["git", "checkout", branch], cwd=OPENDBC)

  recorded = output(["git", "ls-tree", "HEAD", "opendbc_repo"]).split()[2]
  if recorded != new_opendbc:
    run(["git", "add", "opendbc_repo"])
    run(["git", "commit", "-m", "honda: update opendbc after upstream rebase"])
    recorded = output(["git", "ls-tree", "HEAD", "opendbc_repo"]).split()[2]
  if recorded != new_opendbc:
    sys.exit(f"rebased parent pins {recorded}, but opendbc_repo is {new_opendbc}")

  print("\nLocal rebase complete; nothing was pushed.")
  print("Run 'Run Checks', inspect the net tune diff, then explicitly publish or deploy.")
  run(["git", "diff", "--stat", f"{pinned_sha}..{branch}"], cwd=OPENDBC)


if __name__ == "__main__":
  main()
