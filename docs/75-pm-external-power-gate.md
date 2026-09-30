# PM diagnostic external-power gate (NEO-54)

1 October 2026, Pacific/Auckland. A diagnostic-helper correction identified
while testing diagnostic.11 after [installation](73-diagnostic11-installation.md).
No image, kernel, charging setting or battery-guard behavior changes.

## Problem and evidence

The saved PM helper required battery status to be `Charging`, `Full` or
`Not charging` as its `battery_external_power` gate. That status is not an
external-input measurement. The pinned Linux driver's
`drivers/power/supply/axp20x_battery.c:axp20x_battery_get_prop()` uses the
charging-direction bit first, then reports `Discharging` when the discharge
current ADC is nonzero; it does not test USB input presence in that branch.

One ordinary devices stage completed but failed postflight when the valid
battery guard reported 100% and `Discharging`; the USB controller still
reported `configured`. PM controls/tracing were restored, process memory and
the original keypad handle were intact, and Wi-Fi had connected. The capture
is `.local/diagnostics/20260930T120523.519800Z/cycle-2/result.json`, run
`a074a9a333144409830b96af2ad19fab`.

Battery service logs show a Discharging interval from 846.248 to 866.302
monotonic seconds. Later inspection found Charging, both named input supplies
present/online, and a 2 mA charging-current reading. Those later readings do
not prove the input state during the failed snapshot. The owner saw the normal
dim console and a connected cable, but reported an indicator light off that
returned after replugging; they were unsure whether the test or an accidental
knock caused it. The indicator's identity is unconfirmed. Preserve that
uncertainty rather than classifying the old failure as harmless or a driver
regression.

Private supplemental evidence: `.local/neo53-battery-state-journal.log`,
`.local/neo53-power-reading.log` and `.local/neo53-after-rerun-status.log`.

## Corrected contract

Every PM snapshot now reads `type`, `present` and `online` from the named
`axp20x-usb` and `axp22x-ac` supplies. Validation requires the USB supply to
identify as `USB`, with presence and online values both exactly `1`, together
with the existing configured-UDC requirement. AC readings provide additional
board context; AC alone cannot substitute for the required USB supply.

Battery status remains visible and must be one of its four known values.
Monitoring must still be valid and fresh, with capacity above 20%. Kernel,
image, services, radio, recovery deadline, PM stage and restoration checks
are unchanged. Missing or malformed input evidence fails; old captures are
not retroactively reclassified or filled with later readings.

This corrects what the diagnostic measures. It does not suppress a real
input dropout, prove steady electrical power between samples or repair a
charging/connector problem. No charger register is written.

## Validation

`python3 -m unittest discover -s tools/tests -p test_pm_stages.py -v` passed
all 14 test methods. Added cases accept the four valid battery statuses only
with real external-input evidence; reject absent/offline USB, missing fields,
wrong supply type and malformed flags; and retain rejection of unknown battery
status, degraded monitoring and insufficient capacity. Missing whole-snapshot
power evidence and an online AC supply without USB also fail.

The complete `task check` passed the tool/runtime suites, compiled regression
helpers and Bash/ShellCheck. Private logs are `.local/neo54-pm-tests.log` and
`.local/neo54-check.log`.

`task device:pm-inspect` captured the updated fields without entering PM at
`.local/diagnostics/20260930T121138.215307Z/inspection.json`. Validation of that
snapshot against the current source lock passed: both inputs were present and
online, USB configured, battery 100%/Charging with valid monitoring. PM success
remained six with no failure counters. This ticket did not enter another PM
stage; subsequent cycles must use the updated saved helper.
