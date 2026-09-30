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

## Pending qualification

The owner has been asked to reinstall the card, reconnect USB and power on.
Boot and integration, sound-card/control inspection, quiet cue audibility,
amplifier/mixer restoration and audio-assisted physical-input/PM qualification
remain outstanding. No speaker playback has run, and no audible-output or
idle-power claim follows from the successful flash.
