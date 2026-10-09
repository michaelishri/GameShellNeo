# MUSB runtime-PM retirement before resource teardown

9 October 2026, Pacific/Auckland. NEO-167, continuing NEO-106 on
`work/musb-runtime-retirement` from `4d1a07a`. Pinned Linux 6.18.54 plus the
candidate patch queue is authoritative. This is host-only work; NEO-108
installation remains parked. No device connection or image action is needed.

## Problem and acceptance scope

[Report 228](228-musb-core-work-retirement.md) fixed core work/timer closure
and the worker-owned session reference. It retained that reference until
runtime PM was disabled, avoiding a newly exposed callback. The pre-existing
case with no session still has the same resource-ordering defect:

1. Sunxi holds a backend reference; removal holds a temporary core reference.
2. Platform exit drops the backend reference, asserts reset and disables clock.
3. The core's `pm_runtime_put_sync()` drops the last reference and can dispatch
   `musb_runtime_suspend()`, which calls `musb_save_context()` on those registers.

Failed probe also destroys DMA and shuts down the legacy PHY before the final
core PM put/disable. Even an uninitialized controller can reach the suspend
callback: the initialization guard is in runtime **resume**, not suspend.
These are pinned-source ordering defects, not observed CPI hardware failures.

This slice must disable/drain the core device's runtime-PM callbacks before
DMA, PHY or platform resources are released; preserve client cleanup while
runtime PM and resources are available; balance the retained core reference
once even if its original `get_sync()` failed; preserve session and unrelated
reference ownership; and avoid new cleanup on pre-PM or uninitialized-work
failure paths. No driver hot-path branch, polling or retry policy is required.

## Implementation

[Patch 0041](../kernel/patches/0041-musb-runtime-pm-retirement.patch) adds
`musb_disable_runtime_pm()`. It first calls `pm_runtime_disable()`, then
`pm_runtime_dont_use_autosuspend()`. The latter can request idle processing and
can drop a policy-owned reference when the autosuspend delay is negative, so
the callback barrier must precede the policy update.

Normal removal keeps the existing temporary PM get and host/gadget cleanup
first, then disables runtime PM before final core IRQ/work retirement. Pending
or running runtime callbacks therefore finish before final interrupt masking
and before resource release. The PM wait runs without the controller lock.
The core reference is subsequently balanced with `pm_runtime_put_noidle()`;
the session reference retains its separate NEO-166 release helper.

Failed probe has three PM-enabled entry paths:

| Entry | Cleanup after the PM barrier |
| --- | --- |
| `fail3` | Core IRQ/work/timer, DMA, legacy PHY, retained PM references, platform |
| `fail2_5` | Legacy PHY, retained PM references, platform; no uninitialized core work |
| `err_usb_phy_init` | Retained PM references and platform; no shutdown of failed PHY init |

Shared `shutdown_phy` and `release_pm` labels prevent duplicate PM disable or
reference release. Earlier `fail2`/`fail1` paths do not enter the new helper;
they never enabled core runtime PM or acquired its temporary reference.
No backend exit implementation is changed.

The pinned `__pm_runtime_disable(dev, true)` can service an already pending
resume before closing admission, then waits for runtime transitions and idle
notification and cancels pending PM work/timers. This is why resources remain
live across the whole call. It does not guarantee register accessibility after
a failed get, and it does not disable PM on parent devices.

Disabled PM does **not** make every future get fail. The pinned runtime core
returns `1` for a disabled device whose current and last status are active,
without invoking a callback. A suspended disabled device returns `-EACCES`.
Neither result provides admission control for independent backend code that
directly accesses hardware; that retirement stays under NEO-106.

## Repeatable validation

```sh
task check:musb-irq-drivers   # includes native/ARM32 source tests
task test:musb-pm-kunit      # real Linux runtime-PM behavior in UML
task check                 # host regressions and shell checks
```

Run the build tasks sequentially. `task test:musb-irq` remains available for
source-only native/ARM32 verification and is still part of `task build`.

The source fixture extracts actual PM/IRQ/work/session helpers, normal removal
and four probe failure tails, retaining all prior scenarios and adding the
PHY-init failure path. Its 43 scenarios check the barrier before final core
masking and resource release, one disable per PM-enabled path, no disable on
earlier paths, preserved reference counts and uninitialized-work avoidance.
It controls PM and hardware boundaries; it is not real PM scheduling.

Twenty-nine native negative controls include the previous work/IRQ/session
mutations and missing/late barriers or policy-before-barrier ordering, missing PM
closure on each probe entry, and active/missing/duplicate core puts. Only an
assertion failure is accepted. Four source-boundary controls reject missing
or late timer initialization and extra work/PM terminal callers. The five ARM
build configurations remain project gadget, host, dual-role, combined module
and no-PM, covering 21 objects. No bootable image is produced.

The new `musb-pm` UML KUnit suite appends tests to the actual core source and
calls the production PM/session helpers. It uses real Linux runtime-PM dispatch,
usage counts, locks, wait queues and kthreads. Its eight cases cover:

- Eight active-removal combinations: session present/absent, backend hold
  present/absent and zero/two unrelated holds. Modeled resources disappear
  only after the helper; backend/core/session puts must not invoke callbacks.
- A deliberate old-order no-session control that must dispatch a suspend
  callback after modeled resource loss, proving sensitivity to the defect.
- A running suspend callback and a running resume callback, separately held
  open while another kthread calls the helper. Observing PM disable depth under
  the PM lock establishes barrier entry. Resource release and helper return
  must wait; callbacks acquire the controller lock before finishing.
- A failed runtime resume/get retaining its counted reference, followed by
  passive balancing that preserves a separate existing hold.
- Future requests against disabled active and suspended states, including the
  active-success distinction above, with zero additional callback dispatch.
- Balanced re-enable on the synthetic device, then normal suspend and resume.
- Negative autosuspend delay: release the PM policy's extra hold only after
  disabling callbacks, preserving the core-owned reference until its own put.

KASAN, lockdep and atomic-sleep checks are enabled. Strict validation requires
the exact eight passing cases and rejects incomplete/duplicate results or
kernel diagnostics. Binary, configuration, parsed results and raw kernel log
are retained with hashes under `.local/build/musb-pm-kunit/`. The source/ARM
receipt remains under `.local/build/musb-irq-tests/`.

These tests use synthetic resource-access callbacks on one virtual CPU. They
do not invoke physical MUSB context-save MMIO, run full probe/removal, exercise
SMP or independently force the queued-before-dispatch resume race. Re-enable
tests the PM object's API balance, not physical controller rebind. The older
work/IRQ/restart kernel suites are separate tasks; do not treat their historical
results as executions of this candidate.

## Results

- All 43 source scenarios passed natively and on ARM32. The 29 native negative
  controls failed by assertion, and four source-boundary controls were rejected.
- `task check` passed: 16 runtime and 826 tooling tests, with two optional
  tooling skips; compiled helper checks, Bash syntax and ShellCheck passed.
- Strict production-patch checkpatch: zero errors, zero warnings, zero checks.
- Standards review: zero findings. Specification review: zero findings.
- UML KUnit: all eight cases passed under KASAN and lockdep, with no rejected
  kernel diagnostics. The exact suite, 11 inputs, complete production patch
  queue, four retained artifacts and retained receipt were independently
  checked against the saved files.
- All five ARM configurations passed. The 16 recorded inputs, 30 native
  binaries, ARM32 binary, extracted core source, five configurations, 21 ARM
  objects and complete patch queue were checked against the saved files.

| Artifact | SHA256 |
| --- | --- |
| Patch 0041 | `8e4ede64b81a9172108d7210ba10ff6041ee76db416e15d9e536837dec1b69f3` |
| `.local/build/musb-irq-tests/compile-evidence.json` | `c4f348830874a921ef89e7d033c0d03b205b256e8b00aa5ddecb66ae989b132f` |
| `.local/build/musb-pm-kunit/evidence.json` | `aadd29c82e2d81945e1a87f517048f9e4b9b8027995519ab0e03a4ba2ca9935c` |
| Accepted UML `linux` | `61ca6eb09e648c2b569e366e26ce6468af4edfbebf42112ea24e47bc367475bb` |

Accepted kernel artifacts are retained under
`.local/build/musb-pm-kunit/kernel-1b944a0549b3675b/accepted-runs/8e11d3ca07fa47d2af384ce520f415c7/`.
The shared restart/IRQ/work evidence validators also passed their unit tests;
their full kernel suites were not rerun for this change.

## Remaining boundaries

This retires core runtime callbacks, not all controller users. Backend timers,
notifiers, mailbox/role callbacks, parent PM, independent DMA callbacks and
gadget work still need ownership and drain contracts. In particular, the
MediaTek parent/child PM ownership mismatch and MPFS parent-clock-before-child
removal from [report 141](141-musb-removal-backend-contracts.md) are unchanged.

`pending_list` can also be consumed through `musb_queue_resume_work()` and
system resume, not only runtime resume. Disabling runtime PM neither closes
those producer paths nor frees pending callback data. Successful synchronous
resume normally drains existing entries; a failed resume leaves their wider
retirement unresolved. Do not discard request callbacks or claim complete
removal safety based on this barrier alone.

The existing get-error/hardware-access paths, independent DMA destruction and
source masks, separate notifier/backend candidates, full image integration
and physical rebind qualification remain open. There is no measured power or
latency claim for this source-only correction.
