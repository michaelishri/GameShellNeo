# Diagnostic.20: first actual RTC sleep/wake

5 October 2026; capture timestamps are UTC. NEO-117.

Diagnostic.20 passed one actual s2idle/RTC-wake test with USB left connected.
The owner heard the long warning and confirmed the normal dim console returned
without touching the cable or controls. USB and Wi-Fi SSH recovered independently,
the original keypad connection survived, and all three USB/supply wake controls
remained disabled. No further sleep test is running.

This is the unchanged-cable comparison for the new supply wake policy. It does
not yet prove staying asleep when USB is attached: that scenario needs its own
fresh baseline, awake rehearsal and attended attempt. Diagnostic.19's original
early-wake failure in [report 165](165-diagnostic19-usb-attachment-early-wake.md)
remains unchanged.

## Admission and identity

[Report 168](168-diagnostic20-attended-debug-qualification.md) records seven
passing debug stages, owner-confirmed sounds/display returns and the current
source's awake rehearsal. The owner gave fresh readiness for one actual sleep
test, with USB connected, the headphone socket empty and all controls untouched.
The saved command was submitted once:

```sh
task device:sleep-rtc \
  QUALIFICATION=.local/neo117-debug-history.json \
  REHEARSAL=25114c89789149759c63cb19070959cc ATTENDED=1
```

| Identity | Value |
| --- | --- |
| Repository at submission | `8af5a78`, `work/power-insertion-wake` |
| Image / kernel | `0.1.0-diagnostic.20` / `6.18.54-gameshellneo19` |
| Boot | `86a43151-7d9b-44bd-83b3-cc1b9fcff215` |
| Run | `72c11992ffbd4ef1a92243053cd9d5b2` |
| Capture beneath this worktree | `.local/diagnostics/20261005T053119.252371Z/result.json` |
| Original result SHA-256 | `51a785074fe187ee83cccd914572b3f5e513b46aef3a1ee873af49f8d4e08d8d` |

The saved controller revalidated the debug originals, image, boot, source
fingerprints, RTC history and both network routes before submission. It made
one sleep-state write. No image, driver, charging configuration, Mac setting
or wake policy was changed during the test.

## Result

| Check | Observation |
| --- | --- |
| Actual sleep | One s2idle boundary; `freeze` state, `pm_test=none` |
| Submitted interval | 31.604 seconds BOOTTIME |
| In-loop s2idle trace | 29.174 seconds MONOTONIC |
| Alarm interval | 32.473 seconds from arming to userspace return; entry margin 29 seconds |
| Wake source | IRQ31; RTC count 2 → 3; one character event with flags `0xa0` |
| PM counters | Success 7 → 8; fail and every stage-failure counter zero |
| USB / Wi-Fi | Independent SSH recovery to the original boot |
| Wake policy | MUSB, `axp20x-usb` and `axp22x-ac` remain disabled before/after |
| Wi-Fi SDIO | Usage 2, active/forbidden with control `on`, unchanged |
| Keypad | Original handle retained, no disconnect/hangup/poll/ioctl error or held key |
| Trace integrity | Keypad, Wi-Fi and USB complete, with no recorded loss and restored settings |
| POWER ownership | No events; logical release, descriptor handback and original policy verified |
| Cleanup | RTC restored; no retained policy, drop-in, PM-control, RTC or console owner |
| Display / audio | Brightness 1, backlight power 0, original idle audio state restored |
| Health | Same boot, no checked kernel faults/failed units/taint, valid battery telemetry 100% |

All four late/noirq phases and RSB suspend/resume callbacks appear in order
around the actual s2idle boundary. The controller did not restart the gadget,
repair the network or request cable reconnection to obtain the passing result.

Two `SSHException: Timeout opening channel.` entries are preserved in
`collection-errors.txt`. The collector retrieved the same original run and
then independently verified both routes; it did not resubmit sleep. Their
cause and contribution to recovery time remain unassigned under the existing
transport-timing follow-up.

## Warning and owner observation

The warning record contains one level-5, 1,000 ms `screen-blank` cue with
successful playback and mixer restoration. Both speaker/headphone amplifiers
were off before PM. Playback completed before RTC arming and the sleep write.
The owner replied **"Yes—warning clear; dim console returned untouched"**.
This confirms both audible warning and visual recovery for this attempt.

## Final inspection and limits

Saved `task device:pm-inspect` capture
`20261005T053359.145310Z/inspection.json` passes health checks and the existing
continuation validator against all seven debug originals and this one sleep.
PM remains 8/0. Its SHA-256 is
`4d56679aba975e091ac37ddfac59edcadf6e15b1af0500e493c660d82d7edbfa`.

The saved continuation is
`20261005T053119.252371Z/qualification-next.json`, SHA-256
`9243d7e19aee44eda14b85b95ae4caf63ca6cdd32266bdf7c3e5a5898fcd76fc`.
The original first-sleep baseline has been consumed and must not be replayed.
The continuation supports admission checks for its existing connected-USB
profile; cable transitions require independent one-shot evidence.

The saved offline assessment also passes:

```sh
task report:sleep-evidence \
  RESULT=.local/diagnostics/20261005T053119.252371Z/result.json
```

Capture `20261005T053359.163973Z/sleep-evidence.json`, SHA-256
`de3cd313050145be7553851e4286e3d9ff580ac28f7db064c135311d8a34aafd`,
does not rewrite or requalify the original result. Controller logs are
`.local/neo117-first-rtc-wake.log`, `.local/neo117-first-rtc-assessment.log`
and `.local/neo117-after-first-sleep.log`.

The CPU-idle driver remains `none`, there are no timekeeping-freeze pairs, and
the BOOTTIME/MONOTONIC gap is below sampling uncertainty. These results establish
functional s2idle/RTC wake and device recovery for this connected-USB attempt,
not CPU retention, standby energy or production wake latency. The full battery's
reported Charging state is not proof of charge acceptance during sleep.
Ordinary automatic/button sleep stays disabled. USB attachment, removal under
the new policy, POWER wake, other boots and Mac sleep remain separate work.
NEO-117 remains in progress.
