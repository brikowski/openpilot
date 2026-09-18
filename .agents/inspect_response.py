#!/usr/bin/env python3
"""Rank full-rate Odyssey achieved-jerk events with command-path and domain context."""

import argparse
from statistics import median

from extract import PLAN_SOURCE, load
from tuning_metrics import response_jerk_events


GAS_INACTIVE = -30000


def brake_entry_summary(rows, max_edge_age=0.75):
  events = [row for row in rows
            if row["domain"] == "brake" and row["response_jerk"] < 0.0 and
            row["domain_edge_age"] is not None and row["domain_edge_age"] <= max_edge_age]
  if not events:
    return {"count": 0}
  ages = [row["domain_edge_age"] for row in events]
  return {
    "count": len(events),
    "edge_age_min": min(ages),
    "edge_age_max": max(ages),
    "response_jerk_median": median(row["response_jerk"] for row in events),
    "amplification_median": median(row["amplification"] for row in events),
    "without_gear_edge": sum(row["gear_edges_in_history"] == 0 for row in events),
    "plan_request_rms_max": max(row["plan_request_rms"] for row in events),
    "request_wire_rms_max": max(row["request_wire_rms"] for row in events),
  }


def print_brake_entry_summary(rows):
  summary = brake_entry_summary(rows)
  if summary["count"]:
    print("".join((
      f"brake-entry summary: {summary['count']} negative peak(s), edge age ",
      f"{summary['edge_age_min']:.2f}..{summary['edge_age_max']:.2f}s, median response ",
      f"{summary['response_jerk_median']:+.2f} m/s^3, median amplification ",
      f"{summary['amplification_median']:.1f}x, no gear edge ",
      f"{summary['without_gear_edge']}/{summary['count']}, max plan/request/wire RMS ",
      f"{summary['plan_request_rms_max']:.4f}/{summary['request_wire_rms_max']:.4f} m/s^2",
    )))
  else:
    print("brake-entry summary: no qualifying negative peaks")


def inspect(route, *, threshold, limit, summary_only):
  data = load(route)
  clean_active = data["active"] & ~data["gas_pressed"] & ~data["brake_pressed"]
  rows = response_jerk_events(
    data["t"], data["atarget"], data["request"], data["accel_command"], data["aego"],
    clean_active, data["brake_request"], data["gas_command"], data["vego"], data["pitch"],
    data["has_lead"], data["plan_source"], data["gear"], data["engine_torque"], data["rpm"],
    gas_inactive=GAS_INACTIVE,
    threshold=threshold, limit=None,
  )

  print(f"\n=== {data['route']} ===")
  if not rows:
    print(f"no clean achieved-jerk peaks at or above {threshold:.2f} m/s^3")
    return []
  print_brake_entry_summary(rows)
  if summary_only:
    return rows
  display_rows = sorted(sorted(rows, key=lambda row: abs(row["response_jerk"]), reverse=True)[:limit],
                        key=lambda row: row["time"])
  for row in display_rows:
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
  return rows


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("routes", nargs="+")
  parser.add_argument("--threshold", type=float, default=1.0, help="minimum absolute achieved jerk")
  parser.add_argument("--limit", type=int, default=8, help="maximum detailed events per route; summaries use all")
  parser.add_argument("--summary-only", action="store_true", help="print per-route brake-entry summary only")
  args = parser.parse_args()
  combined = []
  for route in args.routes:
    combined.extend(inspect(route, threshold=args.threshold, limit=args.limit, summary_only=args.summary_only))
  if len(args.routes) > 1:
    print("\n=== combined qualifying events ===")
    print_brake_entry_summary(combined)


if __name__ == "__main__":
  main()
