"""Live dongle connectivity, separate from retained inverter measurements."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    hub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(ManyiConnectionSensor(hub, config) for config in hub.configs.values())


class ManyiConnectionSensor(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "dongle_connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub, config):
        self._hub = hub
        self._config = config
        self._attr_unique_id = f"{config.pn}_dongle_connection"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config.pn)}, manufacturer="MANYi",
            name=config.name, serial_number=config.pn,
        )

    @property
    def is_on(self):
        return self._hub.states[self._config.ip]["connected"]

    async def async_added_to_hass(self):
        self.async_on_remove(self._hub.async_add_listener(
            self._config.ip, self.async_write_ha_state,
        ))
