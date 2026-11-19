"""Configuration flow for MANYi Local."""

import errno
import ipaddress
import re

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import network
from homeassistant.helpers import selector

from .discovery import check_port, discover

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
        self._adapters = {}
        self._scan_task = None
        self._results = []
        self._scan_error = None

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        return self.async_show_menu(step_id="user", menu_options=["auto", "manual"])

    async def _port_error(self, port):
        try:
            await check_port(port)
        except OSError as exc:
            if exc.errno in (errno.EADDRINUSE, 10048):
                return "port_in_use"
            return "cannot_listen"
        return None

    async def async_step_auto(self, user_input=None):
        errors = {}
        if not self._adapters:
            adapters = await network.async_get_adapters(self.hass)
            for adapter in adapters:
                if not adapter.get("enabled", True):
                    continue
                for info in adapter["ipv4"]:
                    ip = info["address"]
                    address = ipaddress.IPv4Address(ip)
                    if address.is_loopback or address.is_unspecified or address.is_link_local:
                        continue
                    cidr = str(ipaddress.IPv4Network(f"{ip}/{info['network_prefix']}", strict=False))
                    self._adapters[ip] = cidr
        if not self._adapters:
            return self.async_show_menu(step_id="no_interfaces", menu_options=["manual"])
        values = user_input or self._settings
        if user_input is not None:
            self._settings = {
                CONF_ADVERTISED_IP: user_input[CONF_ADVERTISED_IP],
                CONF_TCP_PORT: user_input[CONF_TCP_PORT],
                CONF_UDP_PORT: user_input[CONF_UDP_PORT],
                CONF_POLL_SECONDS: user_input[CONF_POLL_SECONDS],
            }
            self._deep = user_input.get("deep_scan", False)
            cidr = self._adapters[user_input[CONF_ADVERTISED_IP]]
            if self._deep and ipaddress.IPv4Network(cidr).num_addresses > 1024:
                errors["base"] = "network_too_large"
            else:
                error = await self._port_error(self._settings[CONF_TCP_PORT])
                if error:
                    errors["base"] = error
            if not errors:
                self._scan_task = None
                self._scan_error = None
                return await self.async_step_scanning()
        default_ip = values.get(CONF_ADVERTISED_IP, next(iter(self._adapters)))
        schema = vol.Schema({
            vol.Required(CONF_ADVERTISED_IP, default=default_ip): vol.In({
                ip: f"{ip} ({cidr})" for ip, cidr in self._adapters.items()
            }),
            vol.Required(CONF_TCP_PORT, default=values.get(CONF_TCP_PORT, DEFAULT_TCP_PORT)):
                vol.All(vol.Coerce(int), vol.Range(min=1024, max=65535)),
            vol.Required(CONF_UDP_PORT, default=values.get(CONF_UDP_PORT, DEFAULT_UDP_PORT)):
                vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            vol.Required(CONF_POLL_SECONDS, default=values.get(CONF_POLL_SECONDS, DEFAULT_POLL_SECONDS)):
                vol.All(vol.Coerce(int), vol.Range(min=5, max=3600)),
            vol.Optional("deep_scan", default=bool(values.get("deep_scan", False))): bool,
        })
        return self.async_show_form(step_id="auto", data_schema=schema, errors=errors)

    async def _async_scan(self):
        try:
            self._results = await discover(
                self._settings[CONF_ADVERTISED_IP],
                self._adapters[self._settings[CONF_ADVERTISED_IP]],
                self._settings[CONF_TCP_PORT], self._settings[CONF_UDP_PORT], deep=self._deep,
            )
        except OSError as exc:
            self._scan_error = "port_in_use" if exc.errno in (errno.EADDRINUSE, 10048) else "cannot_scan"
        except (ValueError, TimeoutError):
            self._scan_error = "cannot_scan"

    async def async_step_scanning(self, user_input=None):
        if self._scan_task is None:
            self._scan_task = self.hass.async_create_task(self._async_scan())
        if self._scan_task.done():
            return self.async_show_progress_done(next_step_id="scan_results")
        return self.async_show_progress(step_id="scanning", progress_action="scanning_network",
                                        progress_task=self._scan_task)

    async def async_step_scan_results(self, user_input=None):
        if self._scan_error:
            result = await self.async_step_auto()
            result["errors"] = {"base": self._scan_error}
            return result
        if not self._results:
            return self.async_show_menu(step_id="not_found", menu_options=["auto", "manual"])
        errors = {}
        choices = {item[CONF_PN]: f"{item[CONF_PN]} — {item[CONF_IP]}" for item in self._results}
        if user_input is not None:
            selected = user_input.get("devices", [])
            if not 1 <= len(selected) <= MAX_INVERTERS or any(pn not in choices for pn in selected):
                errors["base"] = "select_devices"
            else:
                self._inverters = [dict(item) for item in self._results if item[CONF_PN] in selected]
                for index, item in enumerate(self._inverters, 1):
                    item[CONF_NAME] = f"Inverter {index}"
                return await self.async_step_names()
        schema = vol.Schema({vol.Required("devices"): selector.SelectSelector(
            selector.SelectSelectorConfig(options=[{"value": pn, "label": label}
                for pn, label in choices.items()], multiple=True)
        )})
        return self.async_show_form(step_id="scan_results", data_schema=schema, errors=errors)

    async def async_step_names(self, user_input=None):
        errors = {}
        if user_input is not None:
            if any(not user_input.get(f"name_{index}", "").strip()
                   for index in range(len(self._inverters))):
                errors["base"] = "invalid_name"
            else:
                for index, item in enumerate(self._inverters):
                    item[CONF_NAME] = user_input[f"name_{index}"].strip()
                return await self._async_finish()
        schema = vol.Schema({
            vol.Required(f"name_{index}", default=item[CONF_NAME]): str
            for index, item in enumerate(self._inverters)
        })
        return self.async_show_form(step_id="names", data_schema=schema, errors=errors)

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        errors = {}
        values = user_input or entry.data
        if user_input is not None:
            try:
                address = ipaddress.IPv4Address(user_input[CONF_ADVERTISED_IP])
                if address.is_unspecified or address.is_multicast or address.is_loopback:
                    raise ipaddress.AddressValueError
            except ipaddress.AddressValueError:
                errors[CONF_ADVERTISED_IP] = "invalid_ip"
            # The current entry owns its existing port; only probe a changed port.
            if user_input[CONF_TCP_PORT] != entry.data[CONF_TCP_PORT]:
                error = await self._port_error(user_input[CONF_TCP_PORT])
                if error:
                    errors["base"] = error
            if not errors:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
        schema = vol.Schema({
            vol.Required(CONF_ADVERTISED_IP, default=values[CONF_ADVERTISED_IP]): str,
            vol.Required(CONF_TCP_PORT, default=values[CONF_TCP_PORT]):
                vol.All(vol.Coerce(int), vol.Range(min=1024, max=65535)),
            vol.Required(CONF_UDP_PORT, default=values[CONF_UDP_PORT]):
                vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            vol.Required(CONF_POLL_SECONDS, default=values[CONF_POLL_SECONDS]):
                vol.All(vol.Coerce(int), vol.Range(min=5, max=3600)),
        })
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)

    async def async_step_manual(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                address = ipaddress.IPv4Address(user_input[CONF_ADVERTISED_IP])
                if address.is_unspecified or address.is_multicast or address.is_loopback:
                    raise ipaddress.AddressValueError
            except ipaddress.AddressValueError:
                errors[CONF_ADVERTISED_IP] = "invalid_ip"
            if not errors:
                error = await self._port_error(user_input[CONF_TCP_PORT])
                if error:
                    errors["base"] = error
            if not errors:
                self._inverters = []
                self._inverter_count = user_input["inverter_count"]
                self._settings = {
                    key: value for key, value in user_input.items()
                    if key != "inverter_count"
                }
                return await self.async_step_inverter()

        values = user_input or self._settings
        schema = vol.Schema(
            {
                vol.Required(CONF_ADVERTISED_IP, default=values.get(CONF_ADVERTISED_IP, "")): str,
                vol.Required(CONF_TCP_PORT, default=values.get(CONF_TCP_PORT, DEFAULT_TCP_PORT)):
                    vol.All(vol.Coerce(int), vol.Range(min=1024, max=65535)),
                vol.Required(CONF_UDP_PORT, default=values.get(CONF_UDP_PORT, DEFAULT_UDP_PORT)):
                    vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                vol.Required(CONF_POLL_SECONDS, default=values.get(CONF_POLL_SECONDS, DEFAULT_POLL_SECONDS)):
                    vol.All(vol.Coerce(int), vol.Range(min=5, max=3600)),
                vol.Required("inverter_count", default=values.get("inverter_count", 1)): vol.In(range(1, MAX_INVERTERS + 1)),
            }
        )
        return self.async_show_form(step_id="manual", data_schema=schema, errors=errors)

    async def async_step_inverter(self, user_input=None):
        errors = {}
        index = len(self._inverters)
        if user_input is not None:
            try:
                ipaddress.IPv4Address(user_input[CONF_IP])
            except ipaddress.AddressValueError:
                errors[CONF_IP] = "invalid_ip"
            user_input = dict(user_input)
            user_input[CONF_PN] = user_input[CONF_PN].strip().upper()
            if not user_input[CONF_NAME].strip():
                errors[CONF_NAME] = "invalid_name"
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
