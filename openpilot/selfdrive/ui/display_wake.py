from dataclasses import dataclass


DISPLAY_TIMEOUT = 15


def alpha_long_cruise_active(alpha_long_enabled: bool, car_params, engaged: bool,
                             car_state_fresh: bool, set_speed: float, unset_speed: float) -> bool:
  return bool(alpha_long_enabled and car_params is not None and car_params.alphaLongitudinalAvailable and
              car_params.openpilotLongitudinalControl and engaged and car_state_fresh and 0 < set_speed < unset_speed)


@dataclass
class DisplayWakePolicy:
  deadline: float = -1.0
  ignition: bool = False
  started: bool = False
  enabled: bool = False
  alert: tuple | None = None
  offroad_alerts: set[str] | None = None
  timed_out: bool = False

  def reset(self, now: float, timeout: int) -> None:
    self.deadline = now + timeout

  def update(self, now: float, timeout: int, *, ignition: bool, started: bool, enabled: bool | None,
             alert: tuple | None, urgent_alert: bool, state_missing: bool, touch: bool,
             offroad_alerts: set[str] | None, keep_on_cruise: bool, pc: bool) -> tuple[bool, bool]:
    reset = touch or ignition != self.ignition or started != self.started or self.deadline < 0
    self.ignition = ignition
    self.started = started

    if started:
      if alert is not None and alert != self.alert:
        reset = True
      self.alert = alert
      if enabled is not None:
        if enabled != self.enabled:
          reset = True
        self.enabled = enabled
    else:
      self.alert = None
      self.enabled = False
      if offroad_alerts is not None:
        if self.offroad_alerts is not None and offroad_alerts - self.offroad_alerts:
          reset = True
        self.offroad_alerts = offroad_alerts

    if reset:
      self.reset(now, timeout)

    timed_out = now > self.deadline
    timeout_edge = timed_out and not self.timed_out
    self.timed_out = timed_out
    return pc or not timed_out or (started and (urgent_alert or state_missing or keep_on_cruise)), timeout_edge
