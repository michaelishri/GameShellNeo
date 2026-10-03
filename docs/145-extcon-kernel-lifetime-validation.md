# Extcon notifier lifetime inside Linux

4 October 2026, Pacific/Auckland. NEO-106, branch
`work/musb-removal-lifetime`.

The extcon consumer-drain candidate now has real-kernel KUnit tests in addition
to [report 144](144-extcon-notifier-drain-candidate.md)'s native/ARM32 source
fixtures. Both TREE and TINY SRCU kernels pass all nine tests with lock and RCU
debugging enabled, including a final run through the default two-configuration
task. These are Linux UML kernels running on the Intel development machine,
not the GameShell.

The tests exercise the original kernel notifier traversal, SRCU grace periods,
kthreads, completions, locks, timer softirqs and extcon allocation/registration.
They remove the modeled scheduler/SRCU boundary from those specific scenarios.
This does not complete Sunxi notifier ownership or the broader MUSB removal
work, and it makes no hardware reliability or energy claim.

## Kernel suite

Patch 0032 adds `EXTCON_NOTIFIER_KUNIT_TEST` and its Kbuild entry. The test source
is in `kernel/overlay/drivers/extcon/extcon-notifier-test.c`, exported through
the existing generated patch. The option depends on KUnit and extcon and does
not enable itself in a normal board image with KUnit disabled. Patch 0031's
production functions are unchanged.

Every case creates a synthetic registered provider. It keeps that provider and
the notifier blocks alive until all callbacks, threads and timers have drained.
There is no emulated MUSB controller, physical connector or firmware involved.

| Case | What is exercised |
| --- | --- |
| `extcon_sync_active_test` | Unlink a callback while its body is sleeping; synchronous removal waits for it |
| `extcon_sync_selected_next_test` | Hold a preceding callback after the real notifier loop has prefetched its next block; remove that next block before its callback enters |
| `extcon_sync_all_chain_test` | Remove the specific subscriber while the later all-connectors chain is still in the same protected dispatch |
| Three corresponding `extcon_async_*` controls | Ordinary unregister returns while the same dispatch is held; the selected original callback can still run |
| `extcon_nested_process_test` | Nested notifications on the same SRCU domain in process context |
| `extcon_nested_softirq_test` | Nested notifications in a real timer softirq, with userspace uevents explicitly suppressed |
| `extcon_unregistered_allocation_test` | Allocate/free without registration, NULL-safe free, invalid arguments and absent-subscriber errors |

The race tests wait until the target is actually unlinked under the extcon lock,
then observe the synchronous operation still waiting while the selected callback
is held. Ordinary-unregister controls show the removal thread can finish in the
same setup. The observer then releases the callback and requires completed
dispatch and removal. It checks that the selected original callback runs exactly
once, a later dispatch cannot reach the removed block, and re-registration works
after retirement.

The 100 ms observation window is a scheduling test boundary, not a measured
minimum grace period or product latency requirement. Worker completion deadlines
are bounded. Cleanup releases held callbacks before stopping threads, including
on an assertion failure; asynchronous controls deliberately keep the subscriber
alive until the old dispatch completes rather than provoking a use-after-free.

## Configurations and acceptance

Both test configurations request `PROVE_LOCKING`, `PROVE_RCU`,
`DEBUG_ATOMIC_SLEEP`, `DEBUG_OBJECTS` and `DEBUG_OBJECTS_RCU_HEAD`. The generated
configuration is checked against the requested options. The first uses
preemptible RCU and TREE SRCU; the second requests a non-preemptible kernel and
TINY SRCU. UML supplies one virtual CPU for both. A TREE SRCU pass here does
not establish concurrent execution across multiple CPUs.

The saved runner requires exactly the named nine cases, each once and passing,
in the expected UML suite. It checks root and suite counts and rejects missing,
skipped, duplicated, extra or failed cases, malformed groups, incomplete logs
and recognized kernel warnings/faults. Five host regression methods exercise
these rejection paths. KUnit's own parser and exit status must also pass.

Each accepted run copies its kernel, effective configuration, raw boot/test log
and parsed report into a unique `accepted-runs/<id>/` directory. Copies are
verified against their source hashes before an individual acceptance receipt is
published. Later Kbuild/KUnit executions reuse their working outputs, while the
accepted copies and receipt remain separate. The receipt includes source
inventory, patch manifest, pinned builder and runner/config input hashes. Prior boot logs and parsed reports are archived
with their kernel/config/source identities before KUnit reuses its conventional
output paths.

The final default task passes all nine cases under both configurations, with no
recognized kernel warnings, faults, RCU stalls or hung tasks. Its accepted
`evidence-all.json` SHA-256 is
`ff82aee8d2104cd3e788b68173f8733bc8b25f4067b2ab1c9bcb58cfd7160fb4`.
The verified source-tree digest is
`1bcb1808a60e0849c55bba021149c88c0cfe3f5f58d74c66db1f365970ff8781`.
All accepted artifact hashes, runner/config inputs and the current patch queue
were checked again after completion.

| Configuration | Kernel SHA-256 | Accepted scratch |
| --- | --- | --- |
| TREE SRCU | `286cb5dda08bec0c8c89b57d37ea011219c77ae87ef2ebccb5d2f32832c5a6e7` | `kernel-tree-34040536586df373` |
| TINY SRCU | `29f291114938940fc8aa95beaa1906f7b69eb1b6700bf27b4fd4459f589846e3` | `kernel-tiny-e504a0f36b42708b` |

Accepted TREE artifacts are under that kernel's
`accepted-runs/453ec7df683a44059a1fe0e0c9b7ac23/`; its `evidence.json` SHA-256 is
`2ffcf11822d68c2f23024df4d40723c8ae460819a0752d81dfb7d4579e54ffa8`.
The TINY artifacts are under
`accepted-runs/584168af3f2341d2a8818995c3332896/`; receipt SHA-256 is
`df70b2683363c41f157b00fb3eb4354b1ef79e3f219b93f5fab11349b57f6185`.
Both receipts and all retained files were reverified. Two additional host
regressions ensure later runs cannot replace retained bytes and an incomplete
copy cannot publish acceptance.

The final host check passes 13 runtime and 494 tooling tests (two existing
optional skips), compiled helper checks and shell lint. Its saved log is
`.local/neo106-kunit-retention-check.log`. The five result-validator methods
also pass independently after adding malformed-case and stall/hung-task
rejection. Individual TREE/TINY runs preceded the final default-task check;
their reports remain as earlier evidence, not substitutes for the final runner.

## Reproduction

Run from the candidate branch/worktree:

```sh
task test:extcon-kunit              # TREE and TINY SRCU, sequentially
task test:extcon-kunit VARIANT=tree # Just the preemptible configuration
task test:extcon-kunit VARIANT=tiny # Just the non-preemptible configuration
task check
```

The task uses the existing pinned builder, a verified read-only source cache,
isolated output directories, no container network and a temporary executable
filesystem for UML. It needs no device credentials or physical interaction.
The runner configures and compiles the test object before building the rest of
a new kernel, catching source/API errors earlier. Initial kernels take several
minutes to compile; unchanged kernels are reused by Kbuild while tests are
executed again. The task log is
`.local/build/extcon-kunit.log`; accepted evidence is
`.local/build/extcon-kunit/evidence-<variant>.json`.

The first completed kernel launch failed before any KUnit test ran because the
container user's default UML state directory was unwritable. The runner now
supplies `uml_dir=/uml-tmp/state`; it does not change the user's home directory.
The original panic log is preserved in that kernel output's `previous-runs/`.
The source error path in UML is tracked separately in `FOLLOW-UP.md`.

## IRQ-context boundary found during validation

The raw callback envelope accommodates matching SRCU read entry/exit in the
caller's original process or interrupt context. That does not establish that
the **whole** existing `extcon_sync()` implementation is safe from an IRQ.
After its callbacks and property-page handling, it calls
`kobject_uevent_env()`. The unsuppressed uevent path in the pinned
`lib/kobject_uevent.c` allocates with `GFP_KERNEL` and can take a mutex.

The timer-softirq test sets the synthetic device's `uevent_suppress` flag, which
causes that tail to return before its sleeping operations. Both nested callbacks
must observe interrupt context. This qualifies the callback/SRCU envelope in a
real softirq, not unsuppressed userspace-event delivery from an IRQ. Process
tests run the ordinary extcon path with uevent suppression off; no userspace
listener or delivery test is claimed.

[Report 141](141-musb-removal-backend-contracts.md)'s earlier wording about
interrupt callers has been qualified accordingly. Full caller-context policy,
actual provider callers and any event-deferral change require separate review.
No GameShell failure is attributed to this source boundary.

## Remaining work

The tested provider stays alive by construction. Consumer/provider removal
ordering, selected callbacks during Sunxi partial-probe failure, child rebind
and final work cancellation still need integration tests. The actual platform
and DMA producer-retirement matrix from reports 139/141 also remains open.

UML checks do not replace SMP, hard-IRQ, ARM or physical-device qualification.
Diagnostic.18 and its installed power policy remain unchanged. Its repeat
RTC-wake session still requires fresh observer readiness; these local tests do
not consume or refresh that device's admission evidence.
