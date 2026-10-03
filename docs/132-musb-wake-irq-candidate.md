# MUSB IRQ-wake source candidate (NEO-98)

4 October 2026, Pacific/Auckland. The separate `work/musb-wake-irq-policy`
branch implements checked IRQ-wake ownership on top of main's diagnostic.18
source. It passes source regressions and six ARM driver compilation
configurations. **No candidate image has been built or installed.** The
verified diagnostic.18 archive on the Mac and the running diagnostic.17 are
unchanged. Assign a new image/kernel identity before image assembly.

[Report 131](131-musb-wake-irq-ownership.md) supplies the primary-source audit
and wider acceptance matrix. The existing driver holds a successful IRQ-wake
reference from probe until removal even when `power/wakeup` is disabled.
The candidate owns that reference around system sleep instead. It does not
establish electrical wake capability, fix the observed USB enumeration failure,
or demonstrate a reduction in power consumption.

## Driver ownership and compatibility boundary

[Patch 0026](../kernel/patches/0026-musb-wake-irq-policy.patch) changes the MUSB
core and its state structure. Separate `bool` fields track successful IRQ
arming and owned device capability initialization; they do not share a packed
flag word with asynchronously written controller flags.

| Boundary | Implemented behavior |
| --- | --- |
| Probe after successful IRQ request | Reject preexisting capability, source or generic wakeirq before mutation. Test compatibility with a checked, immediately balanced enable/disable pair. Unsupported wake still allows ordinary USB initialization. |
| Capability setup | Record capability ownership before `device_init_wakeup(true)`, because it can set capability before allocation fails. Check its result. Supported fresh controllers retain the old enabled policy default. |
| System suspend | Acquire the existing runtime-PM reference. Resolve any retained failed disarm before acquiring another IRQ-wake reference. If current device policy permits wake, check arm success before gadget/platform/context changes. |
| Suspend error | Balance the acquired PM reference, log the wake error and return it. Never mark a failed arm as owned. |
| Resume | Restore the existing controller path, then disarm only the saved successful arm, regardless of current device policy. Report failure, preserve ownership on failure and balance the system-PM reference. Preserve an existing relevant resume-work error. |
| Failed probe or removal | Attempt owned wake cleanup before PHY/platform teardown and outside the controller spinlock. Destroy only device capability/source state created by this core. Free the requested IRQ afterward. |

The candidate uses checked driver callbacks because this pinned kernel's
generic wakeirq arm/disarm path ignores IRQ-chip errors. It does not install
a generic wakeirq attachment or take an additional runtime-PM reference.
Sunxi's existing reference preventing unsupported runtime suspend remains
unchanged. Patch 0025's pull-up gate and connection-intent handling remain.

The freshness contract deliberately rejects a previously preconfigured
controller rather than borrowing or deleting its source. A precheck does not
serialize arbitrary competing kernel owners; this candidate assumes the MUSB
core exclusively initializes capability on its fresh controller device.
Userspace policy changes after capability creation do not transfer ownership.
Other MUSB glue/runtime-wake paths remain unqualified.

The balanced compatibility probe is not proof of electrical wake support:
an existing shared reference can bypass the chip callback. On the observed
GICv2 controller, `IRQCHIP_SKIP_SET_WAKE` makes this software accounting rather
than a new hardware wake-register operation. A policy readback or interrupt
count alone cannot establish the underlying descriptor's wake depth.

An unrecoverable final disarm is explicitly **not** balanced cleanup. The IRQ
core preserves its reference after failure, and platform removal returns
`void`. The candidate logs the failure and retains its owned flag while the
object exists; it cannot guarantee recovery after destruction or reset global
depth without risking another owner's reference. This remains a backend
qualification limit, not a case hidden by retries or a cleared bookkeeping bit.

## Reproducible checks

Run from this branch with the pinned build environment prepared:

```sh
task test:musb-sleep
task check:musb-sleep-drivers
task check:musb-wake-configs
task check
```

The first task extracts the hash-verified Linux 6.18.54 source and applies
MUSB patches 0011, 0025 and 0026 with zero fuzz. It compiles the actual MUSB
PM/pull-up/context/work/ownership helpers together with the actual
`set_irq_wake_real()` and `irq_set_irq_wake()` functions from the pinned IRQ
core. It also compiles the actual per-IRQ suspend/resume, wake-event and normal
handler-dispatch helpers, plus ordinary IRQ enable/disable depth handling.
A second executable runs the complete actual `musb_init_controller()` and
`musb_remove()` functions with the actual wake helpers. Allocation, device-policy,
IRQ-chip, locking, PM and register boundaries are controlled shims. This is not
the entire wakeup core, scheduler or driver executing in a kernel.

**205 scenarios pass natively and under ARM32 emulation:** 106 connection,
wake-ownership and per-IRQ PM scenarios, plus 99 probe/removal scenarios.
The existing 61 sleep-connection scenarios remain. Added coverage includes:

- Fresh probe with zero, one or two independent shared references and with
  ordinary or skip-set-wake IRQ-chip behavior.
- Unsupported wake, preexisting capability/source/wakeirq, source allocation
  failure and failed probe balancing followed by cleanup/recovery.
- Policy changes between arm and resume across shared-reference counts.
- Arm failure before controller mutation, failed resume disarm, prevention
  of stacked references on the next attempt and later recovery.
- Runtime-PM get failure with retained wake debt, and terminal teardown
  disarm failure without an operation after the backend has disappeared.
- Changing shared-owner arrival/departure order, including failure of the last
  disable belonging to either MUSB or the other driver. MUSB never retries or
  clears another driver's remaining reference.
- Combined resume-work and wake-disarm errors. On the existing ungated path,
  the work error remains logged and the disarm error is returned; the callback,
  work summary and disarm each produce an observable error record.
- Per-IRQ suspend/flow/resume with device wake policy on/off, a foreign wake
  owner present/absent and an event present/absent. Wake-enabled delivery is
  deferred and reported once; ordinary masked delivery cannot run the handler.
  Resume restores ordinary depth/dispatch and preserves another owner's wake
  reference. No-event resume exercises the same local unwind used on abort.
- Complete probe error labels across host, gadget and dual-role selections:
  instance/platform/ISR/DMA-ops/PHY/DMA/core/request failures, unsupported wake,
  failed probe disarm, source allocation, host/gadget/mode setup and policy
  attachment during the owned capability window. Expected error values,
  reference counts, requested IRQ lifetime and wake cleanup before backend
  destruction are checked. Eight repeated probe/remove cycles retain a foreign
  wake reference without accumulating MUSB references.

**22 intentionally faulty native variants are rejected.** The previous eight
connection controls remain. Six ownership variants retain the probe reference,
forget failed-disarm ownership, condition disarm on reread policy, ignore arm
failure, suppress resume-disarm failure or erase foreign device wake state.
Two IRQ-flow variants omit wake arming or allow normal handler dispatch while
handling a wake event. Six probe variants omit failure cleanup, clean up after
platform teardown, ignore source allocation failure, lose partial capability
ownership, free before cleanup or destroy preexisting wake state.

The configuration task also compiles complete driver objects with the pinned
ARM toolchain. All six configurations pass:

| Configuration | Objects compiled |
| --- | --- |
| Project gadget/Sunxi, built in | `musb_core.o`, `musb_gadget.o`, `sunxi.o` |
| Host only | `musb_core.o`, `musb_host.o`, `sunxi.o` |
| Dual role | Core, host, gadget and Sunxi objects |
| MUSB/Sunxi modules | Core, gadget and Sunxi objects |
| PM enabled, system sleep disabled | Core, gadget and Sunxi objects |
| PM disabled | Core, gadget and Sunxi objects |

The kernel patch is unchanged from the initial six-configuration compilation;
the expanded tests change no kernel source or board configuration. Those
alternate builds use separately identified scratch trees and explicit
resolved-configuration checks. They skip only the incompatible board-specific
config assertions; the normal board compile still enforces them. They never
replace image configuration, kernel artifacts or the staged image. Kconfig
may omit a hidden disabled symbol entirely; validation treats that as `n`
while still rejecting enabled or tristate mismatches. Two regressions cover
the omission observed during this matrix run and incorrect resolved values.
Object compilation is not full module linking, boot or hardware qualification.

The PM-debug and real-sleep recorders now reject explicit MUSB wake-ownership
errors during admission and result assessment, including after apparent
network recovery. Tests cover suspend/resume/cleanup errors and avoid treating
an ordinary informational wake-IRQ line as a fault.

Repository checks pass: **13 runtime and 466 tooling tests**, with two explicit
skips (the existing opt-in user-systemd recovery test and the prepared-Armbian
journal test because that source tree is absent from this isolated worktree).
Compiled current-limit and mount-guard tests, Bash syntax and ShellCheck pass.
The patch passes checkpatch with no errors or warnings using `--no-tree
--no-signoff`; this is a local candidate, not a signed upstream submission.

## Evidence and remaining gates

Private reproducible evidence is retained in this worktree:

- `.local/build/musb-sleep-tests/matrix-evidence.json`: source/input hashes,
  original 89-scenario results, resolved configuration hashes and complete
  object hashes for the unchanged kernel patch. SHA-256:
  `2c234479fc2135de9bdae6317da54e3ca18549d70c621a4cff8bd72b1f36d3be`.
- `.local/build/musb-sleep-tests/evidence.json`: expanded 106 + 99 scenarios,
  22 negative controls and both ARM32 results, including both harness identities.
  SHA-256: `4ba81743ed3dcf68e18a5a86e253bf6fc12aa15a224607ac2ae6f2924696405d`.
- `.local/build/musb-wake-configs.log`: complete six-configuration execution.
- `.local/wake-probe-repository-check.log`: latest repository checks and skips.
- Patch 0026 SHA-256:
  `fc8c8d43c63d9f31b1d1e821d3492736841ca80be14b0e3d1a3282117b804e84`.

This expands the initial source candidate across report 131's probe/error,
policy-race, shared-order, combined-error and repeated bind/unbind gates.
The full actual probe/remove functions execute, but host/gadget setup and
allocation/PM/PHY operations remain injectable API boundaries. Likewise, the
actual per-IRQ PM/flow helpers execute, but chip startup, pending-event replay
and system wake notification are shims. Global descriptor iteration, full
device-PM traversal/abort, real allocation/sysfs concurrency, handler scheduling,
and backend electrical behavior remain unqualified. No test result here proves
those whole-kernel paths or physical wake behavior.

The wider source review also found unchecked `pm_runtime_get_sync()` results in
existing MUSB probe/removal. Those calls are separate from this wake-ownership
change and the already tested system-suspend get-failure path. They remain in
`FOLLOW-UP.md` alongside the existing gadget start/stop failure audit; the new
probe fixture does not simulate runtime-get failure as a passing case.

Keep NEO-98 open. Qualify staged diagnostic.18's separate connection-lifecycle
experiment first. A later image containing patch 0026 needs a new identity,
fresh boot/prerequisite evidence, ordinary USB behavior and both management
routes, followed by the attended PM-debug/RTC sequence. Measure the candidate's
owned wake contribution across each transition; do not infer it from interrupt
counts. RTC wake, POWER wake, untouched-cable USB recovery, USB absent,
physical reconnect and host sleep are separate conditions. None has been
qualified by this branch, and no lower current or battery-life gain is claimed.
