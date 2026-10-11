#!/usr/bin/env bash
# Align the local Odyssey branches with their fork remotes and restore every pinned submodule.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRANCH=ody-op
OPENDBC_PATH=opendbc_repo

fail() {
  echo "refusing: $*" >&2
  exit 1
}

cd "$ROOT_DIR"

test "$(git branch --show-current)" = "$BRANCH" || fail "parent checkout is not $BRANCH"
test -z "$(git status --porcelain --untracked-files=all --ignore-submodules=none)" || \
  fail "parent or a submodule has local changes; commit or stash them first"

# Make the paired repository available before fetching and verifying both remote tips.
git submodule update --init "$OPENDBC_PATH"
test -z "$(git -C "$OPENDBC_PATH" status --porcelain --untracked-files=all)" || \
  fail "nested opendbc checkout has local changes; commit or stash them first"

echo "Fetching brikowski/openpilot:$BRANCH..."
git fetch --prune origin
echo "Fetching brikowski/opendbc:$BRANCH..."
git -C "$OPENDBC_PATH" fetch --prune origin

parent_remote="origin/$BRANCH"
opendbc_remote="origin/$BRANCH"
expected_opendbc="$(git ls-tree "$parent_remote" "$OPENDBC_PATH" | awk '{print $3}')"
remote_opendbc="$(git -C "$OPENDBC_PATH" rev-parse "$opendbc_remote")"
test "$expected_opendbc" = "$remote_opendbc" || \
  fail "remote openpilot and opendbc $BRANCH tips are not paired"

echo "Updating openpilot..."
git switch --force-create "$BRANCH" "$parent_remote"

echo "Updating pinned submodules..."
git submodule update --init --recursive --force

git -C "$OPENDBC_PATH" switch --force-create "$BRANCH" "$opendbc_remote"

pinned_opendbc="$(git ls-tree HEAD "$OPENDBC_PATH" | awk '{print $3}')"
checked_out_opendbc="$(git -C "$OPENDBC_PATH" rev-parse HEAD)"
test "$pinned_opendbc" = "$checked_out_opendbc" || fail "nested opendbc does not match the parent pin"
test -z "$(git status --porcelain --untracked-files=all --ignore-submodules=none)" || \
  fail "checkout is unexpectedly dirty after sync"

echo
echo "Sync complete:"
git status --short --branch
git -C "$OPENDBC_PATH" status --short --branch
git submodule status
