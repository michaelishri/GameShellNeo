# MUSB wake ownership through kernel IRQ traversal (NEO-218)

23 October 2026, Pacific/Auckland. This bounded offline child of NEO-98 starts
at `5a2f362a39e49415b6a73e732219007ab8f4eb00` in the isolated
`work/musb-wake-irq-qualification` checkout. Kernel qualification used accepted
main `5505fd90e9cd98038fef785bfe6ba19e6548a739`. After all original writers
completed, the branch adopted published main
`49b1c237ea3cd822195362f9462285fc1ee9a75c`. The positive suite passes all eleven
cases. The corrected compiling control produces exactly five required failing
cases and six passing cases. Final review preparation uses the separate
`work/musb-wake-irq-final` checkout on accepted main
`02c633a0349ad986fe384cc0f94e26663baa3df3`, with new owned executions described
below. Independent reviews precede publication/closure; the wider parent remains
open.

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
assertions in each named case. Before replay, a retained rationale records why
the fifth failure follows from the same condition, and an independent source
comparison confirms that reversing this sole condition change reproduces the
positive core file byte-for-byte. The fixture, Kconfig, gadget/header and IRQ-core
files match between both compiled sources.

On the `49b1c23` accepted-main context, both complete 36-patch specifications and
generated test patches match their original compiled inputs. Maintained image
patches, candidate bytes, lock, configuration and overlay are unchanged. Host
input drift consists only of the accepted task/retirement-registry context,
the control oracle/coverage wording and its parser guards. Fresh owned executions
retain the original binary hashes and record the current host input hashes:

| Execution on `49b1c23` | Managed run | Actual result |
| --- | --- | --- |
| Positive | `ef784b94037344babc8d4d2574de3577` | Raw kernel exit 0; all eleven cases PASS |
| Policy-ignored control | `ee85189791a74f939a1062a542ead05b` | Raw kernel exit 1; exactly the five named cases FAIL and six PASS; strict control checker succeeds |

Both results are authoritative exits with no requested stop, OOM or unresolved
writer. The maintained input hashes match before and after execution. The
original eleven-PASS record and rejected four-case-oracle wrapper remain
historical; neither is relabeled as this fresh execution.

| Artifact | Positive SHA-256 | Control SHA-256 |
| --- | --- | --- |
| Complete source tree | `ef10df122813ed1cdf223531980bf2ad02fe997790c0860cc8a70875ebc87a95` | `1b3b8d205b36e96fb18113ddd4bad635080d0d791bec2f8163012e233142a6ef` |
| Generated test patch | `b814d51a4f0ef92ef2be2445ba34c00fcf9b0f79684d9f17479d9ea8ed6fcaae` | `26f5da96dae2da173c10cd2e7052fb2f803420fca9c9c73f23af8901eb4e9aca` |
| UML kernel | `3a74177d67ba3078617070ee998bed7c90589bb8db4aec6c68fa82012fadee17` | `7d31dc381b740ae0f88d6151f71a003bfa15913820c2c0645a7d680e1b8565de` |
| Complete KTAP log | `1a03b4703d732c50e906bda6f9de4416a9c71a5f09969b4f655f1b0ad1815cfa` | `6d26ecfc4d09d97f1b0ea7ddfac3b1309e3c6ea6d4a792759d7fe99eda8df21e` |
| Evidence receipt | `8d06174c1b1abcb36dadcca68990f300c2337328a5827b27834a4f3593c2f09b` | `bbdb3a2fbccd2e0e505d8b85c2be4f8a2a0499ead2185da0584a4cf7086c1b37` |

Both kernels resolve the same required config, SHA-256
`21b603baddcb16204901a2c2c96d6b1b5c5a3832893bfc8b0bf3077cf0f620e3`,
including suspend, PM_SLEEP, the selected fixture, KASAN and lockdep. Final
`task check` passes 24 runtime and 1,310 tooling tests (nine existing skips),
the compiled current-selector and mount-guard checks, Bash syntax and ShellCheck.
Nine focused guards cover wrong/composed profiles, incomplete results, unexpected
control outcomes and assertion values assigned to the wrong case.

Original and final logs/receipts remain under the two
`.local/build/musb-wake-kunit*/` directories; accepted artifacts have unique
retained subdirectories. The private
`.local/build/musb-wake-kunit/neo218-evidence-index.json` indexes their hashes,
the pre-replay oracle rationale/source-equivalence proof and original failures.

## Final accepted-base review context

The final review checkout adopts exactly published main `02c633a` after its
NEO-215 integration lease completed. The original `0a359f6` checkout, its six
managed runs and the index above remain frozen. The only changed maintained
receipt inputs are `Taskfile.yml`, which adds three MPFS Tasks, and
`tools/kernel_candidates.py`, which appends candidate 0061 to the retirement
profile. The wake commands and separate 0026/0029 profile are unchanged.

Before execution, both complete generated specifications match the original
36-patch specifications exactly. Independent copies of the verified immutable
sources and cached outputs retain the source, generated-patch, kernel and
resolved-config hashes above. The normal runner revalidates each complete source
inventory and records new owned executions with the current maintained hashes;
no receipt guard is weakened and no original run is relabeled.

| Execution on `02c633a` | Managed run | Actual result |
| --- | --- | --- |
| Positive | `93c53bce398649899024b1102a77830d` | Raw kernel exit 0; eleven PASS |
| Policy-ignored control | `3a4f50277ff043c0b169c044684a7694` | Raw kernel exit 1; exact five FAIL/six PASS; strict checker succeeds |

Both original jobs are terminal with unchanged inputs, no stop request and no
OOM. Their new evidence receipt hashes are
`6176889a452cf31b4066b2239237594e700a311f908384fd83271fc334ffaded`
and `4a198f7f24bb2e752c882f02e3f5b2721f55c650f503dc4cd823a3e2f4a8aaed`.
The new complete KTAP hashes are
`13152b2c6bf2f6c2f98204105dd0d05b95c4388394e7af9f69a8ca650b389f1c`
and `fb4c291d08de0a8ace4d90eb2a0ec491bb0c743048e18aea0822399673883504`;
the two binary, resolved-config and result-JSON hashes remain exactly equal to
the prior executions. Repeated context checks pass 24 runtime and 1,310 tooling
tests (nine existing skips), the compiled checks and ShellCheck. The final
checkout's private `.local/audit/neo218-final-review-index.json` binds the new
receipts, preflight equality proof and host log to the frozen original index.

## Remaining NEO-98 gates

This suite does not qualify the complete device-DPM traversal, allocation failure
or sysfs concurrency, terminal failed-disarm/destruction ownership, retirement
composition, other physical controllers, SMP, an image, deep sleep or the board.
Those remain explicit NEO-98 work. This milestone grants no board clock/PM
admission; no Mac, GameShell, reboot, cable or deployment operation is part of
this offline work. NEO-216's separately parked probe artifacts are
preserved without reuse.
