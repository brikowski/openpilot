#!/usr/bin/env python3
import datetime
import os
import signal
import sys
import time
import traceback

from openpilot.cereal import log
import openpilot.cereal.messaging as messaging
from openpilot.common.utils import atomic_write
from openpilot.common.params import Params, ParamKeyFlag
from openpilot.common.text_window import TextWindow
from openpilot.common.hardware import HARDWARE
from openpilot.system.manager.helpers import unblock_stdout, save_bootlog
from openpilot.system.manager.process import ensure_running
from openpilot.system.manager.process_config import managed_processes
from openpilot.system.athena.registration import register, UNREGISTERED_DONGLE_ID
from openpilot.system.updated.updated import can_install_update
from openpilot.common.swaglog import cloudlog, add_file_handler
from openpilot.common.version import get_build_metadata
from openpilot.common.hardware.hw import Paths


def manager_init() -> None:
  save_bootlog()

  build_metadata = get_build_metadata()

  params = Params()
  params.clear_all(ParamKeyFlag.CLEAR_ON_MANAGER_START)
  params.clear_all(ParamKeyFlag.CLEAR_ON_ONROAD_TRANSITION)
  params.clear_all(ParamKeyFlag.CLEAR_ON_OFFROAD_TRANSITION)
  params.clear_all(ParamKeyFlag.CLEAR_ON_IGNITION_ON)
  if build_metadata.release_channel:
    params.clear_all(ParamKeyFlag.DEVELOPMENT_ONLY)

  if params.get_bool("RecordFrontLock"):
    params.put_bool("RecordFront", True, block=True)

  if params.get_bool("AlwaysOnDMLock"):
    params.put_bool("AlwaysOnDM", True, block=True)

  # set unset params to their default value
  for k in params.all_keys():
    default_value = params.get_default_value(k)
    if default_value is not None and params.get(k) is None:
      params.put(k, default_value, block=True)

  # Create folders needed for msgq
  try:
    os.mkdir(Paths.shm_path())
  except FileExistsError:
    pass
  except PermissionError:
    print(f"WARNING: failed to make {Paths.shm_path()}")

  # set params
  serial = HARDWARE.get_serial()
  params.put("Version", build_metadata.openpilot.version, block=True)
  params.put("GitCommit", build_metadata.openpilot.git_commit, block=True)
  params.put("GitCommitDate", build_metadata.openpilot.git_commit_date, block=True)
  params.put("GitBranch", build_metadata.channel, block=True)
  params.put("GitRemote", build_metadata.openpilot.git_origin, block=True)
  params.put_bool("IsTestedBranch", build_metadata.tested_channel, block=True)
  params.put_bool("IsReleaseBranch", build_metadata.release_channel, block=True)
  params.put("HardwareSerial", serial, block=True)

  # set dongle id
  reg_res = register(show_spinner=True)
  if reg_res:
    dongle_id = reg_res
  else:
    raise Exception(f"Registration failed for device {serial}")
  os.environ['DONGLE_ID'] = dongle_id  # Needed for swaglog
  os.environ['GIT_ORIGIN'] = build_metadata.openpilot.git_normalized_origin # Needed for swaglog
  os.environ['GIT_BRANCH'] = build_metadata.channel # Needed for swaglog
  os.environ['GIT_COMMIT'] = build_metadata.openpilot.git_commit # Needed for swaglog

  if not build_metadata.openpilot.is_dirty:
    os.environ['CLEAN'] = '1'

  # init logging
  cloudlog.bind_global(dongle_id=dongle_id,
                       version=build_metadata.openpilot.version,
                       origin=build_metadata.openpilot.git_normalized_origin,
                       branch=build_metadata.channel,
                       commit=build_metadata.openpilot.git_commit,
                       dirty=build_metadata.openpilot.is_dirty,
                       device=HARDWARE.get_device_type())

def manager_cleanup() -> None:
  # send signals to kill all procs
  for p in managed_processes.values():
    p.stop(block=False)

  # ensure all are killed
  for p in managed_processes.values():
    p.stop(block=True)

  cloudlog.info("everything is dead")


AUTO_UPDATE_OFFROAD_DELAY_S = 60.0
AUTO_UPDATE_CHECK_INTERVAL_S = 30.0
AUTO_UPDATE_MIN_FREE_SPACE_PERCENT = 5.0
AUTO_UPDATE_MIN_VOLTAGE_MV = 11_800


def _vehicle_offroad_ignition_off(params: Params, sm: messaging.SubMaster) -> bool:
  if not params.get_bool("IsOffroad"):
    return False

  services = ['deviceState', 'pandaStates']
  if not all(sm.updated[s] for s in services) or not sm.all_checks(services) or sm['deviceState'].started:
    return False

  # Offroad can also mean startup was blocked while the car is still running.
  pandas = sm['pandaStates']
  return bool(pandas) and not any(ps.pandaType == log.PandaState.PandaType.unknown or ps.ignitionLine or ps.ignitionCan for ps in pandas)


def _auto_update_environment_ready(params: Params, sm: messaging.SubMaster) -> bool:
  if (not params.get_bool("UpdateAvailable") or params.get_bool("DisableUpdates") or
      params.get("UpdaterState") != "idle" or
      any(params.get_bool(key) for key in ("DoShutdown", "DoUninstall", "DoReboot", "IsDriverViewEnabled", "IsLiveStreaming"))):
    return False

  if not _vehicle_offroad_ignition_off(params, sm):
    return False

  device_state = sm['deviceState']
  if device_state.thermalStatus >= log.DeviceState.ThermalStatus.overheated or device_state.freeSpacePercent < AUTO_UPDATE_MIN_FREE_SPACE_PERCENT:
    return False

  in_car = any(ps.harnessStatus != log.PandaState.HarnessStatus.notConnected for ps in sm['pandaStates'])
  if in_car:
    if 'peripheralState' not in sm.services or not sm.all_checks(['peripheralState']):
      return False
    peripheral = sm['peripheralState']
    if peripheral.pandaType == log.PandaState.PandaType.unknown or peripheral.voltage < AUTO_UPDATE_MIN_VOLTAGE_MV:
      return False

  return True


def should_reboot_for_update(params: Params, sm: messaging.SubMaster) -> bool:
  return _auto_update_environment_ready(params, sm) and can_install_update(params.get("UpdaterTargetBranch"))


class AutoUpdateTracker:
  """Apply an ignition-off settle window and throttle repeated staging inspections."""

  def __init__(self) -> None:
    self._offroad_ign_off_since: float | None = None
    self._next_staging_check: float = 0.0
    self._last_target_branch: str | None = None
    self._last_updater_state: str | None = None
    self._deferred_logged: bool = False

  def should_reboot(self, params: Params, sm: messaging.SubMaster) -> bool:
    now = time.monotonic()
    if _vehicle_offroad_ignition_off(params, sm):
      if self._offroad_ign_off_since is None:
        self._offroad_ign_off_since = now
    else:
      self._offroad_ign_off_since = None

    updater_state = params.get("UpdaterState")
    target_branch = params.get("UpdaterTargetBranch")
    if (not params.get_bool("UpdateAvailable") or
        (updater_state != self._last_updater_state and updater_state == "idle") or
        target_branch != self._last_target_branch):
      self._next_staging_check = 0.0
      self._deferred_logged = False
    self._last_updater_state = updater_state
    self._last_target_branch = target_branch

    if not _auto_update_environment_ready(params, sm):
      return False
    if self._offroad_ign_off_since is None or now - self._offroad_ign_off_since < AUTO_UPDATE_OFFROAD_DELAY_S:
      return False
    if now < self._next_staging_check:
      return False

    if can_install_update(target_branch):
      return True

    self._next_staging_check = now + AUTO_UPDATE_CHECK_INTERVAL_S
    if not self._deferred_logged:
      cloudlog.info("deferring automatic update installation until staging guards pass")
      self._deferred_logged = True
    return False


def manager_thread() -> None:
  cloudlog.bind(daemon="manager")
  cloudlog.info("manager start")
  cloudlog.info({"environ": os.environ})

  params = Params()

  ignore: list[str] = []
  if params.get("DongleId") in (None, UNREGISTERED_DONGLE_ID):
    ignore += ["manage_athenad", "uploader"]
  if os.getenv("NOBOARD") is not None:
    ignore.append("pandad")
  ignore += [x for x in os.getenv("BLOCK", "").split(",") if len(x) > 0]

  sm = messaging.SubMaster(['deviceState', 'carParams', 'pandaStates', 'peripheralState'], poll='deviceState')
  pm = messaging.PubMaster(['managerState'])
  auto_update = AutoUpdateTracker()

  params.put_bool("IsOffroad", True, block=True)
  ensure_running(managed_processes.values(), False, params=params, CP=sm['carParams'], not_run=ignore)

  started_prev = False
  ignition_prev = False

  while True:
    sm.update(1000)

    started = sm['deviceState'].started

    if started and not started_prev:
      params.clear_all(ParamKeyFlag.CLEAR_ON_ONROAD_TRANSITION)
    elif not started and started_prev:
      params.clear_all(ParamKeyFlag.CLEAR_ON_OFFROAD_TRANSITION)

    ignition = any(ps.ignitionLine or ps.ignitionCan for ps in sm['pandaStates'] if ps.pandaType != log.PandaState.PandaType.unknown)
    if ignition and not ignition_prev:
      params.clear_all(ParamKeyFlag.CLEAR_ON_IGNITION_ON)

    # update offroad state for services that don't subscribe to deviceState
    if started != started_prev:
      params.put_bool("IsOffroad", not started, block=True)

    started_prev = started
    ignition_prev = ignition

    ensure_running(managed_processes.values(), started, params=params, CP=sm['carParams'], not_run=ignore)

    running = ' '.join("{}{}\u001b[0m".format("\u001b[32m" if p.proc.is_alive() else "\u001b[31m", p.name)
                       for p in managed_processes.values() if p.proc)
    print(running)
    cloudlog.debug(running)

    # send managerState
    msg = messaging.new_message('managerState', valid=True)
    msg.managerState.processes = [p.get_process_state_msg() for p in managed_processes.values()]
    pm.send('managerState', msg)

    # kick AGNOS power monitoring watchdog
    try:
      if sm.all_checks(['deviceState']):
        with atomic_write("/var/tmp/power_watchdog", "w", overwrite=True) as f:
          f.write(str(time.monotonic()))
    except Exception:
      pass

    if auto_update.should_reboot(params, sm):
      cloudlog.info("installing staged update automatically with ignition off")
      params.put_bool("DoReboot", True, block=True)

    # Exit main loop when uninstall/shutdown/reboot is needed
    shutdown = False
    for param in ("DoUninstall", "DoShutdown", "DoReboot"):
      if params.get_bool(param):
        shutdown = True
        params.put("LastManagerExitReason", f"{param} {datetime.datetime.now()}", block=True)
        cloudlog.warning(f"Shutting down manager - {param} set")

    if shutdown:
      break


def main() -> None:
  manager_init()
  if os.getenv("PREPAREONLY") is not None:
    return

  # SystemExit on sigterm
  signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(1))

  try:
    manager_thread()
  except Exception:
    traceback.print_exc()
    cloudlog.exception("crash")
  finally:
    manager_cleanup()

  params = Params()
  if params.get_bool("DoUninstall"):
    cloudlog.warning("uninstalling")
    HARDWARE.uninstall()
  elif params.get_bool("DoReboot"):
    cloudlog.warning("reboot")
    HARDWARE.reboot()
  elif params.get_bool("DoShutdown"):
    cloudlog.warning("shutdown")
    HARDWARE.shutdown()


if __name__ == "__main__":
  unblock_stdout()

  try:
    main()
  except KeyboardInterrupt:
    print("got CTRL-C, exiting")
  except Exception:
    add_file_handler(cloudlog)
    cloudlog.exception("Manager failed to start")

    try:
      managed_processes['ui'].stop()
    except Exception:
      pass

    # Show last 3 lines of traceback
    error = traceback.format_exc(-3)
    error = "Manager failed to start\n\n" + error
    with TextWindow(error) as t:
      t.wait_for_exit()

    raise

  # manual exit because we are forked
  sys.exit(0)
