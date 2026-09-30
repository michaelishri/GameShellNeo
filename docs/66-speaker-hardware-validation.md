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

## Pending qualification

The owner has been asked to listen to the saved three-tone speaker check.
Quiet cue audibility, mixer/amplifier restoration after playback and
audio-assisted physical-input/PM qualification remain outstanding. No speaker
playback has run yet.
