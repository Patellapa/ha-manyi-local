"""MANYi Local Home Assistant integration."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .const import DOMAIN
from .hub import ManyiHub

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from homeassistant.const import Platform

    hub = ManyiHub(entry.data)
    await hub.async_start()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub
    try:
        await hass.config_entries.async_forward_entry_setups(entry, (Platform.SENSOR,))
    except (Exception, asyncio.CancelledError):
        await hub.async_stop()
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from homeassistant.const import Platform

    if not await hass.config_entries.async_unload_platforms(entry, (Platform.SENSOR,)):
        return False
    hub: ManyiHub = hass.data[DOMAIN].pop(entry.entry_id)
    await hub.async_stop()
    if not hass.data[DOMAIN]:
        hass.data.pop(DOMAIN)
    return True
