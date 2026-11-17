"""C3X and stock C4 white lead bars."""
import importlib
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture(params=['c3x', 'c4'])
def renderer(request, monkeypatch, tmp_path):
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path / 'params'))
  monkeypatch.setenv('SCALE', '1')
  prefix = 'mici.' if request.param == 'c4' else ''
  module = importlib.import_module(f'openpilot.selfdrive.ui.{prefix}onroad.model_renderer')
  widget = module.ModelRenderer()
  x = np.linspace(0, 100, 33)
  widget._path.raw_points = np.column_stack((x, x * 0, x * 0))
  widget.set_transform(np.array([[1080, 1000, 0], [540, 0, 1000], [1, 0, 0]]))
  widget._rect = module.rl.Rectangle(0, 0, 2160, 1080)
  widget._clip_region = widget._rect
  radar = SimpleNamespace(leadOne=SimpleNamespace(present=True, dRel=20., yRel=1., vRel=-2.),
                          leadTwo=SimpleNamespace(present=False, dRel=60., yRel=0., vRel=0.))

  class SubMaster(dict):
    frame = 1
    recv_frame = {'extrinsicsCalibration': 1, 'modelV2': 1}
    updated = {'carParams': False, 'modelV2': False, 'radarState': False}
    valid = {'radarState': True}

  model = SimpleNamespace(velocity=SimpleNamespace(x=[]), position=SimpleNamespace(x=[]))
  sm = SubMaster(radarState=radar, extrinsicsCalibration=SimpleNamespace(height=[1.22]), modelV2=model,
                selfdriveState=SimpleNamespace(enabled=True, engageable=False),
                carState=SimpleNamespace(brakePressed=False, vEgo=20.),
                carOutput=SimpleNamespace(actuatorsOutput=SimpleNamespace(torque=0.)))
  if request.param == 'c4':
    sm['longitudinalPlan'] = SimpleNamespace(longitudinalPlanSource=module.log.LongitudinalPlan.LongitudinalPlanSource.lead0)
  monkeypatch.setattr(module.ui_state, 'sm', sm)
  monkeypatch.setattr(module.ui_state, '_started_frame', 0)

  def update():
    if request.param == 'c4':
      widget._update_lead_bars(sm)
    else:
      widget._update_leads(radar, x)

  return request.param, module, widget, sm, update


def test_stock_lead_shape_and_disappearance(renderer, monkeypatch):
  from openpilot.selfdrive.ui.onroad import lead_bar

  platform, module, widget, sm, update = renderer
  update()
  draws = []
  monkeypatch.setattr(module if platform == 'c4' else lead_bar, 'draw_polygon',
                      lambda rect, points, color: draws.append((points, color)) if len(points) else None)
  widget._draw_lead_indicator()
  assert len(draws) == (1 if platform == 'c4' else 2)
  assert all(len(points) == 4 and np.isfinite(points).all() for points, _ in draws)
  assert (draws[-1][1].r, draws[-1][1].g, draws[-1][1].b) == (255, 255, 255)
  assert draws[-1][1].a > 0
  sm['radarState'].leadOne.present = False
  for _ in range(60):
    update()
  draws.clear()
  widget._draw_lead_indicator()
  assert all(color.a == 0 for _, color in draws)


def test_lead_draw_uses_platform_coordinates(renderer, monkeypatch):
  from openpilot.selfdrive.ui.onroad import lead_bar

  platform, module, widget, _, update = renderer
  widget._rect = module.rl.Rectangle(25, 40, 2160, 1080)
  update()
  leads = widget._lead_bars if platform == 'c4' else widget._lead_vehicles
  points = leads[0].bar.copy()
  draws = []
  monkeypatch.setattr(module if platform == 'c4' else lead_bar, 'draw_polygon',
                      lambda rect, points, color: draws.append(points) if len(points) else None)
  widget._draw_lead_indicator()
  np.testing.assert_allclose(draws[0 if platform == 'c4' else 1], points + ([25, 40] if platform == 'c4' else [0, 0]))


@pytest.mark.parametrize('longitudinal,valid,visible', [(True, True, True), (False, True, False), (True, False, False)])
def test_stock_lead_render_requires_longitudinal_control_and_radar(renderer, monkeypatch, longitudinal, valid, visible):
  _, _, widget, sm, update = renderer
  update()
  widget._longitudinal_control = longitudinal
  widget._transform_dirty = False
  sm.valid['radarState'] = valid
  monkeypatch.setattr(widget, '_draw_lane_lines', lambda: None)
  monkeypatch.setattr(widget, '_draw_path', lambda sm=None: None)
  draws = []
  monkeypatch.setattr(widget, '_draw_lead_indicator', lambda: draws.append(True))
  widget._render(widget._rect)
  assert bool(draws) == visible
