ODYSSEY_CAR_FINGERPRINT = "HONDA_ODYSSEY_5G_MMR"
ODYSSEY_DOWNHILL_MIN_SPEED = 5.0
ODYSSEY_DOWNHILL_COAST_ACCEL_THRESHOLD = -0.20


def effective_allow_throttle(car_fingerprint, experimental_mode, v_ego, model_allow_throttle, accel_coast):
  """Keep steep-downhill Odyssey cruise on the grade-supported coast branch."""
  steep_downhill = (not experimental_mode and car_fingerprint == ODYSSEY_CAR_FINGERPRINT and
                    v_ego >= ODYSSEY_DOWNHILL_MIN_SPEED and
                    accel_coast > ODYSSEY_DOWNHILL_COAST_ACCEL_THRESHOLD)
  return bool(model_allow_throttle and not steep_downhill)
