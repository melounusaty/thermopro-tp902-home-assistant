from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.device_registry import format_mac

DOMAIN = "tp90X_multi"

MODEL_OPTIONS = {
    "TP902": "TP902",
    "TP904 (experimental)": "TP904",
}


class TP902ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            mac = format_mac(user_input["mac"])
            await self.async_set_unique_id(mac)
            self._abort_if_unique_id_configured()

            selected_label = user_input["model"]
            model = MODEL_OPTIONS[selected_label]
            title = f"ThermoPro {model}"
            if model == "TP904":
                title = f"{title} (experimental)"

            return self.async_create_entry(
                title=title,
                data={
                    "mac": mac,
                    "name": user_input["name"],
                    "model": model,
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("mac"): str,
                    vol.Optional("name", default="ThermoPro Thermometer"): str,
                    vol.Required("model", default="TP902"): vol.In(list(MODEL_OPTIONS)),
                }
            ),
        )
