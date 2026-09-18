#!/usr/bin/env python3
"""Rank full-rate Odyssey achieved-jerk events with command-path and domain context."""

import argparse

from extract import PLAN_SOURCE, load
from tuning_metrics import response_jerk_events


GAS_INACTIVE = -30000


def inspect(route, *, threshold, limit):
  data = load(route)
  clean_active = data["active"] & ~data["gas_pressed"] & ~data["brake_pressed"]
  rows = response_jerk_events(
    data["t"], data["atarget"], data["request"], data["accel_command"], data["aego"],
    clean_active, data["brake_request"], data["gas_command"], data["vego"], data["pitch"],
    data["has_lead"], data["plan_source"], data["gear"], data["engine_torque"], data["rpm"],
    gas_inactive=GAS_INACTIVE,
    threshold=threshold, limit=limit,
  )

  print(f"\n=== {data['route']} ===")
  if not rows:
    print(f"no clean achieved-jerk peaks at or above {threshold:.2f} m/s^3")
    return
  for row in rows:
    edge = "none" if row["domain_edge_age"] is None else f"{row['domain_edge_age']:.2f}s"
    source = PLAN_SOURCE.get(row["plan_source"], f"unknown({row['plan_source']})")
    print("".join((
      f"t={row['time']:8.2f}s response={row['response_jerk']:+.2f} m/s^3 ",
      f"prior-wire={row['command_jerk_peak']:+.2f} ({row['amplification']:.1f}x) ",
      f"domain={row['domain']} edge-age={edge} edges/1.5s={row['domain_edges_in_history']}\n",
      f"  plan->request RMS={row['plan_request_rms']:.4f}, request->wire RMS={row['request_wire_rms']:.4f}; ",
      f"request/wire/aEgo={row['request']:+.2f}/{row['wire']:+.2f}/{row['actual_accel']:+.2f} m/s^2; ",
      f"v={row['speed'] * 2.23694:.1f} mph pitch={row['pitch']:+.4f} ",
      f"source={source} lead={int(row['has_lead'])}; gear={row['gear']:.0f} ",
      f"gear-edges/1.5s={row['gear_edges_in_history']} torque={row['engine_torque']:+.0f} ",
      f"rpm={row['rpm']:.0f}",
    )))


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("routes", nargs="+")
  parser.add_argument("--threshold", type=float, default=1.0, help="minimum absolute achieved jerk")
  parser.add_argument("--limit", type=int, default=8, help="maximum events per route")
  args = parser.parse_args()
  for route in args.routes:
    inspect(route, threshold=args.threshold, limit=args.limit)


if __name__ == "__main__":
  main()
