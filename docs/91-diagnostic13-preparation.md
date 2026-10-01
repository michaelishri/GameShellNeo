# Diagnostic.13 preparation (NEO-70)

1 October 2026, Pacific/Auckland. This prepares a CPI v3.1 image containing
[patch 0018](89-wifi-worker-error-handling.md). Diagnostic.12 remains installed;
its supervised PM, physical-input and USB results are in
[report 87](87-diagnostic12-pm-validation.md) and
[report 90](90-diagnostic12-input-usb-validation.md).

The complete kernel/image build and offline verification passed. The 270 MB
archive is staged on the Mac with both compressed and decompressed hashes
verified. Diagnostic.12 remains installed; no candidate
hardware qualification is claimed.

Subsequent installation and baseline results are in
[report 93](93-diagnostic13-installation.md).

## Change being qualified

Image `0.1.0-diagnostic.13` uses kernel `6.18.54-gameshellneo13`. Patch 0018
checks packet-worker wake/clock/status failures, preserves the first error,
stops further radio traffic and completes waiting commands. IRQ shutdown
occurs from process context, and OOB rearm ownership is checked under its
lock. A successful asynchronous clock wait remains distinct from a failed
access, with pending work retained for the next notification.

**A fatal checked worker error requires a cold restart**, even if the
underlying transport fault was transient. Automatic reset/reprobe recovery,
deeper packet/mailbox helper failures and a missing clock-ready notification
remain follow-ups. This patch does not establish NEO-55's cause or solution.

The locked Linux source, toolchain, Debian snapshots, bootloader, firmware,
NVRAM and board wiring are unchanged. Stock USB detection, keypad supply
retention and speaker cues remain selected. Normal sleep is still disabled;
a short power press still shuts down. The agreed short/2-second/8-second
gesture policy and delayed audio confirmations are separate work.

## Recovery and saved preparation

The checkpoint was saved before changing the image identity; the kernel
reset followed the identity update:

```sh
task image:checkpoint NAME=diagnostic12-before-wifi-worker-errors
task kernel:reset
```

The checkpoint verifies and references the retained private files:

- Image: `GameShellNeo-0.1.0-diagnostic.12-cpi31-b7c0ac5fe2a8.img`.
- Raw SHA-256: `b7c0ac5fe2a8836ead3daba2a6b063fc7b002c30a051d45d26a17f00d14c61a2`.
- Gzip SHA-256: `a43abe69bad1c78ea3ae25c5d6a6d301814b48b3f92fcf89de33ce241e26f9eb`.

Metadata is in `.local/recovery/diagnostic12-before-wifi-worker-errors/`.
The preceding source, output, modules and completed kernel record are archived
at `.local/previous-kernels/20261001T092732Z-596127/`. Previous recovery
checkpoints and the original card backup remain retained. Selecting recovery
later uses its own matching manifests:

```sh
task mac:stage-recovery NAME=diagnostic12-before-wifi-worker-errors
```

Add `UPLOAD=1` only if that archive is missing on the Mac and a large transfer
is appropriate. Recovery selection does not write a card. Fresh card
inspection remains mandatory before any flash.

The build disk initially had about 4.8 GiB free. NEO-71 added and tested the
saved `build:prune-driver-scratch` task; preview and explicit application to
`brcmfmac-pm-tests` and `brcmfmac-irq-worker-tests` removed seven superseded
compiler trees and freed about 11.7 GiB. It retained the current normal/debug
builds, parent evidence/logs, recovery/images/downloads and archived full
kernels. Incremental private cleanup records are:

- `.local/build/brcmfmac-pm-tests/prune-20261001T093052.945409Z.json`.
- `.local/build/brcmfmac-irq-worker-tests/prune-20261001T093119.796953Z.json`.

With the release identity advanced and private `.env` provisioning refreshed:

```sh
task provision
task check
task build
```

The host check passed 13 runtime and 283 tool regressions (one optional skip),
the compiled helpers and Bash/ShellCheck. Seven new cleanup tests exercise
preview/application, retained evidence/private paths, busy locking, missing or
escaping evidence, unexpected files, symlinks and unsupported suites.
Host logs are `.local/neo70-*.log`; per-stage logs remain in `.local/build/`.

## Source verification

The full build's saved regressions passed for clock searches, AXP USB
lifetime/suspend, USB PHY suspend, power-supply notifications, MUSB context
and USB policy. Wi-Fi source suites passed on native and ARM32 targets:

| Suite | Passing candidate scenarios |
| --- | --- |
| Sleep/clock helpers | 95 |
| Worker freezing | 44, plus PM-disabled coverage |
| PM rollback and control requests | 89 |
| PM/reset/removal/IRQ lifecycle | 102 |
| Diagnostic.12 interrupt-service baseline | 23, including four old error characterizations |
| Patch 0018 worker errors | 49 normal / 51 DEBUG |
| Patch 0018 lifecycle and waiting commands | 105 |

These suites overlap; the totals are not independent additional coverage.
Their negative controls passed, including 31 worker and 13 worker-lifecycle
mutations rejected by assertions. The new candidate turns the old baseline's
four error characterizations into checked failure behavior. Native/ARM32
shims do not establish physical error recovery, electrical behavior, real
kernel scheduling or energy savings. Report 89 retains the separate full
normal/DEBUG ARM driver compilation from source qualification; this image's
normal configuration is compiled again as part of the complete kernel.

The resolved configuration is byte-identical to the diagnostic.12 checkpoint:
SHA-256 `d370205bf2e4eed5e35483f15372a6785e7d96252d40c343dfee0b2dde37a017`.
All seventeen preceding patch hashes match the checkpoint. The sole addition
is `0018-brcmfmac-worker-errors.patch`, SHA-256
`b5a4905a63cdfcce17c6157e2f78b49885e1dce758e3717811e63864058e6d18`.

## Complete kernel and image verification

`task check:kernel` passed 164 configuration assertions and all 15 recorded
artifact checks. All ten modules' embedded `vermagic` values identify
`6.18.54-gameshellneo13`. The complete kernel build emitted no compiler warnings
or errors. Evidence: `.local/neo70-kernel-check.log`,
`.local/neo70-artifact-inspection.json` and `.local/build/kernel.log`.

The base and keypad-retention device trees passed binding validation. Compiled
USB policy, PM retention, speaker routing/PL3/supply and keypad-supply checks
passed, including negative controls. Evidence: `.local/build/devicetree.log`
and `.local/build/usb-policy-board.log`.

The 4 GiB image passed MBR boundaries, bootloader readback, FAT16/ext4 filesystem
checks, U-Boot CRCs/addresses, kernel/DTB/module and radio hashes, private identity
permissions and service policy. Its package inventory is byte-identical to
diagnostic.12. The fresh rootfs bootstrap used the existing locked Debian
snapshots. Evidence: `.local/build/image-verify.log`,
`.local/artifacts/verification.json` and `.local/neo70-artifact-inspection.json`.

## Prepared artifact and Mac staging

| Artifact | Identity |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.13-cpi31-a3d09a49e27a.img` |
| Raw bytes | `4294967296` (4 GiB) |
| Raw SHA-256 | `a3d09a49e27a48c1e51ac893aa16f899955eb4f3510ac00bf3ce2f03a65cd198` |
| Gzip bytes | `269762188` (about 270 MB) |
| Gzip SHA-256 | `3fe4184b4e5d5c77797edfa1e70346d38c4c4736ce0dc4cdfde974d708a9591b` |

`task mac:stage` packed the verified image, uploaded it over the owner's
confirmed regular Wi-Fi connection and passed compressed/decompressed checksum
verification on the Mac. Evidence: `.local/neo70-mac-stage.log` and
`.local/flash/transfer.json`. No card has been written for diagnostic.13.

## Installation sequence after offline verification

The owner confirmed the Mac is on regular Wi-Fi for the transfer. Staging
used `task mac:stage` and verified compressed and decompressed hashes.
No GameShell command, card write or PM test is part of this preparation.

1. With the image ready on the Mac, request shutdown and movement of the
   Samsung DEV card into the reader. Run fresh `mac:status`, `mac:inspect`,
   `mac:preflight`, then `mac:flash` with full readback and safe ejection.
2. Await the owner's normal login confirmation after reinsertion. Verify
   image/kernel identity, both SSH routes, integration and PM/keypad/audio
   baselines before running a stage.
3. Prepare and describe the whole guided session before requesting readiness.
   Run the saved freezer check, then an owner-observed single traced `devices`
   cycle. Check both routes, original input handle, error counters, firmware
   identity and restoration before continuing.
4. With the owner still attending the described session and the first stage
   passing, run four traced driver cycles, then the speaker-assisted physical
   input and four USB reconnect checks. Prepare each recorder before giving
   physical instructions. Consolidate visual/audio confirmation where valid;
   missing observations remain unqualified. A session interruption requires
   readiness again, and an unexpected result stops the sequence.

Keep the existing time/error gates. Stop after failure and collect the same
persistent run rather than resubmitting a PM stage. A failed radio restore
requires cold restart under the current policy; diagnostic.12 is the recovery
checkpoint if the candidate regresses. These checks do not qualify real
sleep, power-button wake, error injection, energy savings or full radio
recovery. Any intentional fault experiment needs a separately justified plan
with independent USB access.

The owner reconfirmed that the agreed low-level foundation and optimization
work should precede UI development, with one sequential workstream. An early
UI-development handoff was discussed but not selected. The next tooling
priority is reducing manual handoffs through bounded unattended qualification
and prepared guided sessions; candidate module/boot-set deployment and recovery
remain investigations, not capabilities delivered by this image.
