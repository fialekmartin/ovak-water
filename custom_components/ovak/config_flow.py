"""OVAK configuration and synchronization schedule."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.helpers import selector
from .const import DOMAIN

OPT_SYNC_TIME = "sync_time"


class OvakConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            await self.async_set_unique_id("ovak_water")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="OVAK", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OvakOptionsFlow()


class OvakOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    OPT_SYNC_TIME,
                    default=self.config_entry.options.get(OPT_SYNC_TIME, "06:00"),
                ): selector.TimeSelector(),
            }),
        )
