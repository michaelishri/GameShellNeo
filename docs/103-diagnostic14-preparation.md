# Diagnostic.14 preparation (NEO-80)

3 October 2026, Pacific/Auckland (work began 2 October). The complete build,
offline verification and Mac staging passed. The owner’s board remains on
diagnostic.13; no card write, late/noirq test or actual sleep occurred here.

## Candidate and scope

Image `0.1.0-diagnostic.14`, kernel `6.18.54-gameshellneo14`, contains the
checked regmap/PEK/RTC/AC wake-reference patch from
[report 100](100-wake-irq-error-ownership.md), and the persistent-journal policy
from [report 97](97-journal-loss-investigation.md). The accompanying repository
tools provide [diagnostic power-key ownership](101-diagnostic-power-key-ownership.md)
and [RTC/late-noirq qualification](102-rtc-and-platform-diagnostic-preparation.md).
Those tools are uploaded by their saved tasks; this is not a product power-menu
or normal-sleep implementation.

Normal sleep remains masked. The owner's short-press sleep/wake, two-second
power options and eight-second forced-off policy remains the product contract;
rewriting driver handling or emitted events is authorized where needed. The
current ordinary diagnostic short-press shutdown remains until its replacement
is qualified. Actual sleep, independent gesture ownership under forced process
termination, physical wake delivery, latency and energy remain open.

## Recovery and repeatable build

The verified diagnostic.13 recovery checkpoint was created before advancing
the source lock:

```sh
task image:checkpoint NAME=diagnostic13-before-wake-preparation
# Advance image/kernel identity in build/sources.lock.json.
task kernel:reset
task provision
task check
task build
task mac:stage
```

Checkpoint metadata is `.local/recovery/diagnostic13-before-wake-preparation/`.
Its retained image is
`GameShellNeo-0.1.0-diagnostic.13-cpi31-a3d09a49e27a.img`, with raw SHA-256
`a3d09a49e27a48c1e51ac893aa16f899955eb4f3510ac00bf3ce2f03a65cd198`.
The old source, object output and kernel provenance are archived under
`.local/previous-kernels/20261002T101534Z-750620/`. Existing recovery artifacts
and the original card backup remain retained. Diagnostic.13's retained image
predates the journal correction applied live; recovery to it still needs the
saved `device:journal-policy` task.

This was a fresh complete kernel build with the pinned builder and unchanged
single-job setting. No previous object tree was copied into it. Private logs
are `.local/neo80-*.log`, with detailed per-stage output under `.local/build/`.
Provisioning used the existing `.env` and private identity files.

## Verification

- The saved build regressions passed for clocks, USB lifetime/suspend/polling,
  PHY work, freezable supply notifications, MUSB context, all existing radio
  failure/lifecycle suites and the new wake-IRQ tests.
- The complete kernel, ten modules and board DTB compiled successfully. All
  ten module vermagic strings identify `6.18.54-gameshellneo14`.
- Device-tree schemas, compiled USB policy, SDIO retention, speaker routing
  and retained keypad-supply checks passed, including their negative controls.
- The final host check passed 13 runtime tests and 346 tooling tests (one
  existing optional skip), compiled helpers, Bash syntax and ShellCheck.
- The 4 GiB image passed partition boundaries, bootloader readback, FAT16/ext4
  checks, U-Boot CRC/address checks, kernel/DTB/module/radio hashes, private
  identity permissions and service policy. The verifier checked both journal
  policy files against the tracked runtime source.

The resolved kernel configuration is byte-identical to diagnostic.13, SHA-256
`d370205bf2e4eed5e35483f15372a6785e7d96252d40c343dfee0b2dde37a017`.
The package inventory is also byte-identical, SHA-256
`66dc03283bb690e55ab2b2540b0ffe43310dfb39f872672c4d6b3884ecc3358b`.
All eighteen preceding patch hashes match the recovery checkpoint; the sole
new patch is `0019-wake-irq-error-ownership.patch`, SHA-256
`e3cd7c021bb14369fcf6c3d415c84dd96bd37c27a5449583e27180c1d9d03cf3`.
All 215 recorded project inputs matched the source files after image assembly.

Evidence: `.local/neo80-artifact-inspection.json`,
`.local/artifacts/verification.json`, `.local/build/image-verify.log`,
`.local/build/kernel.log`, `.local/build/devicetree.log` and
`.local/neo80-host-check.log`. These checks qualify the artifact offline;
they do not qualify the new kernel on hardware.

## Staged artifact

| Item | Value |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.14-cpi31-3d42271705eb.img` |
| Raw bytes | `4294967296` (4 GiB) |
| Raw SHA-256 | `3d42271705ebf21c74048655fd19145f94442acb585000b0e8985e9e6f3e7f6b` |
| Gzip bytes | `269700440` (about 270 MB) |
| Gzip SHA-256 | `3610b8bcfa758961107d5b1a8729b5b5726533f8c4756ca531beaebc1b9d496f` |

`task mac:stage` uploaded the private archive to the Mac and verified both its
compressed hash and decompressed image hash. No SD card was written. Evidence:
`.local/neo80-mac-stage.log` and `.local/flash/transfer.json`.

## Next attended session

Follow [report 102's sequence](102-rtc-and-platform-diagnostic-preparation.md#prepared-attended-sequence):
fresh card identification, flash/full readback/eject, owner-confirmed login,
new image/journal/network preflight, awake power-key/RTC checks, and observed
ordinary PM before the first single platform debug cycle. Preserve the complete
trace and failed evidence; inspect late/noirq callback order and both management
routes before planning repeats. Same-boot RTC qualification deliberately
prevents the earlier diagnostic.13 results from admitting the new boundary.
