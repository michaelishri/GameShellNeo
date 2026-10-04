# Diagnostic.19: first actual RTC sleep/wake

5 October 2026, Pacific/Auckland; capture timestamps are UTC. NEO-112 and
NEO-115 observation.

Diagnostic.19 passed one actual s2idle/RTC-wake test with USB left connected.
USB and Wi-Fi SSH recovered independently, the original keypad connection
survived, and the owner confirmed the normal dim console returned. The owner
missed the new warning tone, so audible warning observation remains separate
from the recorded successful playback.

This is the unchanged-cable comparison for the USB session-retirement fix.
It does not resolve the removal-during-sleep failure under NEO-112: that
scenario still needs its own fresh baseline, rehearsal and attended attempt.
Diagnostic.18's original failure remains preserved in
[report 153](153-usb-removal-sleep-state-failure.md).

## Admission and identity

The seven same-boot debug stages in
[report 158](158-diagnostic19-attended-debug-qualification.md) passed, followed
by the current-source awake rehearsal in
[report 159](159-audible-diagnostic-warnings.md). The owner gave fresh readiness
to watch and listen for one actual sleep test, with USB connected, headphone
jack empty and controls untouched. The command was submitted once:

```sh
task device:sleep-rtc \
  QUALIFICATION=.local/neo112-office-debug-history.json \
  REHEARSAL=a627b646cc9a45bc8adc62f361ef9dda ATTENDED=1
```

| Identity | Value |
| --- | --- |
| Repository at submission | `4ea9c34` |
| Image / kernel | `0.1.0-diagnostic.19` / `6.18.54-gameshellneo19` |
| Boot | `2fa86697-ead3-4e6f-a295-44e6ad203983` |
| Run | `57a221ef9b624e53a294c042e684b0dc` |
| Original capture | `.local/diagnostics/20261004T224048.337973Z/result.json` |
| Result SHA-256 | `acb95d21914041a7763b048b3fac747398713785f5b4ecc51bb3f69fa5b9047b` |

The saved controller revalidated the original debug records, current image,
boot, source fingerprints, RTC history and both routes before submission.
The earlier different-source rehearsal was not used. No image, driver,
charging setting, USB policy or Mac setting changed during this test.

## Result

| Check | Observation |
| --- | --- |
| Actual sleep | One s2idle boundary, with `pm_test=none` and exactly one state write |
| Submitted interval | 31.213 seconds BOOTTIME |
| In-loop s2idle trace | 28.810 seconds MONOTONIC |
| Alarm interval | 32.074 seconds from arming to userspace return; admitted margin 29 seconds |
| Wake source | IRQ 31; RTC count 3 → 4; one character event with flags `0xa0` |
| PM counters | Success 7 → 8; fail and every stage-failure counter zero |
| USB recovery | Configured/carrier 1 before and after; fresh USB SSH to the same boot |
| Wi-Fi recovery | Independent Wi-Fi SSH to the same boot |
| SDIO runtime usage | 2 throughout, active/forbidden with control `on` |
| Keypad | Original handle retained, no disconnect/hangup/poll/ioctl failure or held key |
| Trace integrity | Keypad, Wi-Fi and USB capture complete, with no recorded loss and restored settings |
| Power key | No events; original policy, logical release and descriptor handback verified |
| Cleanup | RTC restored; no retained policy, drop-in, PM-control, RTC or console ownership |
| Display and audio state | Brightness 1, backlight power 0, both audio amplifiers off before/after |
| Final health | Same boot, kernel taint zero, no failed units, battery telemetry 99% |

All late/noirq phases and RSB suspend/resume appear in order around the actual
s2idle boundary. The ECM trace records reinitialization and connection after
resume. The controller issued no gadget restart, cable recovery or network
repair to obtain the passing result.

Two transient `SSHException: Timeout opening channel.` entries remain in
`collection-errors.txt`. The collector retrieved the same original run and
then verified both routes. It did not resubmit sleep. Their cause and their
contribution to recovery time remain part of the existing transport-timing
follow-up; they are not automatically attributed to a kernel or radio fault.

## Speaker observation

The recorded `screen-blank` cue used level 3 and completed playback in 0.999
seconds, with both amplifiers off afterward and the original mixer restored.
Playback completed before RTC arming and before the sleep state write.
This duration includes the known audio startup cost, not just the 80 ms waveform.

The owner answered: “Console returned normally, but I missed the tone.”
The visual recovery is confirmed; hearing the pre-blank warning is not.
After separate listening readiness, the existing three-tone `device:audio-test`
ran with the screen kept on. Its last tone uses the same level as the warning.
All three PCM operations and software restoration checks passed, but the owner
reported: **“I didn’t hear the tones.”** The owner then visually confirmed the
headphone socket was empty. This is a physical audio failure despite successful
PCM completion, not an audible-warning pass.

| Audio evidence | Value |
| --- | --- |
| Run | `16220675bfa34a6e833cce84b9942163` |
| Capture | `.local/diagnostics/20261004T224432.426765Z/result.json` |
| SHA-256 | `be770b51041e10b05e13bf2657f5c193c03a2331c6166427ce99452efb556563` |
| Quiet levels | 1, 2, 3, with original mixer restored and unchanged boot |
| Read-only audio follow-up | `20261004T224621.211068Z/audio.json` |

The follow-up inspection shows the expected card/PCM and idle amplifier/GPIO
state. It does not show the physical output during playback. The existing
helper checks that playback finishes and audio returns to idle; those checks
cannot prove sound was audible or that the output path powered up correctly.
NEO-116 tracks that investigation. Further sleep tests are paused while a
bounded audio-only diagnostic is prepared. No claim is made that this sleep
caused the silence: the pre-sleep warning was missed too, and this boot lacks
an independently confirmed audible baseline.

## Final inspection and limits

The read-only PM inspection at `20261004T224311.972920Z/inspection.json` passed
the complete continuation receipt validation against the original seven debug
records and this one sleep result. PM remains 8/0; the original sleep masks
and normal diagnostic policy remain in place.

The final inspection SHA-256 is
`aa05f18c85a678093994a0272f23dbc49247f5b1765a865acd3feea7ba98b3f4`.
The accepted continuation is
`20261004T224048.337973Z/qualification-next.json`, SHA-256
`2ab2827c3cb5d899f2e8d14c4f4c48b2960a38845ee84dc7e90a2d090db3ec5e`.
It is evidence for future admission checks, not permission to replay this
consumed first-sleep baseline.

The saved offline `report:sleep-evidence` assessment also passed at
`20261004T224311.986412Z/sleep-evidence.json`, without changing or requalifying
the original result. Controller transcripts are
`.local/neo112-office-sleep-first.log`, `.local/neo112-office-sleep-assessment.log`
and `.local/neo112-office-after-sleep.log`.

The CPU-idle driver remains `none`, there are zero timekeeping-freeze pairs,
and the BOOTTIME/MONOTONIC gap is below sampling uncertainty. This establishes
functional s2idle/RTC wake and device recovery for one connected-USB attempt,
not CPU retention, standby energy, broad reliability or user-visible wake
latency. Normal button/automatic sleep remains disabled. Removal, attachment,
other boots and Mac sleep remain separate qualification work.
