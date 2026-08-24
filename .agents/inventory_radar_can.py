#!/usr/bin/env python3
"""Find raw CAN messages that exist with stock Honda radar but disappear when it is disabled.

This is a discovery tool, not a radar decoder. It inventories native-rate received CAN by
``(bus, address, payload length)`` and compares stock-radar routes with OpenPilot-longitudinal
control routes. A high ranking means only that a message is a useful reverse-engineering
candidate; it does not establish that the payload contains radar objects.

Example::

    uv run python .agents/inventory_radar_can.py \
      --stock-radar 0000002b--4882f84449 \
      --stock-radar 0000003b--08f77bc5c3 \
      --radar-disabled 00000037--0c6fc80a62 \
      --radar-disabled 00000038--5b6729c780 \
      --out /private/tmp/ody-radar-can-inventory.json
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path

from openpilot.common.hardware.hw import Paths
from openpilot.tools.lib.logreader import LogReader


MAX_UNIQUE_PAYLOADS = 4096
MAX_SAMPLES = 8
BUS_ROLES = {
  0: "ACC-CAN radar side",
  1: "F-CAN B powertrain",
  2: "ACC-CAN camera side",
  3: "F-CAN A OBDII",
}


def _route_segments(route, segment_limit=None):
  requested = route.rsplit("/", 1)[-1]
  root = Path(Paths.log_root())
  candidates = [p for p in root.iterdir()
                if p.is_dir() and requested in p.name and (p / "rlog.zst").is_file()]
  route_ids = sorted({p.name.rsplit("--", 1)[0] for p in candidates})
  if not candidates:
    raise SystemExit(f"no local segments matching '{route}' under {root}; pull the route first")
  if len(route_ids) != 1:
    raise SystemExit(f"'{route}' matches multiple routes: {route_ids}; pass the full route id")
  selected = sorted(candidates, key=lambda p: int(p.name.rsplit("--", 1)[-1]))
  if segment_limit is not None:
    selected = selected[:segment_limit]
  return route_ids[0], [str(p / "rlog.zst") for p in selected]


class MessageStats:
  def __init__(self):
    self.count = 0
    self.first_t = None
    self.last_t = None
    self.period_count = 0
    self.period_mean = 0.0
    self.period_m2 = 0.0
    self.previous = None
    self.byte_change_counts = None
    self.bit_flip_counts = None
    self.counter_steps = None
    self.counter_valid = None
    self.unique_payloads = set()
    self.unique_overflow = False
    self.samples = []

  def update(self, timestamp, payload):
    payload = bytes(payload)
    if self.count == 0:
      self.first_t = timestamp
      self.byte_change_counts = [0] * len(payload)
      self.bit_flip_counts = [[0] * 8 for _ in payload]
      # Each byte gets low nibble, high nibble, and full-byte counter hypotheses.
      self.counter_steps = [[0, 0, 0] for _ in payload]
      self.counter_valid = [[0, 0, 0] for _ in payload]
    elif timestamp > self.last_t:
      period = timestamp - self.last_t
      self.period_count += 1
      delta = period - self.period_mean
      self.period_mean += delta / self.period_count
      self.period_m2 += delta * (period - self.period_mean)

    if self.previous is not None:
      for byte_index, (previous, current) in enumerate(zip(self.previous, payload, strict=True)):
        xor = previous ^ current
        self.byte_change_counts[byte_index] += int(xor != 0)
        for bit_index in range(8):
          self.bit_flip_counts[byte_index][bit_index] += int(bool(xor & (1 << bit_index)))
        for counter_index, (mask, shift) in enumerate(((0xF, 0), (0xF, 4), (0xFF, 0))):
          old_value = (previous >> shift) & mask
          new_value = (current >> shift) & mask
          self.counter_steps[byte_index][counter_index] += 1
          self.counter_valid[byte_index][counter_index] += int(new_value == ((old_value + 1) & mask))

    if len(self.unique_payloads) < MAX_UNIQUE_PAYLOADS:
      self.unique_payloads.add(payload)
    elif payload not in self.unique_payloads:
      self.unique_overflow = True
    if len(self.samples) < MAX_SAMPLES and (not self.samples or payload != bytes.fromhex(self.samples[-1])):
      self.samples.append(payload.hex())

    self.count += 1
    self.last_t = timestamp
    self.previous = payload

  def report(self):
    duration = max((self.last_t or 0.0) - (self.first_t or 0.0), 0.0)
    period_std = math.sqrt(self.period_m2 / (self.period_count - 1)) if self.period_count > 1 else 0.0
    counter_candidates = []
    names = ("low_nibble", "high_nibble", "byte")
    for byte_index, steps in enumerate(self.counter_steps or []):
      for counter_index, total in enumerate(steps):
        ratio = self.counter_valid[byte_index][counter_index] / total if total else 0.0
        if total >= 20 and ratio >= 0.8:
          counter_candidates.append({"byte": byte_index, "kind": names[counter_index],
                                     "valid_ratio": ratio, "steps": total})
    changing_bytes = sum(count > 0 for count in (self.byte_change_counts or []))
    transitions = max(self.count - 1, 0)
    byte_slots = transitions * len(self.byte_change_counts or [])
    bit_slots = byte_slots * 8
    return {
      "frames": self.count,
      "duration_s": duration,
      "rate_hz": self.count / duration if duration > 0 else 0.0,
      "period_mean_s": self.period_mean if self.period_count else None,
      "period_cv": period_std / self.period_mean if self.period_mean > 0 else None,
      "changing_bytes": changing_bytes,
      "changing_byte_fraction": changing_bytes / len(self.byte_change_counts) if self.byte_change_counts else 0.0,
      "byte_change_ratio": sum(self.byte_change_counts or []) / byte_slots if byte_slots else 0.0,
      "bit_flip_ratio": (sum(sum(row) for row in (self.bit_flip_counts or [])) / bit_slots
                         if bit_slots else 0.0),
      "byte_change_counts": self.byte_change_counts,
      "bit_flip_counts": self.bit_flip_counts,
      "unique_payloads": f">={MAX_UNIQUE_PAYLOADS + 1}" if self.unique_overflow else len(self.unique_payloads),
      "counter_candidates": counter_candidates,
      "samples": self.samples,
    }


def inventory_route(route, role, segment_limit=None):
  full_route, paths = _route_segments(route, segment_limit=segment_limit)
  stats = defaultdict(MessageStats)
  first_can_t = None
  last_can_t = None
  can_events = 0
  flagged_frames_ignored = 0
  for msg in LogReader(paths):
    if msg.which() != "can":
      continue
    timestamp = msg.logMonoTime / 1e9
    first_can_t = timestamp if first_can_t is None else first_can_t
    last_can_t = timestamp
    can_events += 1
    for frame in msg.can:
      # Panda adds 0x80 to returned transmissions and 0xC0 to rejected transmissions. They are
      # useful for safety debugging, but are not independent messages received from a vehicle bus.
      if frame.src >= 0x80:
        flagged_frames_ignored += 1
        continue
      key = (int(frame.src), int(frame.address), len(frame.dat))
      stats[key].update(timestamp, frame.dat)

  messages = {}
  can_duration = (last_can_t - first_can_t) if first_can_t is not None else 0.0
  for (bus, address, length), message_stats in sorted(stats.items()):
    key = f"{bus}:0x{address:X}:{length}"
    message_report = message_stats.report()
    messages[key] = {"bus": bus, "address": address, "address_hex": f"0x{address:X}",
                     "length": length, **message_report,
                     "route_rate_hz": message_report["frames"] / can_duration if can_duration > 0 else 0.0}
  return {
    "route": full_route,
    "role": role,
    "segments": len(paths),
    "can_events": can_events,
    "flagged_frames_ignored": flagged_frames_ignored,
    "can_duration_s": can_duration,
    "messages": messages,
  }


def rank_candidates(stock_routes, disabled_routes, include_extended=False):
  """Rank cohort differences without claiming that any message encodes an object."""
  keys = sorted({key for route in stock_routes + disabled_routes for key in route["messages"]})
  candidates = []
  for key in keys:
    stock = [route["messages"].get(key) for route in stock_routes]
    disabled = [route["messages"].get(key) for route in disabled_routes]
    stock_present = sum(message is not None for message in stock)
    disabled_present = sum(message is not None for message in disabled)
    if stock_present == 0:
      continue
    stock_messages = [message for message in stock if message is not None]
    disabled_messages = [message for message in disabled if message is not None]
    stock_rate = sum(message["route_rate_hz"] for message in stock_messages) / len(stock_messages)
    disabled_rate = (sum(message["route_rate_hz"] for message in disabled_messages) / len(disabled_messages)
                     if disabled_messages else 0.0)
    changing_fraction = sum(message["changing_byte_fraction"] for message in stock_messages) / len(stock_messages)
    stock_fraction = stock_present / len(stock_routes)
    disabled_fraction = disabled_present / len(disabled_routes) if disabled_routes else 0.0
    exemplar = stock_messages[0]
    if exemplar["address"] > 0x7FF and not include_extended:
      continue
    stock_activity = sum(message["byte_change_ratio"] for message in stock_messages) / len(stock_messages)
    disabled_activity = (sum(message["byte_change_ratio"] for message in disabled_messages) /
                         len(disabled_messages) if disabled_messages else 0.0)
    activity_delta = stock_activity - disabled_activity
    rate_retention = min(disabled_rate / stock_rate, 1.0) if stock_rate > 0 else 1.0
    rate_separation = 1.0 - rate_retention
    # Reproducibility dominates; rate suppression and excess stock-radar activity order candidates.
    score = (5.0 * stock_fraction + 5.0 * (1.0 - disabled_fraction) +
             min(stock_rate, 20.0) / 20.0 + changing_fraction + 2.0 * rate_separation +
             2.0 * max(activity_delta, 0.0))
    candidates.append({
      "key": key,
      "bus": exemplar["bus"],
      "bus_role": BUS_ROLES.get(exemplar["bus"], "unknown"),
      "address": exemplar["address"],
      "address_hex": exemplar["address_hex"],
      "length": exemplar["length"],
      "score": score,
      "stock_routes_present": stock_present,
      "stock_routes_total": len(stock_routes),
      "disabled_routes_present": disabled_present,
      "disabled_routes_total": len(disabled_routes),
      "stock_rate_hz": stock_rate,
      "disabled_rate_hz": disabled_rate,
      "disabled_rate_retention": rate_retention,
      "changing_byte_fraction": changing_fraction,
      "stock_byte_change_ratio": stock_activity,
      "disabled_byte_change_ratio": disabled_activity,
      "byte_change_ratio_delta": activity_delta,
      "stock_route_metrics": {route["route"]: route["messages"].get(key) for route in stock_routes},
      "disabled_route_metrics": {route["route"]: route["messages"].get(key) for route in disabled_routes},
    })
  return sorted(candidates, key=lambda row: (-row["score"], row["bus"], row["address"]))


def analyze(stock_route_ids, disabled_route_ids, segment_limit=None, include_extended=False):
  stock = [inventory_route(route, "stock-radar", segment_limit) for route in stock_route_ids]
  disabled = [inventory_route(route, "radar-disabled", segment_limit) for route in disabled_route_ids]
  return {"stock_radar": stock, "radar_disabled": disabled,
          "candidates": rank_candidates(stock, disabled, include_extended=include_extended)}


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("--stock-radar", action="append", required=True,
                      help="local stock-radar route id/prefix; repeat for multiple routes")
  parser.add_argument("--radar-disabled", action="append", required=True,
                      help="local OpenPilot-longitudinal route id/prefix; repeat for multiple routes")
  parser.add_argument("--segment-limit", type=int,
                      help="development aid: read only the first N segments of each route")
  parser.add_argument("--top", type=int, default=30, help="number of ranked candidates to print")
  parser.add_argument("--include-extended", action="store_true",
                      help="include 29-bit diagnostic addresses in the candidate ranking")
  parser.add_argument("--out", help="write the complete JSON report here")
  args = parser.parse_args(argv)
  report = analyze(args.stock_radar, args.radar_disabled, segment_limit=args.segment_limit,
                   include_extended=args.include_extended)
  if args.out:
    with open(args.out, "w") as handle:
      json.dump(report, handle, indent=2)

  print("Raw CAN candidates (presence difference is not proof of radar-object content):")
  repeatable = [row for row in report["candidates"]
                if row["stock_routes_present"] == row["stock_routes_total"]]
  for row in repeatable[:args.top]:
    line = "".join((
      f"  bus {row['bus']} ({row['bus_role']}) {row['address_hex']}/{row['length']}: ",
      f"score {row['score']:.2f}, ",
      f"stock {row['stock_routes_present']}/{row['stock_routes_total']} at ",
      f"{row['stock_rate_hz']:.1f} Hz, disabled ",
      f"{row['disabled_routes_present']}/{row['disabled_routes_total']} at ",
      f"{row['disabled_rate_hz']:.1f} Hz ({row['disabled_rate_retention']:.0%} retained), changing bytes ",
      f"{row['changing_byte_fraction']:.0%}, activity delta {row['byte_change_ratio_delta']:+.3f}",
    ))
    print(line)
  if args.out:
    print(f"\nJSON report: {args.out}")


if __name__ == "__main__":
  main()
