"""Stock C3X chevrons and C4 lead bars."""
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
  widget.set_transform(np.array([[1080, -1000, 0], [540, 0, 1000], [1, 0, 0]]))
  widget._rect = module.rl.Rectangle(0, 0, 2160, 1080)
  widget._clip_region = widget._rect
  radar = SimpleNamespace(leadOne=SimpleNamespace(present=True, dRel=20., yRel=1., vRel=-2.),
                          leadTwo=SimpleNamespace(present=False, dRel=60., yRel=0., vRel=0.))

  class SubMaster(dict):
    recv_frame = {'extrinsicsCalibration': 1, 'modelV2': 1}
    updated = {'carParams': False, 'modelV2': False, 'radarState': False}
    valid = {'radarState': True}

  sm = SubMaster(radarState=radar, extrinsicsCalibration=SimpleNamespace(height=[1.22]), modelV2=SimpleNamespace(),
                selfdriveState=SimpleNamespace(enabled=True, engageable=False, experimentalMode=False),
                carState=SimpleNamespace(brakePressed=False), carOutput=SimpleNamespace(actuatorsOutput=SimpleNamespace(torque=0.)))
  if request.param == 'c4':
    sm['longitudinalPlan'] = SimpleNamespace(longitudinalPlanSource=module.log.LongitudinalPlan.LongitudinalPlanSource.lead0)
  monkeypatch.setattr(module.ui_state, 'sm', sm)
  monkeypatch.setattr(module.ui_state, 'started_frame', 0)

  def update():
    if request.param == 'c4':
      widget._update_leads(sm)
    else:
      widget._update_leads(radar, x)

  return request.param, module, widget, sm, update


def test_stock_lead_shape_and_disappearance(renderer, monkeypatch):
  variant, module, widget, sm, update = renderer
  update()
  draws = []
  if variant == 'c3x':
    monkeypatch.setattr(module.rl, 'draw_triangle_fan', lambda points, count, color: draws.append((points, color)))
  else:
    monkeypatch.setattr(module, 'draw_polygon', lambda rect, points, color: draws.append((points, color)) if len(points) else None)
  widget._draw_lead_indicator()
  assert len(draws) == (2 if variant == 'c3x' else 1)
  assert all(len(points) == (3 if variant == 'c3x' else 4) for points, _ in draws)
  assert draws[-1][1].a > 0
  sm['radarState'].leadOne.present = False
  for _ in range(60):
    update()
  draws.clear()
  widget._draw_lead_indicator()
  assert all(color.a == 0 for _, color in draws)


@pytest.mark.parametrize('longitudinal,valid,visible', [(True, True, True), (False, True, False), (True, False, False)])
def test_stock_lead_render_requires_longitudinal_control_and_radar(renderer, monkeypatch, longitudinal, valid, visible):
  _, _, widget, sm, update = renderer
  update()
  widget._longitudinal_control = longitudinal
  widget._transform_dirty = False
  sm.valid['radarState'] = valid
  monkeypatch.setattr(widget, '_draw_lane_lines', lambda: None)
  monkeypatch.setattr(widget, '_draw_path', lambda sm: None)
  draws = []
  monkeypatch.setattr(widget, '_draw_lead_indicator', lambda: draws.append(True))
  widget._render(widget._rect)
  assert bool(draws) == visible
