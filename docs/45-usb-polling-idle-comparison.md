# USB polling idle comparison

Date: **29 September 2026 NZDT**. Hardware qualification: **NEO-22**.
Target: the owner's **CPI v3.1**, diagnostic.5 / Linux
`6.18.54-gameshellneo5`. Status: **preparing; no comparison result yet**.

## Question and scope

After the [functional USB checks](44-diagnostic5-hardware-validation.md),
compare the stock 50 ms absent-state policy with the experimental 250 ms
policy. Repeated experimental windows bracket the stock window to expose
drift. This is an exploratory software-telemetry comparison, not calibrated
electrical measurement, a direct count of USB poll callbacks or an endurance
test. Small reductions in recurring work remain useful even if the battery
readings cannot resolve their energy effect.

## Repeatable protocol

Use the existing checked-in tasks; no temporary bespoke measurement program
is required. Keep the Mac awake and on the same enabled hotspot as the
GameShell, with Wi-Fi SSH routed through the Mac's configured tailnet endpoint.
Connection details and credentials remain in `.env`.

1. Check `task device:status ROUTE=wifi` and
   `task device:usb-policy ROUTE=wifi`. Verify experimental activation and
   stop any earlier detailed USB recorder. Preserve brightness 1, unblanked
   console, schedutil governor, 120–1008 MHz limits, 366 microsecond schedutil
   interval and Wi-Fi power saving off. Check these again around each phase.
2. Unplug USB once, leave controls untouched and keep the board in the same
   location. Allow five minutes to cool after charging. Check valid battery
   monitoring, discharge, Wi-Fi and temperature before starting.
3. Run the following **sequentially**, without concurrent device diagnostics:

   ```sh
   task device:idle-sample ROUTE=wifi SECONDS=300 BACKLIGHT=keep
   task device:power-profile ROUTE=wifi SECONDS=120
   ```

   The idle task includes 60 seconds settling and ten-second samples. The
   counter task includes 30 seconds settling, endpoint counters and subsequent
   diagnostic snapshots. Their observers differ; do not combine their readings
   as if measured simultaneously.
4. Select stock with
   `task device:usb-policy ROUTE=wifi MODE=stock`, then separately request
   `task device:exec ROUTE=wifi -- sudo -n systemctl reboot`. Reconnect through
   Wi-Fi, verify a new boot and actual stock policy, check health/settings, and
   allow five minutes to settle before repeating step 3.
5. Select experimental, separately reboot, verify the new boot and actual
   experimental policy, settle five minutes and repeat step 3. Leave the
   experimental policy selected unless a failure justifies rollback.

Both tasks stop on external power, invalid/stale battery monitoring, capacity
at or below 20%, excessive temperature, lost Wi-Fi, kernel taint or changes to
their checked settings. The ordinary battery guard remains active. Preserve
failed and incomplete captures separately; only completed windows are used.
Retain raw private captures under `.local/diagnostics/` and record their paths,
boot identities, policy checks and outcomes below.

## Interpretation

Report time-weighted current/power estimates, voltage and temperature ranges,
signal context, network traffic, CPU accounting coverage and RSB IRQ rates.
Compare both experimental windows with stock before interpreting differences.
Flag thermal, voltage, signal or workload mismatch explicitly; repeating a
window does not remove unmeasured confounders. Aggregate interrupts are not
unique wakeups or direct USB poll invocations. Any actual poll-count claim
requires the separate lightweight instrumentation work.

## Evidence and results

Pending. Preflight Wi-Fi status: `20260929T054253.347046Z/`; experimental
policy verification via USB: `20260929T054305.246521Z/`. Battery monitoring was
valid and reporting 100% while charging; no failed units or kernel taint were
reported. Only the normal USB, readiness and battery GameShellNeo services
remained active. Wi-Fi power saving was verified off separately.

Before battery sampling started, the owner chose to change Wi-Fi networks and
reconnected USB. No idle or counter comparison window has run. Network
reconfiguration and the recurring disconnected-radio firmware crash must be
resolved before starting a fresh settling period; earlier charging or network
transition readings will not be included in the comparison.
