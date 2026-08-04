from typing import Protocol


class ParamsStore(Protocol):
  def remove(self, key: str) -> None: ...
  def put_bool(self, key: str, value: bool, block: bool = False) -> None: ...


def set_lateral_maneuver_mode(params: ParamsStore, state: bool) -> None:
  if state:
    params.remove("LiveDelay")
  params.put_bool("LateralManeuverMode", state, block=True)
