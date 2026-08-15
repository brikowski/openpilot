#!/usr/bin/env python3
"""Reverse-engineer Honda stock-radar ACC_CONTROL from private full-rate rlogs.

The tool compares the command stream that stock Honda radar delivered with the stream our
OpenPilot car-port delivered. It records every ACC_CONTROL field, preserves native CAN timing,
aligns vehicle/planner context with zero-order hold, exports an event CSV, and reports a
route-held-out gas-command model.

Example::

    uv run python .agents/analyze_radar_commands.py \
      --stock-radar 0000002b--4882f84449 \
      --stock-radar 0000003b--08f77bc5c3 \
      --openpilot 00000038--5b6729c780 \
      --openpilot 00000039--ae57d5ce6e \
      --out /tmp/ody-radar-command-analysis.json \
      --events /tmp/ody-radar-command-events.csv

This is command-shape evidence only. It never writes a live command, changes a tune, or treats
the fitted value as acceleration/torque. Use a controlled road drive to validate any candidate.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import numpy as np

from openpilot.common.hardware.hw import Paths
from openpilot.tools.lib.logreader import LogReader
from opendbc.can.dbc import DBC, SignalType
from opendbc.can.parser import CANParser, get_raw_value

sys.path.insert(0, str(Path(__file__).resolve().parent))
from radar_command_metrics import (
  FEATURE_NAMES,
  binned_summary,
  command_domain,
  cross_route_regression,
  domain_seconds,
  feature_matrix,
  pooled_regression,
  quantiles,
  regression_metrics,
  transition_metrics,
)
from tuning_metrics import brake_episode_metrics, hold_last


ODYSSEY_PT_DBC = "acura_rdx_2020_can_generated"
ACC_CONTROL_ADDRESS = 0x1DF
LOGID_RE = re.compile(r"(?P<route>[0-9a-f]{8}--[0-9a-f]+)")
SPEED_EDGES = (3.0, 8.0, 13.0, 18.0, 23.0, 28.0, 33.0, 38.0)
ACCEL_EDGES = (-0.4, -0.2, -0.1, 0.0, 0.1, 0.2, 0.4, 0.8, 1.2, 2.2)

ACC_FIELDS = (
  "GAS_COMMAND", "ACC_ENABLED", "ACC_FAULTED", "CONTROL_ON", "ACCEL_COMMAND", "AEB_STATUS",
  "BRAKE_REQUEST", "STANDSTILL", "STANDSTILL_RELEASE", "MAYBE_DISENGAGE_COMMAND", "AEB_PREPARE",
  "AEB_BRAKING", "MAYBE_DISENGAGE_ALERT", "BRAKE_LIGHTS", "COUNTER", "CHECKSUM",
)
ACC_META_FIELDS = ("_checksum_ok", "_counter_ok")


def _decode_acc_frame(dbc, payload, previous_counter):
  """Decode raw ACC_CONTROL bytes and separately report integrity bits.

  CANParser intentionally rejects bad-checksum/counter frames. Reverse engineering must retain
  those frames, so this uses the DBC signal definitions directly and records the integrity result
  as metadata instead of dropping the command.
  """
  message = dbc.addr_to_msg[ACC_CONTROL_ADDRESS]
  values = {}
  checksum_ok = True
  counter_ok = True
  current_counter = None
  for name, signal in message.sigs.items():
    raw = get_raw_value(payload, signal)
    if signal.is_signed:
      raw -= ((raw >> (signal.size - 1)) & 0x1) * (1 << signal.size)
    values[name] = raw * signal.factor + signal.offset
    if signal.calc_checksum is not None:
      checksum_ok &= raw == signal.calc_checksum(ACC_CONTROL_ADDRESS, signal, bytearray(payload))
    if signal.type == SignalType.COUNTER:
      current_counter = raw
      if previous_counter is not None:
        counter_ok &= raw == ((previous_counter + 1) & ((1 << signal.size) - 1))
  return values, checksum_ok, counter_ok, current_counter


def _route_segments(route):
  """Resolve a full route id or unique route prefix to local rlog segments."""
  requested = route.rsplit("/", 1)[-1]
  root = Path(Paths.log_root())
  candidates = [p for p in root.iterdir() if p.is_dir() and requested in p.name]
  route_ids = sorted({p.name.rsplit("--", 1)[0] for p in candidates})
  if not candidates:
    raise SystemExit(f"no local segments matching '{route}' under {root}; pull the route first")
  if len(route_ids) != 1:
    raise SystemExit(f"'{route}' matches multiple routes: {route_ids}; pass the full route id")
  selected = sorted(candidates, key=lambda p: int(p.name.rsplit("--", 1)[-1]))
  return route_ids[0], [str(p / "rlog.zst") for p in selected]


def _field(obj, name, default=np.nan):
  """Read a capnp field without making optional streams fatal."""
  try:
    return getattr(obj, name)
  except (AttributeError, IndexError, TypeError):
    return default


def _append(series, key, timestamp, value):
  series[key]["t"].append(timestamp)
  series[key]["v"].append(value)


def _new_series():
  names = (
    "request", "active", "pitch", "vego", "aego", "gas_pressed", "brake_pressed", "atarget",
    "allow_throttle", "has_lead", "should_stop", "lead_present", "lead_drel", "lead_vrel",
    "lead_vlead", "lead_prob", "engine_torque", "rpm", "gear", "gasfactor", "windfactor",
  )
  return {name: {"t": [], "v": []} for name in names}


def _decode_route(route, role):
  """Decode one route, retaining both possible ACC_CONTROL origins and all context streams."""
  full_route, paths = _route_segments(route)
  acc_dbc = DBC(ODYSSEY_PT_DBC)
  previous_counter = dict.fromkeys(("can", "sendcan"))
  acc = {source: {key: [] for key in ("t", *ACC_FIELDS, *ACC_META_FIELDS, "raw_hex")}
         for source in ("can", "sendcan")}
  # These are optional context signals. Ignore their alive timeout so a route without one of the
  # messages does not turn the ACC_CONTROL decoder into a warning printer.
  recv = CANParser(ODYSSEY_PT_DBC, [("VSA_STATUS", float("nan")), ("GAS_PEDAL_2", float("nan")),
                                    ("POWERTRAIN_DATA", float("nan")), ("GEARBOX_AUTO", float("nan"))], 1)
  series = _new_series()

  for msg in LogReader(paths):
    which = msg.which()
    timestamp = msg.logMonoTime / 1e9
    if which == "carControl":
      cc = msg.carControl
      actuator = cc.actuators
      orientation = cc.orientationNED
      pitch = orientation[1] if len(orientation) == 3 else np.nan
      _append(series, "request", timestamp, _field(actuator, "accel"))
      _append(series, "active", timestamp, float(_field(cc, "longActive", False)))
      _append(series, "pitch", timestamp, pitch)
    elif which == "carState":
      state = msg.carState
      for key, value in (("vego", _field(state, "vEgo")), ("aego", _field(state, "aEgo")),
                         ("gas_pressed", float(_field(state, "gasPressed", False))),
                         ("brake_pressed", float(_field(state, "brakePressed", False)))):
        _append(series, key, timestamp, value)
    elif which == "longitudinalPlan":
      plan = msg.longitudinalPlan
      source = _field(_field(plan, "longitudinalPlanSource", None), "raw")
      for key, value in (("atarget", _field(plan, "aTarget")),
                         ("allow_throttle", float(_field(plan, "allowThrottle", False))),
                         ("has_lead", float(_field(plan, "hasLead", False))),
                         ("should_stop", float(_field(plan, "shouldStop", False)))):
        _append(series, key, timestamp, value)
      # Keep the planner source in the event CSV when present, without making it a model feature.
      _append(series, "request", timestamp, _field(plan, "aTarget", np.nan)) if source is None else None
    elif which == "radarState":
      lead = msg.radarState.leadOne
      for key, value in (("lead_present", float(_field(lead, "present", False))),
                         ("lead_drel", _field(lead, "dRel")), ("lead_vrel", _field(lead, "vRel")),
                         ("lead_vlead", _field(lead, "vLead")), ("lead_prob", _field(lead, "modelProb"))):
        _append(series, key, timestamp, value)
    elif which == "sendcan":
      frames = msg.sendcan
      if any(c.address == ACC_CONTROL_ADDRESS for c in frames):
        for frame in frames:
          if frame.address != ACC_CONTROL_ADDRESS:
            continue
          values, checksum_ok, counter_ok, current_counter = _decode_acc_frame(
            acc_dbc, frame.dat, previous_counter["sendcan"])
          previous_counter["sendcan"] = current_counter
          acc["sendcan"]["t"].append(timestamp)
          for key in ACC_FIELDS:
            acc["sendcan"][key].append(float(values[key]))
          acc["sendcan"]["_checksum_ok"].append(float(checksum_ok))
          acc["sendcan"]["_counter_ok"].append(float(counter_ok))
          acc["sendcan"]["raw_hex"].append(frame.dat.hex())
    elif which == "can":
      frames = msg.can
      recv.update([(msg.logMonoTime, [(c.address, c.dat, c.src) for c in frames])])
      if recv.can_valid:
        values = recv.vl
        for key, message, signal in (("engine_torque", "GAS_PEDAL_2", "ENGINE_TORQUE_ESTIMATE"),
                                      ("rpm", "POWERTRAIN_DATA", "ENGINE_RPM"),
                                      ("gear", "GEARBOX_AUTO", "TRANS_TARGET_GEAR")):
          _append(series, key, timestamp, float(values[message][signal]))
      if any(c.address == ACC_CONTROL_ADDRESS for c in frames):
        for frame in frames:
          if frame.address != ACC_CONTROL_ADDRESS:
            continue
          values, checksum_ok, counter_ok, current_counter = _decode_acc_frame(
            acc_dbc, frame.dat, previous_counter["can"])
          previous_counter["can"] = current_counter
          acc["can"]["t"].append(timestamp)
          for key in ACC_FIELDS:
            acc["can"][key].append(float(values[key]))
          acc["can"]["_checksum_ok"].append(float(checksum_ok))
          acc["can"]["_counter_ok"].append(float(counter_ok))
          acc["can"]["raw_hex"].append(frame.dat.hex())

  preferred = "can" if role == "stock-radar" else "sendcan"
  source = preferred if acc[preferred]["t"] else ("sendcan" if preferred == "can" else "can")
  if not acc[source]["t"]:
    raise SystemExit(f"{full_route}: no ACC_CONTROL frames in preferred or fallback stream")
  selected = {key: np.asarray(value, dtype=object if key == "raw_hex" else float)
              for key, value in acc[source].items()}
  order = np.argsort(selected["t"])
  selected = {key: value[order] for key, value in selected.items()}
  return {"route": full_route, "role": role, "source": source, "commands": selected, "context": series}


def _align(route):
  """Align context to each ACC_CONTROL frame using interpolation/ZOH appropriate to the signal."""
  command = route["commands"]
  t = command["t"]
  t0 = float(t[0])
  grid = t - t0
  aligned = {key: value.copy() for key, value in command.items()}

  continuous = {"request", "pitch", "vego", "aego", "atarget", "lead_drel", "lead_vrel", "lead_vlead",
                "lead_prob", "engine_torque", "rpm", "gasfactor", "windfactor"}
  for key, values in route["context"].items():
    if not values["t"]:
      aligned[key] = np.full(len(t), np.nan)
      continue
    source_t = np.asarray(values["t"], dtype=float) - t0
    source_v = np.asarray(values["v"], dtype=float)
    if key in continuous:
      aligned[key] = np.interp(grid, source_t, source_v)
    else:
      aligned[key] = hold_last(grid, source_t, source_v)
  aligned["domain"] = command_domain(
    aligned["ACC_ENABLED"], aligned["BRAKE_REQUEST"], aligned["GAS_COMMAND"], control_on=aligned["CONTROL_ON"])
  aligned["commands"] = command
  aligned["route"] = route["route"]
  aligned["role"] = route["role"]
  aligned["source"] = route["source"]
  aligned["t0"] = t0
  return aligned


def _clean_mask(data):
  """Select live gas samples suitable for fitting a radar feedforward shadow model."""
  return ((data["domain"] == "gas") & (data["vego"] > 3.0) &
          ~np.asarray(data["gas_pressed"], dtype=bool) & ~np.asarray(data["brake_pressed"], dtype=bool) &
          np.isfinite(data["ACCEL_COMMAND"]) & np.isfinite(data["GAS_COMMAND"]) &
          np.isfinite(data["vego"]) & np.isfinite(data["pitch"]))


def _counter_metrics(data):
  counter = data["COUNTER"]
  if len(counter) < 2:
    return {"valid_steps": 0, "invalid_steps": 0, "unique_values": []}
  diff = np.mod(np.diff(counter), 4)
  valid = diff == 1
  return {"valid_steps": int(valid.sum()), "invalid_steps": int((~valid).sum()),
          "unique_values": sorted({int(x) for x in counter if np.isfinite(x)})}


def _integrity_metrics(command):
  """Report checksum/counter validity without dropping malformed raw frames."""
  return {
    "checksum_ok": int(np.sum(command["_checksum_ok"] > 0.5)),
    "checksum_bad": int(np.sum(command["_checksum_ok"] <= 0.5)),
    "counter_ok": int(np.sum(command["_counter_ok"] > 0.5)),
    "counter_bad": int(np.sum(command["_counter_ok"] <= 0.5)),
  }


def _raw_bit_metrics(command):
  """Count which payload bits change between adjacent native ACC_CONTROL frames."""
  raw = [bytes.fromhex(value) for value in command["raw_hex"]]
  if len(raw) < 2:
    return {"frames_with_changes": 0, "byte_xor_counts": [0] * 8,
            "bit_flip_counts": [[0] * 8 for _ in range(8)]}
  byte_xor = np.zeros(8, dtype=int)
  bit_flips = np.zeros((8, 8), dtype=int)
  changed = 0
  for previous, current in zip(raw[:-1], raw[1:], strict=True):
    xor = np.frombuffer(bytes(a ^ b for a, b in zip(previous, current, strict=True)), dtype=np.uint8)
    if np.any(xor):
      changed += 1
    byte_xor += xor > 0
    for byte_index, value in enumerate(xor):
      for bit_index in range(8):
        bit_flips[byte_index, bit_index] += int(value & (1 << bit_index) != 0)
  return {"frames_with_changes": int(changed), "byte_xor_counts": byte_xor.tolist(),
          "bit_flip_counts": bit_flips.tolist()}


def _edge_count(values, times):
  values = np.asarray(values)
  times = np.asarray(times, dtype=float)
  if len(values) < 2:
    return 0
  gaps = np.diff(times) > 0.25
  return int(np.sum((values[1:] != values[:-1]) & ~gaps))


def _route_report(data):
  command = data["commands"] if "commands" in data else data
  clean = _clean_mask(data)
  transitions = transition_metrics(command["t"] - data["t0"], data["domain"], command["GAS_COMMAND"])
  report = {
    "route": data["route"], "role": data["role"], "source": data["source"],
    "commands": int(len(command["t"])),
    "duration_s": float(command["t"][-1] - command["t"][0]),
    "command_rate_hz": transitions["rate_hz"],
    "clean_gas_seconds": float(np.sum(np.minimum(np.diff(command["t"], prepend=command["t"][0]), 0.25)[clean])),
    "domain_seconds": domain_seconds(command["t"] - data["t0"], data["domain"]),
    "transitions": transitions,
    "counter": _counter_metrics(command),
    "integrity": _integrity_metrics(command),
    "raw_bit_changes": _raw_bit_metrics(command),
    "signals": {key.lower(): quantiles(command[key]) for key in
                 ("GAS_COMMAND", "ACCEL_COMMAND", "BRAKE_REQUEST", "ACC_ENABLED", "CONTROL_ON")},
    "edge_counts": {key.lower(): _edge_count(command[key], command["t"]) for key in
                     ("ACC_ENABLED", "ACC_FAULTED", "CONTROL_ON", "BRAKE_REQUEST", "STANDSTILL",
                      "STANDSTILL_RELEASE", "AEB_STATUS", "AEB_BRAKING", "BRAKE_LIGHTS")},
    "clean_samples": int(clean.sum()),
  }
  controlling = ((data["domain"] != "inactive") if data["role"] == "stock-radar"
                 else np.asarray(data["active"], dtype=bool))
  report["brake_episodes"] = brake_episode_metrics(
    command["t"] - data["t0"], data["aego"], command["BRAKE_REQUEST"] > 0.5,
    controlling, np.asarray(data["brake_pressed"], dtype=bool), data["vego"], data["pitch"],
    min_speed=5.0, downhill_pitch=-0.012, min_duration_s=0.3,
    smooth_tau=0.20, jerk_window_s=0.10,
  )
  return report


def _model_data(data):
  mask = _clean_mask(data)
  features = feature_matrix(data["vego"][mask], data["ACCEL_COMMAND"][mask], data["pitch"][mask])
  return {"name": data["route"], "features": features, "target": data["GAS_COMMAND"][mask], "mask": mask}


def _jsonable(value):
  if isinstance(value, np.ndarray):
    return value.tolist()
  if isinstance(value, (np.floating, np.integer, np.bool_)):
    return value.item()
  if isinstance(value, dict):
    return {key: _jsonable(item) for key, item in value.items()}
  if isinstance(value, (list, tuple)):
    return [_jsonable(item) for item in value]
  return value


def _write_events(path, data_sets):
  fields = ["route", "role", "source", "time_s", "domain", "raw_hex", *ACC_FIELDS,
            "speed", "aego", "pitch", "request", "atarget", "lead_present", "lead_drel", "lead_vrel",
            "lead_vlead", "lead_prob", "engine_torque", "rpm", "gear", "gas_pressed", "brake_pressed"]
  with open(path, "w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=fields)
    writer.writeheader()
    for data in data_sets:
      command = data["commands"]
      for i in range(len(command["t"])):
        row = {"route": data["route"], "role": data["role"], "source": data["source"],
               "time_s": command["t"][i] - data["t0"], "domain": data["domain"][i],
               "raw_hex": command["raw_hex"][i],
               "speed": data["vego"][i], "aego": data["aego"][i], "pitch": data["pitch"][i],
               "request": data["request"][i], "atarget": data["atarget"][i],
               "lead_present": data["lead_present"][i], "lead_drel": data["lead_drel"][i],
               "lead_vrel": data["lead_vrel"][i], "lead_vlead": data["lead_vlead"][i],
               "lead_prob": data["lead_prob"][i], "engine_torque": data["engine_torque"][i],
               "rpm": data["rpm"][i], "gear": data["gear"][i],
               "gas_pressed": data["gas_pressed"][i], "brake_pressed": data["brake_pressed"][i]}
        row.update({key: command[key][i] for key in ACC_FIELDS})
        writer.writerow({key: _jsonable(value) for key, value in row.items()})


def analyze(stock_routes, openpilot_routes, *, min_count=20):
  stock = [_align(_decode_route(route, "stock-radar")) for route in stock_routes]
  openpilot = [_align(_decode_route(route, "openpilot")) for route in openpilot_routes]
  stock_models = [_model_data(data) for data in stock]
  radar_fit = pooled_regression(stock_models)
  reports = {"stock_radar": [_route_report(data) for data in stock],
             "openpilot": [_route_report(data) for data in openpilot],
             "feature_names": list(FEATURE_NAMES),
             "route_held_out": cross_route_regression(stock_models),
             "custom_against_radar": []}
  if radar_fit["coefficients"] is not None:
    reports["radar_model"] = {key: (value.tolist() if isinstance(value, np.ndarray) else value)
                               for key, value in radar_fit.items()}
    for data in openpilot:
      model_data = _model_data(data)
      prediction = model_data["features"] @ radar_fit["coefficients"]
      reports["custom_against_radar"].append({"route": data["route"],
        "metrics": regression_metrics(model_data["target"], prediction),
        "bias": float(np.mean(prediction - model_data["target"])) if len(prediction) else None,
        "radar_bins": binned_summary(data["vego"][model_data["mask"]],
                                      data["ACCEL_COMMAND"][model_data["mask"]],
                                      data["GAS_COMMAND"][model_data["mask"]],
                                      SPEED_EDGES, ACCEL_EDGES, min_count=min_count)})
  reports["stock_bins"] = [{"route": data["route"], "cells": binned_summary(
    data["vego"][_clean_mask(data)], data["ACCEL_COMMAND"][_clean_mask(data)],
    data["GAS_COMMAND"][_clean_mask(data)], SPEED_EDGES, ACCEL_EDGES, min_count=min_count)} for data in stock]
  return reports, stock + openpilot


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("--stock-radar", action="append", required=True,
                      help="local stock-radar route id/prefix; repeat for multiple routes")
  parser.add_argument("--openpilot", action="append", required=True,
                      help="local OpenPilot longitudinal route id/prefix; repeat for multiple routes")
  parser.add_argument("--out", help="write the JSON report here")
  parser.add_argument("--events", help="write one row per ACC_CONTROL command here as CSV")
  parser.add_argument("--min-count", type=int, default=20, help="minimum samples per speed/accel cell")
  args = parser.parse_args(argv)
  reports, data_sets = analyze(args.stock_radar, args.openpilot, min_count=args.min_count)
  if args.out:
    with open(args.out, "w") as handle:
      json.dump(_jsonable(reports), handle, indent=2)
  if args.events:
    _write_events(args.events, data_sets)

  print("Stock-radar command streams:")
  for row in reports["stock_radar"]:
    t = row["transitions"]
    print(f"  {row['route']}: {row['commands']} ACC_CONTROL frames at {row['command_rate_hz']:.1f} Hz, "
          f"clean gas {row['clean_gas_seconds']:.1f}s, direct gas->brake {t['direct_gas_to_brake']}, "
          f"direct brake->gas {t['direct_brake_to_gas']}")
  print("\nRoute-held-out radar gas model:")
  for row in reports["route_held_out"]:
    m = row["metrics"]
    print(f"  {row['test_route']}: n={m['n']} MAE={m['mae']:.1f} RMSE={m['rmse']:.1f} "
          f"R2={m['r2']:.3f} p90={m['p90_abs_error']:.1f}")
  print("\nOpenPilot commands scored against pooled radar model:")
  for row in reports["custom_against_radar"]:
    m = row["metrics"]
    if m["n"]:
      print(f"  {row['route']}: n={m['n']} MAE={m['mae']:.1f} RMSE={m['rmse']:.1f} "
            f"R2={m['r2']:.3f} bias={row['bias']:+.1f}")
    else:
      print(f"  {row['route']}: no clean gas samples")
  if args.out:
    print(f"\nJSON report: {args.out}")
  if args.events:
    print(f"Event CSV: {args.events}")


if __name__ == "__main__":
  main()
