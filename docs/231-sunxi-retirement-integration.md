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

The corrected source and compilation checks pass:

| Check | Result |
| --- | --- |
| Sunxi source model, native and ARM32 | 240 scenarios each; eight negative controls rejected |
| Extcon source model, native and ARM32 | 29 scenarios each; seven negative controls rejected |
| Core retirement model, native and ARM32 | 43 scenarios each; 34 mutation controls and six source-boundary controls rejected |
| Extcon ARM builds | Board/TREE, standalone module/TREE, TINY; five objects plus notifier/SRCU symbol checks |
| Combined ARM builds | Project, host, dual-role, module, no-PM; 31 objects |
| Repository checks | 16 runtime and 834 tooling tests pass; two optional skips; shell checks pass |
| Production patch style | All three patches: zero checkpatch errors/warnings |

Real-kernel execution passes too: **nine notifier cases and ten provider cases
under each SRCU configuration (38 passing case executions)**. KASAN, lockdep,
RCU and atomic-sleep diagnostics produced no rejected warnings. The final
receipts match the current input hashes and production patch queue. All retained
kernel/config/log/report hashes were rechecked, and each saved report was
readmitted through the strict validator. Within each configuration, both suites
used the identical kernel binary and kept separate accepted artifact directories.

The initial
sandboxed repository-check attempt could not run local socket fixtures; the
same saved checks passed outside that sandbox. No remote connection was made.

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

Reviews against baseline `66e3b55` initially found one Spec defect and one
Standards duplication judgement (no hard standards violation). Both were
addressed in `1209f56`. Separate follow-up reviews report **Standards: zero
remaining findings; Spec: zero remaining findings**. They explicitly leave
final test admission to the retained evidence described above.

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


## Final evidence receipts

Validation completed 9 October 2026 (UTC), code at `1209f56`. Paths below are
relative to `.local/build/` in this worktree; complete source/configuration and
artifact identities are recorded inside each receipt.

| Receipt | SHA-256 |
| --- | --- |
| `sunxi-owner-tests/evidence.json` | `1de2998d194920e8fab374f23cbed8e2adacf1201b2b135a104b168be0b14c49` |
| `extcon-notifier-tests/compile-evidence.json` | `4f2b3cc9aa4e44c7f75e046d6497152681b9f13f6c6389c19b03c9c158668732` |
| `musb-irq-tests/compile-evidence.json` | `34ac83522ee827f5d975cf88a905371e03e7d11044158629cd8943e8c50f2ece` |
| `extcon-kunit/evidence-notifier-all.json` | `a8cb324c53af7c933721af7ee803ba046f794377790108bc8568b5f736e2b30c` |
| `extcon-kunit/evidence-provider-all.json` | `2d22cfb06fa0add99995c4beb232c72e5eb4aaf609599d53dd04a97a65d03afc` |
