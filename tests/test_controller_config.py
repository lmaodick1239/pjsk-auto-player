"""Tests for controller config coercion."""


def test_controller_numeric_config_is_coerced(monkeypatch):
    from controller.base import BaseController
    from controller.scrcpy import ScrcpyController
    from controller.combined import CombinedController

    class DummyController(BaseController):
        def connect(self) -> bool:
            return True

        def disconnect(self) -> bool:
            return True

        def screencap(self):
            return None

        def click(self, x: float, y: float) -> bool:
            return True

        def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 50) -> bool:
            return True

        def get_screen_size(self) -> tuple[int, int]:
            return self._screen_width, self._screen_height

    dummy = DummyController({"screen": {"width": "1080", "height": "2400"}})
    assert dummy._screen_width == 1080
    assert dummy._screen_height == 2400

    monkeypatch.setattr(ScrcpyController, "_find_scrcpy", staticmethod(lambda exe: exe))
    scrcpy = ScrcpyController({
        "scrcpy": {"max_fps": "60", "bit_rate": "12000000", "scale": "0.5"},
        "minitouch": {"port": "1111"},
        "adb": {},
        "screen": {"width": "1080", "height": "2400"},
    })
    assert scrcpy._max_fps == 60
    assert scrcpy._bit_rate == 12_000_000
    assert scrcpy._scale == 0.5
    assert scrcpy._mt_port == 1111

    monkeypatch.setattr(CombinedController, "_find_executable", staticmethod(lambda name: False))
    combined = CombinedController({
        "controller": {"switch_cooldown": "30.0", "perf_sample_size": "10"},
        "adb": {},
        "scrcpy": {},
        "screen": {"width": "1080", "height": "2400"},
    })
    assert combined._switch_cooldown == 30.0
    assert combined._perf_sample_size == 10