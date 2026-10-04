# Active speaker-path investigation

5 October 2026, Pacific/Auckland. NEO-116; warning qualification remains under
NEO-115. The comparison below is historical: following the owner's final
choice, the saved audio-path task now plays only one long tone at level 5.

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

The owner answered: “I think I heard it, it's just really quiet. Can you turn
the volume up a little bit”. This is a tentative sound observation rather than
a definite confirmation of both durations. It changes the next comparison:
test a modest increase in gain at the owner's request before pursuing an
unproven driver fault. Active PCM, DAPM and GPIO evidence alone still does not
establish analogue output or reliable audibility.

## Owner-requested level increase

`task device:audio-path ROUTE=usb LEVEL=4` selects headphone volume 54 (-9 dB),
6 dB above the original level 3. The waveform peak, digital gains, fades,
frequency and two durations remain unchanged. Level 3 remains reproducible
through the same task at this checkpoint. The initial candidate was bounded to
these two levels; normal warnings and button confirmations remained at level 3
during comparison.
Fresh readiness is required for the new comparison; further sleep remains
paused. A gain adjustment is not evidence that a driver issue has been fixed.

The level-selection change also passed `task check` with the same 13 runtime/
567 tooling count (one optional skip), C and shell checks. Private log:
`.local/neo116-level4-check.log`.

After fresh owner readiness, the level-4 comparison was submitted once from
commit `ad71aa9`. Both playback operations completed with the same boot, original
mixer restoration and both amplifiers off afterward:

| Identity | Value |
| --- | --- |
| Run | `2978da2a40054070b5c2892b7098927d` |
| Result | `.local/diagnostics/20261004T225732.895022Z/result.json` |
| Result SHA-256 | `e91ff53c7329ef4f624b7446fcae2ae1a69f472bd718f2021505df32338f7893` |
| Applied headphone volume | 54; digital playback volumes both 160,160 |
| 80 ms cue | 13 samples; both amplifiers On observed; 1.024 s complete operation |
| 1,000 ms cue | 42 samples; PCM RUNNING and both amplifiers On observed; 1.911 s operation |
| PL3 | Low at idle, high with speaker amplifier On in both comparisons |

The owner answered: “Still too quiet but make it only slightly louder”. The
next candidate is `LEVEL=5`: headphone volume 57 (-6 dB), a further 3 dB step.
Frequency, waveform amplitude and durations stay the same; levels 3 and 4 remain
reproducible in the recorded source commits. Normal cue defaults were unchanged
during comparison.

## Selected cue

After another fresh ready response, the level-5 comparison was submitted once:

| Identity | Value |
| --- | --- |
| Source at submission | `a0cda50` |
| Run | `66c31a7fcad247fe98e1e87b453785c7` |
| Result | `.local/diagnostics/20261004T225950.244114Z/result.json` |
| Result SHA-256 | `ac611c31751fd59847152e5e9a906dec7eb1891170dfef345b8172a809031a22` |
| Applied headphone volume | 57; digital playback volumes both 160,160 |
| 80 ms cue | 12 samples; both amplifiers On observed; 0.939 s complete operation |
| 1,000 ms cue | 43 samples; PCM RUNNING and both amplifiers On observed; 1.880 s operation |
| PL3 | Low at idle, high with speaker amplifier On during both cues |
| Cleanup | Same original boot, mixer restored, both amplifiers Off |

The owner first selected “Only the longer tone is clear”, then requested only
long tones moving forward, clarifying: **“The short tone works but the long one
get's my attention.”** This supports an attention/volume choice, not a claim
that the short waveform or driver failed. Both are audible at the latest
setting by that clarification; the long one is preferred. No further gain
increase or speculative driver fix is warranted by these observations.

All feedback now defaults to the one-second, level-5 cue, including button
confirmations and screen-blanking warnings. The screen warning retains its
one-second observer lead-in after audio returns to idle. `device:audio-test`
and `device:reboot` play three such cues at the same level, separated by the
existing two-second gaps. The reboot validator rejects records with the old
short duration or gain even if their playback/restoration passed. The ordinary
`device:audio-path` task now plays just one long cue and defaults to level 5;
explicit levels 3 and 4 remain available for gain comparisons. Historical
short/long runs remain reproducible from commits `4e675f8`, `ad71aa9` and
`a0cda50`, with their original results preserved.

No reboot or additional sleep was performed to validate the new defaults.
Observing the long warning immediately before darkness and the next necessary
reboot remains NEO-115 work. No physical button sequence was requalified here.
The existing amplifier startup delay remains; choosing a longer cue does not
optimize keypress-to-sound latency, and synchronous feedback now occupies
longer. That already-deferred investigation remains separate.

Controls restore after every session, so this is a saved cue policy rather than
a permanent mixer change. Uploaded helpers need no image flash. Final host
checks are recorded below; no further audio or sleep test is
running. Refresh current-source sleep admission before resuming NEO-112,
preserving all original evidence.

Final `task check` passed 13 runtime and 567 tooling tests (one optional skip),
C regressions, Bash syntax and ShellCheck. This includes rejecting old short
reboot warnings and rejecting a result from a different selected level. Private
log: `.local/neo116-long-cues-check.log`. NEO-116's immediate audibility
investigation and requested cue policy are complete; NEO-115's action-specific
observations and wider audio/latency qualification remain separate.
