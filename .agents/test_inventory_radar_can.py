import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from inventory_radar_can import MessageStats, rank_candidates


def test_message_stats_finds_changing_bytes_and_counter_nibble():
  stats = MessageStats()
  for counter in range(32):
    stats.update(counter * 0.05, bytes([counter & 0xF, 0x80, counter]))
  report = stats.report()
  assert report["frames"] == 32
  assert report["rate_hz"] > 20.0
  assert report["changing_bytes"] == 2
  assert report["byte_change_ratio"] > 0.6
  assert {(row["byte"], row["kind"]) for row in report["counter_candidates"]} >= {
    (0, "low_nibble"), (2, "byte"),
  }


def _route(name, role, messages):
  return {"route": name, "role": role, "messages": messages}


def _message(address, rate=20.0, changing=0.5):
  return {"bus": 1, "address": address, "address_hex": f"0x{address:X}", "length": 8,
          "rate_hz": rate, "route_rate_hz": rate, "changing_byte_fraction": changing,
          "byte_change_ratio": changing / 2}


def test_rank_candidates_prioritizes_repeatable_stock_only_message():
  stock = [
    _route("stock-a", "stock-radar", {"1:0x430:8": _message(0x430), "1:0x100:8": _message(0x100)}),
    _route("stock-b", "stock-radar", {"1:0x430:8": _message(0x430), "1:0x100:8": _message(0x100)}),
  ]
  disabled = [
    _route("off-a", "radar-disabled", {"1:0x100:8": _message(0x100)}),
    _route("off-b", "radar-disabled", {"1:0x100:8": _message(0x100)}),
  ]
  ranked = rank_candidates(stock, disabled)
  assert ranked[0]["key"] == "1:0x430:8"
  assert ranked[0]["stock_routes_present"] == 2
  assert ranked[0]["disabled_routes_present"] == 0
  assert ranked[0]["bus_role"] == "F-CAN B powertrain"


def test_rank_candidates_keeps_partial_presence_visible_without_promoting_it():
  stock = [
    _route("stock-a", "stock-radar", {"1:0x430:8": _message(0x430)}),
    _route("stock-b", "stock-radar", {}),
  ]
  disabled = [_route("off-a", "radar-disabled", {})]
  row = rank_candidates(stock, disabled)[0]
  assert row["stock_routes_present"] == 1
  assert row["stock_routes_total"] == 2


def test_rank_candidates_excludes_extended_diagnostics_by_default():
  stock = [_route("stock-a", "stock-radar", {"1:0x18DAB0F1:8": _message(0x18DAB0F1)})]
  disabled = [_route("off-a", "radar-disabled", {})]
  assert rank_candidates(stock, disabled) == []
  assert rank_candidates(stock, disabled, include_extended=True)[0]["address"] == 0x18DAB0F1
