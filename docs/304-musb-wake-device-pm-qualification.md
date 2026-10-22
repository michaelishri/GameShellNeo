# MUSB wake policy through Linux device-PM traversal (NEO-220)

23 October 2026, Pacific/Auckland. This bounded offline child of NEO-98 uses
the isolated `work/musb-wake-device-pm-qualification` checkout, starting at
published main `02c633a0349ad986fe384cc0f94e26663baa3df3`. That original checkpoint
remains frozen at `6d7177b`. A separate `work/musb-wake-device-pm-final` checkout
adopts published NEO-218 at `7120990` for its accepted managed-result API; it
does not change NEO-218's runner, helper or fixture. NEO-219 separately owns
terminal wake/IRQ cleanup and combined retirement qualification.

The first final-admission checkout starts from fixed guard checkpoint `9de70c2` and
adopts independently published `4d680d7` through merge `e78f96d`. The actual DPM
fixture, configuration, support, runner and tests remain byte-identical to that
fixed checkpoint at `1f432d4`. Both saved Task entries are retained alongside the accepted
clock, host-admission and terminal-composition context. This milestone still
selects unchanged wake/startup 0026/0029; the published terminal profile is a
separate opt-in qualification. New owned positive and control executions pass
the final current-input guards at `1f432d4`; their source, configuration and
binary identities match the corresponding genuine original executions.

The separate numeric-admission checkout starts from frozen `7c922e0` on the
same accepted base. It corrects only host parsing and focused tests after the
first final Spec review found a numeric-prefix false acceptance. Actual kernel
fixtures/configuration, the fourteen-assertion map, source generation and the
managed runner remain unchanged.

## Source and ownership boundary

The saved Tasks deliberately select only the existing `musb-wake-startup`
profile: exact candidates 0026/0029 with unchanged production inputs. The new
test append includes a fixture in `musb_core.c` and adds a Kconfig symbol. It
does not replace production functions. Actual Linux `dpm_suspend_start()`,
`dpm_suspend_end()`, `dpm_resume_start()` and `dpm_resume_end()` own the device
lists, dispatch, prepare reference, runtime-PM restriction and global IRQ walk.
The registered type's suspend/resume observers call the unchanged MUSB functions;
its other observers count entry and inject explicit errors at test boundaries.

The type and PM operations are assigned before `device_add()`: Linux's
`device_pm_add()` caches `no_pm_callbacks`. Assigning a type later can skip
prepare while still dispatching other callbacks, so such setup cannot establish
complete traversal. The embedded device has a release callback, and fixture
cleanup verifies its final reference was returned.

The hardware boundary uses a byte/word register bank, a guest-local level
irqchip and two Linux shared IRQ actions with counting handlers. Runtime resume
is staged at a test-owned hardware boundary. No physical MUSB ISR, physical
registers or USB transfer is exercised. A foreign runtime-PM hold remains owned
through every transition and must survive it exactly.

## Finite case plan

| Case | Required observation |
| --- | --- |
| Policy disabled | All eight device-PM callbacks execute; global noirq traversal disables the IRQ without a wake reference; resume restores it |
| Policy enabled | All eight callbacks execute; noirq traversal arms the actual Linux IRQ from the owned wake reference; resume clears it |
| Shared peer | With MUSB policy disabled, the peer's single wake reference survives the full walk and keeps the shared IRQ armed |
| Prepare error | Original `-EIO` returns from start; prepare's temporary PM reference is returned; no driver suspend, resume or complete callback runs |
| Arm error | Actual MUSB suspend returns chip `-EIO`; driver PM hold is returned, with no MMIO/platform disable or driver resume |
| Runtime-resume error | Actual PM core invokes the staged resume failure; MUSB returns `-EIO` without IRQ/MMIO work; original runtime error/status and reference balance remain observable |
| Late error | Start succeeds; end returns the injected `-EIO`; Linux performs matching early unwind and driver resume/complete without double resume-start |
| Noirq error | The actual global IRQ traversal runs; end returns injected `-EIO`; Linux restores IRQs and runtime disable depth before driver resume/complete |
| Resume-disarm error | Full traversal completes; actual MUSB resume returns `-EIO` and retains its wake debt even though the DPM resume helper returns void; assertions precede fixture-only cleanup |

Every started path runs under `lock_system_sleep()` and reaches
`dpm_resume_end()`, including prepare/start/end failures. A successful end also
receives `dpm_resume_start()`. Failed late/noirq paths already perform their
matching early/noirq restoration inside the DPM core and do not receive that
second call. Snapshots are bounded memory/IRQ-state observations; no KUnit
assertion or allocation can bypass restoration while IRQs or the GFP mask are
restricted. Assertions execute after the matching resume/complete and unlock.

Each case checks callback counts, phase flags, runtime usage/status and disable
depth, descriptor wake/disable state, restored GFP mask and shared action
delivery after resume. Prepare/complete observers see the core's temporary
reference; successful MUSB suspend adds another distinct reference. GFP checks
observe only the restriction entered by `dpm_suspend_start()` and the matching
restore, not higher suspend layers. No freezer, platform sleep or CPU-off path
is entered.

## Missing-callback control

`task test:musb-wake-dpm-control` uses a separately identified disposable source
tree. Only the enabled-policy case omits PM-type registration before
`device_add()`; all production functions and the other eight cases are unchanged.
Linux can still return success from its global walk while never invoking the
fixture's callbacks. The control must compile and execute all nine cases, with
exactly the enabled-policy case failing fourteen named assertions: the eight
zero callback counters, absent prepare/complete reference observations, missing
driver suspend reference, and missing armed/reference state at noirq. Every
assertion and observed value is bound to that case. An additional or different
assertion, another failed case, setup/compile failure, skip, incomplete output
or kernel diagnostic rejects the control.

Each required observed operand must occur once on a complete formatter line.
Both its decimal and hexadecimal values must equal the declared number;
numeric prefixes, inconsistent representations, trailing text and duplicate
observations are rejected.

The original raw failed result is retained separately from positive evidence.
Source generation changes only that single fixture registration assignment;
the original MUSB core and Linux PM/IRQ sources remain unchanged.

## Qualification status and remaining scope

The original `6d7177b` chain completed with actual kernel execution: positive
run `e1df48b844cf429790b2e4115424b1ba` passed all nine cases; compiling control
`6368e4d386c3481e9ac62e1c38733c68` exited 1 with the single named failure,
exactly fourteen predeclared assertions and eight passes. Both original managed
jobs are terminal and released, with no stop or OOM. Their immutable private
index is `.local/audit/neo220-original-evidence-index.json` in the original
checkout (SHA-256
`eea3c6930015583099b6179f3c2c46fe92d711404c8afe0ba74ab2551b80ee67`).

Those executions used the earlier admission code. They remain genuine
historical observations and are not relabeled as current evidence. The separate
final checkout now accepts a nonzero control only through NEO-218's typed
`ManagedCommandFailure`, with matching original identity/result, clean exit 1
and released ownership. Generic errors, including unresolved cleanup, propagate.
Both positive and control routes retain and verify any old log or JSON file,
remove the active names before execution, and require both files from the new
execution. New identical result bytes are valid; content inequality is not a
freshness test.

The intermediate focused host qualification passed eleven DPM guard tests and
five accepted managed-result test groups. The actual runner routes reject stale or partial
outputs, unresolved/active ownership, stopped/OOM/running/wrong-original results
and nonzero positive execution; they accept newly produced identical outputs.
The fixture, exact fourteen-assertion control, Kconfig and generated kernel
profile remain unchanged. These intermediate host results and the original
kernel executions remain historical, separate from final current-input evidence.

Fresh source/pre-integration Spec review at `51d0705` required rejecting a
normal successful executor return on the negative-control route. Fresh valid
failed-case output must still be rejected when the original command exit is 0.
The separate `work/musb-wake-device-pm-control-exit` correction preserves that
frozen review checkpoint, reproduces its original false acceptance through
actual `main()` with a disposable executor fixture, and adds the missing guard
and exact regression. Historical raw-1 kernel evidence is unchanged. A read-only
audit reproduced the equivalent gap in the published NEO-218 route; NEO-225
separately fixed that host boundary and is included in the adopted final base.
The corrected focused host run passed twelve DPM tests plus five accepted
managed-result groups, including the new raw-0/current-failed-output regression.
The intermediate Standards review required no fixes; the Spec finding is
addressed by the preserved `9de70c2` correction. Those reviews do not provide
final acceptance of this adopted context.

The one final-admission chain, original observer `53214`, completed with exit 0.
Its positive managed job `22605d827fed496aaff9bb9211b0dec4` exited 0 and passed
all nine cases. The separate compiling control job
`5279349d92a14438bccfbbeef6784a50` retained its original exit 1, exactly one named
failure, eight passes and all fourteen predeclared assertions. Both jobs have
released ownership, with no stop, OOM or rejected kernel diagnostic. Fresh
per-execution outputs were admitted through the unchanged guards; the control
used the typed original-result path. The positive receipt SHA-256 is
`8a3481cdd774adccb15e7f4330563ccf84233e2d6b3b3c1083fbdc1807595448`;
the control receipt SHA-256 is
`765a79f04e703601ed8ccefbfa3248a7ecf870ad297cd50f1ffc416d986753b4`.

The final checkout's `.local/audit/neo220-current-qualification.json` (SHA-256
`cfb40eb0281027809b23acd231521f77e2ddc763c43aae7232fe1e51fe613195`)
binds both durable receipts, original managed results, current maintained inputs
and full source/configuration/binary equivalence with the frozen original
checkout. The five changed maintained host inputs are `Taskfile.yml`, the DPM
runner and its tests, `tools/kernel_candidates.py` and
`tools/managed_container.py`. The registry and shared helper changes come from
the accepted base; the DPM runner/test changes enforce current result admission.
The exact selected profile and generated source are unchanged. Separate copied
cache inodes provisioned the final checkout without changing original caches;
new execution evidence, not those copied receipts, provides current admission.

The complete final host `task check`, original observer `39481`, passed at
clean `1f432d4`: 24 runtime tests, 1,391 tooling tests with nine expected skips,
compiled C regressions, Bash syntax and ShellCheck. Its retained log is
`.local/build/neo220-final-host-check.log` (SHA-256
`9ae0b822362e18e8c2c20ed473f7b9b83f0f51ccfecc23bb7b99400b7bba94e8`).
The complete check includes the twelve DPM tests and five managed-result groups.
The source, index and worktree stayed unchanged through qualification. Only this
report receives the final evidence afterward; executable inputs are unchanged.
Those first final executions remain genuine historical evidence after the
numeric-parser correction; their receipts are not relabeled as current.

The first final review at frozen `7c922e0` returned zero required Standards
findings and one required Spec finding: the prior substring check accepted
`walk->after_start.usage == 20 (0x14)` when the declared value was 2. The new
checkout preserves the original actual-admission counterexample and the red
regressions before correcting it. Its focused check passes fourteen DPM tests
and five managed-result groups. The tests use a verbatim genuine compiled KTAP
section rather than constructing observed values from the admission map, and
exercise both direct control parsing and actual runner admission with fresh
raw-1 output. New owned current-input cached positive/control executions and
the complete host check are pending. A new final Standards and Spec pair is
required before publication or closing NEO-220.

The saved Tasks use the pinned local builder, disabled networking, one build
job, unique managed attempts and retained source/config/binary/KTAP/result
receipts. Original failures remain historical and are never relabeled as later
success.

NEO-98 remains open for its broader allocation/sysfs, controller, deliberate
image-integration and physical acceptance scope. NEO-219's separately published
terminal-composition qualification is not exercised by these Tasks. This
single-CPU UML/KASAN/lockdep milestone does not establish SMP, deep sleep,
clock/PM admission, wake energy or board
behavior. No Mac, GameShell, deployment or main publication is part of this
qualification. The separately parked NEO-216 path remains untouched.
