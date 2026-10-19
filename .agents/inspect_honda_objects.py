#!/usr/bin/env python3
"""Inspect coherent Honda ACC-CAN object records offline, without publishing RadarPoints.

Usage: .venv/bin/python .agents/inspect_honda_objects.py RLOG [RLOG ...] --out REPORT
       [--records RECORDS.jsonl] [--bus 2] [--max-span-ms 30]

The 16-slot, five-frame layout is a byte-layout hypothesis checked against native Odyssey
captures. Names below identify raw field candidates, not qualified sensor origin, physical
units, validity, target identity or control authority. No physical conversion or quality
threshold is applied. The span limit is a diagnostic assembly bound, not sensor latency.
Keep reports/records outside Git; they contain private timestamps and source metadata.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from opendbc.car.honda.hondacan import honda_checksum


MAIN_BASES = tuple(0x280 + 4 * s if s < 4 else 0x2D0 + 4 * (s - 4) for s in range(16))
AUX_IDS = tuple(0x2C8 + s if s < 8 else 0x290 + s - 8 for s in range(16))
ADDRESSES = {base + offset: (slot, offset) for slot, base in enumerate(MAIN_BASES) for offset in range(4)}
ADDRESSES.update({address: (slot, 4) for slot, address in enumerate(AUX_IDS)})


def raw_fields(payloads):
  """Extract candidate fields; retain payloads separately so every bit remains auditable."""
  f0, f1, f2, f3, aux = payloads
  return {
    "status_raw": f0[1] >> 4,
    "range_raw": (f0[2] << 4) | (f0[3] >> 4),
    "angle_raw": (f0[4] << 3) | (f0[5] >> 5),
    "range_sigma_raw": f0[0] >> 1,
    "existence_raw": f1[5] & 127,
    "angular_width_raw": (f1[2] << 3) | (f1[3] >> 5),
    "lifecycle_raw": (f2[0] << 4) | (f2[1] >> 4),
    "normalized_closing_raw": (f2[2] << 2) | (f2[3] >> 6),
    "normalized_closing_sigma_raw": f2[5] & 127,
    "edge_a_raw": (f3[0] << 3) | (f3[1] >> 5),
    "edge_b_raw": (f3[2] << 3) | (f3[3] >> 5),
    "edge_sigma_a_raw": (f3[4] << 2) | (f3[5] >> 6),
    "identity_raw": f3[6],
    "velocity_raw": (aux[0] << 3) | (aux[1] >> 5),
    "velocity_uncertainty_raw": (aux[2] << 2) | (aux[3] >> 6),
    "edge_sigma_b_raw": (aux[4] << 2) | (aux[5] >> 6),
    "range_ratio_raw": (aux[6] << 2) | (aux[7] >> 6),
  }


def sequence(offset, payload):
  if offset == 0:
    return payload[3] & 15
  if offset == 1:
    return (payload[3] >> 1) & 15
  if offset == 2:
    return payload[1] & 15
  return (payload[1] >> 1) & 15


class ObjectAssembler:
  """Assemble only ordered, checksum/counter/phase-coherent records on one physical RX bus."""

  def __init__(self, bus=2, max_span_ns=30_000_000):
    if not 0 <= bus < 128 or max_span_ns <= 0:
      raise ValueError("require physical receive bus and positive assembly span")
    self.bus = bus
    self.max_span_ns = max_span_ns
    self.pending = {}
    self.counts = Counter()

  def feed(self, timestamp_ns, address, payload, bus):
    if bus != self.bus or address not in ADDRESSES:
      return None
    self.counts["bank_frames"] += 1
    slot, offset = ADDRESSES[address]
    if len(payload) != 8:
      self.counts["wrong_length"] += 1
      self.pending.pop(slot, None)
      return None
    payload = bytes(payload)
    if honda_checksum(address, None, bytearray(payload)) != payload[-1] & 15:
      self.counts["checksum_errors"] += 1
      self.pending.pop(slot, None)
      return None
    self.counts["integrity_frames"] += 1
    if offset == 0:
      if slot in self.pending:
        self.counts["replaced_incomplete_records"] += 1
      self.pending[slot] = [(timestamp_ns, payload)]
      return None
    frames = self.pending.get(slot)
    if frames is None:
      self.counts["orphan_frames"] += 1
      return None
    if offset != len(frames):
      self.counts["order_errors"] += 1
      self.pending.pop(slot)
      return None
    first_t, first = frames[0]
    if timestamp_ns < frames[-1][0] or timestamp_ns - first_t > self.max_span_ns:
      self.counts["span_errors"] += 1
      self.pending.pop(slot)
      return None
    if sequence(offset, payload) != sequence(0, first) or (payload[-1] >> 4) & 3 != (first[-1] >> 4) & 3:
      self.counts["phase_errors"] += 1
      self.pending.pop(slot)
      return None
    frames.append((timestamp_ns, payload))
    if offset != 4:
      return None
    self.pending.pop(slot)
    self.counts["complete_records"] += 1
    payloads = [p for _, p in frames]
    return {"slot": slot, "start_ns": first_t, "end_ns": timestamp_ns,
            "sequence_raw": sequence(0, first), "counter_raw": (first[-1] >> 4) & 3,
            "frame_times_ns": [t for t, _ in frames], "payloads": [p.hex() for p in payloads],
            **raw_fields(payloads)}


def inspect_file(path, bus=2, max_span_ns=30_000_000, records=None):
  from openpilot.tools.lib.logreader import LogReader
  from validate_log import _opendbc_pointer_full

  raw = Path(path).read_bytes()
  assembler = ObjectAssembler(bus, max_span_ns)
  source = []
  car_params = []
  histograms = {field: Counter() for field in ("status_raw", "velocity_raw", "velocity_uncertainty_raw", "identity_raw")}
  for message in LogReader.from_bytes(raw):
    kind = message.which()
    if kind == "initData":
      init = message.initData
      source.append({"parent": init.gitCommit, "dirty": init.dirty,
                     "opendbc": _opendbc_pointer_full(init.gitCommit, init.dirty)})
    elif kind == "carParams":
      cp = message.carParams
      car_params.append({"carFingerprint": cp.carFingerprint, "alpha_long": cp.openpilotLongitudinalControl,
                         "radarUnavailable": cp.radarUnavailable})
    elif kind == "can":
      for frame in message.can:
        record = assembler.feed(message.logMonoTime, frame.address, frame.dat, frame.src)
        if record is not None:
          for field, histogram in histograms.items():
            histogram[record[field]] += 1
          if records is not None:
            records.write(json.dumps(record) + "\n")
  return {"file": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
          "source": source, "carParams": car_params, "bus": bus, "max_span_ns": max_span_ns,
          "counts": dict(assembler.counts), "pending_records_at_eof": len(assembler.pending),
          "histograms": {field: dict(sorted(histogram.items())) for field, histogram in histograms.items()}}


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("rlogs", nargs="+", type=Path)
  parser.add_argument("--out", required=True, type=Path)
  parser.add_argument("--records", type=Path, help="optional raw record JSONL; exactly one input rlog")
  parser.add_argument("--bus", default=2, type=int)
  parser.add_argument("--max-span-ms", default=30., type=float)
  args = parser.parse_args(argv)
  if args.records and len(args.rlogs) != 1:
    parser.error("--records requires exactly one input to keep timestamp/source ownership unambiguous")
  paths = [p.resolve() for p in args.rlogs]
  outputs = [p.resolve() for p in (args.out, args.records) if p is not None]
  if len(set(outputs)) != len(outputs) or set(paths) & set(outputs):
    parser.error("outputs must differ from each other and from input logs")
  if not 0 <= args.bus < 128 or not 0 < args.max_span_ms < float("inf"):
    parser.error("require physical receive bus and finite positive --max-span-ms")
  report = {"schema": 1, "scope": "Raw candidate fields only; sensor origin, physical units and control validity unqualified.",
            "files": []}
  for path in args.rlogs:
    if args.records:
      with args.records.open("x") as output:
        result = inspect_file(path, args.bus, int(args.max_span_ms * 1e6), output)
    else:
      result = inspect_file(path, args.bus, int(args.max_span_ms * 1e6))
    report["files"].append(result)
    print(f"{path.name}: {result['counts'].get('complete_records', 0)} coherent raw records")
  with args.out.open("x") as output:
    json.dump(report, output, indent=2)
    output.write("\n")


if __name__ == "__main__":
  main()
