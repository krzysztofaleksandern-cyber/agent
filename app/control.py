"""Global control switch: an owner-operated pause that halts all agent actions."""

import threading


class ControlState:
    """Thread-safe master switch. When paused, agents take no tool actions."""

    def __init__(self, paused: bool = False) -> None:
        self._paused = paused
        self._lock = threading.Lock()

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    def set_paused(self, paused: bool) -> bool:
        with self._lock:
            self._paused = paused
        return paused
