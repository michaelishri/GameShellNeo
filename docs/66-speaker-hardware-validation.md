# Speaker image hardware validation (NEO-48)

30 September 2026. Owner's CPI v3.1, Samsung DEV card. This follows
[diagnostic.10 preparation](65-speaker-confirmation-cues.md).

The owner requested registration sounds from the GameShell speaker. The new
image enables the upstream A33 audio path and bounded, explicitly owned ALSA
playback. Normal sleep remains disabled. This report records installation
separately from successful sound output and PM recovery.

## Installation

The owner confirmed that the GameShell was shut down and its DEV card was in
the Mac reader. Fresh `task mac:status` and `task mac:inspect DISK=disk16`
identified the sole external physical USB card: 64,013,467,648 bytes, 512-byte
sectors, with the expected `armbi_boot` FAT16/Linux layout. The target identity
was recorded again rather than reusing a previous insertion's record.

`task mac:preflight` verified the staged archive and target without writing.
`task mac:flash DISK=disk16` then verified its mount veto, wrote the full
4,294,967,296-byte image, read back that entire region and safely ejected the
card. The readback SHA-256 matched diagnostic.10 exactly:

`85d14dd378728afed41b15f92c992076510f8e3eef9cbd6932b1a8a3f5f439b2`.

Image: `GameShellNeo-0.1.0-diagnostic.10-cpi31-85d14dd37872.img`.
Candidate kernel: `6.18.54-gameshellneo10`.

Private evidence:

- `.local/neo48-mac-card-status.log`
- `.local/neo48-card-inspect.log`
- `.local/neo48-card-preflight.log`
- `.local/diagnostics/20260930T093124.029145Z/flash.log`
- `.local/diagnostics/20260930T093124.029145Z/flash-result.json`

The disk number is historical evidence, not a reusable target selection.
Diagnostic.9 recovery remains available using
`task mac:stage-recovery NAME=diagnostic9-before-speaker` after a fresh card
identification. That archive's compressed/decompressed verification passed
before staging diagnostic.10.

## Boot, home Wi-Fi and integration

The owner confirmed the normal login screen and supplied updated home-network
settings in `.env`. USB SSH reached `6.18.54-gameshellneo10`, image
`0.1.0-diagnostic.10`, boot ID `5bac9cdf-d98f-42ec-a3f3-7454e0c6d92d`.
All seven inspected services were active with zero restarts, no failed units
or kernel taint. Battery telemetry reported 100% and charging over USB.

`task device:wifi-config` refreshed private provisioning, applied the new
credentials through USB, verified independent Wi-Fi SSH to the same boot,
committed the configuration, verified transaction cleanup and updated
`GAMESHELL_IP` privately in `.env`. No reboot or manual credential exposure was
needed. The live network configuration now reflects the home settings rather
than the credentials initially embedded in the image.

`task device:check ROUTE=usb ACTIVE_COUNTRY=AU` passed all six integration
groups: image identity, service state, database/policy, journal ACLs, BPF
enforcement and country checks. The configured country remains NZ; the home
access point advertises AU, which the owner previously asked to leave as-is.
Global regulatory state was AU and the radio domain was 99. This does not
establish the firmware's complete regulatory behavior.

Private evidence:

- `.local/diagnostics/20260930T093816.032464Z/status.txt`
- `.local/diagnostics/20260930T093841.125569Z/wifi-change.json`
- `.local/diagnostics/20260930T093923.867019Z/inspection.json`
- `.local/diagnostics/20260930T093957.642730Z/integration.json`

## Initial audio inspection

`task device:audio-inspect` found exactly one `GameShellNeo` simple-card, with
one playback and one capture PCM. Both PCM handles were closed; DAPM reported
`Speaker Amp DRV: Off` and `Headphone Amp: Off`. The amplifier owns R_PIO pin 3
and its GPIO readback was output-low. All seven selected mixer controls
matched the helper's expected names and value formats. Initial headphone and
digital DAC volumes were zero, their playback switches off, the headphone
route direct-DAC and the card's speaker pin switch on.

The read-only capture is
`.local/diagnostics/20260930T093923.873470Z/audio.json`. These are software
state observations, not a measurement of analogue voltage or idle current.

## First speaker playback

With the owner ready to listen, `task device:audio-test` completed run
`2a3b87417d284cb4a0ad2f643435bf09` on the same boot. All three bounded cues
played successfully. After every cue, both DAPM amplifiers were `Off`; the
final playback and capture PCMs were closed. The complete mixer dump matched
its pre-test state exactly, and the owned-state restoration checks passed.

The owner confirmed all three tones were clear and suitable for button
confirmation, answering the prompt that also asked about increasing level,
clicks and distortion. This is an auditory observation for these quiet tones,
not a general fidelity, loudness or headphone qualification.

Measured helper operation times were 0.975, 0.962 and 0.966 seconds. These
include process/startup/playback/idle checks, including the retained upstream
700 ms amplifier startup delay; they do not measure first-sound latency or
energy. The waveform itself remains 80 ms.

Private evidence:
`.local/diagnostics/20260930T094225.857912Z/result.json`, with host log
`.local/neo48-first-speaker-test.log`.

## Audio-assisted input and driver recovery

The saved `task device:pm-test STAGE=freezer` passed run
`8898dd93621542fb8a1389841e2eb4a7`, with fresh USB and Wi-Fi SSH both verified.
Evidence is `.local/diagnostics/20260930T094345.897766Z/cycle-1/result.json`
and `.local/neo48-freezer.log`. Its 5.314-second stage includes the deliberate
five-second pause, with memory and PM restoration checks passed.

With the owner ready to follow the screen, `task device:keypad-input AUDIO=1`
passed run `bb66759cef58472fb39b0b3a260e57ee` on the same boot:

- All nine cues completed: four A/B/X/Y confirmations before PM, the A hold
  confirmation, and four A/B/X/Y confirmations after PM. Each used the third
  previously qualified quiet level. Both amplifiers were `Off` after every
  cue and immediately before entering the PM stage.
- All physical taps passed through the original input handle. The USB device
  number and input sysfs identity stayed unchanged, with zero keypad
  disconnects or keypad supply-disable events.
- Held A was cleared by Linux during input suspend, as on diagnostic.9. Its
  release timestamp, 558.380885 seconds, lies inside the traced input suspend
  callback at 558.380875–558.380891 seconds. This is a kernel-cleared hold,
  not continuous key-down delivery. Fresh taps after resume worked and the
  final held-key bitmap was empty.
- All 215 input events and 3,814 trace events were retained, with no reader
  error, trace overruns or dropped events. The keypad grab, console, mixer,
  tracing and PM settings were restored.
- Fresh USB and Wi-Fi SSH checks passed. All PM failure counters stayed zero;
  no ULPI warnings, kernel warnings/oopses or additional firmware loads were
  recorded during this driver stage.

The devices debug stage took 7.630 seconds; a fresh healthy input handle was
observed 0.212 seconds afterward. Cue helper operations took 0.953–1.006
seconds. These interactive, instrumented timings include the deliberate PM
debug pause and are not real wake or energy measurements.

The owner confirmed clear confirmation tones before and after the dark
interval and the normal dim login screen at the end.
They subsequently reported a significant delay after **every** keypress,
rather than only the first. Sound clarity passed; responsiveness remains a
known limitation. The helper closes playback and verifies amplifier power-down
after every cue, so each following cue repeats the upstream 700 ms amplifier
startup wait. The measured 0.953–1.006-second helper operations are consistent
with that behavior, but are not a direct keypress-to-audible-onset measurement.
The owner explicitly deferred a fix and requested a future investigation.

Private evidence:
`.local/diagnostics/20260930T094538.147838Z/cycle-1/`, including `result.json`,
`retention.json` and `physical-input.json`; host log `.local/neo48-keypad-audio.log`.

Independent final inspection confirmed the same boot, the complete mixer dump
identical to the initial audio inspection, both PCM handles closed and both
amplifiers `Off`. All seven services remained active with zero restarts; no
failed units or kernel taint; PM success count 2 and every failure counter 0;
`pm_test=none`, `pm_async=1` and USB configured. Captures:

- `.local/diagnostics/20260930T094807.612276Z/audio.json`
- `.local/diagnostics/20260930T094813.878011Z/inspection.json`

## Scope and remaining limits

NEO-48's speaker-confirmation task is qualified on this CPI v3.1 board. The
repeatable guided command is `task device:keypad-input AUDIO=1`; the default
without that option remains silent. The standalone speaker task and recovery
commands are documented in [report 65](65-speaker-confirmation-cues.md).

Normal sleep remains disabled. This covers one audio-assisted driver debug
cycle, not actual sleep/wake reliability, long-run playback, every input chord,
headphone detection, calibrated loudness or idle energy. Those follow-ups and
the significant per-keypress audio delay remain separate work. A future
investigation should measure audible-onset latency and compare a bounded
ready audio path during an interactive sequence against powering down after
each cue, while preserving quiescence before PM and prompt idle restoration.
Any change to the upstream startup delay also needs electrical/pop/noise
evidence. No latency fix was applied in this task.
