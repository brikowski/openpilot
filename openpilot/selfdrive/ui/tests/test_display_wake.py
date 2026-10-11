from openpilot.selfdrive.ui.display_wake import DISPLAY_TIMEOUT, DisplayWakePolicy


def step(policy, now, *, ignition=True, started=True, enabled=False, alert=None, urgent=False,
         missing=False, touch=False, offroad_alerts=None):
  return policy.update(now, DISPLAY_TIMEOUT, ignition=ignition, started=started, enabled=enabled, alert=alert,
                       urgent_alert=urgent, state_missing=missing, touch=touch,
                       offroad_alerts=offroad_alerts, pc=False)


def test_onroad_timeout_touch_and_alert_wake():
  assert DISPLAY_TIMEOUT == 15
  policy = DisplayWakePolicy()
  assert step(policy, 0) == (True, False)
  assert step(policy, 15) == (True, False)
  assert step(policy, 15.1) == (False, True)
  assert step(policy, 16) == (False, False)
  assert step(policy, 17, touch=True) == (True, False)
  assert step(policy, 32.1) == (False, True)

  notification = (1, 0, 'Notification', '')
  assert step(policy, 33, alert=notification) == (True, False)
  assert step(policy, 48.1, alert=notification) == (False, True)


def test_urgent_alert_and_missing_state_keep_display_awake():
  policy = DisplayWakePolicy()
  step(policy, 0)
  assert step(policy, 31, missing=True)[0]
  warning = (2, 2, 'Take control', '')
  assert step(policy, 32, alert=warning, urgent=True)[0]
  assert step(policy, 100, alert=warning, urgent=True)[0]
  assert not step(policy, 101)[0]


def test_engagement_disengagement_and_ignition_transitions_wake():
  policy = DisplayWakePolicy()
  step(policy, 0)
  assert not step(policy, 31)[0]
  assert step(policy, 32, enabled=True)[0]
  assert not step(policy, 63, enabled=True)[0]
  assert step(policy, 64, enabled=False)[0]
  assert not step(policy, 95, enabled=False)[0]
  assert step(policy, 96, ignition=False, started=False, enabled=None)[0]
  assert step(policy, 127, ignition=True, started=True)[0]


def test_new_offroad_notifications_wake_but_existing_ones_do_not_hold_display_on():
  policy = DisplayWakePolicy()
  assert step(policy, 0, ignition=False, started=False, enabled=None, offroad_alerts={'old'})[0]
  assert step(policy, 15, ignition=False, started=False, enabled=None, offroad_alerts={'old'})[0]
  assert not step(policy, 15.1, ignition=False, started=False, enabled=None, offroad_alerts={'old'})[0]
  assert step(policy, 16, ignition=False, started=False, enabled=None, offroad_alerts={'old', 'new'})[0]
  assert not step(policy, 31.1, ignition=False, started=False, enabled=None, offroad_alerts={'old', 'new'})[0]
