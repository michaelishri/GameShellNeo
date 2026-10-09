# Sunxi notifier and worker retirement integration

NEO-169, child of NEO-106. Host-only candidate on `work/sunxi-retirement`,
based on `66e3b55` and pinned Linux 6.18.54. NEO-108's card swap stays parked.
This slice makes no connection to the GameShell or Mac and builds no image.

## Acceptance contract

Integrate the earlier Sunxi child-owned notifier/worker candidate with the
completed core IRQ, work/timer, runtime-PM and pending-resume retirement queue.
A successful child initialization owns exactly one connector notifier. Exit
and failed PHY initialization must unlink and drain it, then permanently
disable the glue worker before releasing PHY, reset, clock or SRAM resources.
A new child must enable the worker and reconstruct current connector/default
role state. Ordinary disable/enable must remain restartable.

The extcon provider must stay bound while the parent and child use it. Resolve
lookup and managed link admission together; defer providers still probing or
unbinding. Preserve explicit consumer cleanup before failed-probe return.
Do not claim whole-provider or all-backend removal safety from these contracts.

Validate the combined source queue with actual-source regression models,
negative controls, relevant ARM configurations, and real Linux SRCU/driver-core
lifetime tests. Keep KUnit fixtures out of the production queue. Save scripts,
commands and evidence, review standards and specification, then commit/push.

## Changes and provenance

These candidates were previously reviewed separately in reports 144–147 on
`work/musb-removal-lifetime` at `48af268`. That branch's patch numbers collide
with subsequent core work, so this integration carries three production patches
forward explicitly instead of merging the old branch wholesale.

| Previous patch | Current patch | Responsibility |
| --- | --- | --- |
| 0031 | 0043-extcon-notifier-drain.patch | Per-provider SRCU envelope around raw notifier traversal; opt-in synchronous consumer unlink/drain |
| 0033 | 0044-sunxi-child-notifier-work.patch | Child ownership, failed-init cleanup, terminal work disable, current-state role reconciliation on rebind |
| 0034 | 0045-extcon-provider-link.patch | Managed provider link during lookup, fully bound supplier admission, Sunxi parent integration |

The existing core stack through patch 0042 retires its owned IRQ, timer/work,
runtime-PM and pending-resume callbacks before the platform exit/resource tail.
The Sunxi exit then clears normal enablement, synchronously unlinks the
notifier, calls `disable_work_sync()`, and only then drops its PM reference
and releases PHY/reset/clock/SRAM. A notifier selected before unlink remains
inside the SRCU reader until its callback returns. A late queue attempt cannot
restart a disabled work item. This does not extend the lifetime of the caller
making that attempt.

Notifier registration moves from parent devres to child init/exit ownership.
PHY-init failure drains explicitly before unwinding; notifier-registration
failure only disables work because it never owned a registration. Earlier
SRAM/clock/reset failures leave the parent work item disabled. Child rebind
preserves hardware capability flags, resets transient state and samples the
current connector rather than replaying a cached event. Ordinary disable only
clears enablement and remains distinct from terminal work shutdown.

The provider API adds a managed `DL_FLAG_AUTOREMOVE_CONSUMER` link without
runtime-PM flags. It requires probing consumer and fully bound supplier state,
and holds the extcon registration-list mutex through lookup/link admission.
It does not acquire a permanent power reference. Consumer cleanup must run
before returning a probe error because driver-core link cleanup precedes
failed-probe devres cleanup. Existing raw lookup APIs remain unchanged.

The drain adds an SRCU reader pair to each extcon dispatch and per-provider
SRCU state. Teardown pays the grace-period wait; normal notifications do not
sleep merely to obtain that reader. This is a lifetime-correctness tradeoff,
not a measured speed or energy optimization.

## Reproducible validation

Run from this worktree, sequentially through the saved Task commands:

```sh
task test:sunxi-owner
task check:extcon-drivers
task check:musb-irq-drivers
task test:extcon-kunit
task test:extcon-provider-kunit
task check
```

The extcon KUnit C fixtures and Kconfig/Makefile patches now live under
`kernel/tests/`. Only the KUnit runner appends them to the production queue in
an isolated source tree. Both suites share a compiled UML kernel for each
SRCU configuration and are selected separately at boot; this avoids compiling
the same kernel twice. TREE/PREEMPT and TINY/PREEMPT_NONE still use separate
kernels. Both enable KASAN, lockdep, RCU and atomic-sleep diagnostics, and run
with `fw_devlink=off` to prove explicit links rather than inferred dependencies.

The source-derived runners require exact scenario summaries and record native
and ARM32 binary hashes. Extcon extraction applies every current queue hunk
for its framework files, including provider lifetime. The shared MUSB extractor
includes patches 0043–0045, and its five ARM builds now compile extcon core and
devres alongside the relevant MUSB objects.

Evidence lives under `.local/build/sunxi-owner-tests/`,
`.local/build/extcon-notifier-tests/`, `.local/build/musb-irq-tests/` and
`.local/build/extcon-kunit/`. KUnit evidence files use
`evidence-{notifier,provider}-{all,tree,tiny}.json`. Each accepted kernel run
retains its own kernel, effective config, raw log, JSON report and hashes;
subsequent suite runs cannot overwrite those accepted artifacts.

Results are pending at this implementation checkpoint.

## Review correction

The first review found that restoring only `glue->phy_mode` did not restore
Allwinner's persistent `data->dr_mode`. After an OTG child selected HOST, the
provider retained HOST across PHY exit/init. Resetting the cache made the new
child's ordinary default-mode request return early. Patch 0044 now also queues
a PHY-mode update, applied by the worker when the new child is enabled.

The model starts with the provider's configured default and explicitly checks
that a previous OTG-to-HOST override survives until rebind. It then requires
both the cached mode and provider mode to return to the default. An eighth
negative control removes only the new pending-mode assignment and must fail.
The duplicate native regression loops were also consolidated into
`tools/native_source_variants.py`; both source suites still retain separate
fixtures, source extraction and evidence. The initial in-progress UML build
was stopped before executing tests when this correction was identified;
its log is retained, with no accepted result for that candidate.

## Boundaries and next work

Source models exercise 240 Sunxi and 29 extcon scenarios but model workqueue,
IRQ/MMIO/PHY and some scheduling behavior. Framework KUnit runs real kernel
notifier/SRCU and device-link lifetimes, using synthetic providers/consumers
on one virtual CPU. They do not execute the entire Sunxi/MUSB/PHY unbind path.
The softirq notifier test suppresses userspace uevents; it does not qualify
the unsuppressed `extcon_sync()` uevent tail in interrupt context.

The real Allwinner PHY detector's own IRQ/work/resource lifetime and other PHY
consumers still need audit. The new link assumes the provider retains extcon
registration throughout its bound lifetime and retires the entire event
producer before freeing it, including the post-callback uevent tail. A failed
synchronous unlink is an invariant violation reported with `WARN_ON`, not a
successful drain or recovery strategy.

Independent DMA callbacks, other MUSB backends, externally admitted caller
frames/role setters, early platform-init resource unwind, truly inaccessible
hardware and the global Sunxi accessor pointer remain separate boundaries.
Core PM failure alone does not prove registers inaccessible. NEO-106 remains
open. No sleep, charging, speed or energy improvement is established by this
host-only integration; an eventual image needs a distinct identity and board
qualification before promotion.
