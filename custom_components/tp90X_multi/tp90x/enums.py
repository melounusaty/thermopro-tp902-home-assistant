"""Public enums used by the tp90x API."""

from enum import Enum


class AlarmMode(Enum):
    """Alarm configuration mode."""

    Off = 0
    Target = 1
    Range = 2


class SearchMode(Enum):
    """How ``connect()`` should locate a BLE device."""

    ADDRESS = "address"
    NAME = "name"
