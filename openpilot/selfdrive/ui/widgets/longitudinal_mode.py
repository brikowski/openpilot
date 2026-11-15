from openpilot.selfdrive.ui.layouts.settings.alpha_longitudinal import alpha_longitudinal_dialog, set_alpha_longitudinal_enabled
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.button import Button


class LongitudinalModeButton(Button):
  def __init__(self):
    super().__init__(lambda: tr("OpenPilot") if ui_state.alpha_long_enabled else tr("Radar"), self._toggle, font_size=40)
    self.set_visible(self._available)

  @staticmethod
  def _available():
    return (ui_state.is_offroad() and not ui_state.ignition and not ui_state.is_release and
            ui_state.CP is not None and ui_state.CP.alphaLongitudinalAvailable)

  def _apply(self, enabled: bool):
    # Recheck after confirmation: ignition may have turned on while the dialog was open.
    if self._available():
      set_alpha_longitudinal_enabled(ui_state.params, enabled)
      ui_state.update_params()

  def _toggle(self):
    if not self._available():
      return
    if ui_state.params.get_bool("AlphaLongitudinalEnabled"):
      self._apply(False)
    else:
      def confirmed(result):
        if result == DialogResult.CONFIRM:
          self._apply(True)

      gui_app.push_widget(alpha_longitudinal_dialog(confirmed))
