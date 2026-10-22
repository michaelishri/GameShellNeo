# MUSB terminal IRQ and wake ownership composition

23 October 2026 NZDT. NEO-219 is a bounded offline child of NEO-102, related
to NEO-98 and NEO-106. Original qualification in the isolated
`work/musb-terminal-wake-ownership` checkout used accepted
`02c633a0349ad986fe384cc0f94e26663baa3df3`, frozen at `6b380ac`.
The final review context below adopts published `4925a67` with identical
qualification inputs; the original receipts retain their original provenance.
No Mac/GameShell, image, selector, PM, unbind or reset operation is included.
Diagnostic.27 stays unconfirmed with recovery the default; clock/PM gates
remain open.

Report 291 identified that unchanged wake/startup 0026/0029 and retirement
0039 cannot simply be stacked. A fresh strict private replay rejects four of
0039's five hunks. A naive contextual merge can also be wrong: 0039 directly
disarms without clearing `irq_wake`, frees the action and invalidates `nIrq`.
Calling 0026's cleanup afterward attempts another disarm with an invalid
number. Keeping the number alone permits a second, unowned disable instead.
If the first disable fails, actual Linux IRQ accounting restores `wake_depth`
to one; action removal does not release that reference. This is a prospective
composition risk in two opt-in candidates, not a shipping or installed fault.

The new explicit `musb-terminal-wake` profile contains unchanged retirement
inputs through 0061, unchanged startup 0029 and
[bridge 0062](../kernel/candidates/musb-terminal-wake/0062-musb-terminal-wake-handoff.patch).
It omits conflicting 0026 from this profile while preserving that candidate
and its original profile. The bridge uses identical `musb_disarm_wake()`,
`musb_init_wakeup()`, `musb_cleanup_wakeup()`, `musb_suspend()` and
`musb_resume()` bodies, compared automatically against unchanged 0026.
The actual UDC-start body also matches unchanged 0029. Production's 33 patches
and locked inputs remain unchanged.

| State | Owner and terminal handoff |
| --- | --- |
| `nIrq` | Valid requested action identity until `free_irq()` returns, then set to `-ENODEV`; later finalization is a no-op |
| `irq_wake` | Core's successfully acquired wake reference; cleared only on successful disarm |
| `wakeup_initialized` | Core-owned capability/source initialization, including partial source-allocation failure; foreign state is preserved |
| IRQ-core `wake_depth` | Shared descriptor reference count; a failed last disable retains its debt, and unrelated peer references survive core removal |

`musb_free_irq()` now performs owned wake/source cleanup once before action
release and identity invalidation. It is reached by terminal IRQ shutdown
after client cleanup and the runtime-PM barrier, or by final allocation
cleanup when no earlier terminal action release occurred. `fail3` follows
role unwind; earlier failure entries preserve 0029's failed runtime get and
never operate on uninitialized work or acquire an IRQ. Failed final disarm
is reported using the valid original IRQ. It leaves explicit debt; subsequent
allocation cleanup does not retry or invoke an invalid number. No guessed
decrement, shared-state force clear or complete failed-power recovery is added.
An existing capability-test disarm failure can enter unwind with an owned
reference; that unwind makes its one terminal attempt. It does not grant
later allocation cleanup another attempt.

The placement is sleepable. Actual `device_init_wakeup(false)` calls
`device_wakeup_disable()`, which detaches under `dev->power.lock`, then
unregisters the source. `wakeup_source_remove()` drops its list lock before
`synchronize_srcu()` and `timer_delete_sync()`. Capability removal also calls
the documented sleepable `device_set_wakeup_capable()` path. This is distinct
from the short controller-mask critical section and blocking IRQ action drain.

| Production call path | Lock/context contract |
| --- | --- |
| `musb_remove()` → `musb_shutdown_irq()` | Process-context client cleanup and runtime-PM barrier precede terminal shutdown; the controller spinlock is released after MMIO masking and before wake/source cleanup or action drain |
| `musb_init_controller()` `fail3` → `musb_shutdown_irq()` | Probe process context after registered-role unwind, outside `musb->lock`, with required platform/PHY resources retained |
| `musb_free()` → `musb_free_irq()` | Probe/removal allocation cleanup; its resume-work barrier returns unlocked, and the IRQ guard excludes repeat finalization after earlier action release |

The native fixture checks unlocked cleanup and required resource availability.
The Linux fixture calls actual wake/source APIs, holds a real wakeup-source
SRCU reader until detach is observed, and proves action retirement cannot
pass that grace period. A separate held threaded IRQ handler proves action
unlink occurs while finalization still waits and modeled resources remain
available. Both checks execute actual helper placement under KASAN/lockdep;
neither substitutes a source-cleanup stub. The fixture retains the sleepable
device lock across finalization, matching driver-core callback context, while
leaving `musb->lock` released.
Pinned `drivers/base/dd.c` documents the device-lock requirement on
`driver_probe_device()` and `__device_release_driver()`; the platform bus does
not request the USB-interface-specific parent lock. IRQ wake accounting takes
its descriptor/chip lock internally. No controller spinlock spans capability
sysfs removal, the wake-source SRCU/timer waits or `free_irq()`'s handler drain.

```sh
task test:musb-terminal-wake-reference
task check:musb-terminal-wake-drivers
task test:musb-terminal-wake-kunit
```

The first reference Task compiles actual 0026 helpers, 0039 action release and
Linux `irq_set_irq_wake()` bodies. Four controls reproduce single correct
cleanup, double disable, invalid-number cleanup and failed-disarm debt. Its
original receipt/binary/input copies remain under
`.local/build/musb-terminal-wake-tests/reference-first/`.

The first full Task failed before any ARM/kernel writer because its new
bounded extractor recognized Git headers but omitted plain unified 0042.
The native fixture's unused resume seam was rejected by `-Werror`. The
extractor now selects both patch formats; a focused regression requires all
three 0042 file diffs. The reference functions above were unaffected. A second
Task passed all 147 candidate scenarios, then rejected a negative control at
compile time because removing its sole call made the helper unused. The
control now retains a harmless function reference and must fail its runtime
assertion. Both original logs are retained; neither is accepted full-suite
qualification.

Final candidate SHA-256 is
`451031f7bc117a6de162c8f4c5b6e3e77ca54f326fd7844fc8cd126836c443d9`.
All **147 actual-source scenarios** pass natively, under ASan/UBSan and on
ARM32/QEMU. The existing 141-case probe/wake matrix is adapted to terminal
retirement, with six further shared/debt/allocation-finalizer cases. Seven
compiling mutations fail their runtime assertions: late cleanup after IRQ
invalidation, omitted cleanup, duplicate final disarm, omitted action
invalidation, clearing failed-disarm ownership, dropping foreign capability
and ignored startup power failure. The fixture is static with no heap; the
known ptrace/LSan limitation is explicit while fail-fast ASan/UBSan remain on.

All six complete ARM configurations pass: project gadget, host, dual-role,
modules, PM without sleep and genuine no-PM. Effective requested settings,
complete object/config/compiler/ELF hashes and all three profiles' full queue
manifests are retained. The bounded extraction independently matches all six
relevant files in each complete prepared Linux source. Final receipt
`.local/build/musb-terminal-wake-tests/compile-evidence.json` has SHA-256
`b29d0f0ca8e33a41c44e1835ad5df043c95683b460c4ed7757806304e61a3172`.
A prior complete pass remains in `qualification-before-format/`; after only
patch-description wrapping and three extra blank-line removals, the final
bytes were fully requalified.

The complete instrumented MUSB core and UML kernel build, and all **eight
real Linux cases** pass under KASAN/lockdep. They cover unowned finalization,
owned wake cleanup, shared peer ownership, failed final disarm, a held real
wakeup-source SRCU reader, a held threaded IRQ handler, foreign source state
and unsupported wake capability. The log retains exactly one expected
`cleanup failed: -5` diagnostic with a valid IRQ number; the failed-reference
test observes debt before any explicit fixture recovery. No kernel warning,
lock/RCU diagnostic or failing/skipped case is accepted. Original session
67295 / managed run `b7d218c56ee24decab67bc24cb736f37` is terminal with exit
zero and managed `active: null`. Independent kernel/config/log/results copies
remain under
`.local/build/musb-terminal-wake-kunit/kernel-d88ed81f8425a06c/accepted-runs/69fa5b0fa4e54fafa110fed414b3e73b/`.
Receipt `.local/build/musb-terminal-wake-kunit/evidence.json` has SHA-256
`20752edb2c1834595e6bc825a9452f63e7cf72b9dcae73de31972799c80304ed`.

The dedicated runner accepts only a zero build/container/test result before
parsing and retaining artifacts. `kernel_checks.run()` propagates nonzero
status with `check=True`; no broad exception fallback or expected-failure
path can substitute old KTAP/JSON after a failed cached rebuild or swallow
unresolved managed cleanup. Prior logs/results remain preserved separately.

The original host `task check` passes **1,310 tooling tests** (nine skipped), current-limit/mount
guards, Bash syntax and ShellCheck; its log SHA-256 is
`36f2105a0bdaf0a9cbd30bf59dc53036fe66b3914ffc551bce855e0a99bb8eb0`.
Strict checkpatch has zero errors/warnings and one check for the existing
`nIrq` field name. The separately retained run with only `CAMELCASE` ignored
has zero errors, warnings or checks; the qualified shared field is preserved.

Fresh independent pre-integration Standards and Spec reviews accepted `6b380ac`
with zero required findings. Standards retained one optional fixture-setup
duplication note; the qualified source stays unchanged.

Final review uses `work/musb-terminal-wake-final-admission`, based on published
`4925a67786269018f4884db753c3ec78892f14f0`. The only cherry-pick conflict was
report navigation; all accepted entries are preserved. All 18 maintained
qualification inputs, candidate 0062 and the complete 35/43/45-entry profiles
match the original bundle exactly. The 33 production inputs remain unchanged.
An independent current-context audit checks fresh strict source extraction,
the native/control/reference bodies, five unchanged 0026 policy bodies,
0029's UDC-start body and the generated Linux test patch against the actual
original tested source. All 167 checks pass. Current published helper APIs and
Task routes are preserved; the dedicated runners do not import the changed
generic managed-container helper.

The native/configuration and Linux receipts and relative private paths above
remain in the original `musb-terminal-wake-ownership` checkout. They are not
new executions on the final base. No unchanged heavy qualification was repeated
solely for ancestry. The new checkout retains
`.local/notes/neo219-current-context-equivalence.json` as the source and artifact
equivalence record. Its one fresh combined host check passes **24 runtime and
1,379 tooling tests** (nine existing opt-in skips), C guards, Bash syntax and
ShellCheck. The new log is
`.local/build/terminal-wake-final-host-check.log`, SHA-256
`8bc133b0d8cfd2c8ef2f521b7387dcd1ebc58855551809cdb903069a2ca39011`.

Fresh final independent Standards/Spec reviews and a separate serialized
integration grant still precede publication. Linux controller construction and the chip wake
callback are fixture seams; hardware MMIO/source masking, complete backend/DMA
producer retirement, caller/global-accessor lifetime, SMP, actual system PM
and physical removal remain parent work. Concurrent sysfs source admission
and complete wake-source allocation failure scheduling retain NEO-98's
existing separate qualification boundary. Do not infer inaccessible registers
from a PM errno or complete NEO-102/98/106 from this composition.
