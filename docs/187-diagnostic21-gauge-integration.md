# Diagnostic.21 gauge-status integration

7 October 2026. NEO-125. Integration, offline verification and checked transfer
to the Mac are complete. Diagnostic.20 remained installed at this build
checkpoint; subsequent diagnostic.21 installation and awake validation are
recorded under NEO-126 in [report 189](189-diagnostic21-installation-and-gauge-validation.md).
No charging/gauge settings, ADC scale or battery calibration policy changes
are included.

## Scope and identity

The source-tested AXP223 B8 volatility correction from
[report 186](186-axp223-gauge-status-candidate.md) is integrated into
`work/power-insertion-wake`. The new image identity is
`0.1.0-diagnostic.21`, with kernel `6.18.54-gameshellneo20`.
The remaining configuration, firmware, userspace policies and supply/USB wake
settings are unchanged. Normal product sleep remains disabled.

The previous diagnostic.20 raw/compressed artifacts and matching metadata were
verified using `task image:checkpoint NAME=diagnostic20-before-gauge-status`
before advancing the identity. They remain available for recovery.

## Inspection contract

Schema 3 of `task device:charge-inspect` accepts only two explicit contracts:

| Image | Kernel | Expected B8 metadata |
| --- | --- | --- |
| diagnostic.20 | `6.18.54-gameshellneo19` | nonvolatile, possibly cached |
| diagnostic.21 | `6.18.54-gameshellneo20` | volatile, hardware register read |

The helper checks the expected pair, installed version/kernel record, running
kernel, CPI/PMIC identity and observed register layout/cache policy. An unknown
pair, cross-paired image/kernel, or wrong B8 volatility rejects before register
access. It retains the same eleven-address read-only allowlist and bounded
seven-byte reads; no cache bypass or charger/gauge write is introduced.

B8 controls/status move from `assessment.cached_configuration` into
`assessment.gauge_control`, carrying the raw byte and the recorded source label.
E0/E1 capacity and other nonvolatile configuration retain their cache limitation.
Fresh B8 does not make them fresh or establish capacity calibration. REG34's
disputed polarity and ADC-byte coherence/accuracy limitations remain explicit.

The awake charging sampler embeds the same helper and therefore emits schema 3
for its nested inventory while retaining its existing outer schema. Historical
captures and their helper hashes remain unchanged.

## Validation

The focused inventory/baseline suite passes 26 tests, including both complete
profile captures, cache-policy mismatch rejection, unknown/cross-paired image
admission, installed-kernel mismatch and separate B8/cached-register provenance.
The first new full-capture fixture incorrectly supplied a backwards mock clock;
it was corrected to advance between checkpoints, retaining the production
continuity guard. No device failure was involved.

Full host checks pass: 13 runtime and 622 tooling tests before build (one
optional user-systemd skip), plus C helpers, Bash syntax and ShellCheck. The
subsequent historical-source compaction tooling raises the tooling count to
626, also passing; it changes no image behavior.

All saved source-regression stages passed, including the variant-specific
gauge test, USB lifecycle/sleep and policy checks, Wi-Fi lifecycle/IRQ/PM cases,
wake ownership, SDIO references and clock ranges. The full kernel completed
with 164 configuration assertions and a 15-file artifact inventory. Device-tree
schemas, compiled board contract, speaker and keypad-retention checks pass.

The completed kernel manifest SHA-256 is
`923b1f01ed2e46e8926fae13351a0c84c6001a97a02c4a545e525e418a170536`.
Patch 0035 SHA-256 is
`99ef36e6a0fa66fc5100e70abc68279ecf6154f10cdeb7d660f6d99d1a6edaa8`.
The linked kernel contains `axp223_volatile_reg`.

The first image stage stopped at Armbian's unchanged 10 GiB free-space gate.
The original `.local/neo125-build.log` preserves that failure. Verified retention
and historical source compaction recovered sufficient space without discarding
recovery or compiler evidence ([report 188](188-historical-driver-source-compaction.md)).
Assembly succeeded through `task build:image`, reusing the completed kernel and
hash-verified base-rootfs cache. Its separate log is
`.local/neo125-image-resume.log`. No source regressions or kernel compilation
were repeated merely because image assembly had stopped for disk space.

## Verified artifacts and transfer

The offline verifier passes MBR bounds, bootloader readback, FAT16/ext4 checks,
U-Boot CRCs/addresses, kernel/DTB/modules/radio hashes, private-identity
permissions and service policy. Its `hardware_qualified` field remains false.

| Artifact | Value |
| --- | --- |
| Raw image | `GameShellNeo-0.1.0-diagnostic.21-cpi31-766436e6428c.img` |
| Raw size | 4,294,967,296 bytes (4 GiB) |
| Raw SHA-256 | `766436e6428c86dcf31003d8f680e6992a6afd217752caa7aca056ff75e3a7a0` |
| Gzip size | 269,669,449 bytes |
| Gzip SHA-256 | `3b7312ab5e21e0aa4745ff086b9767954b6527f34ed7ec34a661062b14573eca` |
| Package inventory SHA-256 | `66dc03283bb690e55ab2b2540b0ffe43310dfb39f872672c4d6b3884ecc3358b` |

Integration commit `ea1edae` contains the image/driver changes. Host compaction
commit `a3ba03e` is described in report 188. The image manifest also records the
project input hashes, source lock and completed kernel inventory.

After the owner confirmed regular Wi-Fi, `task mac:stage` packed and uploaded
the private image. The Mac verified both compressed and fully decompressed
SHA-256 values successfully; `.local/neo125-stage.log` records that result.
This transfer did not write to a card. The private image contains credentials
and firmware and is not a public release artifact.

The matching recovery checkpoint is
`diagnostic21-gauge-status-candidate`, made with `task image:checkpoint`.
Diagnostic.20's earlier checkpoint remains available separately.

At the build checkpoint, hardware checks remained pending. NEO-126 subsequently
qualified startup, owner-confirmed login, fresh B8 inspection and unchanged
reported charger limits (report 189); fresh suspend/resume qualification remains
open. No real calibration transition will be provoked by programming B8 merely
to test its status bit.
