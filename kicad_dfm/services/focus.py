import time
from dataclasses import dataclass


@dataclass
class FocusResult:
    focused: bool = False
    unavailable: bool = False
    error: object = None


class FocusService:
    def __init__(self, backend):
        self.backend = backend

    def can_focus_native(self):
        try:
            capabilities = self.backend.capabilities()
        except Exception:
            return False
        return bool(getattr(capabilities, "can_focus_native", False))

    def focus_item(self, item, layer_id=None, profile=None):
        started_at = time.perf_counter()
        if item is None or not self.can_focus_native():
            self._record(profile, "focus_unavailable", True)
            self._record_elapsed(profile, "focus_ms", started_at)
            return FocusResult(unavailable=True)
        try:
            focused = bool(self.backend.focus_on_item(item, layer_id))
        except Exception as exc:
            self._record(profile, "focus_error", str(exc))
            self._record_elapsed(profile, "focus_ms", started_at)
            return FocusResult(error=exc)
        if focused:
            self._record(profile, "focused", True)
        else:
            self._record(profile, "focus_unavailable", True)
        self._record_elapsed(profile, "focus_ms", started_at)
        return FocusResult(focused=focused, unavailable=not focused)

    def _record(self, profile, name, value):
        if profile is not None:
            profile[name] = value

    def _record_elapsed(self, profile, name, started_at):
        if profile is not None:
            profile[name] = profile.get(name, 0.0) + round(
                (time.perf_counter() - started_at) * 1000.0,
                3,
            )
