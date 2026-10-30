import sys
import types
import unittest
from datetime import date, datetime as RealDateTime
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo


def _install_homeassistant_stubs():
    """Provide the small Home Assistant surface needed by the coordinator."""
    try:
        __import__("homeassistant")
        return
    except ModuleNotFoundError:
        pass

    homeassistant = types.ModuleType("homeassistant")
    homeassistant.__path__ = []
    sys.modules["homeassistant"] = homeassistant

    const = types.ModuleType("homeassistant.const")
    const.CONF_USERNAME = "username"
    const.CONF_PASSWORD = "password"
    sys.modules["homeassistant.const"] = const

    components = types.ModuleType("homeassistant.components")
    components.__path__ = []
    sys.modules["homeassistant.components"] = components

    recorder = types.ModuleType("homeassistant.components.recorder")
    recorder.get_instance = Mock()
    sys.modules["homeassistant.components.recorder"] = recorder

    statistics = types.ModuleType("homeassistant.components.recorder.statistics")
    statistics.async_add_external_statistics = Mock()
    statistics.get_last_statistics = Mock()
    sys.modules["homeassistant.components.recorder.statistics"] = statistics

    models = types.ModuleType("homeassistant.components.recorder.models")
    models.StatisticMeanType = types.SimpleNamespace(NONE="none")
    sys.modules["homeassistant.components.recorder.models"] = models

    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    sys.modules["homeassistant.core"] = core

    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    sys.modules["homeassistant.helpers"] = helpers

    event = types.ModuleType("homeassistant.helpers.event")
    event.async_call_later = Mock()
    event.async_track_time_change = Mock()
    sys.modules["homeassistant.helpers.event"] = event


_install_homeassistant_stubs()

import custom_components.ovak as ovak  # noqa: E402


class FixedDateTime(RealDateTime):
    @classmethod
    def now(cls, tz=None):
        current = cls(2026, 10, 30, 12, tzinfo=ZoneInfo("Europe/Prague"))
        return current.astimezone(tz) if tz is not None else current


class ManualRefreshTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        hass = types.SimpleNamespace(
            config=types.SimpleNamespace(time_zone="Europe/Prague")
        )
        entry = types.SimpleNamespace(data={})
        self.coordinator = ovak.OvakCoordinator(hass, entry)

    async def test_current_reading_skips_download(self):
        self.coordinator.last_day = date(2026, 10, 29)
        self.coordinator.refresh = AsyncMock()

        with patch.object(ovak, "datetime", FixedDateTime):
            result = await self.coordinator.manual_refresh()

        self.assertFalse(result)
        self.coordinator.refresh.assert_not_awaited()

    async def test_successful_manual_refresh_cancels_retry(self):
        self.coordinator.last_day = date(2026, 10, 28)
        self.coordinator.refresh = AsyncMock(return_value=True)
        self.coordinator._cancel_pending_retry = Mock()

        with patch.object(ovak, "datetime", FixedDateTime):
            result = await self.coordinator.manual_refresh()

        self.assertTrue(result)
        self.coordinator._cancel_pending_retry.assert_called_once_with()

    async def test_failed_manual_refresh_preserves_retry(self):
        self.coordinator.last_day = date(2026, 10, 28)
        self.coordinator.refresh = AsyncMock(return_value=False)
        self.coordinator._cancel_pending_retry = Mock()

        with patch.object(ovak, "datetime", FixedDateTime):
            result = await self.coordinator.manual_refresh()

        self.assertFalse(result)
        self.coordinator._cancel_pending_retry.assert_not_called()

    async def test_successful_download_records_time_and_notifies(self):
        listener = Mock()
        self.coordinator.async_add_listener(listener)

        with patch.object(ovak, "datetime", FixedDateTime):
            self.coordinator._record_successful_download()

        self.assertEqual(
            FixedDateTime.now(self.coordinator._tz),
            self.coordinator.last_successful_download,
        )
        listener.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
