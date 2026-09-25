import json

import numpy as np
import pytest

from compare_low_speed_gas import one_to_one_matches, source_for_route, summarize, trial_points, trim_weight


def _route():
  n = 600
  request = np.full(n, 1.0)
  return {"t": np.arange(n) * 0.01, "request": request,
          "active": np.ones(n, dtype=bool), "pid": np.ones(n, dtype=bool),
          "gas_pressed": np.zeros(n, dtype=bool), "brake_pressed": np.zeros(n, dtype=bool),
          "brake_request": np.zeros(n, dtype=bool), "gas_command": np.full(n, 1000.0),
          "vego": np.full(n, 15.0), "pitch": np.zeros(n), "accel_command": request.copy(),
          "gear": np.full(n, 4.0), "rpm": np.full(n, 2000.0), "aego": request + 0.2,
          "has_lead": np.zeros(n, dtype=bool), "plan_source": np.zeros(n, dtype=int)}


def test_trial_points_keep_only_stable_active_wire_exposure():
  d = _route()
  points = trial_points(d)
  assert len(points) > 20
  np.testing.assert_allclose(points[:, 8], 0.2)
  np.testing.assert_allclose(points[:, 9], 1.0)
  assert len(trial_points({**d, "gas_pressed": np.ones(len(d["t"]), dtype=bool)})) == 0
  assert len(trial_points({**d, "gear": np.r_[np.full(300, 4.0), np.full(300, 5.0)]})) < len(points)
  assert len(trial_points({**d, "request": np.linspace(0.5, 1.5, len(d["t"]))})) == 0
  gap_t = d["t"].copy()
  gap_t[300:] += 10.0
  assert len(trial_points({**d, "t": gap_t})) < len(points)


def test_trim_weight_is_zero_outside_trial_and_full_in_core():
  assert trim_weight(15.0, 1.0) == 1.0
  assert np.isclose(trim_weight(9.0, 1.0), 0.15625)
  for speed, request in ((7.0, 1.0), (24.0, 1.0), (15.0, 0.4), (15.0, 2.0)):
    assert trim_weight(speed, request) == 0.0


def test_matching_is_one_to_one_and_preserves_gear_and_lead():
  baseline = trial_points(_route())[:2]
  trial = baseline.copy()
  trial[:, 7] -= 200.0
  trial[:, 8] -= 0.1
  trial[1, 5] = 1.0
  ci, bi = one_to_one_matches(trial, baseline)
  assert len(ci) == len(bi) == 1
  result = summarize(trial, baseline)
  assert result["matched"] == 1
  assert np.isclose(result["wire_gas_delta"], -200.0)
  assert np.isclose(result["expected_trim"], -200.0)
  assert np.isclose(result["paired_error_delta"], -0.1)
  assert np.isclose(result["trial_error_mae"], 0.1)
  trial[0, 6] = 4.0  # experimental model demand is not a cruise-source match
  assert summarize(trial, baseline)["matched"] == 0


def test_source_check_rejects_unknown_mixed_and_qlog(tmp_path):
  ledger = tmp_path / "ledger.jsonl"
  ledger.write_text(json.dumps({"route": "r", "opendbc_commit": "47196b9a4full", "qlog_fallback": False}) + "\n")
  assert source_for_route("r", ledger) == "47196b9a4full"
  with pytest.raises(ValueError):
    source_for_route("other", ledger)
  with ledger.open("a") as stream:
    stream.write(json.dumps({"route": "r", "opendbc_commit": "6915be202bb7", "qlog_fallback": False}) + "\n")
  with pytest.raises(ValueError):
    source_for_route("r", ledger)
  ledger.write_text(json.dumps({"route": "r", "opendbc_commit": "47196b9a4", "qlog_fallback": True}) + "\n")
  with pytest.raises(ValueError):
    source_for_route("r", ledger)
