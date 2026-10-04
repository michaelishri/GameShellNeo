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

Awake battery rehearsal, actual battery sleep and subsequent reattachment
remain to qualify. NEO-109 stays open.
CPU-idle/energy work, Mac sleep, power-button wake and product power policy
remain separate; this tooling makes no performance or battery-life claim.

## Read-only hardware inspection

The saved connection inspector passes on the unchanged diagnostic.18 image,
boot `e419f334-0a16-4b04-96d2-d97a2e4d5d0b`. Uploaded source identities match
main commit `12e050c`. It reads configured UDC, carrier 1, PHY `USB=1` /
`USB-HOST=0`, and both external inputs present/online. The four AC/VBUS
plug/removal counters each read 4; all four CPU columns are present. This
qualifies the passive reader's import, path and IRQ-layout assumptions while
USB is connected, not absent-state admission or sleeping behavior.

Capture: `.local/diagnostics/20261004T025746.439153Z/connection-inspection.json`.
SHA-256: `c463c33b58da0a17c1d2402a732c239d9c85acecc4ebd207a83946cbcd0df2f9`.
The subsequent PM inspection at
`.local/diagnostics/20261004T025820.979608Z/inspection.json` passes the common
validator on the original boot, with PM counts unchanged at 19 successes and
zero failures. No RTC programming, PM entry, key ownership or settings change
occurred during these inspections. Fresh observer readiness is still required
for the next debug prerequisites and actual battery sleep.

## Fresh debug prerequisites

After new owner readiness, the updated tools completed seven sequential debug
checks on the same diagnostic.18 boot. Each result was reviewed before the
next submission. All passed independent USB/Wi-Fi access, original input and
policy restoration, trace checks and stable SDIO usage 2. These checks do not
enter actual sleep. Final owner screen confirmation and physical USB removal
are pending; no battery rehearsal or battery sleep has been submitted.

Capture directories below are relative to `.local/diagnostics/`; each contains
`cycle-1/result.json`.

| Stage | Capture | Run ID | PM successes |
| --- | --- | --- | --- |
| Freezer | `20261004T044102.273356Z` | `acf72704d2be47a191a8b3a28e568db3` | 19 → 20 |
| Devices | `20261004T044216.786117Z` | `ad9f936d94754860a9e9871dc8f19258` | 20 → 21 |
| Late/noirq 1 | `20261004T044339.182655Z` | `d2b83a8fb2664887ac96798d6284c894` | 21 → 22 |
| Late/noirq 2 | `20261004T044453.549291Z` | `045e9304f3074a449bc039b6ab4d7608` | 22 → 23 |
| Late/noirq 3 | `20261004T044612.389598Z` | `bb1830f8ead6403cab73f5b2be3b35cc` | 23 → 24 |
| Late/noirq 4 | `20261004T044732.767735Z` | `b5ea95a3bceb47b4ab0a0e3a124b74fc` | 24 → 25 |
| Late/noirq 5 | `20261004T044849.012048Z` | `3e53fef15d8f46d5bf0b69529786977f` | 25 → 26 |

The saved `check:sdio-ref-history --require-stable` task produced
`.local/neo109-reference-history.json` (SHA-256: `782ab212f10e5a3b50d4e53eb3e29340efbba8e86bb5b3aca72c5cfa994beaac`).
The final independent PM inspection at
`.local/diagnostics/20261004T045012.908755Z/inspection.json` passes the common
validator with PM26/0 and unchanged settings. Pre-test board/Mac captures are
`20261004T044027.107939Z/` and `20261004T044027.109885Z/` respectively. Temporary
USB route failures remain in the `.local/neo109-debug-*.log` files and original
capture directories; all were collected using the original run IDs without
resubmitting a PM stage.

This baseline can admit the new-source awake battery rehearsal only while
boot, image, helper sources and PM history remain unchanged. Source/boot
changes or further PM activity require the appropriate new qualification;
waiting alone does not establish physical readiness or cable absence.
