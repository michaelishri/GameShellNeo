# MUSB callback and UDC concurrency validation

12 October 2026 NZDT. NEO-103. This extends the system-emulator preparation
in [report 273](273-smp-kernel-test-environment.md) with an actual ARM SMP guest
kernel. Two guest attempts exposed fixture bugs, retained below. The corrected
18-case suite passes in the full ARM kernel, including a second run after
improving failed-attempt retention. This completes the missing kernel-concurrency
checks; matching physical bind/unbind qualification remains open on the ticket.

## Exercised ownership

The test-only fixture is included alongside `musb_gadget.c`. It executes the
production MUSB resume, suspend, disconnect and reset functions. A small
test-only EP0 wrapper calls the actual `forward_to_driver()` function and
returns its result. The production admission, reference count, callback drain
and five callback call sites are unchanged.

The fixture registers a real gadget and function driver with the UDC core.
Unregistration calls the actual UDC disconnect, callback-disable, unbind and
stop sequence. Only hardware start/stop/pullup operations and the register
bank are substituted: QEMU does not model the GameShell's MUSB controller.

Fifteen of the cases cover five callback entry points in three contexts: a call
function IPI (hard IRQ), a pinned timer (timer softirq), and a pinned process.
The callback runs on guest CPU 1, unregistration on CPU 2, and the observer on
CPU 0. The guest must have four online CPUs; a uniprocessor run is an error.
The function-driver callback records its actual context and uses a bounded
non-sleeping handshake. It never sleeps while interrupts are disabled.

While that callback is held open, the test waits for the MUSB admission flag
to close, requires the outstanding count to remain one, and verifies that
neither function-driver unbind nor UDC unregistration has completed. It tries
all five real callback entry points while the gate is closed and requires no
new function-driver callback. After releasing the actor, it verifies a zero
count at unbind, the original callback's return, distinct CPUs and the final
closed/null-driver state. The real setup callback's return value is checked.
Every held-callback case also stages a PIO request and runs real MUSB/UDC
giveback while admission is closed, checking completion delivery, status,
queue removal and restoration of endpoint busy state. This does not test
hardware transfer or DMA.

Three additional cases cover two simultaneous hard-IRQ callbacks on CPUs 1
and 3 (unbind must remain blocked after the first returns), four real UDC
unbind/rebind rounds with all five callbacks admitted after each rebind, and
cleanup of a created but never started unbind actor. The shared completion is
only a notification; explicit state records whether unregister finished.

## Reproduction and evidence

```sh
task setup:kernel-qemu
python3 -m unittest discover -s tools/tests -p test_musb_callback_kunit.py -v
task check:musb-callback-kunit
```

The runner uses the locked Linux archive and complete production patch queue
plus a test-only patch. Source inventory, inputs, effective configuration,
kernel, emulator identity, full serial log and KUnit JSON are retained under
ignored `.local/build/musb-callback-kunit/`. Failed attempts remain separate.
Execution uses a uniquely named network-disabled container with CPU, memory,
process and time bounds. The runner retains original exit state and verifies
owned-container termination before removal. A host timeout records a separate
pre-stop container observation; it is not converted into a successful guest
exit. Available kernel/configuration artifacts are copied into the attempt even
on failure, with explicit hashes. Their presence alone does not establish a
successful boot. Earlier result files are archived
before a new attempt; source changes during execution prevent acceptance.

KASAN, lockdep and atomic-sleep diagnostics are enabled. The host verifier
requires all eighteen exact cases, no skips or kernel warnings, and the full
set of distinct-CPU/context/drain markers and matching raw serial TAP. Five offline regression groups
pass, including negative controls for wrong architecture, same-CPU execution,
missing or duplicate cases, incomplete drain, kernel diagnostic output,
timeout cleanup and refusal to remove an unknown or still-running container.

## First guest attempt

The full ARM guest compiled and booted four CPUs. Attempt
`kernel-98b5a405cc40e86e/attempts/dbfe5027f6d64043bb93627e53cc9e77`
retains the original serial log, KUnit JSON, command, original exit 1 and
confirmed owned-container removal. Eleven cases passed; `disconnect_irq`,
`disconnect_timer`, `setup_irq` and `setup_timer` failed after the callback's
ten-second handshake timeout. The outstanding count was already zero when
the observer inspected it, and the fixture correctly refused qualification.

Source review found a scheduling dependency in the fixture: it called
`kthread_create()` for the unbind actor after occupying CPU 1 in an atomic
callback. Thread creation itself waits for child initialization, which may
need that occupied CPU before the caller can pin it. This is a plausible
explanation for the timeout; the failed result alone does not establish a
MUSB defect. The correction creates and pins the unbind task before launching
the callback, then wakes it only after the callback enters. The ten-second
callback deadline and two-second observer waits are unchanged.

The same review attempted to correct cleanup for a created but never started
unbind thread: stopping such a thread is not evidence that unregister ran.
Its first correction incorrectly reused `completion_done()` after the test's
wait had consumed the completion. The second attempt,
`kernel-2ce2e4166d1a92ba/attempts/610bea16703a46c2906e39e0c94666d4`,
reached the first race's successful CPU/drain marker but then tried to
unregister the driver again during cleanup. KASAN reported a use-after-free
with allocation in fixture initialization, first free in its unbind thread
and second access in fixture cleanup. The run failed and reached the bounded
guest timeout; it is not accepted driver evidence.

The correction uses a separate `unregister_finished` flag, read after
joining the actor. A consumed completion can no longer change registration
ownership. The new unstarted-actor case exercises the other branch explicitly.
Both failed attempts and their original results remain retained; no driver
change was made in response to either fixture bug.
The first run also emitted two compiler stack-frame warnings in upstream
`maple_tree.c` and KUnit `test.c` under this KASAN configuration; those are
retained in the build log and are separate from runtime failure evidence.

## Accepted full-kernel results

The corrected guest in
`kernel-04887164832ccc00/attempts/7a3fbf2e43d146e7a98a0db8e104648a`
passes all eighteen tests. The actual CPU/context/count markers agree with
each assertion and the raw serial TAP. No runtime KASAN, lockdep, atomic-sleep
warning or failed/skipped case appears. The original container exits zero,
without OOM, and its stopped state is verified before removal.

The runner was then tightened to retain available kernel/configuration artifacts
on rejected attempts and preserve the pre-stop state after host interruption.
The timeout regression verifies that later scratch replacement cannot change
the retained kernel. A rerun with the same kernel inputs, attempt
`kernel-04887164832ccc00/attempts/9447639de0414190a5db52d68bab3cec`,
also passes all eighteen tests and all post-run validators, exits zero and
confirms cleanup. This second run qualifies the changed retention code; it
is not a claim of broad stress or hardware repeatability.

| Retained final artifact | SHA-256 |
| --- | --- |
| Accepted evidence manifest | `b84ac58b4213b9eb2649eb757ff192ead9ff662715176c924b484ce30528c8f9` |
| ARM guest zImage | `c460f7804de4486e0f92a2866c2ad83b5de1774f66e866e19e54fe2398e7ef86` |
| Effective configuration | `e1b9a0aa80e64c9630db5a4cd85115f2b325fb4654ab63ebcccb21e9f586752c` |
| Raw serial log | `65fcafe5bc674f5382b698eef5d2a43ded1a55dec302155b141fa161cb10a3b7` |
| KUnit JSON | `3a791aa38938dc52045a377bcd50ccee427ab5d8512b10990b4e877cb1662f62` |

All recorded input and retained-artifact hashes were rechecked after the run.
The production callback patch remains unchanged, SHA-256
`bd1e7875d690d6af360392a152ca49f5972145156549e282c91ec256f29d2f80`.
Neither fixture correction changed production driver code.

The final repository check passes 24 runtime tests, 1,009 tooling tests (two
existing optional skips), compiled current-limit and Mac mount-guard checks,
and Bash/ShellCheck lint. Its first sandboxed invocation failed five existing
local socket fixtures; the same offline suite passed with local socket access.
Both logs remain private under `.local/build/callback-repository-check*.log`.
No external SSH diagnostic or device investigation was part of those tests.

## Remaining scope

The earlier native/ARM32 tests remain complementary: they cover spurious wakes,
optional hooks, pointer-clear windows, error paths and deliberately broken
driver variants that this smaller SMP suite does not duplicate. The full-kernel
suite now covers actual scheduler, IRQ, timer, wait queue, UDC lifecycle and
request-completion concurrency. It substitutes the controller register bank
and hardware start/stop/pullup, so it does not establish electrical USB, DMA,
GameShell controller destruction or physical bind/unbind behavior.

Patch 0030 has already been integrated unchanged since diagnostic.19, with
bounded ordinary connection, cable and PM qualification recorded in reports
155–163 and 233–238. Those tests did not deliberately race function-driver
unbind with traffic. NEO-103 remains in progress for that matching-board
qualification when the device's clock admission and access baseline permit it;
NEO-106 owns the wider producer/backend teardown. No new GameShell operation
or image change occurred in this slice.
