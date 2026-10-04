# Battery-only RTC-wake qualification tooling

4 October 2026, Pacific/Auckland. NEO-109; prerequisite for NEO-95's
cable-absent sleep coverage.

The saved RTC diagnostic now has an explicit battery-only profile. It submits
and collects one original attempt over Wi-Fi, while the existing USB profile
continues to require external power, a configured USB gadget and independent
USB/Wi-Fi recovery. This changes diagnostic tooling, not the kernel image,
charging policy or ordinary sleep behavior. No battery-only sleep has yet run.

## Why a separate profile

The [four actual sleep passes](148-diagnostic18-repeat-rtc-wake.md) and
[four subsequent awake cable reconnects](149-diagnostic18-post-sleep-usb-reconnects.md)
establish different behaviors. Neither establishes RTC sleep with external USB
power absent. Previously, the runner deliberately rejected that setup because
its admission, transport and recovery checks all required USB.

The new `battery` profile is explicit in the device command/result, host
submission record, qualification receipt and accepted history. A connected
rehearsal cannot admit a battery attempt, and chains cannot mix profiles.
Device-owned original results, matching hashes, unchanged source/image/boot,
ordered PM/RTC counters and durable single-successor claims remain mandatory.
Old successful results are preserved, not rewritten to match new sources.

## Battery admission and observations

All existing common image, firmware, journal, service, power-key, RTC, input,
memory, SDIO, audio, display and PM-control requirements still apply. The
battery profile additionally requires:

- Fresh valid battery monitoring, reported charge above 20%, and discharging
  status. The existing freshness threshold is unchanged.
- Both AXP223 USB and AC input objects reporting absent and offline.
- UDC state `not attached`, USB carrier 0, and the single qualified Allwinner
  PHY reporting `USB=0` and `USB-HOST=0`.
- Fresh physical cable-absence confirmation, recorded by `UNPLUGGED=1` on
  the host and an explicit device flag. Actual sleep separately requires
  `ATTENDED=1` after observer readiness.

The cable reader captures state before the attempt, immediately before entry
preparation and after return/recovery observation. Each capture includes the
boot, monotonic observation time and AC/VBUS plug/removal IRQ counts. Changed
boot/counts or unordered observations fail validation. A changed cable at
entry fails before either the wakeup-count handshake or sleep-state write.
No periodic cable polling worker, IRQ clearing or raw register access is added.

These samples and interrupt counts are observations, not an electrical edge
recorder. The [known PMIC interrupt limitation](34-usb-status-polling-investigation.md) still exists; unchanged counts
alone cannot establish that every physical transition would be detected.
The observer must leave the cable disconnected throughout. This is a
functional recovery test, not a standby-current measurement.

The profile uses the existing bounded RTC deadline, wakeup-count handshake,
single PM submission, persistent result and owned cleanup. Failed or uncertain
submission is followed by collection of the same run ID, never a second sleep.
Wi-Fi recovery must reach the original boot; successful battery records set
`wifi_ssh_verified=true` and explicitly leave `usb_ssh_verified=false`.
USB reattachment is a separate subsequent physical check. No USB restart or
connection repair is included in battery recovery.

## Saved tasks and hardware sequence

The README documents these tasks and their required variables:

```sh
task device:sleep-connection-inspect             # Passive, via USB by default
task device:sleep-connection-inspect ROUTE=wifi  # Same passive reader via Wi-Fi
task device:sleep-battery-rehearse QUALIFICATION=<history.json> UNPLUGGED=1
task device:sleep-battery QUALIFICATION=<history.json> REHEARSAL=<run-id> UNPLUGGED=1 ATTENDED=1
task device:sleep-collect RUN=<original-run-id> ROUTE=wifi
```

The passive reader uploads matching helper sources, reads cable/PHY/power/IRQ
state, records source identity, and removes its temporary helper directory.
It does not acquire power-key ownership, arm the RTC, enter PM or alter network
settings. Collection remains the separate original-result/postmortem path.

New sources require a fresh, reviewed seven-debug baseline while USB is
connected, then physical removal and absent-state inspection over Wi-Fi.
Run the new-source battery rehearsal while awake; only after it passes and
fresh observer readiness arrives may the one-shot actual sleep run. Keep USB
absent through original-result collection and display confirmation. Then
qualify physical reattachment separately. No card swap or new kernel is
required for these uploaded tools; normal sleep targets remain masked.

There is deliberately no battery batch command in this slice. A successful
one-shot can publish a profile-bound continuation for a later separately
attended one-shot, with the same original rehearsal and all existing ancestry
checks. Do not reuse report148's consumed chain with changed helpers or delete
successor claims to obtain admission.

## Source verification and limits

The focused sleep/PM suite passes 84 tests. New cases cover healthy battery
admission, retained USB/common-health rejection, missing supplies, invalid
telemetry, active PHY/carrier, missing/duplicate/negative IRQ evidence, cable
changes before the PM write, profile/rehearsal mismatches, explicit physical
confirmation, rejected battery batches and Wi-Fi-only collection after an
uncertain submission. They also verify that passive inspection never enters
the PM controller and that no battery success claims USB route recovery.

`task check` passes 13 runtime and 513 tooling tests, with two optional skips,
plus compiled current-limit/mount-guard checks and Bash/ShellCheck. The skips
are the opt-in user-systemd recovery test and the pinned Armbian helper check
whose prepared source is absent in this isolated worktree. Logs are
`.local/neo109-focused-tests.log` and `.local/neo109-check.log` in
`work/battery-rtc-qualification`'s worktree. Tests use modeled transport and
filesystem fixtures, not real sleep or electrical fault injection.

Hardware import/state inspection, awake battery rehearsal, actual battery
sleep and subsequent reattachment remain to qualify. NEO-109 stays open.
CPU-idle/energy work, Mac sleep, power-button wake and product power policy
remain separate; this tooling makes no performance or battery-life claim.
