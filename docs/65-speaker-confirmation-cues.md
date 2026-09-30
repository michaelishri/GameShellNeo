# GameShell speaker confirmation cues

NEO-48, 30 September 2026. The image is built and offline-verified; speaker
playback has not yet been qualified on the owner's board.

The owner requested a sound when a prompted button is registered and explicitly
chose the GameShell speaker. Diagnostic.9 has `CONFIG_SOUND` disabled, so a new
kernel/image is required. Diagnostic.10 adds the upstream A33 audio path and
bounded ALSA cues to the saved physical-input task. It retains the existing
keypad supply experiment and keeps normal system sleep disabled.

## Board route and upstream implementation

The CPI v3.1 schematic, page 8, connects the SoC HPL/HPR outputs through AC
coupling to the two speaker amplifiers and the four-pin J3 speaker connector.
PL3 controls their enable net, which is also connected to the headphone
detection circuit. The amplifier supply labelled `PA_5V` follows board `PS`
through FB12; the label does not establish a separately regulated five volts.

The board DTS enables the upstream A33 DAI, digital codec and simple sound card.
It connects the analogue codec's `HP` output to both inputs of a
`simple-audio-amplifier`, with active-high PL3 enable and the board PS supply.
The old PL3 low GPIO hog is removed so the amplifier driver can own the pin.
The fixed supply description deliberately has no invented voltage. The card
uses the name `GameShellNeo` and exposes a `Speaker Switch` control. There is
no HPCOM route: this board uses AC coupling.

The upstream amplifier driver initially requests its enable GPIO low and
switches it through DAPM when a playback path needs it. No vendor audio driver
patch is copied. Headphone detection, microphone recording, HDMI and Bluetooth
audio remain outside this cue qualification.

Primary source inspected locally:

- `../GameShell/clockwork_Mainboard_Schematic.pdf`, page 8.
- Historical `../GameShell/Code/Kernel/v0.6/515_dts.patch` and
  `515_sound.patch`, used as wiring/behavior references only.
- Pinned Linux 6.18.54 `sound/soc/sunxi/sun8i-codec.c`,
  `sun8i-codec-analog.c`, `sound/soc/codecs/simple-amplifier.c`,
  `sound/soc/generic/simple-card.c` and their device-tree bindings.
- `arch/arm/boot/dts/allwinner/sun8i-a33.dtsi` for the standard codec links.

The upstream analogue driver retains its 700 ms headphone-amplifier startup
delay. A cue may therefore arrive noticeably after input acceptance. Reducing
that delay needs pop/noise and reliable-start evidence; this change does not
alter it. Audio-enabled idle power also needs a separate measurement.

## Repeatable tasks and restoration

| Task | Purpose |
| --- | --- |
| `task device:audio-inspect` | Save card, mixer, PCM, amplifier and GPIO state without changing controls |
| `task device:audio-test` | After a ten-second lead-in, play three quiet cues at increasing conservative levels; owner listens |
| `task device:audio-collect RUN=...` | Retrieve the same persistent result after an interrupted connection |
| `task device:audio-restore` | Stop the audio test and restore its owned mixer state |
| `task device:keypad-input AUDIO=1` | Play a confirmation for each accepted A/B/X/Y tap and the accepted A hold |

The cue is an 80 ms, 880 Hz stereo waveform with a -20 dBFS peak and 10 ms
fades. The three speaker-check levels use analogue gains of -27, -21 and
-15 dB. Both digital volume controls are set to value 160, which is unity
gain; their maximum 192 would add 24 dB and is intentionally not used.
The guided keypad test uses the third conservative level. Actual audibility
must be confirmed on the board before using it for an owner-assisted test.

Playback runs directly through `aplay`, with no audio daemon. Each cue closes
the PCM and requires the headphone and speaker DAPM amplifiers to return to
`Off`. The physical-input test checks that state again immediately before
entering its PM debug stage. It requires all nine cue records and complete
mixer restoration before reporting an audio-assisted pass. The existing
silent task remains available with its default `AUDIO=0`.

The helper saves only the controls it owns, with the boot identity, in a
private exclusive record. It disables the speaker path before restoring
routes/gains, restores the original speaker switch last, and retains the
ownership record if restoration fails. Both normal exception cleanup and
systemd `ExecStopPost` attempt restoration. The PM recovery task still
attempts console, tracing, persistence and PM cleanup if audio restoration
fails. An ambiguous SSH submission is collected using its original run ID,
never blindly submitted again.

The image contains ALSA utilities but masks ALSA state-restoration services
and removes the automatic restore udev rule, keeping test mixer ownership
explicit. Exact mixer names, DAPM widget paths, sound output, lack of unwanted
pops, restoration and suspend recovery all require hardware qualification.
These interactive runs are unsuitable as latency or energy baselines.

## Recovery and verification

`task image:checkpoint NAME=diagnostic9-before-speaker` preserves the known
diagnostic.9 image selection, metadata and checksums. Its raw image SHA-256 is
`4c48c1bd110eabb310b5fa608ea1e99f7eef7560c295700763dc30da91d15567`.
The matching gzip SHA-256 is
`0892550dc47de9b0ba832286636a788903e121be4c88b84a4c32c65dee2f0c27`.
Use `task mac:stage-recovery NAME=diagnostic9-before-speaker` to select and
verify that recovery image; add `UPLOAD=1` only if its archive is missing.
That task passed against the archive already on the Mac, verifying both its
compressed and decompressed checksums without transferring another image or
writing a card. Its selection will be replaced when the candidate is staged.

`task kernel:reset` preserved the previous kernel source, install and build
metadata under `.local/previous-kernels/20260930T075653Z-211181/` before the
audio-enabled build. The candidate kernel is `6.18.54-gameshellneo10`.

The first DT schema pass rejected the supply node name `regulator-speaker-ps`:
the generic units schema interpreted its `-ps` suffix as picoseconds. The node
was renamed to `regulator-speaker-supply`, without changing its wiring or
properties. A second `kernel:reset` archived that candidate under
`.local/previous-kernels/20260930T082839Z-235677/`. Its completed object tree
was copied back with `cp -a --reflink=auto` before `task build:kernel`, allowing
Kbuild to reuse objects with the same kernel version, configuration and pinned
toolchain. The source itself was freshly extracted and the complete current
patch queue reapplied; the rejected DTB was rebuilt and revalidated.

Host checks passed 257 tool tests (one optional skip), 13 runtime tests,
compiled helper checks and shell lint. The new tests cover waveform bounds,
rejected levels, playback interruption, ownership/restoration failures and
PM/audio gating. The compiled-DTB check verifies PL3 ownership, AC-coupled
stereo routing, supply linkage and card composition, with negative controls.
The complete kernel/modules/DTB build passed without compiler warnings or
errors. `task check:kernel` passed 162 configuration assertions and checked
15 recorded artifacts. Both base and keypad-retention DTBs passed schema
validation. The compiled speaker card/route/PL3/supply checks passed and
rejected five negative controls; the existing PM and keypad supply checks
also passed. Image assembly and offline verification passed, including
bootloader readback, partition/filesystem checks, boot CRCs, kernel/DTB/modules
and firmware hashes, private identity permissions and service policy. ALSA
utilities and both mixer-service masks passed the new rootfs assertions.

| Artifact | Value |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.10-cpi31-85d14dd37872.img` |
| Raw size | 4,294,967,296 bytes (4 GiB) |
| Raw SHA-256 | `85d14dd378728afed41b15f92c992076510f8e3eef9cbd6932b1a8a3f5f439b2` |
| Gzip size | 269,857,157 bytes |
| Gzip SHA-256 | `531d76ad13b98792d87b4eebfa03793103a1bd3f1b1e6438bf779d4a305bf6d2` |

The kernel `zImage` is 6,580,328 bytes, 165,720 bytes larger than the prior
6,414,608-byte binary. This is compressed kernel size, not runtime memory or
idle-power measurement. Host evidence is retained in `.local/neo48-final-check.log`
and `.local/build/{kernel,devicetree,image,image-verify}.log`.
The pre-flash USB status capture is
`.local/diagnostics/20260930T084043.493376Z/status.txt`.

The owner confirmed regular Wi-Fi for the transfer. Mac staging is in progress;
card installation, live speaker routing, audibility and audio-assisted input/PM
qualification remain outstanding. No speaker test has run yet.
