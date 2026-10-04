# Power-supply unregister and deferred-registration lifetime

5 October 2026, Pacific/Auckland. NEO-114.

The power-supply core cancels notification work before stopping the deferred
registration worker that can produce another notification. A source-reachable
schedule can leave notification work pending after unregister and eventually
access freed memory. Joining deferred registration first closes that particular
edge, provided every other producer has already stopped. This is a shared-core
finding; the ordinary AXP removal and probe-failure paths on GameShell have an
additional parent-device lock that excludes this schedule. No corresponding
fault has been observed on the board. Sources and the distinction follow.

This report resolves the audit question raised in
[report 71](71-power-supply-notification-freeze.md) and `FOLLOW-UP.md`. It does
not install a kernel change or qualify hardware unbind. The proposed cancellation
order below is a bounded remediation, not a claim that arbitrary supply users
may continue calling the API during or after unregister.

## Source boundary

The audit reads `.local/sources/linux-6.18.54/`, including the project's existing
AXP lifetime, polling, diagnostic and suspend changes. In particular,
[patch 0006](../kernel/patches/0006-axp-usb-work-lifetime.patch) determines the USB
driver's managed-resource order, and
[patch 0013](../kernel/patches/0013-power-supply-freezable-notifications.patch)
changes `changed_work` to `system_freezable_wq`. Neither changes the two
cancellations in `power_supply_unregister()`. The unmodified
[v6.18.54 upstream core][upstream-core] has the same cancellation order.

Local line numbers below refer to that audited tree. The source files were
read without modification. These hashes distinguish the patched local sources
from unmodified upstream files:

| File below the source root | SHA-256 |
| --- | --- |
| `drivers/power/supply/power_supply_core.c` | `10fb014e80e863fbc5f6754abef5a322c9a6e718da885f7775a0fbc9537ed2f4` |
| `drivers/power/supply/axp20x_usb_power.c` | `3c1aa54f986a3dd77d9e453804998389a3e0e8e188225695cb3707b34213e00b` |
| `drivers/power/supply/axp20x_ac_power.c` | `dbbf9808a3e23c54e739bf7019ac98d6e6a173dcc511c2cd78f8ed21ab4a468d` |
| `drivers/power/supply/axp20x_battery.c` | `20fae6ab58e4ce5688d8fb1a7bf24dc7817f879332758fed2866862aa6429cdb` |
| `kernel/workqueue.c` | `889e9c0b529d060424843aa4d7e0f2fc773feee19f1c465d1803b596c0186b46` |
| `drivers/base/dd.c` | `26efc05457b05672d7156cc7c6198dfc7c4875bc3a9cb0629ed716992704ed0f` |
| `drivers/hid/hid-corsair-void.c` | `8af0d7820231df255470d6d822380508ae7fe4c397d564f18bb0d0d33867a3f4` |

## The work and object have different lifetimes

`__power_supply_register()` allocates `struct power_supply`, initializes its
embedded device and both work items, and publishes the device. After the other
registration steps succeed, it increments `use_cnt`, sets `initialized`, and
queues the one-shot `deferred_register_work` with a 10 ms delay on
`system_power_efficient_wq`. The final queued worker has no associated
`get_device()` or `power_supply_get_*()` reference. Source: [core][core],
`__power_supply_register()`, lines 1566–1684, and
`POWER_SUPPLY_DEFERRED_REGISTER_TIME`.

The deferred callback tries to lock `psy->dev.parent`. On a failed trylock it
checks `psy->removing`, returns when removal is underway, or sleeps and retries.
On a successful trylock it calls `power_supply_changed()` before unlocking.
With no parent it calls the notification function immediately. Crucially,
`removing` is checked only after a failed trylock; it does not revoke a callback
that already obtained the lock. Source: [core][core],
`power_supply_deferred_register_work()`, lines 180–197.

`power_supply_changed()` sets `changed`, takes a wake hold, and queues
`changed_work`. It neither checks `use_cnt`/`removing` nor acquires an object
reference. Its worker dereferences `psy` before any property validity check,
may update sysfs groups, notifies supplied devices, updates LEDs, invokes the
blocking notifier chain and sends a change uevent. Thus a later getter returning
`-ENODEV` cannot make a worker using a freed `psy` safe. Source: [core][core],
`power_supply_changed_work()` and `power_supply_changed()`, lines 78–168.

`power_supply_unregister()` decrements `use_cnt`, warns if the resulting count
is nonzero, sets `removing`, cancels `changed_work`, then joins
`deferred_register_work`. It subsequently removes ancillary interfaces and
calls `device_unregister()`. The latter calls `device_del()` and `put_device()`;
the final device reference invokes `power_supply_dev_release()`, which frees
the allocation. An additional reference may postpone that free, but unregister
does not wait for `use_cnt` to become zero. Sources: [core][core], lines
1478–1484 and 1753–1771; [device core][device-core], `device_unregister()`,
lines 3988–4004.

References from `power_supply_get_by_name()` and
`power_supply_get_by_reference()` pair a device reference with a `use_cnt`
increment; `power_supply_put()` drops both. The API explicitly expects the
reference to be released before unregister. That reference protects the supply
allocation, not all driver-private data or resources associated with the
parent. `use_cnt` is also a property-call admission check, not a callback join:
a call that has passed the check is not retrospectively stopped by decrementing
the count. Source: [core][core], lines 460–539, 1245–1272 and 1303–1329.

The wake hold is a separate lifetime again. Supply teardown disables its wakeup
source; `wakeup_source_destroy()` explicitly relaxes and frees that source.
Keeping a wake event active therefore does not retain the `power_supply`
allocation or force pending notification work to run. Source:
[wakeup implementation][wakeup], `wakeup_source_destroy()`,
`wakeup_source_unregister()` and `device_wakeup_disable()`.

## A reachable shared-core schedule

Let D be deferred registration, U be unregister, and C be notification work.
Assume no extra device reference and a caller of U that does not hold the
power supply's parent lock. The following is a permitted interleaving:

| Step | Deferred worker D | Unregister U | Notification C |
| --- | --- | --- | --- |
| 1 | Begins, obtains the parent lock, pauses before `power_supply_changed()` | | Not pending |
| 2 | Paused | Decrements `use_cnt`, sets `removing` | |
| 3 | Paused | `cancel_work_sync(C)` returns | Not pending or running |
| 4 | Resumes, calls `power_supply_changed()`, queues C, unlocks, returns | Enters or waits in `cancel_delayed_work_sync(D)` | Pending; need not have run |
| 5 | Finished | Join returns; interfaces and wake source are removed; final device reference is dropped | Still pending |
| 6 | | | Runs using released storage |

This does not require a stale read of `removing`: D already passed the only
place that reads it. D can also pause inside `power_supply_changed()` before
its queue operation, or begin running between U's first cancellation and its
attempt to cancel D. A pending timer that U successfully cancels without the
callback starting is the safe case. These schedules are deductions from the
[two core callbacks and unregister][core], not hardware observations.

`cancel_work_sync()` only guarantees quiescence absent racing enqueues. The
pinned implementation temporarily disables a work item during cancellation,
flushes any running invocation, then re-enables it before returning. It is not
a permanent gate. `cancel_delayed_work_sync(D)` only joins D; it does not
recursively drain C. Source: [workqueue implementation][workqueue],
`__cancel_work_sync()`, `cancel_work_sync()` and `cancel_delayed_work_sync()`,
lines 4430–4522; the [upstream workqueue documentation][workqueue-doc] states
the same racing-enqueue qualification.

There is a concrete caller class in the pinned upstream tree. Corsair Void's
`battery_work` registers and unregisters its power supply in response to headset
connection changes. The supply's parent is the HID device, but the work callback
does not acquire that device lock. An early remove event can therefore reach U
while D holds the parent lock. The two workers are distinct; serializing
Corsair's own add/remove work does not serialize it against D. Sources:
[Corsair source][corsair], `corsair_void_add_battery()` and
`corsair_void_battery_work_handler()`, lines 544–592, and parent assignment at
657. This establishes a source path, not a reproduced Corsair device failure.
The audited local kernel config has `CONFIG_HID_CORSAIR` disabled, so this
example does not turn the shared-core finding into a GameShell failure.

The accepted no-parent registration path also lacks the lock exclusion, though
the core emits a warning for that registration. It is useful as a test case;
the non-null-parent Corsair example avoids relying on that unusual API usage.
Source: [core][core], lines 1575–1580 and 180–197.

## Why the ordinary AXP path is narrower

All three AXP supplies pass `&pdev->dev` to
`devm_power_supply_register()`. This is both the owner of the devres record and
the parent D tries to lock. Their platform drivers rely on managed cleanup;
they do not issue an independent runtime `power_supply_unregister()` from a
work callback. Sources: [USB][usb], lines 1061–1109;
[AC][ac], lines 394–437; [battery][battery], lines 1122–1150.

Driver-core detach holds the platform device lock through
`device_unbind_cleanup()` and `devres_release_all()`. Probe attachment holds
the same lock while `really_probe()` performs failed-probe cleanup. Sources:
[driver binding][dd], `__device_driver_lock()`,
`device_release_driver_internal()`, `__device_release_driver()`,
`__device_attach()`, `__driver_attach()` and `really_probe()`.
Consequently, for these AXP paths:

1. If D obtains the parent lock first, it completes its enqueue before releasing
   that lock. U cannot start its managed cleanup until afterward. U's existing
   cancellation then sees any outstanding C.
2. If cleanup obtains the lock first, D cannot pass its trylock. Once U marks
   removal, D takes the existing exit path and produces no C. U's join ensures
   D has exited before freeing the supply.
3. An unscheduled D is canceled directly.

The lock stays held during both work cancellations. Reordering them preserves
this behavior, provided the existing trylock/removal escape is retained.
Replacing that loop with a blocking parent lock would restore the historical
deadlock described below. This argument is specific to the deferred producer;
device locking does not stop IRQs or the driver's independent poll worker.
Sources: [core][core], `power_supply_deferred_register_work()`;
[driver binding][dd], `device_unbind_cleanup()`.

## AXP producer retirement and remaining consumers

Managed actions release in reverse registration order. The resulting orders
below cover normal detach and the corresponding partial-probe unwind, with
only successfully registered resources present. Source:
[devres implementation][devres], `release_nodes()`, lines 496–507.

| Supply/path | Notification producers | Retirement before supply unregister |
| --- | --- | --- |
| AXP USB | USB IRQ handler directly calls `power_supply_changed()` and queues private `vbus_detect`; private polling can notify and requeue itself | Diagnostic files, if present, are removed first; IRQ actions are freed/joined; private delayed work is canceled/joined; then supply unregister runs |
| AXP AC | AC IRQ handler calls `power_supply_changed()` | Managed IRQ actions were registered after the supply, so they are freed/joined first; no private poll worker |
| AXP battery | Core's initial deferred registration; no driver IRQ, private periodic work or `external_power_changed` callback | Supply unregister precedes release of earlier driver allocation and IIO resources |
| All three | Core deferred registration | Parent-lock exclusion above; core must still cancel/join the worker |

Sources: [USB][usb], `axp20x_usb_power_irq()`,
`axp20x_usb_power_poll_vbus()` and probe; [AC][ac],
`axp20x_ac_power_irq()` and probe; [battery][battery], descriptors and probe;
[patch 0006](../kernel/patches/0006-axp-usb-work-lifetime.patch).
`devm_delayed_work_autocancel()` calls `cancel_delayed_work_sync()` on release.
Managed IRQ release calls `free_irq()`, which removes the action and waits for
active IRQ/threaded handling. Sources: [managed work helpers][devm-work],
`devm_delayed_work_drop()`; [IRQ devres][irq-devres], `devm_irq_release()`;
[IRQ lifetime][irq-manage], `__free_irq()`.

The diagnostic control is a real extra producer: an accepted synthetic request
can queue `vbus_detect`. Its devres removal action is added after the IRQ
registrations, and its files use the ordinary protected debugfs interface.
Removing that directory waits for active file operations before the later
IRQ/work/supply actions run. An open idle descriptor does not keep access
admitted after removal. Sources: [diagnostic implementation][usb-diag],
`neo_usb_command()`, `neo_usb_remove()` and `neo_usb_register()`;
[debugfs proxies][debugfs-file], `debugfs_file_get()` and operation proxies;
[debugfs removal][debugfs-inode], `__debugfs_file_removed()`.

An allocation failure registering USB's autocancel action is also bounded:
work initialization has occurred, but IRQs and initial polling have not yet
been enabled. A later IRQ or diagnostic setup failure has the successfully
installed actions in the order above. The pre-0006 USB defect was different:
its private poll worker could survive supply unregister. Reordering two core
work items does not replace that driver correction. Sources: [USB probe][usb];
[report 38](38-usb-work-lifetime.md).

Additional producer checks matter before calling any reorder a complete
lifetime solution:

- **Property setters:** the core sysfs store calls `power_supply_set_property()`
  without a generic notification afterward. The AXP setters inspected do not
  call `power_supply_changed()` or queue the poll worker. They do access driver
  data and registers, whose normal lifetime still matters. Sources:
  [sysfs][sysfs], `power_supply_store_property()`; [USB][usb],
  `axp20x_usb_power_set_property()`; [AC][ac] and [battery][battery], setters.
- **Other supply notifications:** a class walk may call a target's
  `external_power_changed` callback, which can be another driver's independent
  producer. The AXP descriptors have no such callback. The check of `use_cnt`
  does not join a callback that passed the check earlier. Sources:
  [core][core], `__power_supply_changed_work()` and
  `power_supply_external_power_changed()`; AXP descriptors above.
- **Extensions:** register/unregister of a supply extension calls
  `power_supply_update_sysfs_and_hwmon()`, which calls `power_supply_changed()`.
  Joining D does not retire extension users or their callbacks. No extension
  registration exists in the three AXP drivers inspected. Source:
  [core][core], lines 1396–1476; AXP sources above.
- **The USB PHY:** its notifier queues the PHY's own detection work; that is
  not another call to `power_supply_changed()`. It does retain a managed supply
  reference and later reads the supply. PHY removal unregisters its notifier,
  retires its detection IRQs and cancels detection before managed references
  are released. Sources: [PHY][phy],
  `sun4i_usb_phy0_vbus_notify()`, probe and `sun4i_usb_phy_remove()`;
  [board DTS][dts], `usb0_vbus_power-supply`.

The PHY reference is particularly important when designing an unbind test:
forcing removal of a supply while its consumers remain active can keep the
allocation alive while violating the driver-resource contract, and may trigger
the unregister warning. A no-UAF result obtained that way is not a proof of
correct teardown. This audit establishes the AXP producer order and the
deferred-worker exclusion; it does not qualify every supplier/consumer removal
sequence, fw_devlink topology, or the broader MUSB/PHY teardown work tracked in
[report 139](139-musb-teardown-power-audit.md).

## Remediation and its proof boundary

For the core-owned deferred producer, the suitable minimal order is:

```c
psy->removing = true;
cancel_delayed_work_sync(&psy->deferred_register_work);
cancel_work_sync(&psy->changed_work);
```

The existing `use_cnt` decrement and later resource teardown stay in their
current positions. After the first join, D cannot enqueue again; after the
second, C cannot still be running or pending because of D. The core queues D
only once during successful registration, and D does not rearm itself. This
establishes the producer-before-consumer ordering independently of whether U
holds the parent lock. Source: [core][core], registration, D and unregister;
[workqueue semantics][workqueue].

This proof assumes all independent callers of `power_supply_changed()` have
been stopped and joined before the final drain. A deliberately admitted IRQ,
poll, extension change or other caller after that drain can still queue C.
Neither the reorder nor an extra unlocked `if (psy->removing)` test repairs
that ownership violation: a caller can pass a test and pause before enqueue,
and a pointer may already be invalid when the test is evaluated. Replacing
cancellation with `disable_work_sync()` blocks later queue insertion while the
work object exists, but callers still touch the supply, lock and wake state.
It cannot grant arbitrary callers a lifetime after unregister. Sources:
[core][core], `power_supply_changed()`; [workqueue][workqueue],
`disable_work()` and `disable_work_sync()`.

Likewise, retaining an extra reference for queued work alone would not retain
every driver's private resources and would require careful handling of queue
coalescing and cancellation. It is unnecessary for this bounded producer-order
repair. No queue, freeze policy, charger setting, polling interval or parent
locking change is required. A production patch should preserve the existing
removal escape, explain the producer relationship, and be qualified separately
from the current audit/test-only work.

## Upstream history

[Commit 7f1a57fdd6cb][defer-commit] introduced deferred registration to prevent
early notification callbacks from reading incompletely initialized driver
state. Its parent-mutex synchronization was an initialization barrier. The same
commit added delayed-work cancellation after notification cancellation, so the
order predates this project's freezable-queue change.

[Commit 3ffa6583e24e][removing-commit] later fixed a removal deadlock: the
unregistering path could hold the parent mutex while waiting for D, which was
itself blocked on that mutex. It introduced the trylock/sleep/removing escape
but retained the two cancellations' order. Its reported Wacom stack is evidence
for that historical deadlock, not evidence of this audit's late-enqueue UAF.

Both commits and the pinned stable source were checked in the upstream
repositories during this audit. The history explains why the removal flag
exists; it does not establish a universal rule that every caller of
`power_supply_unregister()` owns the parent lock. The Corsair runtime worker
above is a concrete counterexample in the pinned source. No claim is made that
a later mainline release or all other power-supply drivers were exhaustively
audited.

## Reproduction and qualification boundary

The saved source test extracts `power_supply_changed()`,
`power_supply_deferred_register_work()` and `power_supply_unregister()` from
the hash-verified locked archive, applies the existing notification-freezer
patch, and compares the original functions with a **test-only** reversal of
the cancellations. It never modifies the installed kernel or production patch
queue. The harness is
[`kernel/tests/power_supply_lifetime_test.c`](../kernel/tests/power_supply_lifetime_test.c).

The deterministic cases distinguish pending, already-running and completed
deferred work; absent, available and held parent locks; and initially pending
or empty notification work. A running callback is modeled as paused before its
body and allowed to complete while unregister joins it. With no parent or an
available parent, it queues a notification even though `removing` is already
true. Original cancellation order leaves that notification pending at the
modeled device release; the reordered comparison drains it. With the parent
held, the callback takes its removal escape. This exercises a concrete late
enqueue schedule, not the separate already-acquired-lock pause shown in the
table above.

Two additional ordinary-registration cases ensure the deferred callback still
emits its notification. A final independent producer is deliberately admitted
after the final drain: both variants leave work pending, demonstrating why the
reorder is insufficient without caller quiescence. The test observes pending
work at a modeled release boundary; it does not execute freed memory or the
notification worker itself.

Run the complete saved comparison with:

```sh
task test:power-supply-lifetime
```

The [runner](../tools/check-power-supply-lifetime.py) uses the pinned builder
and `qemu-arm` for the ARM32 execution. Each variant passes 21 scenarios on
native and ARM32 builds: 42 scenarios per architecture. Here, passing the
original variant means reproducing its late-pending-work behavior, not declaring
that behavior safe. Both native controls that deliberately demand the opposite
variant's behavior fail the expected assertion. No driver object or complete
kernel was rebuilt for this audit.

Final evidence is `.local/build/power-supply-lifetime-tests/evidence.json`,
SHA-256 `230eb2dc6d732ed60c72479a175706ff35273a652abd1f566a0d2dd18e9e63d7`.
It records the verified kernel archive, patched core, harness, runner and
builder identities. The final `task check` also passes 13 runtime and 550
tooling tests (one existing optional user-systemd skip), compiled checks and
shell lint. Diagnostic.19's independent awake results are in
[report 156](156-diagnostic19-unattended-validation.md); those do not exercise
power-supply unregister.

A deterministic scheduler model establishes that the modeled ordering follows
the source and that an adverse schedule is rejected by the candidate. It does
not execute Linux's real scheduler, devres, refcounts, IRQ controller or PMIC.
An ARM object build establishes compile compatibility; neither it nor an awake
hardware health check reproduces or rules out this teardown race. Kernel-level
fault injection with controlled worker gates and KASAN would provide stronger
runtime evidence before a broad upstream claim. Unattended board unbind is not
required to complete this audit and was not performed by the researcher.

[core]: ../.local/sources/linux-6.18.54/drivers/power/supply/power_supply_core.c
[upstream-core]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/power/supply/power_supply_core.c
[workqueue]: ../.local/sources/linux-6.18.54/kernel/workqueue.c
[workqueue-doc]: https://docs.kernel.org/core-api/workqueue.html
[device-core]: ../.local/sources/linux-6.18.54/drivers/base/core.c
[wakeup]: ../.local/sources/linux-6.18.54/drivers/base/power/wakeup.c
[dd]: ../.local/sources/linux-6.18.54/drivers/base/dd.c
[devres]: ../.local/sources/linux-6.18.54/drivers/base/devres.c
[usb]: ../.local/sources/linux-6.18.54/drivers/power/supply/axp20x_usb_power.c
[ac]: ../.local/sources/linux-6.18.54/drivers/power/supply/axp20x_ac_power.c
[battery]: ../.local/sources/linux-6.18.54/drivers/power/supply/axp20x_battery.c
[usb-diag]: ../.local/sources/linux-6.18.54/drivers/power/supply/axp20x_usb_diag_impl.h
[devm-work]: ../.local/sources/linux-6.18.54/include/linux/devm-helpers.h
[irq-devres]: ../.local/sources/linux-6.18.54/kernel/irq/devres.c
[irq-manage]: ../.local/sources/linux-6.18.54/kernel/irq/manage.c
[debugfs-file]: ../.local/sources/linux-6.18.54/fs/debugfs/file.c
[debugfs-inode]: ../.local/sources/linux-6.18.54/fs/debugfs/inode.c
[sysfs]: ../.local/sources/linux-6.18.54/drivers/power/supply/power_supply_sysfs.c
[phy]: ../.local/sources/linux-6.18.54/drivers/phy/allwinner/phy-sun4i-usb.c
[dts]: ../kernel/overlay/arch/arm/boot/dts/allwinner/sun8i-r16-clockworkpi-cpi3.dts
[corsair]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/hid/hid-corsair-void.c
[defer-commit]: https://github.com/torvalds/linux/commit/7f1a57fdd6cb6e7be2ed31878a34655df38e1861
[removing-commit]: https://github.com/torvalds/linux/commit/3ffa6583e24e1ad1abab836d24bfc9d2308074e5
