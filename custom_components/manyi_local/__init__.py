"""MANYi Local Home Assistant integration."""

from __future__ import annotations

import asyncio
import errno
from typing import TYPE_CHECKING

from .const import DOMAIN
from .hub import ManyiHub

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from homeassistant.const import Platform
    from homeassistant.components import persistent_notification
    from homeassistant.exceptions import ConfigEntryNotReady

    hub = ManyiHub(entry.data)
    try:
        await hub.async_start()
    except OSError as exc:
        await hub.async_stop()
        key = "port_in_use" if exc.errno in (errno.EADDRINUSE, 10048) else "cannot_listen"
        port = str(entry.data["tcp_port"])
        if key == "port_in_use":
            italian = getattr(getattr(hass, "config", None), "language", "en") == "it"
            message = (
                f"La porta TCP {port} è già utilizzata. Disabilita il servizio in conflitto "
                "(ad esempio EyeBond Local), oppure apri Impostazioni → Dispositivi e servizi "
                "→ MANYi Local → Riconfigura e scegli una porta libera. "
                "MANYi Local riproverà automaticamente."
                if italian else
                f"TCP port {port} is already in use. Stop the conflicting service "
                "(for example EyeBond Local), or open Settings → Devices & services "
                "→ MANYi Local → Reconfigure and choose a free port. "
                "MANYi Local will retry automatically."
            )
            persistent_notification.async_create(
                hass, message,
                title="MANYi Local: porta TCP occupata" if italian else "MANYi Local: TCP port in use",
                notification_id=f"{DOMAIN}_{entry.entry_id}_listener",
            )
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key=key,
            translation_placeholders={"port": port},
        ) from exc
    persistent_notification.async_dismiss(hass, f"{DOMAIN}_{entry.entry_id}_listener")
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
    hub: ManyiHub = hass.data[DOMAIN][entry.entry_id]
    await hub.async_stop()
    hass.data[DOMAIN].pop(entry.entry_id)
    if not hass.data[DOMAIN]:
        hass.data.pop(DOMAIN)
    return True
