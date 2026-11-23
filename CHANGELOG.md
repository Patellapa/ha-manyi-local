# Changelog

## 0.2.4

- Keep the last complete measurements visible during dongle outages and reconnects; retain settings on failed refreshes.
- Add a diagnostic dongle connection sensor and per-value freshness, last successful read time, and configuration read errors.
- Detect reader disconnections during the polling wait, without waiting for the next cycle.
- Put register codes before all sensor descriptions; calculated estimates identify their source registers.
- Correct APL, the maximum solar charging current label, and vendor-selected protocol 8 without guessing its manufacturer.
- Preserve entity unique IDs and explicit BMS invalidation when live BMS voltage is zero.
- Document the freshness check required by downstream power-based SOC templates.

## 0.2.3

- Expose 28 documented configuration registers and 10 system flags as read-only diagnostic sensors per inverter.
- Include register addresses, raw values and explicit unknown enum codes for menu/SmartValue verification.
- Stagger optional single-register reads and cache them for at least five minutes.
- Mark zero-voltage BMS data unavailable, including the default SOH of 100%.

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
