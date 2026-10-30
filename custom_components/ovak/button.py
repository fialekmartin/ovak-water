"""Manual data refresh button for OVAK."""

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the manual refresh button."""
    async_add_entities([OvakRefreshButton(hass.data[DOMAIN][entry.entry_id])])


class OvakRefreshButton(ButtonEntity):
    """Request the latest missing daily reading on demand."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh"
    _attr_unique_id = "ovak_manual_refresh"
    _attr_icon = "mdi:download"
    _attr_device_info = DeviceInfo(
        identifiers={(DOMAIN, "ovak_water")}, name="OVAK Water"
    )

    def __init__(self, coordinator):
        self.coordinator = coordinator

    async def async_press(self):
        """Handle a button press."""
        await self.coordinator.manual_refresh()
