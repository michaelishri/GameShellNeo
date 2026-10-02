# Returning PMIC parent wake errors safely

2 October 2026. Source and upstream-history research supporting the shallow
sleep preparation in [report 98](98-shallow-sleep-readiness.md). This report
does not implement a kernel change or establish a hardware wake result.
The baseline is Linux `v6.18.54`, commit
`1b357ecb321392158d507b04672ffee57bfa071d`, from the
[source lock](../build/sources.lock.json). Line numbers below describe that
baseline unless a project patch is named.

## Recommendation

Use a bounded synchronous parent-wake path in regmap IRQ for controllers
**without a wake register bank whose parent IRQ chip has neither bus-lock
callback**. Return the public `irq_set_irq_wake(parent, on)` result directly
from the child wake callback, without queuing a second operation in
`wake_count`. Preserve the existing deferred path for other topologies.
This is an engineering recommendation derived from the locking and
reference-count contracts below, not an upstream-approved patch.

The predicate can be derived per registered regmap IRQ instance. That is
smaller than a new public `regmap_irq_chip` flag and avoids making every
AXP221/223 installation opt into an assumption about its parent controller.
For a cached predicate, inspect the parent chip after its successful
`request_threaded_irq()`, because IRQ setup may select a chip while setting
the trigger type. Document that the parent chip's relevant bus-hook
properties must remain stable during registration. R_INTC satisfies the
inspected assumptions; the generic IRQ API does permit chip replacement.
[regmap-irq.c:924–940][regirq], [manage.c:1673–1680][manage],
[chip.c:36–54][irq-chip], [irqdesc.h:215–240][irqdesc-h].

The change should be described as **propagating parent wake errors for this
eligible topology**, rather than fixing every regmap IRQ wake error. Slow
parents and controllers with wake registers still need a broader error-return
and transaction design. Existing PMIC mask/ack write failures are also outside
this narrow parent-reference transaction. [regmap-irq.c:83–207][regirq].

## Why unconditional forwarding is unsafe

`irq_set_irq_wake()` acquires the IRQ chip's bus lock and then the child
descriptor's raw spinlock, with local IRQs disabled. It calls the child's
`irq_set_wake()` while both are held. Its cleanup drops the raw lock before
calling `irq_bus_sync_unlock()`. These are separate lock scopes, even when
all calls originate in a sleepable device suspend callback.
[manage.c:825–894][manage], [irqdesc.c:850–879][irqdesc],
[internals.h:149–160][irq-internals].

For regmap IRQ, the bus lock is `mutex_lock(&d->lock)`. The existing wake
callback only edits `wake_buf` and `wake_count`; its void sync-unlock later
calls parent enable/disable and discards their results. The child IRQ core
has already accepted success by then. Logging a later parent error cannot
repair the returned value or the committed child wake depth/state.
[regmap-irq.c:76–83, 197–207, 278–306][regirq],
[manage.c:868–890][manage].

If every parent call were moved into the child wake callback, a parent
implemented by regmap IRQ would acquire a mutex while the child's raw lock
is held. This is a real supported topology: upstream's 2025 fix records a
MAX77686 RTC below a MAX77620 controller. The fix supplies per-instance bus
mutex lockdep keys; it does not make those mutexes atomic-safe.
[Upstream commit 76b6e14aa7b0][nested-fix],
[regmap-irq.c:803–811][regirq].

The bounded path's lock order is:

```text
child regmap bus mutex
  child IRQ descriptor raw lock
    parent IRQ descriptor raw lock
      parent irq_set_wake callback
    unlock parent raw lock
  unlock child raw lock
  existing regmap register synchronization, which may sleep
unlock child bus mutex
```

The parent public API executes no bus operation when both parent bus hooks
are null. Its own wake callback must already obey an atomic context contract,
because the IRQ core invokes it under the parent's raw lock in ordinary use.
Checking only `irq_bus_lock` is insufficient: a lone sync-unlock hook could
still sleep before the recursive public call returns. These conclusions
follow from [irqdesc.c:850–879][irqdesc] and
[manage.c:825–894][manage].

This is not a runtime proof of arbitrary callback internals. An invalid
parent callback that recursively reaches another sleepable bus is already
invalid under its own raw descriptor lock. A platform opt-in can express a
stronger audited-topology contract if that is required for upstream review;
the board's complete R_INTC callback is inspected below.

## AXP223 and R_INTC satisfy the bounded conditions

The board connects AXP223 at RSB address `0x3a3` to R_INTC hardware IRQ 32.
The AXP22x regmap IRQ definition provides status, acknowledgement and unmask
banks, but no `wake_base`; regmap therefore allocates no `wake_buf`.
[Board DTS:171–182][board], [axp20x.c:850–860][axp],
[regmap-irq.c:744–749][regirq].

Both R_INTC chip variants omit the bus hooks. Their wake callback changes
a bitmap for supported direct or muxed IRQs and returns `-EPERM` otherwise.
It performs no regmap operation, does not acquire a mutex, and does not
propagate wake to the GIC. IRQ 32 is the supported NMI/direct range base on
this board. Thus the normal mapping is not evidence that a parent failure
currently occurs; injected failure is needed to verify the repaired error
path. [irq-sun6i-r.c:68–72, 159–195, 317–328][r-intc],
[SoC R_INTC description][soc].

The nested child descriptor uses `regmap_irq_lock_class`, while the R_INTC
parent uses a different descriptor class. Preserve these annotations.
Regmap's per-instance `d->lock_key` applies to its bus mutex; it is not the
descriptor lock key and cannot justify nesting two descriptor locks with
the same class. A direct regmap parent is excluded by the bus-hook check.
[regmap-irq.c:533–546, 803–811][regirq],
[irqdesc.c:25, 215–225][irqdesc].

Arizona provides a useful existing pattern: its wake callback returns the
public parent's `irq_set_irq_wake()` result, and its mapped child descriptors
have a distinct lock class. Its 2016 accepted correction used those class
annotations instead of adding bus-lock deferral merely to avoid a warning.
This is a precedent for the mechanism, not proof about all possible regmap
parents. [arizona-irq.c:172–197][arizona],
[accepted Arizona v2 patch][arizona-v2].

## Reference ownership and failure invariants

Keep the public parent API. Calling `parent_chip->irq_set_wake()` directly,
or substituting `irq_chip_set_wake_parent()`, bypasses the separate parent
descriptor's wake-depth accounting. The latter helper traverses hierarchical
`irq_data`, whereas regmap's children have their own mapped descriptors
and a shared parent Linux IRQ. [regmap-irq.c:536–546][regirq],
[chip.c:1453–1471][irq-chip], [manage.c:857–894][manage].

The IRQ core invokes a chip wake callback only for a child's zero-to-one
or one-to-zero depth transition. A failed enable restores depth zero; a
failed final disable restores depth one and leaves `IRQD_WAKEUP_STATE` set.
Returning the parent result unchanged lets the same rule apply at both
levels. No compensating parent call is needed when the parent's public API
itself fails. [manage.c:868–890][manage].

For the eligible path, preserve this invariant, derived from that core code:

```text
parent wake_depth = independent parent references
                  + number of regmap children with nonzero wake_depth
```

Repeated enables on the same child increase its local depth but do not add
another parent reference until the child's depth returns to zero and is
enabled again. PEK's two edges are distinct children; USB insertion and AC
insertion are two more. Their suspend order must not change ownership.
[PEK:330–361][pek], [AC:285–314][ac],
[USB project patch](../kernel/patches/0010-axp-usb-suspend-work.patch),
[manage.c:868–890][manage].

| Operation, starting with no independent parent references | Child state after return | Parent depth / hardware callback |
| --- | --- | --- |
| First PEK edge enable succeeds | First edge depth 1 | Depth 1; parent hardware enable runs |
| Second PEK edge, USB insertion, AC insertion enable | Each enabled child depth 1 | Depth 4; no further parent hardware enable |
| Any three of those children disable | Their depths 0 | Depth 1; parent stays enabled |
| Final child disable succeeds | Final depth 0 | Depth 0; hardware disable runs |
| First parent hardware enable fails | Attempted child's depth 0 and wake bit clear | Depth 0; error reaches client |
| Final parent hardware disable fails | Final child's depth 1 and wake bit retained | Depth 1; error reaches client |

This table is a derivation from the core algorithm, not a test result.
Each client must retain its own ownership flag after a failed disable and
must avoid stacking another enable on a later suspend. A failing device's
suspend callback must unwind earlier successful arms itself; a successful
second PEK edge cannot be assumed when its call failed. Keep cleanup errors
observable and preserve the remaining owned reference.

Tests must distinguish failure of a **second child arm** from failure of a
**second parent hardware enable**: when another child already owns a
reference, the real parent hardware callback is not invoked at all. Inject
the former at the child/public-call boundary; inject a real parent error at
the first enable or final disable. [manage.c:868–890][manage].

## Wake-register errors and the wider API option

For controllers with `wake_base`, the buffered wake-mask change is written
through `regmap_update_bits()` in sync-unlock. A write error is logged but
cannot reach the wake caller. Moving only the parent call earlier leaves
that defect and can create two independent failure points: child wake-mask
I/O and parent reference ownership. [regmap-irq.c:140–155, 197–207][regirq].

That is why the bounded synchronous path should exclude all controllers
with wake registers. An eventual general solution needs a sleepable,
error-returning wake transaction outside the child raw lock, while retaining
serialization against concurrent child wake updates. A dedicated IRQ-core
wake callback or preparation/commit mechanism is a possible design. It must
specify rollback order, ownership after failed rollback, partial register
writes, register-cache state, runtime-PM failure, and nested parent calls.
This is a proposed API direction, not a claim that such an API exists in
the pinned tree. [irq_chip API:464–511][irq-h],
[regmap synchronization][regirq], [wake-depth commit][manage].

Changing `irq_bus_sync_unlock` from `void` to `int` is not sufficient on its
own. The IRQ core currently commits the child's depth/state before that
callback, and the callback also releases the serialization mutex. A rollback
after it returns must not race another wake transaction. Likewise, dropping
the child's raw lock from inside an ordinary `irq_set_wake` callback violates
the core callback scope. A correct general change needs an explicit core
protocol, not a driver-local unlock/relock trick.
[irqdesc.c:874–879][irqdesc], [manage.c:857–894][manage],
[regmap-irq.c:197–207][regirq].

| Approach | Engineering assessment |
| --- | --- |
| Unconditional direct parent call | Reject: sleeping nested-parent bus locks under the child raw lock. |
| Log errors in sync-unlock | Useful diagnostics, but child return/state and parent ownership remain inconsistent. |
| Explicit per-platform atomic-parent opt-in | Safe with audited parent topology, both bus-hook checks, no wake bank, correct lock classes and stable parent properties; larger public configuration surface. |
| Set that opt-in on the shared AXP22x definition | Avoid assuming all boards use R_INTC. Rejecting incompatible parents at probe would unnecessarily break their entire MFD; rejecting wake changes also changes previously accepted suspend behavior. |
| Derive the bounded path per instance, preserve the fallback | Recommended for this repair, with the parent-lifetime assumption documented and tested. Returns genuine errors for eligible instances without changing slow-parent registration. |
| New sleepable IRQ-core wake transaction | Appropriate route to complete generic error handling; requires broader IRQ/regmap review and transactional tests. |

Even without wake registers, ordinary unmask/ack synchronization can still
fail. Successful parent arming proves the parent API transaction succeeded;
it does not prove PMIC I/O health or physical wake delivery.
[regmap-irq.c:109–183][regirq].

## Historical and current upstream evidence

- Mark Brown's June 2012 wake-support patch introduced buffered wake state
  and deferred parent wake-count propagation. [Original patch][initial-wake].
- Laxman Dewangan's December 2012 change enabled parent wake support even
  without a device wake register bank. Thus absence of `wake_base` does not
  mean absence of wake support. [Original patch][no-wake-bank].
- Arizona's accepted April 2016 correction used a distinct child descriptor
  lock class with direct parent forwarding. [Accepted patch][arizona-v2].
- The November 2024 regmap change, commit
  `953e549471cabc9d4980f1da2e9fa79f4c23da06`, added descriptor/request lock
  classes when mapping regmap IRQs. [Maintainer application][desc-class].
- The August 2025 nested-regmap fix, commit
  `76b6e14aa7b081337d118a82397d919b5e072bb4`, allocated a per-instance bus
  mutex key for real nested controllers. [Merged commit][nested-fix].
- Upstream `master` inspected on 2 October 2026 still used the deferred
  counter and unconditional success in the regmap wake callback. This was
  a bounded current-source check, not an exhaustive search of every pending
  mailing-list proposal. [Upstream file][upstream-regirq].

## Verification required for the implementation

Exercise actual IRQ-core child and parent depths and wake-state flags,
with a fake parent chip and fault injection. Cover first-enable failure,
successful shared PEK/USB/AC arms, repeated enables on one child, last-disable
failure, retry cleanup, and repeated cycles. Verify the eligible path never
also queues `wake_count`; include independent parent references. These are
tests of the invariants above, not source-text or call-count assertions alone.

Use separate sleepable parent-bus and wake-bank fixtures to prove those
instances stay on the deferred path without a sleep-under-raw-lock warning.
Enable lockdep and atomic-sleep debugging when exercising both eligible and
nested paths. Preserve the existing mutex and descriptor lock classes.
If eligibility is cached, include trigger setup that replaces the parent
chip before request completion; document later chip replacement as outside
the cached-property contract. These cases follow from the source contracts
and the upstream regressions cited above.

Compile the relevant ARM drivers and then use the planned bounded PM
`platform` qualification before any real s2idle trial. Physical PEK wake,
USB/AC wake policy and retained wake ownership still require hardware
evidence; this research supplies none. [Report 98](98-shallow-sleep-readiness.md).

[regirq]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/base/regmap/regmap-irq.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[manage]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/irq/manage.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[irqdesc]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/irq/irqdesc.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[irqdesc-h]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/linux/irqdesc.h?id=1b357ecb321392158d507b04672ffee57bfa071d
[irq-internals]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/irq/internals.h?id=1b357ecb321392158d507b04672ffee57bfa071d
[irq-chip]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/irq/chip.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[irq-h]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/linux/irq.h?id=1b357ecb321392158d507b04672ffee57bfa071d
[r-intc]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/irqchip/irq-sun6i-r.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[axp]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/mfd/axp20x.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[board]: ../kernel/overlay/arch/arm/boot/dts/allwinner/sun8i-r16-clockworkpi-cpi3.dts
[soc]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/boot/dts/allwinner/sun8i-a23-a33.dtsi?id=1b357ecb321392158d507b04672ffee57bfa071d
[pek]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/input/misc/axp20x-pek.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[ac]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/power/supply/axp20x_ac_power.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[arizona]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/mfd/arizona-irq.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[initial-wake]: https://lkml.iu.edu/1206.0/01574.html
[no-wake-bank]: https://lists.openwall.net/linux-kernel/2012/12/19/230
[arizona-v2]: https://lkml.rescloud.iu.edu/hypermail/linux/kernel/1604.1/01667.html
[desc-class]: https://lists.openwall.net/linux-kernel/2024/11/04/1119
[nested-fix]: https://github.com/torvalds/linux/commit/76b6e14aa7b081337d118a82397d919b5e072bb4
[upstream-regirq]: https://raw.githubusercontent.com/torvalds/linux/master/drivers/base/regmap/regmap-irq.c
