# Diagnostic.11 ordinary PM qualification (NEO-53)

1 October 2026, Pacific/Auckland. Owner's CPI v3.1, diagnostic.11,
`6.18.54-gameshellneo11`, boot `3bf2069f-24a7-4e0b-b7d3-18d4048e3c7f`.
[Installation and boot checks](73-diagnostic11-installation.md) passed first.
The owner then chose to perform the previously deferred tests immediately.

The fresh owner-ready four-cycle batch, audio-assisted physical input and
four awake USB reconnects passed. Two earlier failed batches and an interrupted
session are preserved below. One delayed Wi-Fi recovery remains unresolved
(NEO-55); the external-power test predicate was corrected separately (NEO-54).

This tests the ordinary freezer/devices path with PHY-work drain/restart
(patch 0012) and freezable power-supply notifications (patch 0013). It does not
enter late/noirq stages or actual sleep. Normal sleep stays disabled.

## Freezer and initial devices stage

```sh
task device:pm-test STAGE=freezer
task device:keypad-retention CYCLES=1
```

Both saved tasks passed, including process-memory integrity, restored PM
controls, fresh USB SSH and independent Wi-Fi SSH to the same boot. The
freezer stage took 5.262 seconds and the devices stage 7.518 seconds. These
include the deliberate five-second debug pause; they are not wake latency.

The first devices stage preserved the original keypad handle, USB device
number and input sysfs identity. There were no keypad disconnects or supply
disable events, no lost trace events and no new kernel warning/error lines.
A fresh healthy input handle was observed 0.213 seconds after the stage.
Tracing and debug flags were restored. PM success advanced to two, with all
failure counters zero. The owner confirmed the normal dim login console and
brightness returned before the four-cycle batch started.

Private evidence under `.local/diagnostics/`:

- Freezer: `20260930T115716.326081Z/cycle-1/result.json`, run
  `90cae1f0b43e45c6b748a9cbab1c4d76`.
- First devices stage: `20260930T115824.522315Z/cycle-1/result.json` and
  `retention.json`, run `59a90638ad894f57bcea118443c654c2`.

## Observed callback ordering

The complete first devices trace contains the following ordinary **bus**
callbacks, all returning zero. Generic prepare/complete callbacks also appear
in the trace and must not be confused with the driver suspend/resume calls.

| Callback | Start–end, kernel monotonic seconds |
| --- | --- |
| USB PHY suspend | 317.916498–317.916508 |
| AXP USB supply suspend | 317.916943–317.918130 |
| RSB ordinary suspend | 317.920828–317.920833 |
| RSB ordinary resume | 322.970656–322.970661 |
| AXP USB supply resume | 322.973295–322.974420 |
| USB PHY resume | 322.974809–322.974819 |

This confirms that the newly registered PHY PM callbacks execute on this
board and return successfully. The observed suspend order is PHY, AXP USB,
RSB; resume reverses that order. The devices test stops before the RSB noirq
cutoff, so this does not prove a physically unavailable bus was protected.
The trace also does not directly record notification-worker execution or
deliberately inject cable edges during freezing. Source/API exclusion and
modeled race coverage remain in [report 69](69-usb-phy-suspend-work.md) and
[report 71](71-power-supply-notification-freeze.md).

## Interrupted four-cycle batch

`task device:keypad-retention CYCLES=4` passed its first cycle but stopped on
the second. Its raw results are retained under
`.local/diagnostics/20260930T120012.168539Z/`.

- Cycle 1, run `54c2d64fa2a24d469f8bf891990b1a16`: passed, stage 7.625 seconds,
  healthy-handle observation 0.216 seconds, original connection and both SSH
  routes verified.
- Cycle 2, run `19cad390d8e34367b3fc67afd3dbb39d`: device postflight failed
  `wifi_connected`. The 7.548-second stage completed with intact process
  memory and original keypad connection, restored tracing and no trace loss.
  PM success reached four and all failure counters remained zero, but Wi-Fi
  was `DISCONNECTED` at the postflight snapshot. This is a failed qualification
  cycle, not a pass inferred from successful kernel return.

USB remained available. The supplicant associated shortly after resume,
timed out authenticating ten seconds later, and then reported repeated
association rejections with status 16 and temporary network backoff. Kernel
logs contained `brcmf_netdev_start_xmit: xmit rejected state=0` during the PM
interval, without a firmware-crash message. These observations do not identify
whether the cause lies in firmware, the driver or the access point. They are
not evidence of a wrong password; the same profile had connected before and
after earlier cycles.
The transmit-rejection line also appeared in the preceding successful cycle,
so it does not uniquely identify the recovery failure.

Later radio logs recorded successful connections at 647.620 and 658.838
seconds. The first is about 135 seconds after PM exit, outside the unchanged
30-second postflight window. A manual `wpa_cli -i wlan0 reassociate` request
was also made through `task device:exec ROUTE=usb` during diagnosis; no profile,
firmware or service was replaced. The connection messages and command log are
retained without attributing recovery to that request. A subsequent saved
`task device:boot-cycles CYCLES=0` passed both routes and boot health on the same
boot. A fresh complete four-cycle batch was then started, preserving the failed
batch separately and keeping the same gates/deadlines.

Private recovery evidence: `.local/neo53-radio-recovery-journal.log`,
`.local/neo53-radio-reassociation-journal.log`,
`.local/neo53-wifi-reassociate.log`, and
`.local/diagnostics/20260930T120447.477637Z/` for the recovered boot/routes.

## Second interrupted batch and input-power correction

The next batch, `.local/diagnostics/20260930T120523.519800Z/`, also stopped on
its second cycle, this time for a different predicate:

- Cycle 1, run `7b0a21cb9f194fdcaf2be73c662ceb4b`: passed, stage 7.651 seconds,
  healthy-handle observation 0.220 seconds and both routes verified.
- Cycle 2, run `a074a9a333144409830b96af2ad19fab`: stage 7.570 seconds, intact
  memory, original keypad connection and restored tracing/PM controls, but
  `battery_external_power` rejected a fresh `Discharging` status at 100%.
  USB was configured and Wi-Fi was connected. PM success reached six with
  zero failures. No retroactive pass is assigned.

The owner confirmed the normal dim console and a connected cable, but noticed
an indicator off and replugged USB, after which it lit. They were unsure whether
the test or a possible knock caused it. Later they reported the light off again.
That later live capture showed both inputs present/online, battery 100% and
Charging with 2 mA reported current; see
`.local/neo54-light-off-power-reading.log`. The unidentified light alone cannot
establish power loss or its cause.

Source review showed that the old gate confused battery-current status with
external input. [NEO-54 / report 75](75-pm-external-power-gate.md) corrects the
helper to capture fresh USB/AC input flags and require USB present/online plus
configured UDC, retaining battery-health/freshness/capacity and all other gates.
The full host checks and read-only hardware preflight passed. This changes no
charger, kernel or image setting. A new four-cycle batch uses the corrected
helper; earlier captures remain separate because their input flags are unknown.

The corrected-helper batch at
`.local/diagnostics/20260930T121443.902864Z/` completed its first devices stage
(run `b8fc13280a514660ae322b7f4342b284`) with software checks passed, then was
stopped during the 20-second inter-cycle pause. The owner had replugged USB to
locate the light and explained they expected an explicit readiness exchange
before testing. The assistant had started prematurely. This batch is retained
as an interrupted/uncontrolled session, not a completed qualification batch.
No second PM run was submitted. The saved `device:pm-restore` task confirmed
the unit stopped and owned controls restored; private evidence is
`.local/neo53-owner-interruption-restore.log` and
`.local/diagnostics/20260930T121603.152325Z/`.

Further owner-observed tests require a fresh explicit ready response. A message
asking to be told when ready is not itself that response.

## Complete owner-ready four-cycle batch

After a fresh explicit ready response, `task device:keypad-retention CYCLES=4`
completed all four cycles with the corrected power gate. The owner confirmed
the normal dim console and readiness for the subsequent physical-button test.
Evidence is `.local/diagnostics/20260930T121722.088925Z/cycle-N/` and
`.local/neo53-owner-ready-batch.log`.

| Cycle | Run ID | Stage seconds | Healthy-handle observation after stage, seconds |
| --- | --- | ---: | ---: |
| 1 | `df8ed7987f4f43108fd4e67cf0e4ff70` | 7.594 | 0.247 |
| 2 | `1aa57b63fef2498eb9b7bcd3f1dda2ab` | 7.611 | 0.219 |
| 3 | `cfc0253bb4f04e2eb4537ea5bac73af4` | 7.648 | 0.233 |
| 4 | `fd44b90d6cfe4d0d8216c38b5ec6312e` | 7.508 | 0.234 |

Every cycle passed process memory, fresh USB/Wi-Fi SSH, original keypad-handle
health, unchanged USB/input identity, no keypad disconnect/supply-disable
event, complete tracing and restored PM/debug settings. USB input was present
and online before and after each stage; battery status was Charging in every
snapshot. PM success advanced from seven to eleven, with all failure counters
zero. There were no new kernel warnings, unsupported-ULPI messages or firmware
crashes. These bounded software checks do not measure uninterrupted electrical
power or physical key delivery. The stage timings include the five-second
debug pause and are not real wake latency.

The earlier Wi-Fi failure remains a separate NEO-55 investigation. This rerun
establishes four successful consecutive cycles; it does not establish that
the prior authentication/backoff problem is fixed.

## Physical input and speaker cues

After explicit owner readiness, `task device:keypad-input AUDIO=1` passed run
`4343cf19a1c54f98b775241d3c3878e4`. Evidence is
`.local/diagnostics/20260930T122317.330994Z/cycle-1/` and
`.local/neo53-physical-input.log`. The owner confirmed the buttons, tones and
final dim console were correct.

The A/B/X/Y tap sequences before and after the devices stage passed on
the original input handle. All nine speaker confirmations completed at the
previously qualified quiet level. Both amplifiers were off after each cue and
before PM, and mixer state was restored. The known cue delay remains deferred.

Linux cleared held A during its input suspend callback: release event
1860.381147 seconds lies within callback 1860.381136–1860.381155. Fresh taps
worked after resume and the final held-key bitmap was empty. This is the
expected kernel-cleared hold behavior, not continuous held-button delivery.
Original USB/input identity and handle health survived, with no keypad
disconnects, supply-disable events, trace loss or new PM failures. All 3,814
PM trace events were retained. USB input was present/online before and after,
both SSH routes passed, and grab/console/audio/tracing/PM controls were restored.

The devices stage took 7.766 seconds, including the deliberate pause; fresh
healthy-handle observation followed 0.231 seconds later. This interactive
stage is not a latency benchmark. PM success reached twelve, with all failure
counters zero; that counter includes the earlier rejected/uncontrolled runs
and must not be read as twelve fully qualified tests.

## Awake USB reconciliation and final state

After owner readiness and recorder readiness, `task device:usb-reconnects
CYCLES=4` passed four ordinary unplug/replug cycles. The owner followed the
requested three-second disconnection and 30-second connected pause, then
confirmed the final cable remained connected. Every cycle recorded
`not attached` followed by `configured` and independently verified USB SSH to
the same boot. The recorder stopped and cleaned up normally. Evidence:
`.local/diagnostics/20260930T122637.492116Z/summary.json`,
`usb-reconnects.jsonl`, `device-states.jsonl` and
`.local/neo53-usb-reconnects.log`. Nominal sampling was 250 ms; physical timing
is unqualified. This is awake cable reconciliation after repeated driver
cycles, not a cable-edge-during-suspend experiment.

Final saved current-boot, PM, keypad and audio inspections passed. Both SSH
routes reached the original boot; all seven checked services were active
without restarts, no failed units or kernel taint were present, and the pinned
firmware had loaded once with zero crashes, SDIO removals or PM-usage underflows.
USB/AC inputs were present/online, battery monitoring valid at 100%/Charging,
normal sleep still masked, `pm_test=none`, `pm_async=1`, all PM failure
counters zero. Both sound PCMs were closed and both amplifiers off. No
permanent keypad quirk or charger setting was changed.

Final private evidence under `.local/diagnostics/`:

- Current boot/routes: `20260930T122959.909043Z/`.
- PM and direct input flags: `20260930T123000.009027Z/inspection.json`.
- Keypad: `20260930T123000.052752Z/keypad.json`.
- Audio: `20260930T122959.985360Z/audio.json`.

The owner is leaving USB connected and the Mac awake. Further unattended work
is limited to awake tests and source review. Physical tests and observed PM
stages wait until the owner returns and explicitly confirms readiness.

## Remaining boundaries

The intermittent authentication/backoff delay remains NEO-55; passing later
cycles do not resolve it. [Report 76](76-wifi-resume-authentication-source-audit.md)
records the subsequent source audit and passing awake comparison. The indicator-light identity/meaning remains a
follow-up. No missing data in the earlier power-status rejection is inferred
from later captures. The complete late/noirq bus-client inventory, wake/error
contract and other sleep prerequisites remain in `FOLLOW-UP.md`.

No actual sleep, physical wake, retention energy, noirq bus-exclusion or
critical-battery result is claimed. The known audio confirmation delay remains
deferred, and the keypad's single-reset experiment is not made permanent.
