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
