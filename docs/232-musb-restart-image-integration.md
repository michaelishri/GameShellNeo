# Diagnostic.25: MUSB deferred restart integration

9 October 2026. NEO-170, under NEO-108. Branch:
`work/musb-restart-integration`, based on reviewed source `2d40f6f`.

## Purpose

This image integrates the endpoint-owned USB restart correction reviewed in
[report 225](225-musb-resume-request-ownership.md). A transfer request can finish
or be cancelled before deferred controller resume runs. The old callback kept
that request's address; the corrected callback owns the endpoint and selects
its current queue head while holding the controller lock. It also preserves
progress when resume overlaps a completion callback, including callbacks that
queue another request.

The identity is **0.1.0-diagnostic.25 / 6.18.54-gameshellneo24**. Linux remains
pinned to 6.18.54. Relative to diagnostic.24, the production driver addition is
`0037-musb-resume-request-ownership.patch`, SHA-256
`1f43648b48c14bd29a6aff68bdeb26077bf8d4888f174afb2b24fbf3396e8137`.
The reviewed patch is unchanged. The new image and kernel version distinguish
the candidate and bind its future qualification evidence to this build.

The extra runtime-PM reference exists only during an overlapping completion
handoff and is released after restart or endpoint cancellation. Pending entries
are removed before invoking their callbacks, and callbacks run without the
pending-list lock. The first callback error is preserved while the remaining
work drains. These are ownership and progress fixes; source tests do not prove
a particular observed CPI failure was caused by these paths.

The incomplete NEO-106 controller-removal stack is excluded. Failed-queue DMA
mapping, general dequeue progress outside an owned restart, complete producer
retirement and other backend contracts remain separate follow-ups. This image
retains diagnostic.24's WFI/s2idle, keypad, speaker, battery, cable-wake and
diagnostic power-key policies. It does not enable the future product power menu
or establish improved battery life or faster recovery.

## Preparation and retained recovery

The owner returned home and requested resumption of physical testing. Before
any image change, matching diagnostic.24 tools reached the Mac and GameShell
over USB and Wi-Fi. The device reported kernel `6.18.54-gameshellneo23`, boot
`a73c7c3c-5ed4-473d-85c4-8d71f4a89bc2`, configured high-speed USB and no failed
services. The initial software battery sample reported 68% and Charging; it is
not a calibrated capacity measurement.

Private captures in `work/cpi-wfi-integration` are
`20261009T050429.134191Z` (USB), `20261009T050537.806386Z` (Wi-Fi) and
`20261009T050625.803558Z` (read-only PM inspection). No sleep, screen blanking,
reboot or cable operation was performed for these checks.

The new worktree has independent kernel output, source, Armbian cache and image
storage. It copies the prior kernel outputs for incremental compilation, applies
the complete queue to a fresh locked-source extraction and records the newly
completed kernel. Existing downloads are shared and checksum-verified. The
copied base-rootfs archive must pass the saved provenance and checksum check;
kernel and image version fields are its documented exclusions. No completed
kernel receipt is copied as proof of the new build.

The root `.env` remains the credentials source. Private device identity is
preserved, and `task provision` refreshes Wi-Fi data without changing that
identity. The generated Wi-Fi configuration matches the diagnostic.24 workspace.
No secrets or private provisioning are committed.

Diagnostic.24's original raw image, compressed archive, matching tools and
`diagnostic24-wfi-s2idle` checkpoint remain in `work/cpi-wfi-integration`.
Its image SHA-256 is
`11fb47777b6273667b4702845ffc3f2b4f223d1b63acfea82b86017cee4012c9`.
The existing recovery resolver reverified its metadata, raw image and compressed
archive before installation work; the result is saved as
`.local/resume-neo108-recovery-check.log` in the diagnostic.24 worktree.

## Saved workflow and validation

Use the repository tasks from this worktree, with a private workspace temporary
directory (`TMPDIR="$PWD/.local/host-tmp"`) rather than the constrained host
`/tmp`:

```sh
task provision
task check
task build:kernel
task test:usb-policy-board
task check:dt
task build:image \
  BOOTLOADER=/home/mishri/workspace/clockworkpi/GameShell/Code/Kernel/v0.2/u-boot-sunxi-with-spl.bin \
  RADIO_DIR=/home/mishri/workspace/clockworkpi/GameShellNeo/.local/hardware-baseline/2026-09-27/radio-reference
task image:pack
task image:checkpoint NAME=diagnostic25-musb-restart
```

Report 225 retains the reviewed patch's 48 request scenarios per execution,
seven real Linux UML KUnit cases, sleep/callback regressions and six ARM compile
configurations. Those unchanged-source receipts are prior evidence, not new
runs in this integration worktree.

Fresh host validation passes 16 runtime and 814 tooling tests, with one optional
skip, plus current-selector/mount-guard regressions and Bash/ShellCheck. The
initial sandboxed run could not send on the existing local SSH fixture sockets;
the complete normal host run passed. This did not reopen the abandoned live
SSH-stall investigation. The saved kernel task passes all 177 configuration
assertions and records release `6.18.54-gameshellneo24` with the exact reviewed
patch hash. Its compiler log contains no warning or error diagnostics.

The compiled-board USB-policy checks pass natively and on ARM32: 4,665
gate/state/race cases, 160 probe/unwind cases and 96 diagnostic cases in each
execution, with accepted peripheral wiring and rejected DT mutations. Device-tree
schema validation emits no diagnostics. The PM, speaker and keypad-retention
board checks and their negative controls also pass.

The base-rootfs archive SHA-256 is
`5fd103e68cdbed979f86384a41f50f6c9652500bc8efb4fc450bfbdf5c4d60bd`;
the saved image workflow admits it only after checking the copied ledger's
input identities and archive contents.

Preparation attempted while the kernel build owned the workflow lock was
correctly rejected; the image workflow prepares its inputs after that build.
The cache copy excludes temporary APT locks/partial downloads and Python bytecode;
the copied rootfs archive is separately verified before reuse.

## Verified image

The saved image workflow completed and passed offline verification: MBR and
partition boundaries, bootloader readback, FAT16/ext4 filesystem checks, U-Boot
CRCs/load addresses, kernel/DTB/module/radio hashes, private identity permissions
and service policies. The manifest retains `hardware_qualified=false`.

| Artifact | Identity |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.25-cpi31-c88d158d446b.img` |
| Image bytes | 4,294,967,296 |
| Image SHA-256 | `c88d158d446b6ed14617b815ec17bfd2b3e90fee858ddd30e008ed74640aeb77` |
| Kernel | `6.18.54-gameshellneo24` |
| Compressed kernel bytes | 6,581,752 |
| Image manifest SHA-256 | `d45bcea1e79e9d2518c9e8632642183eb06387a0868cce75e78838f50fd0faf9` |
| Gzip archive bytes | 269,523,036 |
| Gzip SHA-256 | `bba945400469d85238bbc11b2444668faf196b67e94cdafbe7f814ad11a58329` |
| Recovery checkpoint | `.local/recovery/diagnostic25-musb-restart` |

All 344 project-input hashes in the image manifest match this worktree.
The image and matching manifests are private under `.local/artifacts/`; the
compressed archive and transfer manifest are under `.local/flash/`. The saved
checkpoint task reverified the raw and compressed hashes and their metadata.
It preserves metadata referencing those artifacts rather than another 4 GiB copy.
Original stage logs are `.local/build/{kernel,usb-policy-board,devicetree,
prepare,image,image-verify}.log`; the full host check is
`.local/diagnostic25-check-full.log`. Compression/checkpoint receipts are
`.local/diagnostic25-pack.log` and `.local/diagnostic25-checkpoint.log`.
Transfer awaits confirmation that the Mac is on regular Wi-Fi. No card has been
written and no new-image hardware test has run.

## Attended qualification

After offline verification and transfer on confirmed regular Wi-Fi, obtain fresh
card-swap readiness, play the long speaker warning, shut down using the matching
installed-image tools and freshly identify the Samsung DEV card in the Mac.
Use the saved guarded flash with complete 4 GiB readback and safe ejection.

After owner-confirmed boot, use this worktree's tools for identity, services,
USB/Wi-Fi routes, journal continuity, power-key ownership, battery, all-CPU WFI
inventory and awake RTC checks. Obtain fresh readiness before staged freezer,
driver and late/noirq tests and before actual RTC sleep. Play long warnings before
dark intervals, inspect every result, stop on failure and retain original evidence.
Then qualify repeated connected sleep and USB reconnect behavior, with separate
battery/cable profiles as needed. Old source-bound qualification receipts do not
authorize new-image sleep tests. No hardware reliability, energy saving or
week-long standby claim follows from build or host tests alone.
