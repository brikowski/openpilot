"""Find the ignored, local-only analysis archive."""

import os
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / ".private"


def private_root() -> Path:
  if configured := os.environ.get("OPENPILOT_PRIVATE_ROOT"):
    root = Path(configured).expanduser()
  else:
    root = DEFAULT_ROOT
  if not root.is_dir():
    raise FileNotFoundError(root)
  return root


def rlog_root() -> Path:
  root = Path(os.environ["LOG_ROOT"]).expanduser() if os.environ.get("LOG_ROOT") else private_root() / "rlogs"
  if not root.is_dir():
    raise FileNotFoundError(root)
  return root


def evidence_root() -> Path:
  root = (Path(os.environ["ODYSSEY_EVIDENCE_ROOT"]).expanduser()
          if os.environ.get("ODYSSEY_EVIDENCE_ROOT") else private_root() / "evidence")
  if not root.is_dir():
    raise FileNotFoundError(root)
  return root


def evidence_path(name: str) -> Path:
  try:
    return evidence_root() / name
  except FileNotFoundError:
    # Pure metric tests can import the tools without a private archive. CLI entry points
    # require evidence_root() before they read or write route data.
    return Path(__file__).with_name(name)
