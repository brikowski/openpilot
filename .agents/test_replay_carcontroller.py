import numpy as np

from replay_carcontroller import gas_command_samples, same_domain_gas_steps


def test_gas_steps_use_transmitted_frames_not_held_controller_ticks():
  samples = []
  for tick in range(200):
    gas = 150 if tick == 198 else 0
    sends = [(0x1DF, gas.to_bytes(2, "big", signed=True) + bytes(6), 1)] if tick % 2 == 0 else []
    samples.extend(gas_command_samples(tick * 10_000_000, sends))
  assert len(samples) == 100
  result = same_domain_gas_steps(samples)
  assert result["pairs"] == 99
  assert result["max"] == 150
  assert result["over_100"] == 1
  assert np.isclose(result["p99"], 3.0)
  assert gas_command_samples(0, [(0x1DF, bytes(8), 0), (0xE4, bytes(8), 1)]) == []


def test_gas_steps_exclude_domain_edges_gaps_and_nonmonotonic_time():
  samples = [(0.00, 100), (0.02, 110), (0.04, -30000), (0.06, 1000),
             (0.20, 0), (0.20, 999), (0.19, 500)]
  assert same_domain_gas_steps(samples) == {"max": 10.0, "p99": 10.0, "over_100": 0, "pairs": 1}
