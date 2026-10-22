# MUSB wake policy through Linux device-PM traversal (NEO-220)

23 October 2026, Pacific/Auckland. This bounded offline child of NEO-98 uses
the isolated `work/musb-wake-device-pm-qualification` checkout, starting at
published main `02c633a0349ad986fe384cc0f94e26663baa3df3`. Report 301's separate
NEO-218 checkpoint remains frozen for review; this fixture does not change or
reuse its runner, maintained helper or fixture. NEO-219 separately owns terminal
wake/IRQ cleanup and combined retirement qualification.

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

The original raw failed result is retained separately from positive evidence.
Source generation changes only that single fixture registration assignment;
the original MUSB core and Linux PM/IRQ sources remain unchanged.

## Qualification status and remaining scope

Implementation and host admission guards are prepared. Actual managed kernel
execution and the compiling control are pending; no result is claimed yet.
The saved Tasks use the pinned local builder, disabled networking, one build job,
unique managed attempts and retained source/config/binary/KTAP/result receipts.
Original failures remain historical and are never relabeled as later success.

NEO-98 remains open for allocation/sysfs concurrency, terminal destruction and
combined wake/retirement ownership, other controllers, deliberate image
integration and physical acceptance. This single-CPU UML/KASAN/lockdep milestone
does not establish SMP, deep sleep, clock/PM admission, wake energy or board
behavior. No Mac, GameShell, deployment or main publication is part of this
qualification. The separately parked NEO-216 path remains untouched.
