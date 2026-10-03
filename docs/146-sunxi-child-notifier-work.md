# Sunxi child notifier and worker ownership

4 October 2026, Pacific/Auckland. NEO-106.

Patch 0033 makes each Sunxi MUSB child own its extcon registration and the
period during which its parent-owned worker can run. Failed PHY initialization
and normal child exit synchronously unlink the callback and disable/drain the
worker before releasing platform resources. A subsequent child initializes its
own role state and re-enables the worker. This closes specific source-level
ownership gaps identified in [report 139](139-musb-teardown-power-audit.md).

The candidate is on
[work/musb-removal-lifetime](https://github.com/michaelishri/GameShellNeo/tree/work/musb-removal-lifetime).
It is not installed on diagnostic.18. It does not yet establish complete safe
MUSB removal: provider lifetime and core IRQ, PM and other producer retirement
remain open. No board command, sleep test, charging change or image build was
performed for this slice. No latency or energy improvement is claimed.

## Ownership change

Previously `sunxi_musb_init()` called `devm_extcon_register_notifier()` against
the parent glue device. Its registration could therefore remain after child
initialization failed or the child alone was unbound. `sunxi_musb_exit()` only
canceled the worker once. An already-selected notifier, or a subsequent core
callback, could queue it again. Parent role flags and `phy_mode` also survived
child-only rebind.

The new source does the following:

1. Initializes the parent worker disabled and retains the initial PHY mode
   derived from the existing device-tree role selection.
2. During child initialization, preserves hardware feature flags but resets
   transient role flags, publishes the new child pointer, restores the initial
   PHY mode and marks connector state for sampling. It then enables work and
   explicitly registers the notifier before `phy_init()`.
3. If notifier registration fails, disables/drains work. If `phy_init()` fails,
   first uses patch 0031's synchronous unlink/drain, then disables/drains work.
   Both paths retain the original reset/clock/SRAM unwind.
4. On normal child exit, clears the enabled flag, synchronously unregisters the
   notifier, and uses `disable_work_sync()` before the existing PM/PHY/reset/
   clock/SRAM cleanup. Later queue attempts cannot execute that worker while
   it remains disabled. They are not evidence that the caller itself is safe
   after its own owner is freed.
5. Leaves ordinary `sunxi_musb_disable()`/`enable()` restartable. Permanent
   worker shutdown belongs to terminal child teardown, not ordinary stop or
   system sleep.

Initialization and exit are serialized by child driver binding. The successful
registration has one owner and one matching unlink: there is no parent devres
registration left to unregister the same block a second time. A failed unlink
is reported with `WARN_ON`; that assertion is not a fallback lifetime barrier.
An unlink failure would invalidate safe-cleanup claims and require diagnosis.

The notifier now only marks pending connector work. The worker reads current
`EXTCON_USB_HOST` state instead of copying the callback's event into a persistent
host flag. This also supplies initial state on rebind even if no fresh event is
emitted. An event after a worker's state snapshot marks work pending again;
the next execution samples the newer state. Event coalescing remains workqueue
behavior, not a promise to process every intermediate role transition. A
negative extcon state result returns without changing role registers.

## Reproducible checks

Run from the candidate worktree:

```sh
task test:sunxi-owner
task check:sunxi-owner-drivers
task check
```

The first command verifies the locked archive, extracts the actual Sunxi file,
and applies every patch-queue section targeting it. It compiles the actual
worker, notifier, init/exit, enable/disable, VBUS, mode and recovery functions,
plus the actual parent worker/default-role initialization statements. DT lookup,
parent resource acquisition and the core driver are outside that fixture.

`kernel/tests/sunxi_owner_test.c` executes 240 scenarios natively and under
ARM32 emulation. The matrix varies SRAM/reset/config-data features, initial
host/peripheral/OTG roles, each applicable initialization failure and event
arrival during PHY initialization. Each case subsequently exercises successful
initialization, role changes, normal disable/enable, terminal teardown, late
queue attempts and a new child on the same parent. A cable change after the
worker's snapshot must converge to the new role on the next execution.

Seven deliberately broken variants must fail assertions:

- PHY initialization failure leaks its notifier.
- Exit uses asynchronous unlink despite a selected callback.
- Exit only cancels work, allowing later queues.
- Initialization does not re-enable work.
- Rebind preserves a changed PHY mode.
- Rebind never schedules its initial connector-state sample.
- The worker uses a stale fixed host state.

The fixture models workqueue disable/cancel behavior, selected notifier
completion, register access, PM, PHY, clock/reset and SRAM boundaries. It is
deterministic and contains no actual concurrent Linux execution. The separate
[report 145 KUnit results](145-extcon-kernel-lifetime-validation.md) qualify the
framework drain on real Linux SRCU; they do not turn this Sunxi fixture into a
real-kernel workqueue, core-removal or provider-lifetime test.

The compile task builds complete `sunxi.o` and `extcon.o` objects in isolated
ARM peripheral, host and dual-role configurations using the complete candidate
queue and locked builder. It verifies the requested Kconfig results and records
object/configuration/source hashes. These are object compilations, not a linked
bootable image or hardware role qualification. Normal `task build` on this
branch includes the source fixture before kernel compilation.

Evidence is under `.local/build/sunxi-owner-tests/`; source and compile runs use
`evidence.json` and `compile-evidence.json`. Task logs use
`.local/build/sunxi-owner.log` and `.local/build/sunxi-owner-drivers.log`.
The initial compile qualification log is `.local/sunxi-owner-compile.log`.

## Recorded result

All 240 scenarios pass natively and on ARM32; all seven negative controls
fail their required assertions. All three ARM object configurations pass.
`task check` passes 13 runtime and 494 tooling tests, with two existing optional
skips, plus the C regressions, Bash syntax and ShellCheck. Strict patch
checkpatch reports zero errors, warnings or checks. The initial fixture build
needed a signed-enum comparison correction and an unused-mock annotation;
neither was accepted as a passing test.

- Patch 0033 SHA-256:
  `be37aec0e9b4cac25e3172b9df071899ed850545c2283919eeda6177a97b2d00`.
- `compile-evidence.json` SHA-256:
  `2427ffcc8781d63680b7d2e6784a8fd991c1ff49278e717be09c360679189983`.
- Shared complete-source inventory SHA-256:
  `fceb62c0ddb6433366b31ae40edf44c25ef622dda8703722453da65c97073ac1`.
- Peripheral output: `kernel-7ec3e474410e5bfc`.
- Host output: `kernel-10a68694808d2382`.
- Dual-role output: `kernel-ac2b0e4cf29e8195`.

Output directories are relative to `.local/build/sunxi-owner-tests/`. Current
input hashes, full patch manifests, extracted Sunxi source, configurations and
all recorded object hashes were checked against the evidence after compilation.
The host-check log is `.local/sunxi-owner-host-check.log`.

## Remaining integration requirements

The explicit framework contract requires the extcon provider to remain
registered while unlink/drain runs. The existing `extcon_get_edev_by_phandle()`
returns a raw pointer after dropping the extcon device-list mutex. It does not
itself establish provider driver lifetime. The generic PHY getter's stateless
device link is not a provider-unbind barrier, and the extcon and generic PHY
providers must not be assumed identical.

The pinned driver core supports managed device links that unbind consumers
before their supplier and wait for probing consumers. Default firmware links
can supply this ordering, but a proof depending on those defaults is not valid
with firmware links disabled, relaxed or otherwise absent. The next integration
must secure lookup-to-link admission, reject an already-unbinding supplier,
and keep that dependency through child teardown. A device reference alone does
not preserve provider devres or its registration.

Patch 0033 also leaves the core shared IRQ registered across platform exit,
the core global Sunxi register-access pointer, runtime-PM ordering and core
work/timers unchanged. Disabling glue work prevents execution of that worker;
it does not retire those other callers. Full producer retirement must retain
resources needed by endpoint cleanup and completions, release locks before
synchronous waits, and handle partial probes. The other platform/DMA contracts
in [report 141](141-musb-removal-backend-contracts.md) still apply.

Before integration into a new image, require provider-lifetime implementation
and concurrent kernel qualification, core retirement integration, full kernel
link/configuration checks, and a new image identity. Later device checks must
cover ordinary startup/USB/sleep regressions and attended child/parent
remove/rebind and failure recovery. NEO-106 remains in progress.
