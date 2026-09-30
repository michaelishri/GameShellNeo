# Diagnostic.11 preparation (NEO-51)

1 October 2026, Pacific/Auckland. Candidate image for ordinary freezer/devices
qualification of the PMIC-access fixes. The 4 GiB image is built and verified,
and its 270 MB archive is staged on the Mac with compressed/decompressed
checksums passed. It has not been flashed or booted. Diagnostic.10 remains
installed on the GameShell.

## Candidate contents

- Image version `0.1.0-diagnostic.11`; kernel `6.18.54-gameshellneo11`.
- Patch 0012: drain/disable USB PHY detection during ordinary system suspend,
  then re-enable and reconcile cable state on resume. [Report 69](69-usb-phy-suspend-work.md).
- Patch 0013: freeze power-supply notifications before devices suspend and
  replay queued state after resume/unwind. [Report 71](71-power-supply-notification-freeze.md).
- Explicit suspend-freezer config requirements, already enabled in the
  diagnostic.10 resolved configuration.
- Existing stock USB detection policy, keypad supply retention and speaker
  cues. No permanent keypad port quirk or audio-latency change.

Linux, toolchain, Debian snapshot, bootloader, firmware and board wiring stay
at their existing locks. Normal sleep stays masked. No late/noirq or actual
sleep stage is enabled by this image; short power presses still shut down.
Its purpose is to qualify the two new worker-lifecycle fixes before widening
the test scope.

## Recovery and reproducible preparation

```sh
task image:checkpoint NAME=diagnostic10-before-notification-freeze
task kernel:reset
task provision
task build
```

The checkpoint verified the existing raw image and compressed archive and
saved their matching image, kernel, patch, package and transfer manifests in
`.local/recovery/diagnostic10-before-notification-freeze/`. It references the
retained `GameShellNeo-0.1.0-diagnostic.10-cpi31-85d14dd37872.img`; artifacts
are retained at their existing private paths, not copied into Git.

The reset preserved the old source, objects, installed modules and metadata
under `.local/previous-kernels/20260930T110952Z-287797/`. The new build uses a
fresh source extraction with the entire current patch queue. Private
provisioning was refreshed from `.env` before image assembly. Secrets remain
in ignored private files.

The initial clean kernel compilation was stopped to reuse the compatible
diagnostic.10 object cache. Before reuse, the source archive/commit, pinned
builder, byte-identical resolved config, every pre-existing patch hash and all
15 recorded old kernel/module artifacts were checked against the recovery
checkpoint. Only patches 0012/0013 were additional. The old cache was copied
with `cp -a --reflink=auto` into the new output tree after the build container
had stopped; the fresh patched source tree was retained. The saved stages
then resumed with:

```sh
task build:kernel
task test:usb-policy-board
task check:dt
task build:image
```

Kbuild still handles changed-source and release-header dependencies. This is
incremental object reuse, not substitution of an old kernel image or bypass
of artifact verification. Initial logs are retained in `.local/neo51-build.log`
and `.local/neo51-kernel-clean-partial.log`; resumed stages are logged in
`.local/neo51-build-resume.log` and the usual `.local/build/` logs.

The saved recovery selection task is:

```sh
task mac:stage-recovery NAME=diagnostic10-before-notification-freeze
```

It uses the checkpoint's own manifests and reuses the previously uploaded
archive when available. `UPLOAD=1` is needed only if that archive is missing.
Selecting/staging recovery does not write a card.

## Verification

All saved kernel source regressions passed before compilation, including the
new 68-scenario power-supply check and 148-scenario PHY check, native/ARM32 and
their negative controls. The full kernel/modules/DTB build then completed
without compiler warnings or errors. Its log confirms recompilation of both
`power_supply_core.o` and `phy-sun4i-usb.o`; ELF symbols confirm the former's
`system_freezable_wq` reference and the latter's new PM operations plus work
disable/enable calls.

`task check:kernel` passed 164 configuration assertions and all 15 recorded
artifact checks. The resolved config is byte-identical to the verified
diagnostic.10 config, SHA-256
`d370205bf2e4eed5e35483f15372a6785e7d96252d40c343dfee0b2dde37a017`.
The completed kernel release is `6.18.54-gameshellneo11`.
All ten installed modules' ELF `vermagic` strings were independently checked
against that release, confirming that cache reuse did not retain old module
version metadata.

Both base and keypad-retention device trees passed schema validation. The
compiled PM contract, speaker routing/PL3/supply checks and keypad-retention
checks passed, including their missing/altered-property negative controls.
The final `task check`, after the version bump, passed 266 tool tests (one
optional skip), 13 runtime tests, compiled helper checks and Bash/ShellCheck;
its log is `.local/neo51-final-check.log`.

Image assembly and offline verification passed MBR boundaries, bootloader
readback, FAT16/ext4 filesystem checks, U-Boot CRCs/addresses, kernel/DTB/module
and firmware hashes, private identity permissions and service policy. The
package inventory is byte-identical to diagnostic.10. Normal sleep remains
masked, with the existing speaker and keypad-retention policies.

| Artifact | Value |
| --- | --- |
| Raw image | `GameShellNeo-0.1.0-diagnostic.11-cpi31-b833bedf0ed0.img` |
| Image bytes | `4294967296` (4 GiB) |
| Image SHA-256 | `b833bedf0ed068d519f808dfa7f8b4dc3e6585e9e5f143168e7aa260229cae9c` |
| Transfer bytes | `269820072` (about 270 MB) |
| Transfer SHA-256 | `8dc60b23f1853d7ccd90393025453e9a1965ca673bd7b99b47cdb18d00595721` |
| Kernel zImage SHA-256 | `77e72f83d33ecdc8fb1dc3570406fb24f63605c6a5772183008d8caaecd839cf` |

Exact manifests, package inventory and logs are under `.local/artifacts/`;
the transfer manifest is `.local/flash/transfer.json`. The final image build
completed successfully in `.local/neo51-build-resume.log`. Image verification
is recorded in `.local/build/image-verify.log` and
`.local/artifacts/verification.json`.

## Mac staging

```sh
task mac:status
task mac:stage
```

The Mac was reachable and reported the GameShell USB route. The owner had
last confirmed regular Wi-Fi; the saved stage task uploaded the new archive
and verified both its compressed and decompressed hashes on the Mac. Evidence
is `.local/neo51-mac-status.log` and `.local/neo51-stage.log`. The verified
current image was immutable while the separate bundle checksum index finished.
No GameShell command, SD-card write or PM test was performed in this slice.

The next physical step is to shut down the GameShell and move the Samsung DEV
card to the Mac reader. Its current disk identifier must be inspected afresh;
the old identifier is not authorization to write a newly appearing disk.

## Next hardware sequence

1. Freshly identify the Samsung DEV card, preflight the verified candidate,
   flash it, complete full readback and eject through the saved Mac tasks.
2. Confirm normal login, then capture integration, PM, keypad and audio state
   and independently prove USB and Wi-Fi SSH access.
3. Run the saved freezer check, one owner-observed devices check, and a
   four-cycle devices batch. Require healthy services, no PM failures,
   expected input continuity, both routes and complete restoration.
4. Requalify ordinary USB attachment/removal and final cable state. Repeat the
   saved physical-input sequence with speaker cues when the owner is ready;
   its previously recorded audio delay remains deferred.

These stages do not qualify physical wake, real sleep current, noirq bus
exclusion on hardware, critical-battery wake or the complete regulator/radio
contract. Those gates remain in `FOLLOW-UP.md` and report 71.
