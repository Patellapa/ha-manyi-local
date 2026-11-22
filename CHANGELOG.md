# Changelog

## 0.2.3

- Display inverter battery voltage with one decimal place (0.1 V), so 52.6 V is shown instead of 53 V.
- Verify that register value 526 is preserved as 52.6 V and the sensor requests one decimal place.

## 0.2.2

- Add the integration logo.

## 0.2.1

- Fix integration removal and reload hanging while a logger remains connected.
- Close callback transports and cancel polling/identity tasks before waiting for server shutdown.
- Apply the same shutdown ordering to discovery cancellation.
- Bound stream closure and join reader/heartbeat tasks even after remote disconnects.
- Keep the hub registered until unload has completed.
- Add regressions using connected silent loggers during identity and polling.

## 0.2.0

- Automatic LAN discovery with TCP identity verification, logger selection and custom inverter names.
- Optional bounded deep scan and manual setup fallback.
- Actionable setup forms for occupied TCP ports and network failures.
- Persistent notification and automatic setup retry when the listener cannot bind.
- Reconfigure connection settings without deleting saved loggers.
- Close discovery listeners, sessions and tasks on completion or cancellation.
- Italian/English interface strings and Home Assistant runtime regression checks.

Existing 0.1.0 configurations remain compatible.
