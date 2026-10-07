# Legacy PTY allocation and the user-manager startup candidate

7 October 2026, NEO-136. Diagnostic.22 remains installed. The source candidate
is diagnostic.23, kernel `6.18.54-gameshellneo22`. It removes legacy BSD PTY
preallocation, retaining Unix98 PTYs and the existing console support. The
live board has not been rebooted or changed to the candidate during this work.

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

The existing manager can be reused if another session is still active. These
timestamps describe its recorded startup, not the entire inspection duration.
For before/after timing comparisons, allow normal session teardown rather than
restarting logind/user services, then capture fresh SSH sessions separately.

Other private inspection evidence is `.local/neo136-user-dump.txt`,
`neo136-systemd-version.txt`, `neo136-systemd-udev-rules.txt` and
`neo136-tty-drivers.txt`. The repeatable task sends only parsed inventory and
timings back from the manager dump, excluding its environment strings.

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
Image build results will be recorded after verification finishes.

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
