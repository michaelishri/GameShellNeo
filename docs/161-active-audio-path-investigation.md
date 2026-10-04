# Active speaker-path investigation

5 October 2026, Pacific/Auckland. NEO-116; warning qualification remains under
NEO-115.

The owner heard none of diagnostic.19's three isolated speaker cues and
visually confirmed an empty headphone socket. The original playback and
restoration checks passed. Those observations, and the preceding successful
RTC sleep/wake, are preserved in
[report 160](160-diagnostic19-first-rtc-wake.md). There is no confirmed audible
baseline earlier in this boot, so these results do not establish sleep as the
cause of silence.

## Reproducible comparison

```sh
task device:audio-path ROUTE=usb
task device:audio-collect RUN=<saved-run-id> ROUTE=usb
task device:audio-restore ROUTE=usb
```

Start only after fresh listening readiness. The new audio-only task waits ten
seconds, plays the existing 80 ms cue, waits two seconds after audio has returned
to idle, then plays a 1,000 ms cue. Both use the existing level 3: headphone
volume 48 (-15 dB) and a stereo 880 Hz waveform with a peak below -20 dBFS and
10 ms fades. It does not change the screen, enter PM or request a reboot.

The comparison records the applied mixer controls and samples playback PCM
status, hardware parameters, both DAPM amplifier widgets and GPIO state. GPIO
text is kept privately, including PL3's reported enable level. Widget paths are
resolved once, avoiding a repeated debugfs tree walk. A sample includes bounding
timestamps: its individual reads are sequential and can span a driver
transition. A DAPM read may also wait for the existing amplifier startup mutex.
Software state and pin readback cannot prove an analogue voltage, speaker
current or audible output.

Observation is limited to eight seconds and 400 samples per cue, with a nominal
20 ms interval. A separate read-only observer runs while the existing bounded
playback helper operates. Failure stops the comparison, saves its partial
evidence and attempts mixer restoration. The existing 90-second systemd service
limit, child playback timeout and independent stop-time mixer cleanup also
apply. Collection retrieves the original run after an SSH interruption; it does
not replay tones. A successful result means the comparison and cleanup
completed, not that the owner heard sound or that every active state was seen.

The shared waveform helper now accepts only 80 or 1,000 ms; the default remains
80 ms, byte-for-byte identical. Unsupported durations are rejected before
touching the mixer or opening PCM. No warning gain, warning duration, driver,
image or installed policy changes in this slice. Helpers are uploaded through
the existing task controller, and `run.json` records their SHA-256 hashes.

The changed shared helper is part of the protected sleep source set. Older
rehearsal/source receipts must not be reused as current-source admission; the
historical sleep result remains valid evidence of its original sources.

## Host validation

`task check` passed 13 runtime and 567 tooling tests (one optional skip), C
regression checks, Bash syntax and ShellCheck. New coverage checks waveform
amplitude, stereo/fades/duration bounds, rejection before PCM/mixer writes,
observation limits/read errors, cleanup after playback/observer failures,
same-boot mixer restoration and complete comparison collection. Existing
80 ms cue, warning ordering and reboot failure checks still pass.

Private validation log: `.local/neo116-check.log`.

## First hardware comparison

The owner gave fresh listening readiness. The task was submitted once and
completed with restored mixer controls and both amplifiers off. No PM, reboot,
cable intervention or driver reload occurred.

| Identity | Value |
| --- | --- |
| Image / kernel | `0.1.0-diagnostic.19` / `6.18.54-gameshellneo19` |
| Boot before/after | `2fa86697-ead3-4e6f-a295-44e6ad203983` |
| Run | `b358bb50a29d43b18adf8f655b1a2917` |
| Result | `.local/diagnostics/20261004T225335.335819Z/result.json` |
| Result SHA-256 | `71f68e27f65dd8432e44aef262eb4820229099eb8df55597e6f8a257eecbe62c` |

| Observation | 80 ms cue | 1,000 ms cue |
| --- | --- | --- |
| Playback/idle-check operation | 1.024 s | 1.961 s |
| Samples | 13 | 44 |
| PCM states observed | closed, SETUP, DRAINING | closed, SETUP, RUNNING, DRAINING |
| Both amplifier widgets On | 5 samples | 32 samples |
| PL3 output | Low at idle, high with speaker amplifier On | Low at idle, high with speaker amplifier On |
| Maximum sequential sample interval | 0.781 s | 0.776 s |

Both used level 3 and the intended mixer settings, stereo S16_LE at 48 kHz,
period size 6,000 and buffer size 24,000. The short waveform is smaller than one
period, so observing DRAINING without RUNNING is not evidence of failed playback.
The longest sample spans the known startup wait; samples are not uniformly
spaced 20 ms hardware snapshots. PL3 is the `enable` line at offset 3 of the
`1f02c00.pinctrl` GPIO controller, mapped by the board DTS; its current global
GPIO number happens to be 3.

Owner short/long audibility observation is pending. Active PCM, DAPM and GPIO
evidence alone does not establish analogue output or audible sound. Further
sleep testing remains paused. Use the combined evidence to choose the next
investigation rather than assuming a longer tone, gain increase or driver reload
fixes the underlying issue.
