"""Set up: find the Pligt-pilot add-on by itself; ask for its address only when it isn't found."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from . import DOMAIN, find_addon


class PligtFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is None:
            host = await find_addon(self.hass)
            if host:
                return self.async_create_entry(title="Pligt-pilot", data={"host": host})
            return self.async_show_form(step_id="user", data_schema=vol.Schema({vol.Required("host"): str}),
                                        errors={"base": "no_addon"})
        host = user_input["host"].strip().removeprefix("http://").removeprefix("https://").split(":")[0].split("/")[0]
        return self.async_create_entry(title="Pligt-pilot", data={"host": host})
