import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sync_upstream


def test_only_recovery_branch_is_allowed():
  assert sync_upstream.ALLOWED_BRANCHES == {"ody-op"}


def test_opendbc_rebase_is_skipped_when_pinned_base_is_already_present(monkeypatch):
  calls = []

  def fake_run(args, **kwargs):
    calls.append((args, kwargs))
    return subprocess.CompletedProcess(args, 0)

  monkeypatch.setattr(sync_upstream, "run", fake_run)

  assert not sync_upstream.opendbc_needs_rebase("compatible-pin", "ody-op")
  assert calls == [
    (["git", "merge-base", "--is-ancestor", "compatible-pin", "ody-op"],
     {"cwd": sync_upstream.OPENDBC, "check": False}),
  ]


def test_opendbc_rebase_is_required_when_pinned_base_is_missing(monkeypatch):
  monkeypatch.setattr(
    sync_upstream,
    "run",
    lambda args, **kwargs: subprocess.CompletedProcess(args, 1),
  )

  assert sync_upstream.opendbc_needs_rebase("new-pin", "ody-op")
