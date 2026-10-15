"""Synthetic wire fixtures exercise integrity/loss boundaries, not physical object semantics."""
import io
import json
from types import SimpleNamespace

import pytest

from inspect_honda_objects import ADDRESSES, AUX_IDS, MAIN_BASES, ObjectAssembler, inspect_file, main
from opendbc.car.honda.hondacan import honda_checksum


PAYLOADS = (
  "2461abc981604510", "152345b2675a8910", "56798abcde654310",
  "12b23456789a2b10", "67b289abcdef0110",
)


def checked(address, payload):
  data = bytearray(payload)
  data[-1] &= 0xF0
  data[-1] |= honda_checksum(address, None, data)
  return bytes(data)


def frames(slot=0):
  addresses = [MAIN_BASES[slot] + i for i in range(4)] + [AUX_IDS[slot]]
  return [(i * 1_000_000, address, checked(address, bytes.fromhex(payload)), 2)
          for i, (address, payload) in enumerate(zip(addresses, PAYLOADS, strict=True))]


def collect(assembler, packets):
  return [record for packet in packets if (record := assembler.feed(*packet)) is not None]


@pytest.mark.parametrize("slot", range(16))
def test_raw_fields_preserve_independent_literal_values_in_every_slot(slot):
  packets = frames(slot)
  assembler = ObjectAssembler()
  records = collect(assembler, packets)
  assert len(records) == 1
  record = records[0]
  expected = {"status_raw": 6, "range_raw": 2748, "angle_raw": 1035, "range_sigma_raw": 18,
              "existence_raw": 90, "angular_width_raw": 557, "lifecycle_raw": 1383,
              "normalized_closing_raw": 554, "normalized_closing_sigma_raw": 101,
              "edge_a_raw": 149, "edge_b_raw": 418, "edge_sigma_a_raw": 482,
              "identity_raw": 43, "velocity_raw": 829, "velocity_uncertainty_raw": 550,
              "edge_sigma_b_raw": 823, "range_ratio_raw": 4}
  assert {field: record[field] for field in expected} == expected
  assert record["slot"] == slot and record["sequence_raw"] == 9 and record["counter_raw"] == 1
  assert record["frame_times_ns"] == [packet[0] for packet in packets]
  assert record["payloads"] == [packet[2].hex() for packet in packets]
  assert assembler.counts["integrity_frames"] == 5
  assert len(ADDRESSES) == 80


@pytest.mark.parametrize("offset", range(5))
def test_corrupted_payload_never_completes_a_record(offset):
  packets = frames()
  t, address, data, bus = packets[offset]
  bad = bytearray(data)
  bad[4] ^= 1
  packets[offset] = t, address, bytes(bad), bus
  assembler = ObjectAssembler()
  assert collect(assembler, packets) == []
  assert assembler.counts["checksum_errors"] == 1
  assert len(collect(assembler, frames())) == 1


@pytest.mark.parametrize("offset", range(1, 5))
@pytest.mark.parametrize("fault", ["phase", "counter", "missing", "duplicate", "length", "time_backwards", "too_old"])
def test_incoherent_or_incomplete_records_cannot_inherit_stale_fields(offset, fault):
  packets = frames()
  t, address, data, bus = packets[offset]
  bad = bytearray(data)
  if fault == "phase":
    bad[3 if offset == 1 else 1] ^= 2
  elif fault == "counter":
    bad[-1] ^= 0x10
  elif fault == "missing":
    packets.pop(offset)
  elif fault == "duplicate":
    packets.insert(offset, packets[offset])
  elif fault == "length":
    packets[offset] = t, address, data[:4], bus
  elif fault == "time_backwards":
    packets[offset] = -1, address, data, bus
  elif fault == "too_old":
    packets[offset] = 31_000_000, address, data, bus
  if fault in ("phase", "counter"):
    packets[offset] = t, address, checked(address, bad), bus
  assembler = ObjectAssembler()
  result = collect(assembler, packets)
  # A duplicate final AUX arrives after an already-completed record; it is just an orphan.
  assert len(result) == int(fault == "duplicate" and offset == 4)
  assert len(collect(assembler, frames())) == 1


@pytest.mark.parametrize("bus", [0, 1, 3, 128, 130, 194])
def test_other_buses_and_panda_echoes_cannot_create_or_poison_records(bus):
  assembler = ObjectAssembler()
  packets = frames()
  noise = [(t, address, b"bad", bus) for t, address, _, _ in packets]
  assert collect(assembler, noise) == []
  assert not assembler.counts
  assert len(collect(assembler, packets)) == 1


def test_raw_zero_is_retained_without_velocity_conversion_or_validity_claim():
  packets = frames()
  t, address, data, bus = packets[-1]
  data = bytearray(data)
  data[0] = 0
  data[1] &= 31
  packets[-1] = t, address, checked(address, data), bus
  record, = collect(ObjectAssembler(), packets)
  assert record["velocity_raw"] == 0
  assert "vRel" not in record and "valid" not in record and "measured" not in record


def test_interleaved_slots_and_header_replacement_keep_record_ownership():
  first, second = frames(0), frames(15)
  assembler = ObjectAssembler()
  assert assembler.feed(*first[0]) is None
  packets = [packet for pair in zip(first, second, strict=True) for packet in pair]
  records = collect(assembler, packets)
  assert [r["slot"] for r in records] == [0, 15]
  assert assembler.counts["replaced_incomplete_records"] == 1


def test_log_report_keeps_source_hash_and_ignores_host_sendcan(tmp_path, monkeypatch):
  from openpilot.tools.lib import logreader
  import validate_log

  path = tmp_path / "rlog.zst"
  path.write_bytes(b"synthetic input")
  messages = []
  def event(kind, payload, timestamp=0):
    return SimpleNamespace(which=lambda: kind, logMonoTime=timestamp, **{kind: payload})
  messages.append(event("initData", SimpleNamespace(gitCommit="a" * 40, dirty=False)))
  messages.append(event("carParams", SimpleNamespace(carFingerprint="synthetic", openpilotLongitudinalControl=True,
                                                     radarUnavailable=True)))
  for t, address, data, bus in frames():
    frame = SimpleNamespace(address=address, dat=data, src=bus)
    messages.extend([event("sendcan", [frame], t), event("can", [frame], t)])
  monkeypatch.setattr(logreader.LogReader, "from_bytes", lambda _: iter(messages))
  monkeypatch.setattr(validate_log, "_opendbc_pointer_full", lambda parent, dirty: "b" * 40 if not dirty else None)
  output = io.StringIO()
  report = inspect_file(path, records=output)
  assert report["sha256"] == "3f48d11458e37cd22c904295e44cb2e10fec3d19095046a0c9197efb3c5286c7"
  assert report["source"] == [{"parent": "a" * 40, "dirty": False, "opendbc": "b" * 40}]
  assert report["counts"]["complete_records"] == 1
  assert report["counts"]["bank_frames"] == 5
  assert json.loads(output.getvalue())["identity_raw"] == 43


@pytest.mark.parametrize("extra", [["--bus", "130"], ["--max-span-ms", "nan"], ["--max-span-ms", "0"]])
def test_cli_rejects_invalid_capture_settings(tmp_path, extra):
  with pytest.raises(SystemExit):
    main([str(tmp_path / "input"), "--out", str(tmp_path / "output"), *extra])


def test_cli_rejects_overwriting_input(tmp_path):
  path = tmp_path / "rlog.zst"
  path.write_bytes(b"preserve input")
  with pytest.raises(SystemExit):
    main([str(path), "--out", str(path)])
  assert path.read_bytes() == b"preserve input"
