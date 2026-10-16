import time

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog, alert_dialog
from openpilot.system.ui.widgets.list_view import ButtonAction, ListItem
from openpilot.tools.odyssey.radar_test import ACTIVE, STOP, STATUS, supported, start_allowed, request_start


class OdysseyRadarTestItem(ListItem):
  def __init__(self):
    self.params = Params()
    super().__init__("Parked Radar ECU Capture", description=self.description_text, callback=self.action,
                     action_item=ButtonAction(lambda: "STOP" if self.params.get_bool(ACTIVE) else "START",
                                              enabled=lambda: self.params.get_bool(ACTIVE) or start_allowed(
                                                self.params, ui_state.sm, ui_state.is_offroad())))
    self.set_visible(lambda: self.params.get_bool(ACTIVE) or supported(self.params))

  def description_text(self):
    status = self.params.get(STATUS) or {}
    message = status.get("message", "Start with vehicle ignition OFF.")
    if self.params.get_bool(ACTIVE) and not 0 <= time.monotonic() - status.get("monotonic", 0) <= 5:
      message = "Test process interrupted. Press STOP, turn vehicle OFF, and reboot the comma if the test does not exit."
    return (message + "<br><br>Stay in Park with parking brake set. Read-only CAN capture and ECU identifiers. " +
            "Existing SSH stays available. Turn ignition OFF to exit. This does not validate AEB or FCW.")

  def action(self):
    if self.params.get_bool(ACTIVE):
      self.params.put_bool(STOP, True, block=True)
      return

    def confirm(result):
      if result == DialogResult.CONFIRM and not request_start(self.params, ui_state.sm, ui_state.is_offroad()):
        gui_app.push_widget(alert_dialog("Start with vehicle ignition OFF and OpenPilot offroad."))

    gui_app.push_widget(ConfirmDialog("Parked capture only. Set parking brake, turn ignition OFF, and stay with the vehicle. " +
                                    "Turn ignition ON when prompted. Do not drive during this test.", "Start", callback=confirm))

  def _update_state(self):
    super()._update_state()
    # Keep instructions and live status visible without requiring another tap.
    self._set_description_visible(True)

  def _handle_mouse_release(self, mouse_pos):
    pass
