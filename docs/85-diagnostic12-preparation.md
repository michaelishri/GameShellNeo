# Diagnostic.12 preparation (NEO-64)

1 October 2026, Pacific/Auckland. This candidate brings the four brcmfmac
suspend fixes into a complete image for CPI v3.1. The 4 GiB image has passed
offline verification, and its 277 MB archive is staged on the Mac with both
compressed and decompressed checksums verified. Diagnostic.11 remains on the
DEV card; this preparation slice did not run a GameShell command, PM test or
card write. Installation and hardware qualification follow separately.

## Candidate contents

Image `0.1.0-diagnostic.12` uses kernel `6.18.54-gameshellneo12` with the
existing patch queue and these additions since diagnostic.11:

| Patch | Behaviour being qualified |
| --- | --- |
| [0014 / report 81](81-brcmfmac-sleep-error-propagation.md) | Propagate KSO, clock and sleep errors; balance retune cleanup and revalidate uncertain state after a partial transition. |
| [0015 / report 82](82-brcmfmac-freezer-lifecycle.md) | Serialize worker collection, bound its wait, thaw on timeout and protect completion reuse. |
| [0016 / report 83](83-brcmfmac-pm-rollback.md) | Check retained-power transitions and wake ownership, unwind failed suspend and block firmware I/O after an unsuccessful restore. |
| [0017 / report 84](84-brcmfmac-pm-lifecycle.md) | Exclude conflicting PM/reset/removal operations, retire parked workers before removal, track power-off ownership and defer interrupt status reads during radio sleep. |

Linux source, toolchain, Debian snapshot, bootloader, firmware/NVRAM and board
wiring retain their existing locks. Stock USB detection, keypad supply
retention and speaker cues remain selected. There is no audio-latency change.
Normal sleep remains masked, and a short power-button press still shuts down.
The agreed short/2-second/8-second gesture policy is future implementation.

The source fixes do not establish the cause or resolution of NEO-55's
intermittent Wi-Fi authentication failure. Failed radio restoration still
requires a cold restart; automatic reset/reprobe recovery is not added.

## Recovery and reproducible preparation

The saved workflow was used in this order, with the image/release identity
advanced after preserving the diagnostic.11 checkpoint:

```sh
task image:checkpoint NAME=diagnostic11-before-wifi-pm-hardening
task kernel:reset
task provision
task build
```

Checkpoint metadata is under
`.local/recovery/diagnostic11-before-wifi-pm-hardening/`. It preserves image,
kernel, patch, configuration, package and transfer evidence and references the
retained private recovery files:

- Image: `GameShellNeo-0.1.0-diagnostic.11-cpi31-b833bedf0ed0.img`.
- Raw SHA-256: `b833bedf0ed068d519f808dfa7f8b4dc3e6585e9e5f143168e7aa260229cae9c`.
- Compressed SHA-256: `8dc60b23f1853d7ccd90393025453e9a1965ca673bd7b99b47cdb18d00595721`.

The reset archived the previous source, output, modules and completed kernel
metadata at `.local/previous-kernels/20261001T005804Z-475387/`. Diagnostic.12
uses a fresh extraction and clean kernel compilation. Private provisioning
was refreshed from `.env`; credentials and personalized artifacts stay in
ignored storage. Build progress is saved in `.local/neo64-build.log`, with
individual stage logs under `.local/build/`.

Recovery selection remains reproducible:

```sh
task mac:stage-recovery NAME=diagnostic11-before-wifi-pm-hardening
```

That task uses the checkpoint's own manifests and reuses the existing Mac
archive when present. Add `UPLOAD=1` only if the archive is missing. Selection
does not write a card; flashing still requires a fresh inspection of the
Samsung DEV card. The original GameShell card remains preserved.

## Verification

The saved source regressions passed for clocks, AXP USB lifetime/suspend,
USB PHY suspend, power-supply notification freezing, MUSB context and the
experimental USB policy. All four brcmfmac suites passed natively and on
ARM32, including their negative controls: 95 low-level sleep scenarios,
44 collector scenarios, 89 PM scenarios and 102 lifecycle scenarios. These
totals overlap; they are not independent additional tests.

`task check` passed 13 runtime tests, 276 tool tests (one optional skip), the
compiled helpers and Bash/ShellCheck. Evidence: `.local/neo64-check.log`.
The resolved configuration passed 164 assertions and is byte-identical to
diagnostic.11, SHA-256
`d370205bf2e4eed5e35483f15372a6785e7d96252d40c343dfee0b2dde37a017`.
The full kernel/modules build completed without compiler warnings or errors.
`task check:kernel` passed all 15 recorded artifact checks and the configuration
assertions. All ten modules' embedded `vermagic` values identify
`6.18.54-gameshellneo12`. The first thirteen patch hashes match the recovery
checkpoint; only patches 0014–0017 are additional. Evidence is in
`.local/neo64-kernel-check.log`, `.local/neo64-artifact-inspection.json` and
`.local/build/kernel.log`.

The base and keypad-retention device trees passed schema validation. The
compiled USB policy, PM retention contract, speaker routing/PL3/supply and
keypad-supply checks passed, including their negative controls. The expected
missing-property message is from a rejected negative control, not a candidate
schema failure. Evidence: `.local/build/usb-policy-board.log` and
`.local/build/devicetree.log`.

Image assembly and offline verification passed MBR boundaries, bootloader
readback, FAT16/ext4 filesystem checks, U-Boot CRCs/addresses, kernel/DTB/module
and radio hashes, private identity permissions and service policy. The package
inventory is byte-identical to diagnostic.11. Normal sleep remains masked.
Evidence is in `.local/build/image-verify.log` and
`.local/artifacts/verification.json`; package inventories are in the current
artifact directory and the recovery checkpoint.

| Artifact | Value |
| --- | --- |
| Raw image | `GameShellNeo-0.1.0-diagnostic.12-cpi31-b7c0ac5fe2a8.img` |
| Image bytes | `4294967296` (4 GiB) |
| Image SHA-256 | `b7c0ac5fe2a8836ead3daba2a6b063fc7b002c30a051d45d26a17f00d14c61a2` |
| Transfer bytes | `276613805` (about 277 MB) |
| Transfer SHA-256 | `a43abe69bad1c78ea3ae25c5d6a6d301814b48b3f92fcf89de33ce241e26f9eb` |
| Kernel zImage SHA-256 | `ae7f97700b9ab6df10a326da5b7c444c6689818118af9cdaff0d59fc3d682abc` |

Exact build inputs, manifests, package inventory and logs are retained under
`.local/artifacts/`; no personalized image or credentials are committed.

## Mac staging

```sh
task mac:status
task mac:stage
```

The owner confirmed regular Wi-Fi, and the saved task compressed the verified
image, uploaded it and checked its compressed and decompressed hashes on the
Mac. Compression/staging overlapped only the final build's read-only hashing
of retained artifacts, after the new image's offline verification had passed.
Both `task build` and `task mac:stage` completed successfully.

Evidence is in `.local/neo64-mac-status.log`, `.local/neo64-stage.log` and
`.local/neo64-build.log`; the transfer manifest is `.local/flash/transfer.json`.
The Mac archive is under the SSH account's `.local/share/GameShellNeo/`.
Staging neither identifies nor writes an SD card. A fresh card inspection is
still required before flashing the owner's Samsung spare.

## Saved observation for the next hardware session

The existing PM recorder now saves raw `/proc/interrupts` and `/proc/stat`
alongside each before/after snapshot. It performs no recurring polling and
changes no PM gate, wait or acceptance threshold. Counter differences can
show unusual interrupt or CPU activity across the complete observation.

These cumulative snapshots include ordinary awake work and the post-resume
network wait. They do **not** isolate the brief SDIO IRQ-deferral interval,
attribute every interrupt to brcmfmac or measure energy. Unexpected activity
requires a focused trace before drawing a driver or power conclusion.

## Staged physical qualification

Diagnostic.11's installed baseline and subsequent traced PM results are in
[report 73](73-diagnostic11-installation.md),
[report 74](74-diagnostic11-pm-validation.md) and
[report 78](78-wifi-resume-metadata-capture.md). Preserve the original failure
evidence when comparing the new candidate.

1. Shut down and move the Samsung DEV card to the Mac. Inspect its current
   identity, preflight, flash, verify the entire 4 GiB readback and eject using
   the saved tasks. Confirm normal login after reinsertion.
2. Check the actual boot/kernel identity, integration groups and independent
   USB/Wi-Fi access. Capture PM, keypad and audio baselines before a test.
3. Run the saved freezer check. After the owner's explicit readiness, run one
   `devices` cycle with Wi-Fi metadata capture; verify both network routes,
   original keypad continuity and restored settings, then confirm the screen.
4. After separate readiness, run four consecutive traced `devices` cycles.
   Retain the existing postflight deadline and error gates. Review kernel PM
   counters, firmware recovery messages, authentication progress and the new
   interrupt/CPU snapshots. A clean counter alone does not prove pending IRQ
   service or race freedom.
5. When the owner is ready, repeat the saved audio-assisted A/B/X/Y and held-A
   sequence, followed by four USB reconnect checks with the recorder ready
   before giving the unplug instructions. The known cue delay remains.

Useful saved PM commands, each subject to the applicable readiness gate:

```sh
task device:pm-test STAGE=freezer CYCLES=1
task device:pm-test STAGE=devices CYCLES=1 WIFI_TRACE=1
task device:pm-test STAGE=devices CYCLES=4 WIFI_TRACE=1
```

Stop on a failed stage and retrieve its persistent run rather than resubmitting
it automatically. Preserve USB recovery and use a cold restart if Wi-Fi is
left unavailable by a failed restore. A repeated candidate regression can
return to the verified diagnostic.11 image. Later PM stages, actual sleep,
power-button wake, battery protection and energy/latency qualification remain
separate work; this image enables none of those acceptance claims.
