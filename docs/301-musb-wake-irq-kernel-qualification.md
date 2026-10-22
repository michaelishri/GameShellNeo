# MUSB wake ownership through kernel IRQ traversal (NEO-218)

23 October 2026, Pacific/Auckland. This bounded offline child of NEO-98 starts
at `5a2f362a39e49415b6a73e732219007ab8f4eb00` in the isolated
`work/musb-wake-irq-qualification` checkout. Kernel qualification used accepted
main `5505fd90e9cd98038fef785bfe6ba19e6548a739`. After all original writers
completed, the branch adopted published main
`49b1c237ea3cd822195362f9462285fc1ee9a75c`. The positive suite passes all eleven
cases; corrected control-oracle execution and independent reviews are pending.
The wider parent remains open.

## Acceptance boundary

Report 291 retains exact wake/startup candidates 0026/0029 and tests copied
actual-source IRQ functions. Those tests do not walk the running kernel's IRQ
descriptors. This suite adds that specific missing acceptance check using the
full MUSB driver and real `suspend_device_irqs()` / `resume_device_irqs()` in a
disposable Linux UML guest with KASAN and lockdep.

The selected source profile remains `musb-wake-startup`. Its MUSB extraction
includes production 0011/0025/0030/0033/0037 and exact candidates 0026/0029 in
queue order. The complete immutable kernel source replays the full production
queue plus that profile and a generated test-only append. The append adds the
fixture include and its Kconfig symbol; it does not replace production
functions in the positive suite. A separately identified source control changes
only the suspend wake-policy condition in a disposable source tree. Retirement
candidates, the image patch queue, source lock and board
configuration remain outside this change.

The hardware boundary consists of a guest-local level irqchip, controlled chip
errors, a byte/word register bank and counting shared IRQ handlers; the physical
MUSB ISR is not invoked. The fixture calls the actual MUSB wake
initialization, system suspend/resume and cleanup functions. Linux owns shared
IRQ actions, wake-depth accounting, runtime-PM references and global IRQ
traversal. It restores guest IRQs before allocating, sleeping or asserting.
A synthetic level source is explicitly reasserted after resume; this does not
qualify physical pending-event replay.

## Cases and failure ownership

The named cases cover balanced compatibility probing, unsupported wake chips,
foreign device capability, failed compatibility disarm, enabled/disabled wake
policy, shared peer references acquired before/after MUSB, failed system arm,
failed resume disarm and a runtime-resume failure. The policy cases observe
actual `IRQD_WAKEUP_ARMED`, disabled state, wake reference count, handler
suppression during suspend and action delivery after resume. Shared-peer cases
require MUSB to preserve the peer's reference even when MUSB wake policy is off.

Injected errors are checked before teardown, including the IRQ core's restored
reference after failed chip disarm. A later failed suspend must report retained
debt without adding another reference or touching registers. The fixture clears
its artificial chip error only after those observations so it can release its
disposable resources; this is not a production retry or final-destruction fix.

The runner has a dedicated `--suite wake` route and saved
`task test:musb-wake-kunit`. Other suites keep their existing retirement profile
and ownership behavior. Wake builds use the pinned local builder with networking
disabled, a fresh managed receipt and retained result/log. The evidence validator
requires every named case exactly once, all passing, and rejects kernel warnings,
skips, extra suites and incomplete logs. Host guards reject missing, duplicated,
reordered and retirement-composed source profiles.

`task test:musb-wake-policy-control` compiles a separate disposable source tree
with `musb_suspend()`'s wake-policy condition forced true. The control must execute
the kernel and fail exactly five named cases: unsupported wake-chip handling,
disabled-policy IRQ/reference assertions, both shared-peer cases, and the
policy-off recovery step in the disarm-error case. All six other cases must pass.
The checker binds each expected assertion and observed value to its named case,
including armed=true/reference=1 under disabled policy, peer reference=2, and
an extra arm/owned reference after debt recovery. The last failure follows
directly from the same mutation: clearing retained disarm debt must not arm
again when policy is disabled, while the forced condition always arms.
A compile/setup failure, kernel diagnostic or unexpected failing case is
inconclusive. Its failed managed result and `control-evidence.json` stay separate
from positive success evidence.

## Qualification status

The initial overbroad retirement guard
incorrectly rejected the unchanged production 0037 dependency; its original
five-test/two-error observation is retained privately, and the corrected guard
selects all seven intended MUSB source inputs. The first managed kernel run,
`dbb46b26278a47fe815246dd96d87340`, exited 1 with a fixture-only compiler error:
it initialized `resume_work_wait`, which belongs to the separate retirement
profile. Its authoritative result confirms no stop or OOM and unchanged hashed
inputs. That initialization is removed. The next original run,
`1c38b5368fe1409c91ec8b93e99d963c`, compiled and executed all eleven cases:
ten passed, and the enabled-policy setup failed because it tried to enable the
source already enabled by initialization (`-EEXIST`). The fixture now disables
the policy before explicitly enabling it. Both original results/logs and the
second run's kernel, complete KTAP and JSON remain retained. No driver source
is changed.

The corrected positive run `9c2aa17e3fd9419ebee65ae47bbbf860` compiled the whole
UML kernel and passed all eleven cases with KASAN/lockdep, no kernel diagnostic,
no stop/OOM and unchanged maintained input hashes. The first compiled source
control, `101d3ef869374921bb10dd26ca72c3b6`, then executed all eleven cases:
six passed and the five source-justified cases above failed. Its original
wrapper predicted only four and rejected the additional debt-recovery failure.
That rejected wrapper result, complete logs/KTAP/JSON and kernel remain historical
and unchanged. The exact five-case oracle now requires the specific IRQ/reference
assertions in each named case; fresh cached-kernel execution is pending.

Private logs and receipts are retained under
`.local/build/musb-wake-kunit/`; the report will record exact managed run and
artifact identities after authoritative completion.

## Remaining NEO-98 gates

This suite does not qualify the complete device-DPM traversal, allocation failure
or sysfs concurrency, terminal failed-disarm/destruction ownership, retirement
composition, other physical controllers, SMP, an image, deep sleep or the board.
Those remain explicit NEO-98 work. This milestone grants no board clock/PM
admission; no Mac, GameShell, reboot, cable or deployment operation is part of
this offline work. NEO-216's separately parked probe artifacts are
preserved without reuse.
