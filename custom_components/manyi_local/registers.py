"""Register origins for the exposed telemetry and calculated estimates."""

TELEMETRY_REGISTERS = {
    "output_voltage": (25206,),
    "inverter_current": (25210,),
    "load_current": (25212,),
    "ac_output_power": (25215,),
    "inverter_temperature": (25233,),
    "bms_battery_voltage": (109,),
    "bms_battery_current": (110,),
    "inverter_battery_power": (25273,),
    "inverter_battery_voltage": (25205,),
    "inverter_battery_current": (25274,),
    "bms_soc": (113,),
    "bms_soh": (114,),
    "bms_calculated_power": (109, 110),
}
for channel, base in ((1, 15200), (2, 16200)):
    for key, offsets in {
        "radiator_temperature": (9,), "pv_voltage": (5,),
        "charger_current": (7,), "charger_power": (8,),
        "estimated_output_power": (6, 7),
    }.items():
        TELEMETRY_REGISTERS[f"mppt{channel}_{key}"] = tuple(base + offset for offset in offsets)
