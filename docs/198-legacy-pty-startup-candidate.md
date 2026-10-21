# Legacy PTY allocation and the user-manager startup candidate

7 October 2026, NEO-136. Diagnostic.22 remains installed. The source candidate
is diagnostic.23, kernel `6.18.54-gameshellneo22`. It removes legacy BSD PTY
preallocation, retaining Unix98 PTYs and the existing console support. The
live board has not been rebooted or changed to the candidate during this work.
Subsequent [report 199](199-diagnostic23-installation-and-pty-validation.md)
records its installation and measured awake startup improvement.

## Evidence and mechanism

[Report 197](197-ssh-collection-timing.md) measured repeated 4.7-second first
SSH command-channel openings while awake, and about 3.4 seconds in the user
manager's unit-loading interval. The new inventory shows where much of its
device population comes from:

| Diagnostic.22 inventory | Count |
| --- | ---: |
| User-manager unit records | 588 |
| Device-unit records | 557 |
| Records naming legacy PTY slaves | 512 |
| Legacy PTY slave entries in `/sys/class/tty` | 256 |

There are 256 `/dev/tty[p-za-e][0-9a-f]` devices, with two systemd device units
per slave: one named for the `/dev` path and one for its sysfs path. This is
512 unit records, not 512 physical devices or 512 running services. The kernel
also registers the corresponding legacy master driver. The baseline resolved
configuration enables `CONFIG_LEGACY_PTYS=y` and `CONFIG_LEGACY_PTY_COUNT=256`.

The installed systemd version is `257.13-1~deb13u1`. Its installed
`99-systemd.rules` tags matching alphabetic tty names for systemd, including
these legacy slaves. Upstream's corresponding `device_enumerate()` enumerates
that tag and builds device units, including additional path units. The
`UnitsLoadStart/FinishTimestampMonotonic` interval brackets
`manager_enumerate_perpetual()` and `manager_enumerate()`: it includes loading
units discovered from the kernel, not just parsing service files.
[Device implementation](https://github.com/systemd/systemd/blob/v257.13/src/core/device.c#L916),
[manager startup](https://github.com/systemd/systemd/blob/v257.13/src/core/manager.c#L1922).

In the locked Linux 6.18.54 tree, `drivers/tty/pty.c::legacy_pty_init()` allocates
and registers the legacy drivers when this option is enabled; its disabled
branch is empty. `pty_init()` separately initializes Unix98 PTYs.
`drivers/tty/Kconfig` describes modern `/dev/ptmx` and `/dev/pts/N` terminals
separately from the old fixed names and permits disabling the legacy option.
The upstream [TTY Kconfig](https://github.com/torvalds/linux/blob/v6.18/drivers/tty/Kconfig#L84)
documents the same distinction; the inspected build source is the pinned
6.18.54 archive, not an unpinned branch.

This explains the large legacy-device population and justifies removing its
source. It does **not** yet quantify how much of the 3.4 seconds will disappear.
Other units, disk access, CPU work and network latency remain. The original
untimestamped post-sleep connection failures are still unattributed.

## Baseline task and terminal compatibility

```sh
task device:user-startup LEGACY=enabled
```

Capture: `.local/diagnostics/20261007T091013.050693Z/user-startup.json`.
SHA-256: `68366b1895d5667b711461bd0e01250c207af6e673f23dd91cc6450c9999e4c0`.
The task runs as the ordinary SSH user. Its manager startup is 3.971636 seconds,
including 0.120862 seconds in generators and 3.440275 seconds loading units.
It confirms 256 legacy sysfs slaves and 512 matching device-unit records.
Both directions of data transfer and window-size propagation pass on a new
private Unix98 PTY. An actual SSH terminal request then returns `/dev/pts/N`.
The original boot, PM13/0, brightness 1 and backlight power 0 are preserved
through the on-device inspection. No physical console is used for the PTY test.

The task also supports `LEGACY=disabled` for the candidate and `LEGACY=either`
for inventory. A disabled configuration with remaining legacy slave nodes or
device units fails. Unknown expectations, absent required console/Unix98
support, invalid manager timestamps, failed transfers/resize or failed SSH
terminal allocation are rejected. Opened PTYs and SSH channels are closed on
failure. `ROUTE=usb` is the default; `ROUTE=wifi` uses the configured Wi-Fi path.
The saved result is complete only when both its on-device `passed` field and
the separate `ssh_pty_verified` field are true; a partial capture is not SSH
terminal qualification.

The existing manager can be reused if another session is still active. These
timestamps describe its recorded startup, not the entire inspection duration.
For before/after timing comparisons, allow normal session teardown rather than
restarting logind/user services, then capture fresh SSH sessions separately.

Other private inspection evidence is `.local/neo136-user-dump.txt`,
`neo136-systemd-version.txt`, `neo136-systemd-udev-rules.txt` and
`neo136-tty-drivers.txt`. The repeatable task sends only parsed inventory and
timings back from the manager dump, excluding its environment strings.

A separate ordinary-user `systemctl show user@1000.service -p MainPID
-p MemoryCurrent -p MemoryPeak -p CPUUsageNSec` capture, using `device:exec`,
records 4,317,184 current cgroup memory bytes, 6,860,800 peak bytes and
4,121,870,000 CPU nanoseconds. These describe that particular user-manager
instance, including its group accounting, not whole-device RAM or idle power.
The raw capture is `.local/neo136-user-resources.txt`; repeat the same task
after installation if comparing memory, alongside the more reproducible unit
counts and startup timestamps.

## Candidate implementation

The fragment adds explicit `TTY=y`, `VT=y`, `VT_CONSOLE=y`, `UNIX98_PTYS=y`
and `LEGACY_PTYS=n`. The existing framebuffer and serial-console settings are
retained. This uses the upstream driver's existing configuration boundary;
no new kernel patch or userspace filtering is required. The patch queue,
board DT, firmware and charger/power policies remain unchanged.

Only programs that specifically require the old BSD `/dev/ptyXY`/`ttyXY`
interface lose that interface. The tested diagnostic SSH path uses Unix98.
Future software must use the retained modern terminal API. This candidate does
not turn off PAM, change SSH authentication, keep a user manager alive through
linger, suppress device events or add recovery delays.

The image identity advances to `0.1.0-diagnostic.23`, kernel suffix
`-gameshellneo22`. The read-only charge inventory admits this exact pair with
the same volatile-B8/masked-ADC contract as diagnostic.22, preserving all older
profiles and rejecting mismatched or unknown pairs. Its schema remains 4;
the new identity introduces no measurement-format or charging-control change.

## Build and validation

Before changing the kernel configuration, the saved checkpoint task verified
`diagnostic22-before-legacy-pty-removal`. It retains the previous verified image,
compressed transfer and metadata. `.local/neo136-baseline.config` and
`neo136-baseline-artifacts.json` retain the old resolved configuration and
kernel/object size/hash observations for comparison.

The full host check passes 13 runtime and 651 tool tests (one existing opt-in
skip), both compiled host checks and shell lint. Seven new tests exercise real
Unix98 data/resize behavior, descriptor cleanup on timeout, SSH terminal
requests/failure cleanup, manager-unit parsing and invalid clock/expectation
rejection. The charge-inventory matrix includes all four valid historical and
candidate pairs plus rejected cross-pairs. `.local/neo136-check.log` retains
the full check output.

The full ARM kernel/modules build passes 169 resolved configuration assertions
and the completed 15-file artifact check. Comparing resolved configurations
against diagnostic.22 finds only `LEGACY_PTYS: y → n` and removal of
`LEGACY_PTY_COUNT=256`; the newly explicit console/Unix98 settings were already
enabled. The patch queue is unchanged, so the saved incremental kernel build
reuses its verified patched source/output rather than resetting that tree.
The pinned Docker builder was fetched because it was no longer cached locally.

| Artifact | Diagnostic.22 bytes | Diagnostic.23 bytes |
| --- | ---: | ---: |
| `drivers/tty/pty.o` | 15,048 | 12,252 |
| Compressed `zImage` | 6,581,896 | 6,580,864 |

These are file-size observations, not a measurement of runtime RAM saved.
`.local/neo136-kernel-comparison.json` retains both artifact hashes and the
resolved configuration comparison. Kernel build logs are
`.local/neo136-kernel.log` and `.local/build/kernel.log`.
The compiled PTY object retains `ptm_unix98_ops`/`pty_unix98_ops` and contains no
legacy initializer, count or BSD operation tables. The symbol inventory is
`.local/neo136-pty-symbols.txt`. Device-tree validation and the unchanged PM,
speaker and keypad board contracts pass. The USB board policy suite passes
4,665 gate/state/race cases, 160 lifecycle cases and 96 diagnostic scenarios.
Logs are `.local/neo136-dt.log` and `.local/neo136-usb-board.log`.

Source implementation commit: `c155496`. The saved image build uses the nested
worktree's explicit original bootloader and private radio-reference paths:

```sh
task build:kernel
task check:kernel
task check:dt
task test:usb-policy-board
task build:image \
  BOOTLOADER=/home/mishri/workspace/clockworkpi/GameShell/Code/Kernel/v0.2/u-boot-sunxi-with-spl.bin \
  RADIO_DIR=/home/mishri/workspace/clockworkpi/GameShellNeo/.local/hardware-baseline/2026-09-27/radio-reference
task image:pack
task image:checkpoint NAME=diagnostic23-no-legacy-pty-candidate
```

Offline verification passes MBR bounds, bootloader readback, filesystem checks,
U-Boot CRCs/addresses, kernel/DTB/modules/radio hashes, private identity permissions
and service policy. All 298 recorded project input hashes match this source
checkpoint. The completed kernel manifest SHA-256 is
`474f30de8774406f238e081d8a783da29f6916cde72f5a83c44e13cd0e8267b2`;
the image manifest SHA-256 is
`f82d8dce7b40d0d31c057b0d723c5d97cea2488c6458a1e56c4a3d381506b3d3`.
The package inventory hash remains
`66dc03283bb690e55ab2b2540b0ffe43310dfb39f872672c4d6b3884ecc3358b`,
matching diagnostic.22. Validation targets the configuration/integration change:
host regressions, the complete compiled kernel and resolved configuration,
device-tree contracts, the USB board policy suite and offline image checks.

| Artifact | Value |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.23-cpi31-bf64ca854137.img` |
| Raw bytes | 4,294,967,296 |
| Raw SHA-256 | `bf64ca85413711b991cfaafbe7d8c7dabcf4355fe1bb8590085850f68b13d726` |
| Gzip bytes | 269,588,963 |
| Gzip SHA-256 | `f62aced17fbce378e371f7337533f89d5b3799070fe3072a6c0380f3eed8c404` |

Build/pack logs are `.local/neo136-image.log` and `.local/neo136-pack.log`.
The raw image is under `.local/artifacts/`, and its compressed transfer and
manifest are under `.local/flash/`. They contain private provisioning and must
remain private. The verified candidate checkpoint is
`.local/recovery/diagnostic23-no-legacy-pty-candidate`; the previous diagnostic.22
checkpoint and image remain available.

## Mac staging checkpoint

NEO-137, 7 October 2026, approximately 09:30 UTC. The owner confirmed regular
Wi-Fi, and `task mac:stage` completed successfully. It repacked the verified
source, transferred the 269,588,963-byte private archive to the owner's Mac,
and verified both compressed and full 4 GiB image checksums there. They match
the artifact table above. The saved flash helper and transfer manifest select
diagnostic.23; no card was written and diagnostic.22 remains installed.

Private log: `.local/neo137-stage.log`, SHA-256
`e9fdbf211fab153b45c85c65e3177a91b2c6544cccfccb8f59dcdebc831df6ff`.
Transfer manifest: `.local/flash/transfer.json`, SHA-256
`1211164e23ca7200495dc2f85f0c03f7ad85e117d8dcabd4f9c43996b5e1b681`.
[Report 199](199-diagnostic23-installation-and-pty-validation.md) continues
with the owner's readiness, warning and shutdown. Card inspection, flash/readback
and new-boot qualification follow as separate evidence.

## Installation acceptance and limits

After the next card swap, confirm the normal login screen and both independent
SSH routes. Run `device:user-startup LEGACY=disabled` and fresh
`device:ssh-timing` captures; require zero legacy slave nodes and matching
device units, working ordinary-user Unix98/SSH PTYs, unchanged display and no
PM failure. Compare recorded startup phases and first-session channel times
against reports 197/198 without attributing all network variation to the kernel.
Repeat the normal image integration and staged PM/RTC qualification on the new
boot when an observer is available. Retain the original results independently.

Image building does not consume the installed diagnostic.22 sleep continuation.
However, this checkout's lock now selects diagnostic.23: do not use its new
qualification commands to admit the old image. Existing report 196 evidence
remains historical evidence, not a substitute for qualification of the new boot.

No faster-boot, lower-memory, wake-latency or battery-life result is established
until measured on the installed candidate. The first opportunity being removed
is unnecessary device allocation and manager bookkeeping; CPU retention,
standby energy and the original intermittent SSH failures remain separate work.
