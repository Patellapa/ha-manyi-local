"""MANYi Local sensor entities."""

from dataclasses import dataclass, replace

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.config_entries import ConfigEntry

from .const import CONF_INVERTERS, CONF_IP, CONF_NAME, CONF_PN, DOMAIN
from .hub import CollectorConfig, ManyiHub
from .settings import SETTINGS


@dataclass(frozen=True)
class ManyiSensorDescription(SensorEntityDescription):
    value_key: str = ""


INVERTER_SENSORS = (
    ManyiSensorDescription(
        key="output_voltage", value_key="inverter_output_voltage",
        translation_key="output_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE, state_class=SensorStateClass.MEASUREMENT,
    ),
    ManyiSensorDescription(
        key="inverter_current", value_key="inverter_current",
        translation_key="inverter_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT, state_class=SensorStateClass.MEASUREMENT,
    ),
    ManyiSensorDescription(
        key="load_current", value_key="load_current", translation_key="load_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT, state_class=SensorStateClass.MEASUREMENT,
    ),
    ManyiSensorDescription(
        key="ac_output_power", value_key="ac_output_power",
        translation_key="ac_output_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT,
    ),
    ManyiSensorDescription(
        key="inverter_temperature", value_key="inverter_temperature",
        translation_key="inverter_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)

MPPT_SENSORS = (
    ManyiSensorDescription(
        key="radiator_temperature", translation_key="radiator_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT,
    ),
    ManyiSensorDescription(
        key="pv_voltage", translation_key="pv_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE, state_class=SensorStateClass.MEASUREMENT,
    ),
    ManyiSensorDescription(
        key="charger_current", translation_key="charger_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT, state_class=SensorStateClass.MEASUREMENT,
    ),
    ManyiSensorDescription(
        key="charger_power", translation_key="charger_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT,
    ),
    ManyiSensorDescription(
        key="estimated_output_power", translation_key="estimated_output_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT,
    ),
)

BATTERY_SENSORS = (
    ManyiSensorDescription(
        key="bms_battery_voltage", value_key="bms_battery_voltage",
        translation_key="bms_battery_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE, state_class=SensorStateClass.MEASUREMENT,
    ),
    ManyiSensorDescription(
        key="bms_battery_current", value_key="bms_battery_current",
        translation_key="bms_battery_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT, state_class=SensorStateClass.MEASUREMENT,
    ),
    ManyiSensorDescription(
        key="inverter_battery_power", value_key="inverter_battery_power",
        translation_key="inverter_battery_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT,
    ),
    ManyiSensorDescription(
        key="inverter_battery_voltage", value_key="inverter_battery_voltage",
        translation_key="inverter_battery_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE, state_class=SensorStateClass.MEASUREMENT,
    ),
    ManyiSensorDescription(
        key="inverter_battery_current", value_key="inverter_battery_current",
        translation_key="inverter_battery_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT, state_class=SensorStateClass.MEASUREMENT,
    ),
    ManyiSensorDescription(
        key="bms_soc", value_key="bms_soc", translation_key="bms_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY, state_class=SensorStateClass.MEASUREMENT,
    ),
    ManyiSensorDescription(
        key="bms_soh", value_key="bms_soh", translation_key="bms_soh",
        native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT,
    ),
    ManyiSensorDescription(
        key="bms_calculated_power", value_key="bms_calculated_power",
        translation_key="bms_calculated_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT,
    ),
)

SETTING_SENSORS = tuple(
    ManyiSensorDescription(
        key=setting.key,
        translation_key=setting.key,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=setting.unit,
    )
    for setting in SETTINGS
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: ManyiHub = hass.data[DOMAIN][entry.entry_id]
    configs = {
        item[CONF_IP]: CollectorConfig(
            name=item[CONF_NAME], ip=item[CONF_IP], pn=item[CONF_PN],
            wire_mode=item["wire_mode"], slave_id=item["slave_id"],
        )
        for item in entry.data[CONF_INVERTERS]
    }
    entities = []
    for config in configs.values():
        entities.extend(
            ManyiSensor(hub, config, description)
            for description in INVERTER_SENSORS
        )
        for channel in (1, 2):
            entities.extend(
                ManyiSensor(
                    hub,
                    config,
                    replace(description, translation_key=f"mppt{channel}_{description.key}"),
                    channel,
                )
                for description in MPPT_SENSORS
            )
        entities.extend(
            ManyiSensor(hub, config, description)
            for description in BATTERY_SENSORS + SETTING_SENSORS
        )
    async_add_entities(entities)


class ManyiSensor(SensorEntity):
    entity_description: ManyiSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        hub: ManyiHub,
        config: CollectorConfig,
        description: ManyiSensorDescription,
        channel: int | None = None,
    ) -> None:
        self._hub = hub
        self._config = config
        self.entity_description = description
        self._channel = channel
        suffix = f"mppt{channel}_" if channel is not None else ""
        key = description.value_key or suffix + description.key
        self._value_key = key
        self._attr_unique_id = f"{config.pn}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config.pn)},
            manufacturer="MANYi",
            name=config.name,
            serial_number=config.pn,
        )

    @property
    def available(self) -> bool:
        state = self._hub.states[self._config.ip]
        return state["connected"] and state["values"].get(self._value_key) is not None

    @property
    def native_value(self) -> int | float | str | None:
        return self._hub.states[self._config.ip]["values"].get(self._value_key)

    @property
    def extra_state_attributes(self) -> dict | None:
        setting = next((item for item in SETTINGS if item.key == self._value_key), None)
        if setting is None:
            return None
        attributes = {
            "register": setting.address,
            "raw_value": self._hub.settings_raw[self._config.ip].get(setting.address),
            "verification": "compare_with_inverter_menu",
        }
        if setting.bit is not None:
            attributes["bit"] = setting.bit
        return attributes

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._hub.async_add_listener(self._config.ip, self.async_write_ha_state)
        )
