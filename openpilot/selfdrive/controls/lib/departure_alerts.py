import math

from opendbc.car.structs import car


ARM_TIME = 2.0
CONFIRM_TIME = 0.5
MAX_SAMPLE_AGE = 0.25
MAX_LEAD_DISTANCE = 35.0
LEAD_MOVEMENT = 1.5


class DepartureAlerts:
  """Observe stopped traffic independently of engagement; never request actuation."""

  def __init__(self):
    self.last_time = None
    self.notified = False
    self._clear_observations()

  def _clear_lead(self):
    self.previous_lead = None
    self.lead_since = None
    self.lead_distance = None
    self.departure_since = None

  def _clear_observations(self):
    self._clear_lead()
    self.had_lead = False
    self.stop_since = None
    self.traffic_armed = False
    self.ready_since = None

  def update(self, sm) -> tuple[bool, bool]:
    CS = sm['carState']
    model = sm['modelV2']
    lead = sm['radarState'].leadOne
    now = sm.logMonoTime['modelV2'] / 1e9
    valid = (sm.all_checks(['carState', 'modelV2', 'radarState']) and CS.canValid and
             all(abs(now - sm.logMonoTime[s] / 1e9) <= MAX_SAMPLE_AGE for s in ('carState', 'radarState')) and
             math.isfinite(CS.vEgo) and math.isfinite(model.action.desiredAcceleration))

    if self.last_time is not None and not 0.0 < now - self.last_time <= MAX_SAMPLE_AGE:
      self._clear_observations()
    self.last_time = now

    stopped = CS.standstill and abs(CS.vEgo) < 0.1
    if not valid or not stopped or CS.gearShifter != car.CarState.GearShifter.drive or CS.gasPressed or CS.parkingBrake:
      self._clear_observations()
      # Missing data must not rearm a notification already delivered at this stop.
      if valid and not stopped:
        self.notified = False
      return False, False
    if self.notified:
      return False, False

    if lead.present:
      self.had_lead = True
      self.stop_since = self.ready_since = None
      self.traffic_armed = False
      if not all(math.isfinite(v) for v in (lead.dRel, lead.vRel)) or not 0.0 < lead.dRel < MAX_LEAD_DISTANCE:
        self._clear_lead()
        return False, False

      current_lead = (lead.dRel, lead.vRel, lead.radarTrackId)
      if self.previous_lead is not None:
        distance, speed, track_id = self.previous_lead
        dt = now - self.previous_lead_time
        # Track changes or discontinuous range must not masquerade as departure.
        if track_id != lead.radarTrackId or abs(lead.dRel - distance) > 1.0 + max(abs(speed), abs(lead.vRel)) * dt:
          self._clear_lead()
      self.previous_lead = current_lead
      self.previous_lead_time = now

      if self.lead_distance is None:
        if abs(lead.vRel) < 0.3:
          if self.lead_since is None:
            self.lead_since = now
          if now - self.lead_since >= ARM_TIME:
            self.lead_distance = lead.dRel
        else:
          self.lead_since = None

      departing = self.lead_distance is not None and lead.dRel - self.lead_distance >= LEAD_MOVEMENT and lead.vRel > 0.5
      if departing:
        if self.departure_since is None:
          self.departure_since = now
        if now - self.departure_since >= CONFIRM_TIME:
          self.notified = True
          return True, False
      else:
        self.departure_since = None
    else:
      self._clear_lead()
      # Losing a lead is not evidence that a traffic signal changed.
      if self.had_lead:
        return False, False
      if model.action.shouldStop:
        self.ready_since = None
        if self.stop_since is None:
          self.stop_since = now
        if now - self.stop_since >= ARM_TIME:
          self.traffic_armed = True
      else:
        self.stop_since = None
        # This is a model stop-to-proceed transition, not traffic-light classification.
        if self.traffic_armed and model.action.desiredAcceleration > 0.2:
          if self.ready_since is None:
            self.ready_since = now
          if now - self.ready_since >= CONFIRM_TIME:
            self.notified = True
            return False, True
        else:
          self.ready_since = None

    return False, False
