from types import SimpleNamespace

from openpilot.selfdrive.controls.lib.drive_helpers import stopped_lead_should_stop, stopped_lead_stop_intent


def _lead(**kwargs):
  values = {"present": True, "modelProb": 1.0, "vLead": 0.2, "vRel": -0.1, "dRel": 4.5}
  values.update(kwargs)
  return SimpleNamespace(**values)


def test_stopped_lead_screen_accepts_route_like_event():
  assert stopped_lead_should_stop(0.42, -0.20, _lead())


def test_stopped_lead_screen_rejects_each_unsafe_or_incomplete_condition():
  base = {"v_ego": 0.42, "a_target": -0.20}
  for field, value in (
    ("present", False),
    ("modelProb", 0.9),
    ("vLead", 0.35),
    ("vRel", 0.0),
    ("dRel", 6.5),
  ):
    assert not stopped_lead_should_stop(**base, lead=_lead(**{field: value}))

  assert not stopped_lead_should_stop(1.0, -0.20, _lead())
  assert not stopped_lead_should_stop(0.42, -0.05, _lead())


def test_stopped_lead_stop_intent_requires_persistence():
  assert not stopped_lead_stop_intent(True, 4)
  assert stopped_lead_stop_intent(True, 5)
  assert not stopped_lead_stop_intent(False, 5)
