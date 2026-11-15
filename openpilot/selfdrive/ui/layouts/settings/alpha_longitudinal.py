from openpilot.common.params import Params
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog


ALPHA_LONGITUDINAL_DESCRIPTION = tr_noop(
  "<b>WARNING: openpilot longitudinal control is in alpha for this car and may disable Automatic Emergency Braking (AEB).</b><br><br>" +
  "On this car, openpilot defaults to the car's built-in ACC instead of openpilot's longitudinal control. " +
  "Enable this to switch to openpilot longitudinal control. " +
  "Changing this setting will restart openpilot if the car is powered on."
)


def set_alpha_longitudinal_enabled(params: Params, enabled: bool):
  params.put_bool("AlphaLongitudinalEnabled", enabled, block=True)
  params.put_bool("OnroadCycleRequested", True, block=True)


def alpha_longitudinal_dialog(callback):
  content = (f"<h1>{tr('openpilot Longitudinal Control (Alpha)')}</h1><br>" +
             f"<p>{tr(ALPHA_LONGITUDINAL_DESCRIPTION)}</p>")
  return ConfirmDialog(content, tr("Enable"), rich=True, callback=callback)
