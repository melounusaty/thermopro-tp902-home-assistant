from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.device_registry import format_mac

DOMAIN = "tp902"


class TP902ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            mac = format_mac(user_input["mac"])
            await self.async_set_unique_id(mac)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input["name"],
                data={
                    "mac": mac,
                    "name": user_input["name"],
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("mac"): str,
                    vol.Optional("name", default="TP902"): str,
                }
            ),
        )
