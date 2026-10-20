"""OVAK daily consumption sensor with restored last known reading."""
from datetime import date
import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfVolume
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([OvakDailySensor(hass.data[DOMAIN][entry.entry_id])])


class OvakDailySensor(RestoreEntity, SensorEntity):
    """Display latest available daily reading even after reload/restart."""

    _attr_has_entity_name = True
    _attr_name = "Včerejší spotřeba"
    _attr_unique_id = "ovak_yesterday_consumption_auto"
    _attr_device_class = SensorDeviceClass.WATER
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_device_info = DeviceInfo(
        identifiers={(DOMAIN, "ovak_water")}, name="OVAK Water"
    )

    def __init__(self, coordinator):
        self.coordinator = coordinator

    @property
    def available(self):
        return self.coordinator.last_day is not None and self.coordinator.last_m3 is not None

    @property
    def native_value(self):
        return self.coordinator.last_m3

    @property
    def extra_state_attributes(self):
        return (
            {"date": self.coordinator.last_day.isoformat()}
            if self.coordinator.last_day is not None else {}
        )

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

        # Reload creates a fresh coordinator. Preserve the last stored measurement
        # without contacting OVAK outside the configured daily schedule.
        if self.coordinator.last_day is not None:
            return
        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state in (
            "unknown", "unavailable", "none", ""
        ):
            return
        day_str = last_state.attributes.get("date")
        if not isinstance(day_str, str):
            return
        try:
            restored_day = date.fromisoformat(day_str)
            restored_value = float(last_state.state)
            if restored_value < 0 or not (restored_value < float("inf")):
                return
        except (ValueError, TypeError):
            _LOGGER.warning("OVAK: invalid previous reading; waiting for synchronization")
            return
        self.coordinator.last_day = restored_day
        self.coordinator.last_m3 = restored_value
        _LOGGER.debug("OVAK: restored reading from %s", restored_day)
        self.async_write_ha_state()
