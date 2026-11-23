# MANYi Local

Home Assistant integration for read-only local monitoring of up to three MANYi
inverters through their EyeBond dataloggers. It reads the dataloggers directly;
the separate FastAPI project is not required.

## Installation

For manual installation, copy `custom_components/manyi_local/` into
`config/custom_components/manyi_local/` on the Home Assistant system, then
restart Home Assistant. The integration can also be added as a HACS custom
repository once this project is published on GitHub.

### Automatic setup (recommended)

Open **Settings → Devices & services → Add integration → MANYi Local** and
choose **Search automatically**. Confirm the Home Assistant network address,
keep the default settings unless needed, and wait for discovery. Select up to
three detected loggers and give each inverter a name. Logger IPs and PNs are
read and verified automatically over TCP; a UDP acknowledgement alone is never
accepted as identification.

If nothing is found, retry with **Deep scan**, which probes the selected IPv4
subnet (limited to 1024 addresses), or use manual configuration. Discovery is
limited to the selected local subnet and currently identifies `framed` loggers.
Broadcast traffic and TCP callbacks must be allowed on the VM/network.
Discovery requests invite compatible loggers to connect to Home Assistant;
stop other integrations using the same loggers before scanning.

### Manual setup

After restarting, open **Settings → Devices & services → Add integration** and
select **MANYi Local → Manual configuration**. Configure the Home Assistant LAN address, callback
ports, polling interval, and between one and three inverter loggers. For each
logger, enter its IPv4 address and the PN printed on the logger. Keep the
`framed` protocol and Modbus slave ID `4` unless another setting has been
confirmed for that device.

## Network requirements

Home Assistant and the loggers must be able to communicate on the LAN.
Home Assistant opens a TCP listener (default port `8899`) and sends a UDP
request (default logger port `58899`) asking each logger to connect back.
Allow inbound TCP traffic to the configured callback port from the logger
addresses. The advertised Home Assistant address must be stable and reachable
from every configured logger.

Only one process can listen on the callback TCP port. Stop the separate MANYi
API service (or choose another free port) before enabling this integration on
the same host.

The UDP acknowledgement is not proof of identity. The integration verifies the
configured PN after the TCP callback connects. Disconnected loggers are
re-requested periodically. The integration does not use cloud APIs or write
inverter settings.

On each framed connection, the integration waits for the initial heartbeat
response before sending the full PN identity query. If the heartbeat response
does not arrive, the session is closed and the log reports
`initial_heartbeat_reply_timeout`; identity checking is never bypassed.

## Entities

Each inverter provides 23 sensors:

- 5 inverter measurements;
- 5 measurements for each of MPPT1 and MPPT2;
- 8 battery measurements, retaining BMS and inverter sources separately.

The estimated MPPT output power and calculated BMS power are derived values.
Missing registers remain unavailable; they are not reported as zero.

## Connection troubleshooting

If sensors become unavailable, check the Home Assistant logs for `manyi_local`.
Connection warnings identify the logger, the setup/polling phase, and the
exception type. Read failures also identify the register range. Invalid frame
length errors include the received eight-byte header.

For intermittent failures, enable debug logging from the integration menu,
reproduce the failure, then disable debug logging and download the log.
Debug messages show callback attempts and frame metadata without recording
telemetry payloads.

## Development checks

Run the focused tests from this repository root with `python -m pytest tests`.

## Port conflicts and reconfiguration

During setup, a busy TCP port is shown as an actionable form error. Change the
port or stop the conflicting service (for example EyeBond Local), then retry.
If the port becomes occupied after configuration, MANYi Local shows a persistent
notification and a translated setup status, then retries automatically instead
of reporting an unhandled setup exception. Successful startup clears the
notification.

Use the integration entry menu **Reconfigure** to change the Home Assistant LAN
address, TCP/UDP ports or polling interval without deleting the saved loggers.
The selected TCP port must be reachable from every logger. Reconfiguration does
not change entity identifiers or inverter PNs.

## Updating from 0.1.0

Update through Marketplace (or HACS on older Home Assistant versions) and restart Home Assistant. Existing configurations keep
working without migration. Automatic discovery is available when adding a new
configuration; an existing entry can use **Reconfigure** for connection settings.
To try discovery on an existing installation, record your current settings,
remove the integration entry, and add it again using automatic setup.

## Protocol references

The discovery design was informed by the user-provided EyeBond Local 0.1.53
sources: `collector/discovery.py`, `collector/profile.py`, and
`onboarding/eybond.py` from https://github.com/groove-max/ha-eybond-local
(MPL-2.0). MANYi discovery is an independent implementation built on this
integration's existing protocol/session code; upstream files are not bundled.

## Removal and reload

Version 0.2.1 fixes a shutdown deadlock affecting removal/reload with connected
loggers, including unresponsive loggers. Update and restart Home Assistant to
load the fix before retrying removal. A polling timeout alone is a separate
connection problem; shutdown no longer waits for the logger to finish polling.


## Read-only inverter configuration

All 28 configuration addresses documented in `Protocollo_Modbus_RTU_PV_PH1800.md`
are exposed for each inverter, plus 10 decoded system flags (38 new sensors).
They appear in Diagnostics and are enabled by default. No write operations are
implemented. Names begin with the register address; attributes include `register`,
`raw_value`, `verification`, and `bit` where applicable. Unknown enum codes are
shown as `unknown_<raw>` rather than guessed.

Four single-register reads are performed after each live telemetry update,
without crossing reserved gaps. Each address is refreshed no sooner than five
minutes; the first complete scan takes about seven polling cycles (about two
minutes at the default 15-second interval). A rejected read or timeout preserves
any previously read setting, including its raw value and last successful read
time; never-read settings remain unavailable. Timeouts may cause a logger
reconnection; that address is not retried for five minutes. Cached settings are
retained across reconnections. Missing or zero BMS voltage in a completed live
poll still makes BMS measurements unavailable instead of publishing the default
SOH of 100%.

These are candidate PV/PH1800 mappings: compare both raw and decoded values with
the inverter menu and SmartValue. Zero/default values do not prove support.
PV registers 10101/10103/10104/10110 are marked WR in the document; their read
support must be checked on the installed firmware. Enum labels use the PV/PH
variant, not the EP variant. System flags 4 and 5 are documented for PV1800.
Some settings are conditional on operating mode and may remain readable while
inactive. Unsupported values are not used to control the inverter.

| Register | Configuration sensor | Scale / codes |
| --- | --- | --- |
| 10101 | PV charger enable code | 1 raw (codes not specified) |
| 10103 | Float voltage | 0.1 V |
| 10104 | Absorption voltage | 0.1 V |
| 10110 | Battery type | 0=not_selected, 1=user_defined, 2=lithium, 3=sealed_lead, 4=AGM, 5=GEL, 6=flooded |
| 20101 | Off-grid output enabled | 0=off, 1=on |
| 20102 | Output voltage setting | 0.1 V |
| 20103 | Output frequency setting | 0.01 Hz |
| 20104 | Power saver enabled | 0=off, 1=on |
| 20108 | Battery feed-in enabled | 0=off, 1=on |
| 20109 | Output source priority | 1=SBU, 2=SUB, 3=UTI, 4=SOL |
| 20111 | Grid protection standard | 0=VDE4105, 1=UPS, 2=APL, 3=GEN |
| 20112 | Solar use priority | 0=LBU, 1=BLU |
| 20114 | Max inverter current (AC) | 0.1 A |
| 20118 | Stop discharging voltage | 0.1 V |
| 20119 | Stop charging voltage | 0.1 V |
| 20125 | Max grid charging current (DC) | 0.1 A |
| 20127 | Battery low voltage | 0.1 V |
| 20128 | Battery high voltage | 0.1 V |
| 20132 | Max total solar charging current | 0.1 A |
| 20142 | System settings mask | 1 raw |
| 20143 | Charging source priority | 0=solar_first, 2=solar_and_utility, 3=solar_only |
| 20145 | BMS control method | 0=VOL, 1=SOC |
| 20146 | Low DC cut-off SOC | 1 % |
| 20147 | Stop discharging SOC | 1 % |
| 20148 | Stop charging SOC | 1 % |
| 20149 | Lithium battery protocol | 0=MUST, 8=8 (vendor-selected protocol, manufacturer unverified) |
| 20150 | Second output cut-off voltage | 0.1 V |
| 20151 | Second output cut-off SOC | 1 % |
| 20142 | Overload restart forbidden | bit 0: on / off |
| 20142 | Overtemperature restart forbidden | bit 1: on / off |
| 20142 | Overload bypass forbidden | bit 2: on / off |
| 20142 | LCD auto paging forbidden | bit 3: on / off |
| 20142 | Grid buzzer enabled | bit 4: on / off |
| 20142 | Buzzer forbidden | bit 5: on / off |
| 20142 | LCD backlight always on | bit 6: on / off |
| 20142 | Fault recording forbidden | bit 7: on / off |
| 20142 | Operation on BMS communication fault enabled | bit 8: on / off |
| 20142 | Dual output enabled | bit 9: on / off |


## Retained measurements and connectivity (0.2.4)

A lost dongle connection keeps the last complete live sample visible. Values are
held in memory during this integration session, not restored from disk after
Home Assistant restarts or the integration is reloaded. Sensors with no valid
reading remain unavailable. An explicit missing BMS measurement is still
invalidated; this is different from a dongle transport outage.

Each inverter has a diagnostic **Dongle connection** binary sensor. Every
measurement exposes `dongle_connected`, `data_stale`, and
`last_successful_update` (UTC ISO timestamp). A cached value remains stale after
reconnection until its own next successful read. Configuration sensors also
expose `last_read_error`. A rejected refresh retains the last configuration
value and timestamp, and marks it stale.

All sensor descriptions start with `[register]`. Calculated estimates show both
source registers, for example `[109 × 110]`. Entity unique IDs remain unchanged;
existing entity IDs and user-defined names are not migrated. Do not remove and
recreate the integration just to change labels.

Owner checks confirmed the menu labels APL (20111), maximum solar battery
charging current from both MPPTs of one inverter (20132), and vendor-selected
lithium protocol 8 (20149). Protocol 8 is shown as `8`, without guessing a brand.
The live inverter 1 probe returned SOC method 1, low SOC 10, stop discharge 20,
stop charge 80, and protocol 8 at the original documented addresses.

### SOC templates consuming power

Retaining a displayed power value does not make it a current measurement.
Energy/SOC calculations must also check `data_stale`; a numeric state or
`has_value` alone no longer proves fresh communication. For the user's total
battery power template, replace its `availability` with:

```yaml
availability: >
  {% set p1 = 'sensor.inverter_1_potenza_batteria_da_inverter' %}
  {% set p2 = 'sensor.inverter_2_potenza_batteria_da_inverter' %}
  {{ is_number(states(p1)) and is_number(states(p2))
     and state_attr(p1, 'data_stale') == false
     and state_attr(p2, 'data_stale') == false }}
```

Adapt the entity IDs to the existing installation. Energy exchanged while
communication is absent cannot be reconstructed from held power values; the
estimate may require recalibration. This integration release does not edit the
user's Home Assistant configuration or SOC automations.
