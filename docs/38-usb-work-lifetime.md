# AXP USB delayed-work lifetime correction

Date: **2026-09-28 NZDT**. Ticket: **NEO-17**.

The AXP USB power-supply driver could release its power-supply object before
canceling the polling work that references it. Patch 0006 corrects the managed
resource order. Host regressions reproduce the previous failure and pass with
the patch; an isolated ARM kernel-object build also passed. The change is not
installed on the GameShell and does not change the polling interval.

## Trigger and correction

In the locked Linux 6.18.54 probe, the managed delayed-work cancellation action
was registered before the managed supply. IRQ handlers were registered last.
Managed resources unwind in reverse registration order, yielding IRQ release,
supply unregister, then work cancellation. A pending timer can run between the
latter two actions. `axp20x_usb_power_poll_vbus()` can then call
`power_supply_changed()` using the unregistered supply. Supply unregister frees
the object immediately or when its last external reference is dropped, so the
window can become a use-after-free. The same order matters when a later IRQ
registration fails after an earlier IRQ has already queued work.

Sources: [locked probe and worker](https://github.com/gregkh/linux/blob/v6.18.54/drivers/power/supply/axp20x_usb_power.c),
[reverse managed release](https://github.com/gregkh/linux/blob/v6.18.54/drivers/base/devres.c),
[supply unregister and notification](https://github.com/gregkh/linux/blob/v6.18.54/drivers/power/supply/power_supply_core.c),
[managed cancellation helper](https://github.com/gregkh/linux/blob/v6.18.54/include/linux/devm-helpers.h).
All were also inspected in the local locked source.

[Patch 0006](../kernel/patches/0006-axp-usb-work-lifetime.patch) moves
`devm_delayed_work_autocancel()` after successful supply registration and before
the first IRQ request. Teardown now releases IRQ handlers, synchronously cancels
work, then unregisters the supply. Work initialization still precedes every
IRQ request, preserving the protection against an immediate interrupt during
probe. No work is queued by the preceding setup code.

The patch moves one existing initialization/action-registration block and adds
an explanatory comment. Polling, notifications, register access, PMIC settings
and normal successful runtime behavior are unchanged. This is a lifecycle
correctness fix, not a measured idle-power optimization. No corresponding
failure has been observed on the owner's board.

## Reproducible host checks

```sh
task test:usb-lifecycle
task check:usb-driver
```

[The workflow](../tools/check-usb-lifecycle.py) verifies the locked Linux archive
hash and extracts the actual driver structures, probe, IRQ handler and polling
callback. It applies only patch 0006 for the regression and checks that code
outside the tested probe did not change. The helper does not substitute a
rewritten probe algorithm.

[The C harness](../kernel/tests/usb_lifecycle_test.c) supplies deterministic
models of managed resources, delayed work and the AXP223's optional-field-free
probe path. It runs forty cases: successful probe or nine failure locations,
each with all four combinations of immediate plug/removal IRQ delivery.
Failures cover allocation, field setup, supply/action registration and both
IRQ lookup/request positions. It checks probe outcomes, initial-read queueing,
immediate notification delivery and complete resource release.

During unwind the harness deliberately expires pending work immediately after
supply unregister. The actual polling callback then attempts its notification;
the shim rejects access to a supply whose lifetime has ended. This models one
legal adverse schedule rather than hoping to reproduce a race probabilistically.

| Code | Cases | Lifetime violations | Result |
| --- | ---: | ---: | --- |
| Original locked probe | 40 | 8 | Negative control reproduced the failure |
| Patched probe | 40 | 0 | Passed |

The eight violations are failing scenarios of one ordering defect, not eight
independent defects. The harness also fails if cancellation precedes live IRQ
producers, an IRQ queues uninitialized work, or work survives driver-memory
release. Kernel `sign-compare` and unused IRQ-argument diagnostics are suppressed
only around the extracted upstream code; harness compilation retains
`-Wall -Wextra -Werror`.

The shims do not execute the kernel scheduler, real devres internals, regmap
interrupt handling or electrical transactions. They establish the intended
ownership sequence for the AXP223 paths exercised, not every variant or all
possible concurrency interleavings. Hardware unbind was not attempted.

## ARM integration build

The optional compile check extracts a separate full kernel tree, applies the
complete project patch queue, merges the project configuration and compiles
`drivers/power/supply/axp20x_usb_power.o` with the locked builder. The object is
ELF32 ARM EABI5; all 132 project configuration assertions passed.

Private evidence:

- `.local/build/usb-driver.log`
- `.local/build/usb-lifecycle-tests/compile-evidence.json`
- `.local/build/usb-lifecycle-tests/original/result.txt`
- `.local/build/usb-lifecycle-tests/candidate/result.txt`
- `.local/build/usb-lifecycle-tests/kernel-fc090a732f2da60d/`

Built object SHA-256:
`ea37a5997eb38c83274aaae166a2c3de0c808708e0eb7489ece62dae3572dcbe`.
The evidence records hashes for the Linux archive, patch, harness, helper and
resolved config, plus the pinned builder identity.

`task check` also passed 13 runtime and 58 tool tests (one optional user-systemd
case skipped), the compiled current-limit regression and shell lint. Its log
is `.local/build/neo17-check.log`.

No full image or module installation was produced during NEO-17. The normal
diagnostic.3 source/output and completed image were preserved. Later builds use
the normal patch-queue reset workflow before applying the expanded queue.

## Remaining validation

The subsequent NEO-19 session built and installed diagnostic.4 with this patch,
retaining diagnostic.3 for recovery. [Report 40](40-diagnostic4-hardware-validation.md)
records the full build, flash readback and hardware integration results.
Kernel-level fault injection or concurrency instrumentation can supplement the
host lifetime model; they were not performed here. The separate USB polling
experiment in [report 36](36-usb-polling-policy.md), battery-voltage investigation
and future suspend/resume work remain unchanged.
