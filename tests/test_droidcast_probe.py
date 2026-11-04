"""DroidCast native-preview layout probe should not request a scaled preview."""

from types import SimpleNamespace
from unittest.mock import Mock

from module.device.method.droidcast import DroidCast


def test_probe_uses_native_dimensions_without_resize_parameters():
    head = b'\x89PNG\r\n\x1a\n' + (13).to_bytes(4, 'big') + b'IHDR'
    head += (720).to_bytes(4, 'big') + (1280).to_bytes(4, 'big') + b'\x08\x02\x00\x00\x00'
    session = Mock()
    session.get.return_value.raw.read.return_value = head
    fake = SimpleNamespace(orientation=0, _droidcast_raw_probe_key=None,
                           _droidcast_raw_transposed=False, _droidcast_port=53516,
                           droidcast_session=session, droidcast_url=Mock())

    assert DroidCast._droidcast_raw_probe_transposed(fake, (720, 1280))
    session.get.assert_called_once_with(
        'http://127.0.0.1:53516/preview', timeout=3, stream=True)
    fake.droidcast_url.assert_not_called()
