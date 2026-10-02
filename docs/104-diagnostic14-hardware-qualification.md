# Diagnostic.14 hardware qualification (NEO-81)

3 October 2026, Pacific/Auckland. Installation of the candidate prepared in
[report 103](103-diagnostic14-preparation.md), followed by the guarded sequence
in [report 102](102-rtc-and-platform-diagnostic-preparation.md).

## Card write and recovery

The owner confirmed the Samsung DEV card was in the Mac reader. Fresh inspection
identified the external physical USB card, 64,013,467,648 bytes, 512-byte blocks,
Micro SD/M2 reader and the existing diagnostic FAT16/Linux layout. For this
insertion its identifier was `disk16`; this is not a reusable target identity.

```sh
task mac:status
task mac:inspect DISK=disk16
task mac:preflight
task mac:flash DISK=disk16
```

Both staged archive and decompressed image checksums passed. The saved flash
workflow demonstrated the mount veto, wrote all 4,294,967,296 bytes, read back
every written byte, matched the image SHA-256 and safely ejected the card.

| Item | Value |
| --- | --- |
| Image | `0.1.0-diagnostic.14` |
| Expected kernel | `6.18.54-gameshellneo14` |
| Readback SHA-256 | `3d42271705ebf21c74048655fd19145f94442acb585000b0e8985e9e6f3e7f6b` |
| Private flash evidence | `.local/diagnostics/20261002T111156.328105Z/` |

That directory retains `flash.log` and `flash-result.json`. The fresh target
inspection is `.local/flash/target.json`. Diagnostic.13 recovery remains under
`.local/recovery/diagnostic13-before-wake-preparation/`; its retained artifact
predates the journal correction and needs the saved journal-policy task if used.
The original card backup remains untouched.

## Running baseline and awake gates

The owner confirmed the normal login screen with USB connected. Independent USB
and Wi-Fi SSH reached boot `8131c0a8-0a8c-4f83-bf08-e63e493c020c`, with the
expected image and kernel. All seven boot-inspected services were active with
zero restarts, no failed units and kernel taint zero. The pinned radio firmware
identity appeared once, with no tracked firmware-crash, SDIO-removal or PM usage
underflow markers.

```sh
task device:status ROUTE=usb
task device:boot-cycles CYCLES=0
task device:keypad-inspect
task device:audio-inspect
task device:exec ROUTE=usb -- /usr/sbin/iw reg get
task device:pm-inspect
task device:check ROUTE=usb ACTIVE_COUNTRY=AU
task device:journal-rotation
task device:power-key-smoke
task device:rtc-smoke
```

`CYCLES=0` verifies the current boot without requesting a physical power cycle.
All six integration groups passed. Provisioning remains NZ; this access point
still announces AU, as previously accepted by the owner. Firmware country-99
qualification remains open. The keypad retained its initial USB device number
2 and expected input path, with its supply enabled. The audio card was present
and idle; this slice played no tones and requested no button input.

Initial PM success and failure counters were all zero, with `pm_test=none`,
`pm_async=1`, five-second debug delay and only s2idle available. Normal sleep
remains disabled. Software battery monitoring reported 100%/Charging, around
4.190 V at the early baseline; this is not capacity or voltage calibration.
No charging settings changed. The ready marker was 16.841 seconds after the
kernel monotonic origin; systemd reported 2.418 seconds kernel plus 19.334 seconds
userspace. These are one diagnostic boot's software milestones, not physical
button-to-display timing or proof of the five-second boot goal.

The image's journal correction passed loaded-policy checks and ordinary
`logrotate.service` execution. Journald did not restart, and the kernel history
and displaced-journal inventory remained intact. This exercises the service
used by the timer; a later timer-triggered run remains to be observed.

Untouched awake power-key ownership passed: the helper verified its inhibitor,
held the expected PEK event device exclusively, checked logical release and
returned ownership normally. No power-key gesture was tested. The same-boot RTC
check delivered one `RTC_IRQF | RTC_AF` notification after **10.064 seconds** for
its ten-second deadline, then restored the original disabled logical alarm.
Run ID: `efdf0d8ede344581862325c526b7569b`. This proves awake alarm delivery only.

Private evidence under `.local/diagnostics/`:

| Check | Capture directory |
| --- | --- |
| USB status | `20261002T111706.360760Z` |
| Current boot and independent Wi-Fi | `20261002T111732.795082Z` |
| Keypad | `20261002T111732.893530Z` |
| Audio | `20261002T111732.873787Z` |
| PM baseline | `20261002T111744.276260Z` |
| Integration | `20261002T111756.579610Z` |
| Journal policy and ordinary rotation | `20261002T111807.374606Z` |
| Awake power-key ownership | `20261002T111816.618618Z` |
| Awake RTC delivery/restoration | `20261002T111832.531041Z` |

Host transcripts are `.local/neo81-*.log`.

## Attended ordinary gates

After explicit observer readiness, one freezer and one devices debug cycle
passed with exclusive power-key ownership. Both independent SSH routes recovered
on the same boot; all failure counters remained zero and the success counter
advanced from zero to two. Key ownership handed back cleanly, without any PEK
events. PM controls returned to `none`, async 1 and delay 5.

```sh
task device:pm-power-key STAGE=freezer CYCLES=1
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
```

| Stage | Run ID | Private capture |
| --- | --- | --- |
| Freezer | `e82bf7ba015f4482a4172c5d9be1fb75` | `20261002T112055.779474Z/cycle-1` |
| Devices | `96df4d8afdd444c98c916b641083bb80` | `20261002T112204.035838Z/cycle-1` |

The original keypad handle, device number and input path survived. The devices
trace recorded no keypad disconnect or supply-disable event, no callback error,
and no trace loss; PM/keypad and Wi-Fi tracing restored successfully. Whole-stage
times were 5.533 and 7.930 seconds, including the deliberately imposed five-second
debug wait and diagnostic overhead. These are not real resume latency figures.

The devices journal delta contains one `brcmf_sdio_bus_rxctl: resumed on timeout`
and one `brcmf_cfg80211_reg_notifier: Firmware rejected country setting`.
Diagnostic.13 deltas at `20261002T084447.379018Z`, the four cycles under
`20261002T084640.118494Z`, and `20261002T085323.939272Z` already show this family
of messages. Their recurrence is not a new diagnostic.14-only finding, but the
cause remains unresolved. Source inspection shows the generic country rejection
message follows any error from the country setter, including transport failure;
it does not independently prove firmware refusal. No fault was injected and no
country setting changed. NEO-82 tracks this separately from the earlier intermittent
authentication failure. Successful restoration is not a warning-free radio claim.

The owner confirmed the normal dim console after the ordinary gate and gave
fresh readiness for the first platform boundary.

## First platform late/noirq gate

```sh
task device:pm-platform
```

One `platform + freeze` cycle passed, run
`195e604e49ec41c89eea06932b0e0997`, captured under
`.local/diagnostics/20261002T112617.341350Z/cycle-1/`. The owner subsequently
confirmed that the normal dim console and brightness returned. No repeat batch
was submitted in this slice.

The saved trace contains exactly one ordered begin/end pair for suspend late,
suspend noirq, resume noirq and resume early. There were no callback errors,
trace overruns or actual-sleep markers, and both trace configurations restored.
Relevant monotonic timestamps from the PM trace:

| Callback | Entry (s) | Successful return (s) |
| --- | --- | --- |
| RSB noirq suspend | 612.246788 | 612.246813 |
| RSB noirq resume | 617.252844 | 617.252929 |
| PEK noirq resume | 617.252999 | 617.253008 |

Thus the recorded RSB restore completed before the power-key driver's noirq
resume callback. The RSB controller also logged its 3 MHz reinitialization.
The five-second debug interval occurred between noirq suspend and resume;
the complete measured stage took 7.719 seconds including that interval and
diagnostic overhead. The test returned before `s2idle_loop()` and did not test
a sleeping CPU, physical wake delivery or energy consumption.

The same-boot restored RTC record admitted the test; the alarm remained disabled.
The original keypad handle, USB device number and input path survived, with no
keypad disconnect or supply-disable event. Power-key ownership handed back
normally without a PEK event. Both independent SSH routes verified the original
boot after completion. One collection connection timed out opening an SSH channel
while the cycle was in progress; the wrapper subsequently collected the exact
run without resubmitting it. That observation is preserved in
`collection-errors.txt` and is not a failed PM callback or an extra cycle.

The radio again recorded an `rxctl` timeout, this time followed by
`Country code iovar returned err = -110`, identifying a timed-out country read.
NEO-82 includes this evidence. PM restoration passed, but radio control-request
behavior is still unresolved; this pass does not erase that finding.

## Final state and remaining gates

Final PM success was **3**, with every failure counter zero, no failed services
and kernel taint zero. Boot, sleep masks, PM controls, retained-power policies,
USB experiments, Wi-Fi profile/power-save policy, charging configuration, CPU
policy, input devices and backlight matched the initial baseline. The idle audio
snapshot matched every baseline field. All six integration groups passed again.
The RTC alarm was disabled, the power-key identity was unchanged, and the PM,
RTC and power-key helpers left no ownership marker or loaded transient service.

Final evidence under `.local/diagnostics/`:

| Check | Capture directory |
| --- | --- |
| PM and health | `20261002T112807.177631Z` |
| Idle audio | `20261002T112807.203237Z` |
| Integration | `20261002T112832.015129Z` |
| Power-key identity/ownership | `20261002T112903.616653Z` |
| RTC state | `20261002T112910.529891Z` |

The final explicit unit/ownership-marker check is `.local/neo81-cleanup.log`.
All work used the saved tasks; no build or runtime code changed in this slice.

This completes installation and the first guarded late/noirq qualification,
not reliability qualification. Next are observed repeats of this boundary and
the remaining driver/control-request investigation. Before actual sleep, finish
independent power-key gesture ownership (including abnormal termination), RTC
deadline ownership and a supervised physical-wake/recovery protocol. Normal sleep
remains disabled. Physical key wake, short-press sleep/wake, the two-second menu,
eight-second forced poweroff, resume latency and standby energy remain open.
