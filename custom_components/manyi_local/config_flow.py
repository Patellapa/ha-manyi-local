"""Configuration flow for MANYi Local."""

import ipaddress
import re

import voluptuous as vol
from homeassistant import config_entries

from .const import (
    CONF_ADVERTISED_IP,
    CONF_INVERTERS,
    CONF_IP,
    CONF_NAME,
    CONF_PN,
    CONF_POLL_SECONDS,
    CONF_SLAVE_ID,
    CONF_TCP_PORT,
    CONF_UDP_PORT,
    CONF_WIRE_MODE,
    DEFAULT_POLL_SECONDS,
    DEFAULT_TCP_PORT,
    DEFAULT_UDP_PORT,
    DOMAIN,
    MAX_INVERTERS,
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up one to three inverters behind a shared callback listener."""

    VERSION = 1

    def __init__(self) -> None:
        self._settings = {}
        self._inverters = []
        self._inverter_count = 0

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                ipaddress.IPv4Address(user_input[CONF_ADVERTISED_IP])
            except ipaddress.AddressValueError:
                errors[CONF_ADVERTISED_IP] = "invalid_ip"
            if not errors:
                self._inverter_count = user_input["inverter_count"]
                self._settings = {
                    key: value for key, value in user_input.items()
                    if key != "inverter_count"
                }
                return await self.async_step_inverter()

        schema = vol.Schema(
            {
                vol.Required(CONF_ADVERTISED_IP): str,
                vol.Required(CONF_TCP_PORT, default=DEFAULT_TCP_PORT):
                    vol.All(vol.Coerce(int), vol.Range(min=1024, max=65535)),
                vol.Required(CONF_UDP_PORT, default=DEFAULT_UDP_PORT):
                    vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                vol.Required(CONF_POLL_SECONDS, default=DEFAULT_POLL_SECONDS):
                    vol.All(vol.Coerce(int), vol.Range(min=5, max=3600)),
                vol.Required("inverter_count", default=1): vol.In(range(1, MAX_INVERTERS + 1)),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_inverter(self, user_input=None):
        errors = {}
        index = len(self._inverters)
        if user_input is not None:
            try:
                ipaddress.IPv4Address(user_input[CONF_IP])
            except ipaddress.AddressValueError:
                errors[CONF_IP] = "invalid_ip"
            if not re.fullmatch(r"[A-Z]\d{13,17}", user_input[CONF_PN]):
                errors[CONF_PN] = "invalid_pn"
            if any(item[CONF_IP] == user_input[CONF_IP] for item in self._inverters):
                errors[CONF_IP] = "duplicate_ip"
            if any(item[CONF_PN] == user_input[CONF_PN] for item in self._inverters):
                errors[CONF_PN] = "duplicate_pn"
            if not errors:
                self._inverters.append(user_input)
                if len(self._inverters) < self._inverter_count:
                    return await self.async_step_inverter()
                return await self._async_finish()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=f"Inverter {index + 1}"): str,
                vol.Required(CONF_IP): str,
                vol.Required(CONF_PN): str,
                vol.Required(CONF_WIRE_MODE, default="framed"): vol.In(
                    ("framed", "at_raw", "at_fc4")
                ),
                vol.Required(CONF_SLAVE_ID, default=4):
                    vol.All(vol.Coerce(int), vol.Range(min=1, max=247)),
            }
        )
        return self.async_show_form(
            step_id="inverter", data_schema=schema, errors=errors, description_placeholders={
                "inverter_number": str(index + 1),
                "inverter_count": str(self._inverter_count),
            }
        )

    async def _async_finish(self):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        data = {
            **self._settings,
            CONF_INVERTERS: self._inverters,
        }
        names = ", ".join(item[CONF_NAME] for item in self._inverters)
        return self.async_create_entry(title=f"MANYi Local: {names}", data=data)
