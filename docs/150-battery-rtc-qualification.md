# Battery-only RTC-wake qualification tooling

4 October 2026, Pacific/Auckland. NEO-109; prerequisite for NEO-95's
cable-absent sleep coverage.

The saved RTC diagnostic now has an explicit battery-only profile. It submits
and collects one original attempt over Wi-Fi, while the existing USB profile
continues to require external power, a configured USB gadget and independent
USB/Wi-Fi recovery. This changes diagnostic tooling, not the kernel image,
charging policy or ordinary sleep behavior. The awake rehearsal and one attended
battery-only actual sleep now pass on unchanged diagnostic.18. The owner
confirmed normal dim-console return without intervention. Subsequent physical
USB reattachment also passed independently, completing NEO-109's bounded
tooling and first hardware qualification.

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

The awake battery rehearsal, one actual sleep and subsequent USB reattachment
have now passed, as recorded below. NEO-109 is complete for this bounded scope;
NEO-95 retains broader cable/host and repeat-boot qualification.
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
occurred during these inspections. The subsequent debug checks and awake
battery rehearsal are recorded below; actual sleep requires fresh readiness.

## Fresh debug prerequisites

After new owner readiness, the updated tools completed seven sequential debug
checks on the same diagnostic.18 boot. Each result was reviewed before the
next submission. All passed independent USB/Wi-Fi access, original input and
policy restoration, trace checks and stable SDIO usage 2. These checks do not
enter actual sleep. The owner subsequently confirmed normal dim-console
returns after every dark interval, then physically removed USB for the
separately recorded battery rehearsal below.

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

## Awake battery rehearsal

The initial physical confirmation did not match the hardware readings: captures
`20261004T045249.604694Z` and `20261004T045751.385524Z` still showed external
power, configured UDC, carrier 1 and PHY `USB=1`. The absent-cable validator
rejected both. No rehearsal or sleep was submitted in that state. The owner
then clarified that USB was still connected and removed it from the GameShell.

The fresh passive capture at `20261004T045904.794573Z` passes absent-state
validation: both external inputs absent/offline, UDC `not attached`, carrier 0
and PHY `USB=0` / `USB-HOST=0`. AC/VBUS removal counters advanced from 4 to 5;
plug counters remained 4. Boot and helper sources were unchanged.

The saved task then passed without entering sleep:

```sh
task device:sleep-battery-rehearse QUALIFICATION=.local/neo109-reference-history.json UNPLUGGED=1
```

Run `e0de7c35a0044bf99149e2bff9d0d4a9`, capture
`.local/diagnostics/20261004T045932.183842Z/result.json`, establishes:

- RTC IRQ 31 advanced from 9 to 10, with exactly one alarm delivery after
  30.781 seconds and successful restoration of the original RTC state.
- PM counts remained 26 successes / zero failures. The trace contains no
  sleep transition. Original keypad, process memory, audio and power policy
  remained intact, with trace and diagnostic ownership cleanup complete.
- Cable state and all four cable IRQ counts remained unchanged across the
  before/entry/after observations. Battery monitoring was valid and discharging,
  reporting 98% before and 97% afterward; these are gauge readings, not a
  measurement of energy consumed by this short test.
- Independent Wi-Fi SSH reached the original boot. The result explicitly
  records `usb_ssh_verified=false`; absent USB is not a recovery claim.

The original result also passes offline revalidation against unchanged helper
sources and the image lock. No image, driver, charging or network settings were
changed. The separately attended actual sleep follows below; physical
reattachment remains a distinct check.

| Artifact | SHA-256 |
| --- | --- |
| Absent connection inspection | `bdf7cdf05cd9817ab0ce166fc7119ab84abdefed42bfc3082056f5b658a93887` |
| Awake rehearsal result | `379ecb8d1630700448594ba28084ff8b3928cf72c8d2a6217433a97ae82e80a7` |

## One actual battery-only sleep

After fresh observer readiness, the unchanged saved task submitted exactly one
actual `freeze` request, with `pm_test=none` and `pm_async=0` temporarily selected:

```sh
task device:sleep-battery QUALIFICATION=.local/neo109-reference-history.json REHEARSAL=e0de7c35a0044bf99149e2bff9d0d4a9 UNPLUGGED=1 ATTENDED=1
```

Run `b646d6376cbd47f2bbb739cce201cd2d` completed successfully. Its original result
is `.local/diagnostics/20261004T050133.659161Z/result.json`. Independent Wi-Fi
SSH recovered to boot `e419f334-0a16-4b04-96d2-d97a2e4d5d0b`, and offline
revalidation passed. The owner confirmed that the normal dim login console
returned without touching either the cable or controls.

| Observation | Result |
| --- | --- |
| PM successes / failures | 26 → 27 / zero failures |
| RTC IRQ 31 | 10 → 11; exactly one alarm interrupt, original RTC state restored |
| Alarm elapsed time | 31.743 seconds |
| State-write-to-return interval | 30.858 seconds; includes entry, RTC wait and resume |
| Actual s2idle trace interval | 28.439 seconds, inside the expected late/noirq boundaries |
| Cable state | Absent before, immediately before entry and after recovery |
| Cable IRQ counts | Plug counts 4, removal counts 5; unchanged throughout |
| Battery telemetry | Valid/discharging, 95% before and 94% after |
| SDIO runtime usage | 2 before and after, unchanged policy |
| Original input and memory | Preserved; original evdev handle remained connected |
| Display / idle audio / policies | Restored to original values |
| Cleanup | RTC, trace, power-key and PM ownership fully released |
| USB SSH proof | Explicitly false; physically absent, not tested |

The parent debug run was consumed once through the durable successor claim.
The saved `qualification-next.json` preserves the accepted result for any
later separately attended battery attempt; it does not authorize another
unobserved submission.

No CPU-idle driver is installed (`none`), and the trace contains zero
timekeeping-freeze pairs. This establishes the functional s2idle/RTC-wake path
and device recovery on battery, not CPU retention, standby energy, deep suspend
or subsecond resume. The one-point percentage difference cannot quantify
energy use. No repair, reboot, cable intervention or automatic retry was used.

| Artifact | SHA-256 |
| --- | --- |
| Actual battery sleep result | `99d5d59c923a17950ca01da66b2b458b8db0fb8001206ed8456eaf0bea828fd7` |
| Continuation qualification | `fdd7c9efc23fb6a80f8349725ef5d33309564908a872b9a92d70213f42c3e58e` |

Before requesting reattachment, `task device:sleep-collect` retrieved the same
original run over Wi-Fi into `20261004T050423.642052Z`. Its normalized digest
matches the accepted result. The separate live snapshot confirms the same
boot, absent USB, disabled USB wake, restored `pm_async=1` / `pm_test=none`
and no retained policy or PM owners; the service cleanup record has no errors.
Mac capture `20261004T050355.381052Z` has no GameShell USB device and unchanged
sleep/wake history compared with the pre-debug capture.

An attempted `device:pm-inspect ROUTE=wifi` at `20261004T050355.397541Z`
timed out because that task currently ignores `ROUTE` and always connects by
USB. It produced no health snapshot and made no PM submission. This tooling
limitation is recorded in `FOLLOW-UP.md`; the battery test's validated after
snapshot and Wi-Fi original-result collection remain the relevant evidence.

## Separate USB reattachment

Only after the original battery result and the owner's untouched screen-return
confirmation were saved did the owner receive the separate instruction to
reconnect USB, wait thirty seconds and leave it connected. The owner confirmed
completion. Saved read-only tasks then checked the board and Mac:

```sh
task device:pm-inspect
task device:status ROUTE=wifi
task mac:usb-inspect
task device:sleep-connection-inspect
task device:sleep-collect RUN=b646d6376cbd47f2bbb739cce201cd2d ROUTE=wifi
```

USB SSH reached the original boot and the common connected-health validator
passed. UDC was `configured`, carrier 1, PHY `USB=1` / `USB-HOST=0`, and both
external supplies were present/online. AC/VBUS plug counters each advanced
from 4 to 5; removal counts stayed at 5. The Mac saw GameShellNeo in its USB
tree, all six host capture groups succeeded, and its sleep/wake history was
unchanged from the pre-debug capture. Independent Wi-Fi collection reached
the same boot and retrieved the unchanged original battery result.

PM remained 27 successes / zero failures, with SDIO runtime usage 2 and
unchanged policy. Image, kernel, PM controls, ordinary sleep masks, original
input identity, display settings, Wi-Fi configuration/policy, charger settings
and CPU policy matched the successful battery result. No new kernel journal
entries appeared. Battery monitoring reported valid/charging at 92%; this is
not a capacity or charging-accuracy measurement. The live recovery snapshot
confirmed complete original cleanup and no retained diagnostic policy owners.

This is one physical reattachment after an independently successful battery
sleep. It is not a plug-to-ready latency measurement, a cable change during
sleep, host-sleep coverage or repeated qualification on another boot. No gadget
restart, network repair, new PM submission or hardware-policy change occurred.
The battery sleep record retains `usb_ssh_verified=false`; the later USB proof
belongs to this separate check.

Capture paths are relative to `.local/diagnostics/`:

| Evidence | Capture |
| --- | --- |
| Connected PM health and USB SSH | `20261004T050848.834026Z/inspection.json` |
| Mac USB/network/sleep history | `20261004T050850.227609Z/` |
| Cable/PHY/IRQ inspection | `20261004T050927.748915Z/connection-inspection.json` |
| Independent Wi-Fi original-result collection and live state | `20261004T050953.423025Z/` |

`.local/neo109-reattach-review.json` records the checks and capture hashes.
Its SHA-256 is
`9e0c6e32feeb3bab69ac4ccb45ed520a4dfad9d901b826c56b57b017bd02f2f6`.
The offline review also revalidates all seven debug records and the one actual
battery sleep against unchanged sources/image/boot and PM history. The present
connected state is not admission for another battery attempt: a later attempt
still requires cable removal, fresh physical readiness and current validation.
