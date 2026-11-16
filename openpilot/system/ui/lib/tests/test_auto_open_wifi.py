import subprocess
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from jeepney import DBusAddress
from jeepney.low_level import MessageType

from openpilot.common.params import Params
from openpilot.system.ui.lib.networkmanager import NMDeviceState, NMDeviceStateReason, NM_802_11_AP_FLAGS_PRIVACY
from openpilot.system.ui.lib.wifi_manager import (WifiManager, WifiState, ConnectStatus, Network, SecurityType,
                                                AUTO_OPEN_CONNECTION_ID, AUTO_OPEN_RETRY_SECONDS, get_security_type)


@pytest.fixture
def wifi(tmp_path, monkeypatch):
  wm = WifiManager.__new__(WifiManager)
  wm._exit = True
  wm._active = False
  wm._params = Params(str(tmp_path / 'params'))
  wm._wifi_device = '/device/wifi'
  wm._nm = DBusAddress('/org/freedesktop/NetworkManager', bus_name='org.freedesktop.NetworkManager', interface='org.freedesktop.NetworkManager')
  wm._wifi_state = WifiState()
  wm._ipv4_address = ''
  wm._user_epoch = 0
  wm._connections = {'Home': '/saved/home'}
  wm._tethering_ssid = 'Hotspot'
  wm._networks = [Network('Cafe', 50, SecurityType.OPEN, False)]
  wm._activation_lock = threading.Lock()
  wm._auto_open_connection = None
  wm._auto_open_cooldown = {}
  wm._auto_open_idle_since = 0.0
  wm._callback_queue = []
  wm._activated = wm._forgotten = []
  wm._get_connection_settings = Mock(return_value={'connection': {'id': ('s', 'Home')}})
  wm._get_active_wifi_connection = Mock(return_value=('/settings/auto', {}))
  wm._update_active_connection_info = Mock()
  wm._conn_monitor = Mock()
  wm._wifi_has_internet = Mock(return_value=True)
  wm._init_wifi_state = Mock()
  props = {'State': ('u', NMDeviceState.DISCONNECTED), 'ActiveConnection': ('o', '/'), 'IpInterface': ('s', 'wlan0')}
  clock = [30.0]
  monkeypatch.setattr('openpilot.system.ui.lib.wifi_manager.time.monotonic', lambda: clock[0])

  def reply(message):
    member = message.header.fields[3]
    body = (props,) if member == 'GetAll' else ('/settings/auto', '/active/auto', {}) if member == 'AddAndActivateConnection2' else ()
    return SimpleNamespace(header=SimpleNamespace(message_type=MessageType.method_return), body=body)

  wm._router_main = Mock()
  wm._router_main.send_and_get_reply.side_effect = reply

  def calls(member):
    return [c.args[0] for c in wm._router_main.send_and_get_reply.call_args_list if c.args[0].header.fields[3] == member]

  def connected(state=NMDeviceState.ACTIVATED, path='/active/auto'):
    props.update(State=('u', state), ActiveConnection=('o', path))

  return SimpleNamespace(wm=wm, clock=clock, props=props, calls=calls, connected=connected)


def test_default_enabled_and_persistent_opt_out(wifi, tmp_path):
  wm = wifi.wm
  assert wm.auto_connect_open_wifi
  wm.set_auto_connect_open_wifi(False)
  assert not wm.auto_connect_open_wifi
  assert Params(str(tmp_path / 'params')).get_bool('DisableAutoConnectOpenWifi')
  wm._auto_connect_open_network()
  assert not wifi.calls('AddAndActivateConnection2')
  wm.set_auto_connect_open_wifi(True)
  wifi.clock[0] += 30.0
  wm._auto_connect_open_network()
  assert len(wifi.calls('AddAndActivateConnection2')) == 1


def test_saved_network_grace_and_strongest_eligible_open_network(wifi):
  wm = wifi.wm
  wm._networks += [Network('Home', 100, SecurityType.OPEN, False), Network('Secure', 95, SecurityType.WPA, False),
                   Network('Hotspot', 100, SecurityType.OPEN, True), Network('Blocked', 90, SecurityType.OPEN, False),
                   Network('Library', 80, SecurityType.OPEN, False)]
  wm._auto_open_cooldown['Blocked'] = 100.0
  wifi.clock[0] = 29.0
  wm._auto_connect_open_network()
  assert not wifi.calls('AddAndActivateConnection2')
  wifi.clock[0] = 30.0
  wm._auto_connect_open_network()
  message, = wifi.calls('AddAndActivateConnection2')
  settings, device, _, options = message.body
  assert settings['802-11-wireless']['ssid'] == ('ay', b'Library')
  assert '802-11-wireless-security' not in settings
  assert settings['connection']['autoconnect'] == ('b', False)
  assert settings['connection']['id'] == ('s', AUTO_OPEN_CONNECTION_ID)
  assert options == {'persist': ('s', 'volatile'), 'bind-activation': ('s', 'dbus-client')}
  assert device == wm._wifi_device


@pytest.mark.parametrize('state', [NMDeviceState.UNAVAILABLE, NMDeviceState.UNMANAGED, NMDeviceState.PREPARE,
                                  NMDeviceState.IP_CONFIG, NMDeviceState.ACTIVATED, NMDeviceState.DEACTIVATING])
def test_never_replaces_an_existing_connection_or_enables_wifi(wifi, state):
  wifi.props['State'] = ('u', state)
  wifi.wm._auto_connect_open_network()
  assert not wifi.calls('AddAndActivateConnection2')
  assert not wifi.calls('DeactivateConnection')


def test_manual_selection_during_device_lookup_wins(wifi):
  wm = wifi.wm
  old_reply = wm._router_main.send_and_get_reply.side_effect

  def user_action(message):
    wm._set_connecting('Home')
    return old_reply(message)

  wm._router_main.send_and_get_reply.side_effect = user_action
  wm._auto_connect_open_network()
  assert not wifi.calls('AddAndActivateConnection2')


def test_manual_selection_while_waiting_for_activation_lock_wins(wifi):
  wm = wifi.wm

  @contextmanager
  def manual_action():
    wm._set_connecting('Home')
    yield

  wm._activation_lock = manual_action()
  wm._auto_connect_open_network()
  assert not wifi.calls('AddAndActivateConnection2')


@pytest.mark.parametrize('enabled', [True, False])
def test_background_scanning_does_not_require_settings_visible(wifi, monkeypatch, enabled):
  wm = wifi.wm
  wm.set_auto_connect_open_wifi(enabled)
  wm._exit = False
  wm._last_network_scan = 0.0
  wm._request_scan = Mock()
  wm._wifi_state = WifiState(status=ConnectStatus.DISCONNECTED)
  monkeypatch.setattr(wm, '_auto_connect_open_network', Mock())
  monkeypatch.setattr('openpilot.system.ui.lib.wifi_manager.time.sleep', lambda _: setattr(wm, '_exit', True))
  wifi.clock[0] = 31.0
  wm._network_scanner()
  assert wm._request_scan.call_count == int(enabled)


@pytest.mark.parametrize('failure', ['timeout', 'portal', 'activation_failed'])
def test_failed_attempt_is_temporarily_skipped(wifi, failure):
  wm = wifi.wm
  wm._auto_connect_open_network()
  wifi.connected(NMDeviceState.IP_CONFIG if failure == 'timeout' else NMDeviceState.ACTIVATED)
  if failure == 'timeout':
    wifi.clock[0] = 60.0
  elif failure == 'activation_failed':
    wifi.connected(NMDeviceState.FAILED)
  else:
    wm._wifi_has_internet.return_value = False
  wm._auto_connect_open_network()
  assert wifi.calls('DeactivateConnection')[-1].body == ('/active/auto',)
  assert wm._auto_open_connection is None
  assert wm._auto_open_cooldown['Cafe'] == wifi.clock[0] + AUTO_OPEN_RETRY_SECONDS
  wifi.props.update(State=('u', NMDeviceState.DISCONNECTED), ActiveConnection=('o', '/'))
  wifi.clock[0] += AUTO_OPEN_RETRY_SECONDS - 1
  wm._auto_connect_open_network()
  assert len(wifi.calls('AddAndActivateConnection2')) == 1
  wifi.clock[0] += 1
  wm._auto_connect_open_network()
  assert len(wifi.calls('AddAndActivateConnection2')) == 2


def test_working_connection_stays_and_is_periodically_rechecked(wifi):
  wm = wifi.wm
  wm._auto_connect_open_network()
  wifi.connected()
  wm._auto_connect_open_network()
  wm._wifi_has_internet.assert_called_once_with('wlan0')
  wifi.clock[0] += 29
  wm._auto_connect_open_network()
  assert wm._wifi_has_internet.call_count == 1
  wifi.clock[0] += 1
  wm._wifi_has_internet.return_value = False
  wm._auto_connect_open_network()
  assert len(wifi.calls('AddAndActivateConnection2')) == 1
  assert len(wifi.calls('DeactivateConnection')) == 1


def test_opt_out_disconnects_only_the_automatic_connection(wifi):
  wm = wifi.wm
  wm._auto_connect_open_network()
  wm.set_auto_connect_open_wifi(False)
  wm._auto_connect_open_network()
  assert wifi.calls('DeactivateConnection')[-1].body == ('/active/auto',)
  wm._auto_connect_open_network()
  assert len(wifi.calls('DeactivateConnection')) == 1


def test_rejected_activation_is_skipped_without_saving_or_deleting_profiles(wifi):
  wm = wifi.wm
  old_reply = wm._router_main.send_and_get_reply.side_effect

  def rejected(message):
    if message.header.fields[3] == 'AddAndActivateConnection2':
      return SimpleNamespace(header=SimpleNamespace(message_type=MessageType.error), body=('not available',))
    return old_reply(message)

  wm._router_main.send_and_get_reply.side_effect = rejected
  wm._auto_connect_open_network()
  assert wm._auto_open_connection is None
  assert wm._auto_open_cooldown['Cafe'] == wifi.clock[0] + AUTO_OPEN_RETRY_SECONDS
  assert not wifi.calls('Save')
  assert not wifi.calls('Delete')


def test_failed_probe_cannot_disconnect_manual_replacement(wifi):
  wm = wifi.wm
  wm._auto_connect_open_network()
  wifi.connected()

  def manual_replacement(_interface):
    wm._set_connecting('Home')
    wifi.connected(path='/active/manual')
    return False

  wm._wifi_has_internet.side_effect = manual_replacement
  wm._auto_connect_open_network()
  assert wifi.calls('DeactivateConnection')[-1].body == ('/active/auto',)
  assert wm.connecting_to_ssid == 'Home'


@pytest.mark.parametrize('automatic', [False, True])
def test_only_manually_selected_connections_are_saved(wifi, automatic):
  wm = wifi.wm
  wm._get_connection_settings.return_value = {'connection': {'id': ('s', AUTO_OPEN_CONNECTION_ID if automatic else 'Home')}}
  wm._handle_state_change(NMDeviceState.ACTIVATED, NMDeviceState.IP_CONFIG, NMDeviceStateReason.NONE)
  assert wm._conn_monitor.send_and_get_reply.call_count == (0 if automatic else 1)


@pytest.mark.parametrize('code,returncode,expected', [(b'204', 0, True), (b'302', 0, False), (b'200', 0, False), (b'204', 60, False)])
def test_connectivity_requires_verified_wifi_https_response(wifi, monkeypatch, code, returncode, expected):
  run = Mock(return_value=SimpleNamespace(stdout=code, returncode=returncode))
  monkeypatch.setattr('openpilot.system.ui.lib.wifi_manager.subprocess.run', run)
  assert WifiManager._wifi_has_internet(wifi.wm, 'wlan0') == expected
  command = run.call_args.args[0]
  assert command[0:2] == ['curl', '--disable']
  assert command[command.index('--interface') + 1] == 'if!wlan0'
  assert command[command.index('--noproxy') + 1] == '*'
  assert command[command.index('--max-time') + 1] == '10'
  assert command[-1].startswith('https://')
  assert not {'--insecure', '-k', '--location', '-L'} & set(command)


@pytest.mark.parametrize('error', [OSError(), subprocess.TimeoutExpired('curl', 12)])
def test_probe_failure_is_unusable_wifi(wifi, monkeypatch, error):
  monkeypatch.setattr('openpilot.system.ui.lib.wifi_manager.subprocess.run', Mock(side_effect=error))
  assert not WifiManager._wifi_has_internet(wifi.wm, 'wlan0')
  assert not WifiManager._wifi_has_internet(wifi.wm, '')


def test_network_settings_toggle_controls_the_same_policy(wifi, monkeypatch, tmp_path):
  import raylib_nb as rl
  from openpilot.system.ui.widgets import network

  monkeypatch.setattr(network.gui_app, 'font', lambda *args: rl.Font())
  monkeypatch.setattr(network, 'Keyboard', Mock())
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path / 'ui_params'))
  wm = wifi.wm
  wm.add_callbacks = Mock()
  panel = network.AdvancedNetworkSettings(wm)
  assert panel._auto_open_action.get_state()
  auto_item = panel._scroller._items[0]
  panel._auto_open_action.set_state(False)
  auto_item.callback()
  assert not wm.auto_connect_open_wifi
  panel._auto_open_action.set_state(True)
  auto_item.callback()
  assert wm.auto_connect_open_wifi


def test_security_flags_cannot_misclassify_encrypted_network_as_open():
  assert get_security_type(0, 0, 0) == SecurityType.OPEN
  assert get_security_type(NM_802_11_AP_FLAGS_PRIVACY, 0, 0) != SecurityType.OPEN
  assert get_security_type(0, 0, 0x800) != SecurityType.OPEN
