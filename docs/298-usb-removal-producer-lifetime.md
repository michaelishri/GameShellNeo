# USB removal producer and backend lifetime

23 October 2026 NZDT. NEO-106 remains open. This work starts from reviewed
main `98aff1fe86689c916cd930f2b5c5a8bb218088f0` in the isolated
`work/usb-removal-completion` checkout. The production image queue, preserved
source caches and frozen hardware checkout are unchanged. No Mac or GameShell
operation has been performed.

The review checkout also combines published main
`5a2f362a39e49415b6a73e732219007ab8f4eb00`. The original qualified feature
commit `57f885ea34412fe35ff99a58a4c20268bc9865eb` and its evidence checkout
remain intact. The only overlapping edits were Task/FOLLOW-UP/report-index
context; both report entries are retained. Every native and kernel receipt
input hash matches the combined source byte for byte. A fresh combined
`task check` passes all 1,283 regressions (nine skipped) and shell/workflow
checks; its log SHA-256 is
`07a5b6bd9ad7691112994c477ea9b37aaf783aa8a4e281feb9751eb990731dee`.

## Sun4i post-notification resource ownership (NEO-214)

The actual detector drops `phy0->mutex` before extcon dispatch. A consumer can
exit the PHY during that callback, asserting reset and disabling its clocks.
The original detector then resumes forced session-end, passby and dual-route
MMIO after those resources have been retired. It can also rearm a poll after
a VBUS callback exits the PHY. This is a source defect, not an observed board
failure.

[Candidate 0060](../kernel/candidates/musb-retirement/0060-sun4i-phy-detector-generation.patch)
adds a generation published by each successful PHY0 initialization under the
generic PHY mutex. The detector captures that generation with its first
resource admission. After host notification it reacquires the same mutex and
requires both initialization and the original generation before its hardware
tail. This covers a callback that exits and reinitializes the same object;
checking only a boolean would admit the old scan into its replacement state.
The final poll decision and queue are also admitted under that mutex after
VBUS notification. Notifications remain outside the mutex, preserving their
ability to call PHY operations. A new initialization retains its own immediate
rescan; an old scan never cancels it.

The candidate is added only to the explicit `musb-retirement` profile. The
ordinary USB PHY suspend regression and raw production image inputs retain
their original queues. Complete provider removal still needs the remaining
consumer graph, producer lifetime and parent/backend contracts documented in
reports 141, 147, 289 and 291.

The existing retirement profile's provider removal first unregisters the
power-supply notifier, then explicitly frees the two acquired detector IRQs,
then calls `cancel_delayed_work_sync()` before managed GPIO/extcon/clock state
is released. The corresponding late probe failures use that same cleanup.
These producer drains remain unchanged. They rely on the consumer/provider
contract to exclude new PHY operations; this slice does not establish that
full graph or authorize live provider removal.

```sh
task test:phy-detector
task check:phy-detector-drivers
task test:phy-detector-kunit
```

The actual-source harness executes the detector, exit, IRQ, power-supply
notifier and exact generation-publication slice. It covers live notifications,
exit and exit/reinit from both notification stages, forced session ends,
dual-route hardware, preserved replacement scans, polling and already-inactive
work. All **162 cases** pass natively, under ASan/UBSan, and on ARM32/QEMU.
Five independently compiled mutations lose publication, active admission,
generation admission, tail locking or poll admission and each fails its
required assertion. Clocks/reset/MMIO, notifier scheduling and workqueues are
explicit deterministic seams in this harness.

The complete PHY driver also compiles with verified effective configurations
for board gadget, host, dual role, modules and no PM. Receipt
`.local/build/phy-detector-tests/compile-evidence.json` has SHA-256
`b1e78427099d43d683135ad8b602f14f935a92eab46fcf04a53b3460d3e0aabd`.
Candidate SHA-256 is
`d1cc429523bed0c952955be24f4f28c657875f876276fe209ed452d79652804a`.

Real Linux UML qualification passes. It compiles the complete
actual driver with test-only hardware seams, then exercises actual init/exit,
delayed work, mutexes, extcon/SRCU dispatch and held kthreads. Ten cases cover
inline and parallel exit/rebind, VBUS polling, queued stale work, live polling,
exit blocked by a held hardware tail, and a safely intercepted unguarded
control. All ten pass under KASAN/lockdep with no kernel diagnostic. The
strict result parser rejects missing/duplicate/skipped cases and diagnostics.
GPIO/MMIO/clock/reset effects and pulse delays are test seams; generic-PHY
callers follow its mutex contract. This UML run does not establish SMP, the
complete provider/consumer graph, real-register behavior or board removal.

Managed run `92a505b7b0f74b3ca0d6bc0a02c7ca78` completed with exit zero;
its stage has no active container. The receipt
`.local/build/phy-detector-kunit/evidence.json` has SHA-256
`71010ace1e7a32efd652d14bdd3aad1676c1f88faf46eb2d2b12f15e08fc22ac`.
Independent copies of its kernel, effective config, complete test log and
JSON result are retained beneath
`.local/build/phy-detector-kunit/kernel-f91c82f0bb3d2ce8/accepted-runs/2d188f5c4aa441d4a94e0afa8d054010/`;
the receipt pins each hash and all maintained source/test inputs. Independent
Standards/Spec review and serialized integration remain pending.

The authorized offline `task check` passes all 1,283 Python regressions
(nine skipped), current-limit selection, Mac mount-guard fixtures, Bash syntax
and ShellCheck. Its retained log has SHA-256
`bbffb9ab6777a869693d1e096e333141feee962699a5ec3d93a7c773ab28e2bd`.

Original failed attempts are retained separately. The first host sanitizer
attempt reached the expected native assertions but LeakSanitizer could not
operate under host ptrace. The static harness allocates no heap; subsequent
ASan/UBSan execution explicitly disables leak detection and still fails on
address/undefined-behavior diagnostics. A sandbox Docker refusal started no
writer. The first escalated ARM matrix rejected an ineffective `CONFIG_PM=n`
override because SUSPEND selected PM back on; the corrected full no-PM
override disables PM_SLEEP/SUSPEND/HIBERNATION too. The original failure is
not relabeled as a no-PM pass. The first complete UML kernel panicked during
test setup in `extcon_dev_register()`, before any detector assertion: the
synthetic extcon lacked a parent. The corrected fixture follows the existing
extcon tests by registering a parent, uses the managed allocator to attach it,
and frees the extcon before unregistering that parent. That original panic
and the six sandbox-denied local-socket host checks remain retained; none is
reported as a detector result. The corrected kernel then passed inline exit
and exit/reinit before KASAN found a fixture helper task that had returned
before `kthread_stop()` joined it. The helper now follows existing fixtures
by staying alive until its owner joins it; a start completion also admits
the held-tail test's blocked-exit observation. The original KASAN failure is
retained separately from the accepted final run. Its log SHA-256 is
`682c86c628e556332a6dcae2f1ab555962758810da2b9ad85d4e23cc214fcfa7`;
the first setup-panic log is
`f690643dc0c9abdcd9eb67303bd75d2747727bae7345086c6e53f5a1b6c2c38e`.

## Remaining backend work

The next independently tracked source defect is NEO-215. In the pinned MPFS
backend, `mpfs_remove()` disables its clock before unregistering the MUSB
child, violating the child's client/IRQ/DMA cleanup prerequisite. It also
passes the parent `pdev` to `usb_phy_generic_unregister()` although probe
registered and saved a distinct `glue->phy`. The actual generic helper directly
calls `platform_device_unregister()` on its argument. Partial-probe unwind
is being traced against the actual platform helpers as part of that audit.
Both `platform_device_del()` and `platform_device_put()` guard
`IS_ERR_OR_NULL()`, so early NULL/error-pointer PHY cleanup is benign; it is
not an additional demonstrated crash. The confirmed correction remains
parent-clock lifetime and unregistering the actual owned PHY.

Caller/global-accessor frames, other backend and DMA producer retirement,
source masking, wake/startup composition and inaccessible-hardware teardown
remain software work. Complete image and physical remove/rebind qualification
require separate identified builds and coordinator admission. NEO-192's clock
fault and PM gates remain unresolved. Diagnostic.27 stays unconfirmed, with
fixed recovery the default; this source work grants no hardware lease.
