# Power-supply deferred-notification teardown candidate

9 October 2026, Pacific/Auckland. NEO-161, branch
`work/power-supply-unregister`.

Patch 0037 joins the deferred registration worker before draining notifications
during power-supply unregister. This closes the producer-after-drain schedule
identified in [report 157](157-power-supply-unregister-lifetime.md). The change
is two reordered calls and a comment; it adds no awake polling or per-event
work. It is a source-level lifetime correction, with no claimed energy saving
or diagnosis of a fault observed on the GameShell.

The installed diagnostic.24 remains unchanged. All work in this slice runs on
the Intel host, using the pinned Linux 6.18.54 archive and builder.

## Change and scope

The old unregister order cancels `changed_work` and then joins
`deferred_register_work`. The latter calls `power_supply_changed()`, which can
queue the former after its cancellation has completed. The corrected order
joins the producer first, then drains its downstream work before teardown.

The existing parent-device trylock loop and `removing` escape are unchanged.
These are needed because managed cleanup can hold the parent lock while it
waits for deferred registration. Replacing the trylock with a blocking lock
would introduce a deadlock; reversing the two cancellations does not require
that change. No queue selection, notifier behavior, charger parameter, wake
policy or polling interval is changed.

The audit's core SHA-256 still matches the diagnostic.24 source before the new
patch: `10fb014e80e863fbc5f6754abef5a322c9a6e718da885f7775a0fbc9537ed2f4`.
The AXP USB, AC and battery call sites and the Corsair runtime unregister path
were checked again against that tree:

- AXP USB releases diagnostic access, IRQ producers and its private polling
  work before managed supply unregister. Patch 0006 remains necessary.
- AXP AC's managed IRQ actions were registered after its supply and retire first.
- The AXP battery descriptor has no private notification worker or
  `external_power_changed` callback.
- Ordinary managed AXP teardown holds the parent lock, excluding the particular
  overlapping deferred callback used in the generic-core demonstration.
- Corsair's runtime battery worker can call unregister without acquiring the
  parent lock. It remains a concrete source-level caller for the generic race,
  although this driver is disabled in the GameShell configuration.

An independent IRQ, poll worker, supply extension or external callback can still
violate lifetime if its owner lets it run after unregister. The core reorder
does not retire those producers. Supply references also do not retain every
piece of parent-driver state. The Sunxi PHY's managed supply reference and
notifier/detection teardown remain part of the separate consumer-order audit;
this slice does not approve arbitrary AXP or PHY unbind on the board.

## Linux worker-gate tests

The saved `task test:power-supply-kunit` runs two Linux UML kernels: the project
queue without patch 0037, then the candidate queue with it. Each has an isolated
test-only instrumentation patch. That patch inserts completion gates at worker
entry, immediately before/after deferred notification, and around the original
cancellation calls. It does not replace the workqueue, cancellation, device
registration, teardown or parent-lock implementations.

The fixture creates a synthetic registered supply with a real non-null parent.
An extra device reference preserves the allocation until all work has drained.
It deliberately does not increment the power-supply API's `use_cnt`, so the
normal unregister warning is neither triggered nor suppressed. The reference
allows the original-order control to demonstrate work surviving unregister
without executing a deliberate use-after-free.

| Case | Required behavior |
| --- | --- |
| Deferred producer overlaps unregister | Hold deferred registration after it obtains the parent lock. Start unregister, then let it queue a real notification whose worker is held. Original unregister must return with that worker running; candidate unregister must wait until it is released. |
| Parent lock held through unregister | Start deferred registration while another context holds the parent lock. Unregister must complete using the existing removal escape, without waiting for that lock to be released or queuing a notification. |
| Deferred registration already complete | Finish both workers before unregister; removal must leave both work items idle and `use_cnt` zero. |
| Notification already running | Finish the deferred producer but hold its notification. Both orders must wait for the active notification to finish. |

The 100 ms observation windows check that removal has not completed while an
explicitly held worker is active. They are not product latency measurements.
Observations require the corresponding cancellation-entry marker first, and
completion waits have five-second deadlines. Cleanup releases gates even when
an assertion aborts a test. The outer kernel runner has a 120-second execution
deadline for a hung fixture.

Requested configuration includes KASAN, lock dependency checking, atomic-sleep
checks, RCU checks and work-object debugging. The runner verifies the effective
configuration. It requires exactly four passing cases, rejects recognized
kernel warnings, faults or incomplete results, and preserves each accepted
kernel/config/log/report separately from reusable Kbuild outputs. Patch and
source inventories are hashed, including the generated test instrumentation.

These are real Linux scheduler/workqueue tests on one UML virtual CPU. They do
not cover SMP interleavings, physical IRQs, AXP hardware removal, every external
producer or the complete supplier/consumer graph. KASAN detects memory faults
in the exercised paths; the retained control reference means the original
defect is demonstrated by outstanding work, not by a deliberate KASAN report.

## Validation

The final default KUnit task passes all four scenarios under both cancellation
orders, with no recognized kernel warnings, faults, lock diagnostics or KASAN
reports. In the overlap case, the original order completes unregister with its
notification worker still held; the reordered candidate waits for release.
Both parent-lock cases finish without the deferred worker acquiring that lock.

Final KUnit receipt:
`.local/build/power-supply-kunit/evidence-all.json`, SHA-256
`993a0b3e45eb0c7c6b87c3070144723272856faec05954de82d86087705d3244`.

| Variant | Retained run below its `accepted-runs/` directory | Kernel SHA-256 |
| --- | --- | --- |
| Original, `kernel-original-d77587a45249375a` | `38405451e16b43b9a4bcf25139146e59` | `c78a00a4585895984c14d643713cdfba378a7bb64548aedd7cf494527dc0452f` |
| Reordered, `kernel-reordered-e2bb8b2df20e2821` | `1dabcaa179174079987f9ceef317fd62` | `e4454e51268d9f9fb70f40f56e94ed970ba875a95e0fb8c933cdc36bef91217b` |

Directories are beneath `.local/build/power-supply-kunit/`. Their full verified
source-tree digests are
`d22bb51b1aabb516514d47a757fc2526855a7c792da7eb1ce280b876b7a69bf5`
and `9304d49d74858c2646e0be45c010cf3ecf69f7ba7a1bf5683bf888bf5d616a49`.
All retained kernel/config/log/report hashes and runner input hashes were
reverified against this final receipt.

Earlier initial builds also passed; their artifacts remain retained separately.
The final run verifies the saved task after changing variant selection to an
environment value validated by the runner. Initial full kernel builds took
about eight minutes each. Unchanged Kbuild checks then took about eight seconds
per variant, excluding source preparation; kernel test execution itself was
under one second. These are host build/test timings, not GameShell measurements.

The existing deterministic source harness now applies the actual candidate
patch instead of synthesizing a test-only reorder. `task test:power-supply-lifetime`
passes 21 scenarios per variant on both native and ARM32 execution, or 42 per
architecture, with two expected native opposite-order assertion controls.
Its receipt is `.local/build/power-supply-lifetime-tests/evidence.json`, SHA-256
`61f30c75b25699cf41c5eaf8a619d278003b400b604687b84b290a843fa4540f`.
It retains the independent-producer counterexample: a caller that notifies
after the final drain can still leave work pending under either order.

`task check:power-supply-driver` also passes: 68 existing notification/freeze/
replay scenarios on native and ARM32, five expected native negative controls,
and complete production ARM `power_supply_core.o` compilation with the candidate
patch queue and board configuration. The compiled object SHA-256 is
`18a8123af5de64c7c7f937b4c0d30b22bc45c36f546b833f4b1ade45a20c356f`;
compile receipt SHA-256 is
`18a5935e944bfcb8bbe89a3a80aab744e4768c30f615cb5236f72ac9e3aefc9b` at
`.local/build/power-supply-suspend-tests/compile-evidence.json`.
The production source and queue contain no test hooks or fixture files.
Object and effective-config hashes were reverified; the checked production
source-tree digest is
`3518ee20e935c7321059687533f13d347c2ba89c257a21f6efe89eda6b0596b2`.

Final `task check` passes 16 runtime and 813 tooling tests, two optional skips,
compiled helper checks and Bash/ShellCheck. Nine new host tests check result
acceptance, gate insertion/order preservation, invalid variant rejection and
artifact retention. The skips are the opt-in user-systemd fixture and an
Armbian-source-dependent fixture not available in this isolated worktree.
Final logs are `.local/neo161-final-kunit.log`, `.local/neo161-native-arm.log`,
`.local/neo161-arm-core.log` and `.local/neo161-final-host-check.log`; the saved
Task wrappers retain their detailed build logs under `.local/build/`.

## Integration gate

Do not install this candidate as the existing diagnostic.24 identity. Bundle it
into a separately identified future image when the pending lower-level changes
are selected for integration, then check startup supply registration and the
normal PM/USB paths. Source and host tests do not replace board qualification.
Keep the broader supply/PHY removal contract open; there is no need to risk a
live supplier unbind simply to reproduce this synthetic core race.
