from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture
def renderer(monkeypatch, tmp_path):
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path / 'params'))
  monkeypatch.setenv('SCALE', '1')
  from openpilot.selfdrive.ui.onroad import model_renderer as module

  monkeypatch.setattr(module.ui_state, 'status', module.UIStatus.ENGAGED)
  widget = module.ModelRenderer()
  x = np.linspace(0, 100, 33)
  widget._path.raw_points = np.column_stack((x, x * 0, x * 0))
  for line, y in zip(widget._lane_lines[1:3], (-1.8, 1.8), strict=True):
    line.raw_points = np.column_stack((x, x * 0 + y, x * 0))
  # C3X absolute screen coordinates, with a nonzero viewport origin.
  widget.set_transform(np.array([[1080, -1000, 0], [540, 0, 1000], [1, 0, 0]]))
  widget._rect = module.rl.Rectangle(30, 30, 2100, 1020)
  return module, widget


def signals(module, source='lead0', enabled=True, engageable=False, brake=False):
  return {
    'longitudinalPlan': SimpleNamespace(longitudinalPlanSource=getattr(module.log.LongitudinalPlan.LongitudinalPlanSource, source)),
    'modelV2': SimpleNamespace(leadsV3=[SimpleNamespace(prob=0.9, x=[40.0], y=[2.0]),
                                     SimpleNamespace(prob=0.9, x=[65.0], y=[-1.0])]),
    'radarState': SimpleNamespace(leadOne=SimpleNamespace(present=True, dRel=20.0, yRel=1.0),
                                  leadTwo=SimpleNamespace(present=True, dRel=60.0, yRel=-1.0)),
    'selfdriveState': SimpleNamespace(enabled=enabled, engageable=engageable, experimentalMode=False),
    'carState': SimpleNamespace(brakePressed=brake),
  }


def test_radar_and_model_positions(renderer):
  module, widget = renderer
  sm = signals(module)
  widget._update_leads(sm)
  assert widget._lead_vehicles[0].d_filter.x == 20 + module.RADAR_TO_CAMERA
  assert widget._lead_vehicles[0].y_filter.x == 1
  sm['longitudinalPlan'].longitudinalPlanSource = module.log.LongitudinalPlan.LongitudinalPlanSource.e2e
  widget._lead_vehicles = [module.LeadVehicle(), module.LeadVehicle()]
  widget._update_leads(sm)
  assert widget._lead_vehicles[0].d_filter.x == 40
  assert widget._lead_vehicles[0].y_filter.x == -2


def test_duplicate_lead_and_fade(renderer):
  module, widget = renderer
  sm = signals(module)
  sm['radarState'].leadTwo.dRel = 22
  widget._update_leads(sm)
  first, second = widget._lead_vehicles
  assert first.bar.shape == (4, 2)
  assert second.bar.size == 0
  alpha = first.fade_filter.x
  widget._update_leads(sm)
  assert first.fade_filter.x > alpha  # update at UI rate, even without a new model
  sm['radarState'].leadOne.present = False
  alpha = first.fade_filter.x
  widget._update_leads(sm)
  assert 0 < first.fade_filter.x < alpha
  assert not first.d_filter.initialized


@pytest.mark.parametrize('engageable,brake,visible', [(False, False, False), (True, False, True), (False, True, True)])
def test_disengaged_availability(renderer, monkeypatch, engageable, brake, visible):
  module, widget = renderer
  monkeypatch.setattr(module.ui_state, 'status', module.UIStatus.DISENGAGED)
  sm = signals(module, enabled=False, engageable=engageable, brake=brake)
  for _ in range(60):
    widget._update_leads(sm)
  assert (widget._lead_vehicles[0].bar.size > 0) == visible
  assert widget._lead_vehicles[0].fade_filter.x == pytest.approx(0.4 if visible else 0, abs=0.001)


def test_new_vehicle_snaps(renderer):
  module, widget = renderer
  sm = signals(module)
  widget._update_leads(sm)
  sm['radarState'].leadOne.yRel = 5.0
  sm['radarState'].leadOne.dRel = 45.0
  widget._update_leads(sm)
  assert widget._lead_vehicles[0].d_filter.x == 45 + module.RADAR_TO_CAMERA
  assert widget._lead_vehicles[0].y_filter.x == 5


def test_c3x_geometry_and_draw_origin(renderer, monkeypatch):
  module, widget = renderer
  lane = (widget._lane_lines[1].raw_points + widget._lane_lines[2].raw_points) / 2
  for distance in (2.0, 20.0, 99.0):
    bar = widget._get_lead_bar(lane, distance, 0)
    assert bar.shape == (4, 2) and bar.dtype == np.float32
    assert np.isfinite(bar).all()
    np.testing.assert_allclose(bar[[0, 3]].mean(axis=0), [1080, 540 + 1000 * widget._path_offset_z / distance], rtol=1e-6)
    length = np.linalg.norm(bar[[1, 2]].mean(axis=0) - bar[[0, 3]].mean(axis=0))
    assert 13.5 - 0.001 <= length <= 54.0 + 0.001
  widget._lead_vehicles[0].bar = bar
  draws = []
  monkeypatch.setattr(module, 'draw_polygon', lambda rect, points, color: draws.append(points))
  widget._draw_lead_indicator()
  np.testing.assert_array_equal(draws[0], bar)


@pytest.mark.parametrize('transform', [np.zeros((3, 3)), -np.eye(3), np.full((3, 3), np.nan),
                                       np.array([[1, 0, 0], [0, 0, 0], [1, 0, 0]])])
def test_invalid_projection_is_not_drawn(renderer, transform):
  _, widget = renderer
  widget.set_transform(transform)
  assert widget._get_lead_bar(widget._lane_lines[1].raw_points, 20, 0).size == 0


def test_render_updates_each_frame_and_resets_when_unavailable(renderer, monkeypatch):
  module, widget = renderer

  class SubMaster(dict):
    pass

  sm = SubMaster(signals(module))
  sm['extrinsicsCalibration'] = SimpleNamespace(height=[1.22])
  sm.recv_frame = {'extrinsicsCalibration': 1, 'modelV2': 1}
  sm.updated = {'carParams': False, 'modelV2': False, 'radarState': False}
  sm.valid = {'radarState': True}
  monkeypatch.setattr(module.ui_state, 'sm', sm)
  monkeypatch.setattr(module.ui_state, 'started_frame', 0)
  widget._longitudinal_control = True
  widget._transform_dirty = False
  monkeypatch.setattr(widget, '_draw_lane_lines', lambda: None)
  monkeypatch.setattr(widget, '_draw_path', lambda sm: None)
  monkeypatch.setattr(module, 'draw_polygon', lambda *args: None)
  widget._render(widget._rect)
  alpha = widget._lead_vehicles[0].fade_filter.x
  assert alpha > 0
  widget._render(widget._rect)
  assert widget._lead_vehicles[0].fade_filter.x > alpha
  sm.valid['radarState'] = False
  widget._render(widget._rect)
  assert all(lead.bar.size == 0 and lead.fade_filter.x == 0 for lead in widget._lead_vehicles)
