# Diagnostic.22 ADC width integration

7 October 2026. NEO-131. The kernel, driver checks and offline image verification pass.
The image is staged on the Mac with both compressed and decompressed hashes
verified. Diagnostic.21 remains installed; the last read-only check found it
awake and USB connected. No new hardware PM or charging experiment is part of this build.

## Scope and recovery

The next image is `0.1.0-diagnostic.22`, kernel `6.18.54-gameshellneo21`.
It adds patch 0036's low-byte ADC width correction from
[report 192](192-axp-adc-width-correction.md). The board configuration, firmware,
charging/gauge controls, voltage scales and USB/supply wake policy are unchanged.
Normal button/automatic sleep remains disabled.

Before advancing the identity, `task image:checkpoint
NAME=diagnostic21-before-adc-width` verified the installed image's raw/compressed
artifacts and recorded matching recovery metadata. `task kernel:reset` preserved
its kernel source/output under
`.local/previous-kernels/20261007T035816Z-2080522`. These are recovery artifacts;
source-qualified ADC changes are not yet installed or hardware-qualified.

## Measurement-report contract

Schema 4 retains three exact image/kernel profiles:

| Image | Kernel | B8 | Linux low-byte voltage formula |
| --- | --- | --- | --- |
| diagnostic.20 | `6.18.54-gameshellneo19` | possibly cached | unmasked |
| diagnostic.21 | `6.18.54-gameshellneo20` | volatile | unmasked |
| diagnostic.22 | `6.18.54-gameshellneo21` | volatile | masked to four bits |

The allowlisted eleven reads, strict identity/cache/layout gates, read-only
access and continuity checks remain. Unknown/cross-paired versions reject
before register access. `adc_width_masked` records the selected contract;
the raw bytes, unused bits, masked formula and legacy unmasked formula are
all preserved. `linux_helper_formula_uv` now follows the admitted image's
implementation, with `linux_helper_width_masked` alongside it. Neither formula
is labeled coherent or calibrated. Existing historical captures are unchanged.

The standalone inventory and embedded awake charging inventory use schema 4;
the outer charging sampler schema is unchanged. The 27 focused tests pass,
including complete captures for all three profiles, differing masked/legacy
values, raw-byte preservation and rejected version pairings. Full host checks
pass 13 runtime and 632 tooling tests (one existing optional skip), C helpers,
Bash syntax and ShellCheck. The additional five tests cover the storage
cleanup extension below. Logs are `.local/neo131-focused.log` and
`.local/neo131-host-check.log`.

## Build storage

Before the long build, available space was below the unchanged 10 GiB image
gate. Two maintenance operations recovered approximately 5 GiB net while
preserving recovery images, diagnostics and current compiler evidence:

```sh
task build:compact-driver-sources SUITE=brcmfmac-lifecycle-tests \
  TARGET=/home/mishri/workspace/clockworkpi/GameShellNeo RECORDED_PATCHES=1
task build:compact-driver-sources SUITE=brcmfmac-lifecycle-tests \
  TARGET=/home/mishri/workspace/clockworkpi/GameShellNeo RECORDED_PATCHES=1 APPLY=1
task build:prune-driver-scratch SUITE=usb-policy-tests \
  TARGET=/home/mishri/workspace/clockworkpi/GameShellNeo
task build:prune-driver-scratch SUITE=usb-policy-tests \
  TARGET=/home/mishri/workspace/clockworkpi/GameShellNeo APPLY=1
```

The first replays the historical patch export and verifies both complete
source trees before sharing them, preserving their outputs and evidence. The
second retains the qualified USB-policy compiler tree and deletes two
superseded trees. Its new explicit suite profile verifies retained object and
configuration hashes and preserves all additional references from saved
evidence files. Target selection permits maintenance of the older checkout
without editing its tracked files. Thirteen cleanup tests pass, covering the
new profile, additional references, output corruption, evidence symlinks and
object paths that could escape the output tree or override configuration checks.

The first USB preview rejected an incorrect assumed evidence key before any
deletion; the corrected tool uses the recorded `arm_build` contract and passed
its revised tests and preview. Cleanup records in the main worktree are:

| Record | SHA-256 |
| --- | --- |
| `.local/build/brcmfmac-lifecycle-tests/compact-20261007T035545.067456Z.json` | `0c0f01832a26851d52ac7ec7207314b170f883ff68939ba2756a7db29b797204` |
| `.local/build/usb-policy-tests/prune-20261007T035737.287701Z.json` | `90a57125a6726daa43b19cde759d33dc8750b9f1c3a8d2a24e9d03a466ce1cab` |

The final cleanup audit reports 13,544,505,344 bytes free before the full build.
No storage threshold was lowered. Unrelated user edits in the main checkout
were preserved.

## Kernel and assembly

Integration commit `e1ab1cb` advances the image/reporting contracts; storage
tool commits `792d43c` and `501e6d5` add the guarded cleanup support. The saved
`task build` passes all driver regression stages, the complete ARM kernel and
modules, the compiled board contract and device-tree checks. Its log is
`.local/neo131-build.log`, with per-stage logs beneath `.local/build/`.

The kernel configuration passes 164 assertions. The completed kernel manifest
checks 15 files and has SHA-256
`253f3961372de42501d93b58506bf2424d11d57f45e505bbbc32d512f624e7ae`.
Patch 0036 SHA-256 is
`cb84828849caa61875bcdca3732dc6953b1b4ffbd75b6fbedae33b7c4e85452c`.

The first preparation stage could not locate the default sibling bootloader
path from the nested worktree. Its original failure is retained in the full
build log and `.local/neo131-prepare-initial-failure.log`. The bootloader and
private radio-reference directory are supplied using the documented overrides:

```sh
task build:image \
  BOOTLOADER=/home/mishri/workspace/clockworkpi/GameShell/Code/Kernel/v0.2/u-boot-sunxi-with-spl.bin \
  RADIO_DIR=/home/mishri/workspace/clockworkpi/GameShellNeo/.local/hardware-baseline/2026-09-27/radio-reference
```

Their locked hashes pass; this reuses the completed kernel without rerunning
its passing regressions. The resumed assembly log is `.local/neo131-image.log`.
Offline verification passes MBR bounds, bootloader readback, FAT16/ext4 checks,
U-Boot CRCs/addresses, kernel/DTB/modules/radio hashes, private-identity
permissions and service policy. Its `hardware_qualified` flag remains false.

## Verified artifacts and transfer

| Artifact | Value |
| --- | --- |
| Raw image | `GameShellNeo-0.1.0-diagnostic.22-cpi31-08136efbd5f9.img` |
| Raw size | 4,294,967,296 bytes (4 GiB) |
| Raw SHA-256 | `08136efbd5f939c88d1390240ecc00cd60f0a40ae7789b90cd6d7377f622fadf` |
| Gzip size | 269,657,695 bytes |
| Gzip SHA-256 | `34c5c2cbade2a6b27b1f625c785e023ade9dfbba5f91d2a0120b5b7eece523d8` |
| Package inventory SHA-256 | `66dc03283bb690e55ab2b2540b0ffe43310dfb39f872672c4d6b3884ecc3358b` |

The saved `task mac:stage` packed the private image, uploaded it and verified
both compressed and fully decompressed hashes on the Mac. Its log is
`.local/neo131-stage.log`. No physical card was written. The private image
contains provisioned credentials and is not a public release artifact.

`task image:checkpoint NAME=diagnostic22-adc-width-candidate` preserves its
verified recovery metadata and artifact references. Diagnostic.21's separate
recovery checkpoint remains available.

## Hardware handoff and limits

A card swap and attended hardware qualification remain separate from the host
and build results. First confirm boot and both SSH routes, then run awake
health checks and read-only charge inventory with the admitted diagnostic.22
contract. Check raw ADC bytes against the masked Linux formula while preserving
the legacy formula and settings. Follow with the saved staged PM qualification
when the owner is ready to watch and listen.

No sleep, reboot, charger/gauge write or extended charging experiment ran during
this slice. The source-level defect is proven; the read-only diagnostic.21
sample had zero unused low-byte bits, so it does not show that this defect
caused the earlier voltage discrepancy. Absolute battery accuracy, calibration,
direct charging during sleep and energy savings remain unresolved.
