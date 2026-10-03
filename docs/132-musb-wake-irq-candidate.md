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
core. Allocation, device-policy, IRQ-chip, locking, PM and register boundaries
are controlled shims. This is not the entire wakeup core, scheduler or driver
probe executing in a kernel.

**89 scenarios pass natively and under ARM32 emulation.** The existing 61
sleep-connection scenarios remain, with 28 additional ownership scenarios:

- Fresh probe with zero, one or two independent shared references and with
  ordinary or skip-set-wake IRQ-chip behavior.
- Unsupported wake, preexisting capability/source/wakeirq, source allocation
  failure and failed probe balancing followed by cleanup/recovery.
- Policy changes between arm and resume across shared-reference counts.
- Arm failure before controller mutation, failed resume disarm, prevention
  of stacked references on the next attempt and later recovery.
- Runtime-PM get failure with retained wake debt, and terminal teardown
  disarm failure without an operation after the backend has disappeared.

**14 intentionally faulty native variants are rejected.** The previous eight
connection controls remain. Six new variants retain the probe reference,
forget failed-disarm ownership, condition disarm on reread policy, ignore arm
failure, suppress resume-disarm failure or erase foreign device wake state.

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

These alternate builds use separately identified scratch trees and explicit
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
  all native results, ARM32 result, resolved configuration hashes and complete
  object hashes. SHA-256:
  `2c234479fc2135de9bdae6317da54e3ca18549d70c621a4cff8bd72b1f36d3be`.
- `.local/build/musb-wake-configs.log`: complete six-configuration execution.
- `.local/wake-candidate-check.log`: repository checks and explicit skips.
- Patch 0026 SHA-256:
  `fc8c8d43c63d9f31b1d1e821d3492736841ca80be14b0e3d1a3282117b804e84`.

This completes an initial source candidate, not all of report 131's matrix.
The full probe/request/error ladder and post-initialization host/gadget/mode
failures are source-reviewed and compiled, but not dynamically fault-injected
end to end. Remaining source gates include policy changes during capability
allocation, shared owners changing order across zero-depth boundaries,
combined resume-work/disarm failure, full IRQ suspend/abort traversal and
repeated driver bind/unbind. Passing helper tests cannot substitute for those
integration paths or prove concurrent scheduling behavior.

Keep NEO-98 open. Qualify staged diagnostic.18's separate connection-lifecycle
experiment first. A later image containing patch 0026 needs a new identity,
fresh boot/prerequisite evidence, ordinary USB behavior and both management
routes, followed by the attended PM-debug/RTC sequence. Measure the candidate's
owned wake contribution across each transition; do not infer it from interrupt
counts. RTC wake, POWER wake, untouched-cable USB recovery, USB absent,
physical reconnect and host sleep are separate conditions. None has been
qualified by this branch, and no lower current or battery-life gain is claimed.
