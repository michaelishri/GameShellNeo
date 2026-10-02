# SDIO interrupt runtime-reference ownership (NEO-92)

3 October 2026, Pacific/Auckland. The source audit explains a reachable
reference leak matching [report 116's](116-bounded-power-key-pm-release.md)
seven-cycle hardware trend. Patch 0023 and its source/ARM checks are complete.
Diagnostic.17 builds, passes offline verification and is staged on the Mac
with compressed/decompressed checksums verified. Installation and hardware
comparison remain pending. No new board
PM cycle, runtime-PM setting or power-key policy
change was performed during this work.

## Cause and ownership

Diagnostic.16's saved `1c10000.mmc` runtime-usage counter advances from 2 to 9,
one reference per devices/platform debug cycle on one boot. The last value
persists in a later inspection. This is the Wi-Fi host, not the root-filesystem
SD host. brcmfmac's deliberate runtime-PM forbid and the RSB dependency are separate
owners and constraints; changing either would not repair this accounting.

A later evidence-only `task device:pm-inspect` capture at
`20261002T221147.344063Z` still records usage 9, active/forbidden policy and
the same boot, with eight PM successes and zero failures. Its monotonic time
is 13586.045129266 seconds, about 44 minutes after the last PM return. No new
suspend was submitted. This confirms persistence in that awake snapshot;
it is not continuous observation of every intermediate reference change.

In locked Linux 6.18.54, the threaded SDIO path is:

1. `sdio_irq_thread()` enables the host's interrupt before waiting. Sunxi
   records `sdio_imask=SDXC_SDIO_INTERRUPT` and takes a runtime reference.
2. A real host interrupt calls `mmc_signal_sdio_irq()`, disabling the SDIO
   interrupt and waking the thread. The next enable normally balances that
   disable. Request completion and initialization preserve the cached mask.
3. `mmc_sdio_suspend()` marks the retained-power card suspended and drains its
   work item. It does not stop the interrupt thread or unconditionally disable
   an already-enabled interrupt.
4. Successful `mmc_sdio_resume()` clears the suspended flag and wakes that
   thread when IRQs remain registered. This wake does not require an intervening
   hardware interrupt/disable.
5. The thread services pending work and calls enable again. The old Sunxi
   callback increments the reference counter even when the cached state is
   already enabled. One later disable cannot balance both enables.

Thus a resume rearm is a state request, not a new independent reference owner.
The actual-source regression below reproduces one surviving excess reference
after a modeled retained-power resume and final thread exit. This explains a
source defect consistent with the board trend; board confirmation of the
candidate remains required.

The reverse case also matters: the thread's final disable can follow an IRQ's
earlier disable, including an aborted host claim during teardown. The old
callback drops a reference even when its own state is already disabled. Locked
`pm_runtime_put_noidle()` uses `atomic_add_unless(..., -1, 0)`: it does not go
negative at zero, but it can consume a positive reference belonging to another
owner. This finding does not attribute the older firmware-recovery underflow
or NEO-55's delayed authentication.

## Driver change

[Patch 0023](../kernel/patches/0023-sunxi-mmc-sdio-reference-ownership.patch)
uses the existing `sdio_imask` state under `host->lock`:

| Previous state | Request | SDIO reference change |
| --- | --- | ---: |
| Disabled | Enable | +1 |
| Enabled | Enable | 0 |
| Enabled | Disable | −1 |
| Disabled | Disable | 0 |

The callback still reads and writes IMASK on every request. A repeated enable
can restore the hardware bit after register loss; skipping the whole callback
would be incorrect. Unrelated command/error interrupt bits remain intact.
The get happens before register access, and the put follows hardware masking.
Both non-sleeping operations and the cached-state change are serialized by the
existing IRQ spinlock. No extra persistent state, work item, retry or delay is
introduced. Both operations use `host->dev`, the same parent device assigned
when the host is allocated.

The pinned runtime-PM helpers are atomic counter operations and neither calls
a driver callback nor starts a synchronous suspend/resume. Their use within
this spinlock therefore does not add a sleeping operation. The upstream
[runtime-PM API documentation](https://docs.kernel.org/power/runtime_pm.html)
also distinguishes reference-only operations from helpers that resume a device.
The [upstream Sunxi file retrieved during this audit](https://raw.githubusercontent.com/torvalds/linux/master/drivers/mmc/host/sunxi-mmc.c)
still contains unconditional accounting; this file comparison is not an
exhaustive search of proposed or queued fixes.

The driver initializes cached state with its zeroed host allocation. The only
assignments to `sdio_imask` in the pinned driver are this callback's enable and
disable branches. Hardware initialization restores the mask without taking
another reference. Full host removal first removes SDIO functions and their
IRQ registrations; the core's last-user release stops the thread (or directly
disables the no-thread host). Probe before IRQ registration owns no SDIO IRQ
reference. Failed card reinitialization or bus-width restoration returns
without the successful-resume thread wake. These paths were inspected; the
test scope below distinguishes executed functions from complete kernel lifetime
qualification.

The fix leaves brcmfmac's intentional forbid, card power retention, IRQ
delivery policy, system-PM callbacks and RSB links unchanged. It prevents new
accounting drift after boot; it does not reset accumulated counts in the
already-running old kernel. No claim of lower idle power, sleep current or
wake latency follows from correcting the counter alone.

## Reproducible source validation

```sh
task test:sunxi-sdio-refs
task check:sunxi-sdio-driver
task check
```

[The checker](../tools/check-sunxi-sdio-refs.py) verifies the locked archive,
applies patch 0023 to isolated source, and extracts the actual Sunxi enable
callback plus MMC IRQ signal, interrupt thread, card IRQ acquisition/release
and card suspend/resume functions. [The C harness](../kernel/tests/sunxi_sdio_refs_test.c)
supplies deterministic MMIO, counter, scheduler and lock shims.

**2,058 scenarios pass natively and under ARM32/QEMU**:

- All 256 eight-request enable/disable histories, from both initial states,
  with zero through three independent baseline references: 2,048 cases.
- Actual core-thread flows containing interrupts, retained-power resumes,
  spurious wakes, pending-work errors, normal exit and aborted claims.
- Register-loss rearming; both failed card-resume branches; threaded/no-thread
  multiple-user release; thread-creation failure; and resume without an IRQ
  registration.

The original code separately reproduces the resume leak and a disabled-state
put consuming a foreign reference. Eight negative controls fail assertions:
the original callback, repeated get, repeated put, missing get, missing put,
lost unrelated mask bits, skipped duplicate rearm, and put outside the lock.
The shims check reference ownership at the hardware-unmask point and require
masking before put. They model the pinned saturating put semantics.

The complete ARM `sunxi-mmc.o`, `sdio.o` and `sdio_irq.o` compile with the full
project patch queue in isolated scratch. The host suite passes 13 runtime and
399 tooling tests (one existing optional skip), compiled helper regressions and
shell lint.

Evidence is `.local/build/sunxi-sdio-ref-tests/compile-evidence.json`,
`.local/build/sunxi-sdio-driver.log`, `.local/neo92-host-check.log` and the saved
build regression log.
These are actual-function tests with modeled APIs, not running-kernel
concurrency, complete removal/unbind qualification, physical-register testing
or a replacement for the attended PM comparison.

## Diagnostic.17 preparation

The source lock advances only image version to `0.1.0-diagnostic.17` and
kernel localversion to `-gameshellneo17`. The kernel configuration, firmware,
charging policy and rootfs package choices remain unchanged. The new patch is
included automatically in the exported queue, and its regression task is now
part of `task build`.

```sh
task image:checkpoint NAME=diagnostic16-before-sdio-reference-fix
# Advance only image version and kernel localversion in the source lock.
task kernel:reset
task provision
task build
# After offline verification, on the previously accepted regular-Wi-Fi Mac:
task mac:stage
```

The recovery checkpoint verifies and retains diagnostic.16's image, compressed
archive and matching provenance under
`.local/recovery/diagnostic16-before-sdio-reference-fix/`. Its raw hash is
`de531424ec88e55cbc991e757e295e49658a8991fb0058c5380bc969814d90c7`.
The previous source/output/install trees are preserved under
`.local/previous-kernels/20261002T215824Z-1026953/`. The build transcript is
`.local/neo92-build.log`; each saved task also writes its normal per-stage log.
Private provisioning comes from `.env` without copying credentials into this
report.

The full saved build regression sequence, complete kernel/modules, compiled
board checks and DT schemas pass. The completed kernel record checks fifteen
files. Kernel compilation reports no warnings or errors. The resolved config
is byte-identical to diagnostic.16, SHA-256
`d370205bf2e4eed5e35483f15372a6785e7d96252d40c343dfee0b2dde37a017`.
All 22 previous patch hashes match the checkpoint; the sole addition is
patch 0023, SHA-256
`52f4e3d8b966f8f69718340697606e30d174033d998be84f98b42bc2c97e92ee`.
The lock differs only in the two version fields. Evidence:
`.local/neo92-kernel-config-comparison.json` and `.local/build/kernel.log`.

The conservative rootfs cache identity requires a new base after that version
change. Its resulting package inventory still matches diagnostic.16 exactly,
SHA-256 `66dc03283bb690e55ab2b2540b0ffe43310dfb39f872672c4d6b3884ecc3358b`.
All **238** recorded project-input hashes match the working files. The 4 GiB
image passes the saved bootloader/partition/filesystem/kernel/DTB/module/radio,
private identity and service-policy checks. Evidence:
`.local/neo92-artifact-comparison.json`, `.local/artifacts/verification.json`
and `.local/build/image-verify.log`. It is not yet hardware-qualified.

| Artifact | Value |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.17-cpi31-7923af46c3e5.img` |
| Raw bytes | `4294967296` (4 GiB) |
| Raw SHA-256 | `7923af46c3e58bc85030adb2702bba9b822f61f25d03ed8573702040f7a31048` |
| Gzip bytes | `269856767` (about 270 MB) |
| Gzip SHA-256 | `c2e7d3af1cac087bc88955058270fdeaf5448c47563f5f7ff6c19c2b76ab26c0` |

`task mac:stage` completed over the established Mac connection and verified
both compressed and full decompressed hashes there. The transfer record is
`.local/flash/transfer.json`; transcript `.local/neo92-mac-stage.log`.
No card was written as part of preparation. Diagnostic.16 and its verified
recovery remain available until the attended installation/comparison.

After staging, the saved `build:prune-retained KEEP=3` preview and
`build:prune-retained KEEP=3 APPLY=1` cleanup verified recovery before removing
the redundant diagnostic.14 raw image and one old kernel snapshot (about
2.73 GiB allocated). Raw diagnostic.15/16/17, the three newest kernel snapshots,
compressed recovery archives and original-card backup remain. Final free space
was about 52.1 GiB. Evidence:
`.local/retention/prune-20261002T224536.713160Z.json` and
`.local/neo92-retention-{preview,apply}.log`.

## Hardware acceptance still required

After image verification and staging, arrange one guided card swap and verify
the new kernel and patch identity, startup/integration, journal continuity,
idle audio and both USB/Wi-Fi routes. Repeat the saved awake ownership and RTC
checks on this boot before using the established attended freezer/devices/
late-noirq sequence. Normal sleep stays disabled throughout.

For each accepted cycle, preserve both snapshots and review
`rsb_links["consumer:platform:1c10000.mmc"].consumer.power.runtime_usage`,
along with runtime policy, boot identity and the existing PM health gates.
Compare one driver and five late/noirq cycles with diagnostic.16's saved
2→3→4→5→6→7→8 progression. Check the final value in a later evidence-only
`task device:pm-inspect` capture. A growing count is a failure requiring review,
even if the older general PM checker says the cycle passed. Preserve every
failed/rejected capture; do not repeat until the original evidence is reviewed.

The saved offline comparison accepts explicit `result.json` files from one
boot; use each boot separately when comparing old and new images:

```sh
task check:sdio-ref-history -- path/to/cycle-1/result.json path/to/another/result.json
# Candidate acceptance: any observed drift returns nonzero and requires review.
task check:sdio-ref-history -- --require-stable path/to/cycle-1/result.json path/to/another/result.json
```

It rejects failed/duplicate/incomplete runs, mixed boots/kernels, overlapping
times and changed runtime policy. It catches both per-cycle drift and changes
between the supplied captures. It does not silently pick a new baseline after
each cycle. Two host regressions cover these evidence rules. Running it on all
seven original recordings reproduces the 2→9 progression in
`.local/neo92-original-reference-history.json`; `--require-stable` rejects
the known 8→9 cycle as expected, with the original rejection retained in
`.local/neo92-original-reference-rejection.{json,log}`. Neither mode contacts
the board or submits a PM cycle.

These sysfs reads are sequential snapshots, not atomic attribution of all
runtime users. Ordinary host claims or IRQ processing can create transient
changes; investigate variation rather than silently accepting or subtracting
it. Reference stability must accompany retained input, successful callback
returns, restored settings, clean kernel logs and both recovered routes.
Do not force runtime auto mode, unload Wi-Fi or reset the counter to make the
comparison pass. Broader removal/recovery and real sleep remain separate gates.

## Primary source map

The exact archive identity is in [sources.lock.json](../build/sources.lock.json),
Linux `v6.18.54`, commit `1b357ecb321392158d507b04672ffee57bfa071d`.
Paths below are relative to that verified source tree; offsets refer to the
unmodified files unless stated otherwise:

- `drivers/mmc/host/sunxi-mmc.c`: cached mask, initialization, IRQ dispatch,
  `sunxi_mmc_enable_sdio_irq`, probe/remove and runtime PM callbacks.
- `drivers/mmc/core/sdio_irq.c`: suspended-card check, `sdio_irq_thread`,
  `sdio_card_irq_get/put` and function-level IRQ registration/release.
- `drivers/mmc/core/sdio.c`: `mmc_sdio_suspend/resume`, card removal.
- `include/linux/mmc/host.h`: `mmc_signal_sdio_irq`.
- `include/linux/pm_runtime.h`: reference-only helper implementations.
- `drivers/net/wireless/broadcom/brcm80211/brcmfmac/bcmsdh.c`: host fixup's
  intentional forbid and corresponding removal allow.
