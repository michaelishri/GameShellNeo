# Product power-button policy

Status: owner-confirmed requirement, 1 October 2026; NEO-57. Implementation and hardware qualification remain follow-up work. This extends the [base power policy](06-base-requirements.md#power-policy).

## Agreed behaviour

| Gesture and state | Required result |
| --- | --- |
| Quick press while awake | Enter low-power sleep, preserving the running session. |
| Quick press while asleep | Wake and resume the existing session. |
| Hold for **2 seconds** | Open the power menu, with restart/reset and orderly shutdown options. |
| Continue holding to **8 seconds total** | Force power off, including when the UI is unresponsive. Do not automatically restart. |

The owner selected the 2/8-second thresholds. Eight seconds is measured from the original press, not from when the menu appears. Menu wording and additional options belong to later launcher design; “reset” here does not authorize a factory reset or data erasure.

For an awake device, recognize the short action on release before two seconds. Reaching two seconds emits the menu action once; a later release must not also request sleep. Continuing to hold must leave the hardware forced-off path available even if the menu, launcher or userspace is stuck. Selecting shutdown from the menu uses the orderly shutdown path. Forced power removal is the emergency fallback and can lose unsaved state.

The press used to wake the device must be consumed as a wake gesture: neither its press nor its subsequent release may immediately request another sleep, open a menu spuriously or shut down through the existing diagnostic handler. A fresh press after release starts a new gesture. Holding the wake press still needs the hardware eight-second fallback; qualify this across the eventual sleep implementation. A sleep request that fails must leave a usable awake session, without stale timers or a delayed short action.

USB power and active SSH inhibit **automatic inactivity sleep**, as previously agreed. They do not change the deliberate short-press requirement. Battery inactivity remains two minutes by default, configurable separately. The sub-second resume and week-long standby goals remain aspirations, not measured capabilities.

## Hardware and driver evidence

The supplied **AXP223 Datasheet V1.1, 2013-11-28**, section 10.2.30, describes the PEK settings in register `36h`: bits 1:0 select 4/6/8/10-second automatic power-off, bit 3 enables that action, and bit 2 controls automatic restart afterward. Thus an eight-second hardware cutoff is documented, but selecting its duration alone does not establish that it is enabled or that the device will remain off. Section 9.1.3 describes this action removing outputs except VCC-RTC. Section 10.2.43 also describes a separate optional sixteen-second key-hold reset (`8Fh[3]`), which needs auditing alongside the intended off policy. These are specification capabilities, not readings of the installed configuration. [Supplied PMIC manual](<../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf>).

The same PEK register has an independent long-key interrupt threshold of 1/1.5/2/2.5 seconds in bits 5:4. Its two-second option is compatible with the menu target, but it does not implement a menu. The locked Linux power-key driver reports ordinary `KEY_POWER` press/release edges. Its `shutdown` sysfs attribute controls only the two duration bits; it does not configure the auto-off enable or restart policy. The AXP223 MFD instantiates `axp221-pek`, which uses the common 4/6/8/10-second shutdown table. [Locked power-key driver](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/input/misc/axp20x-pek.c?id=1b357ecb321392158d507b04672ffee57bfa071d); [locked MFD registration](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/mfd/axp20x.c?id=1b357ecb321392158d507b04672ffee57bfa071d).

The power-key driver's special wake-edge clearing in `resume_noirq()` applies to AXP288, not AXP223. Its presence is not evidence that wake-press consumption already works here. The [PMIC ordering audit](68-pmic-suspend-ordering-audit.md) also leaves end-to-end wake-IRQ error handling open.

The owner explicitly accepts changing the signals emitted by the power-button driver to support these behaviours. Driver-level press/release, long-hold and wake-event handling is therefore within the permitted design scope. Select and document the logical events before implementation, preserve standard Linux input semantics where possible, and ensure compatibility with consumers of `KEY_POWER`. This is permission to adapt the driver, not a requirement to replace it wholesale or a claim that the existing event stream already implements the policy.

Implementation must assign a single owner to software gesture recognition, coordinate it with logind and the future launcher, and keep the eight-second fallback in the PMIC. The UI consumes the menu request; competing driver/userspace timers must not produce duplicate actions. Use supported driver interfaces and narrowly scoped, documented changes where needed. Preserve unrelated PMIC fields and inherited charging settings.

## Current diagnostic image

Diagnostic.11 keeps normal sleep masked and both logind short/long power-key actions set to `poweroff`. Its driver debug cycles return without entering actual low-power sleep. The new product gestures are therefore **not active**. This ticket changes documentation only; it does not write PMIC registers, change the running image, exercise forced power-off or establish wake reliability. [Diagnostic logind policy](../runtime/etc/systemd/logind.conf.d/50-gameshellneo.conf); [sleep policy](../runtime/etc/systemd/sleep.conf.d/50-gameshellneo.conf).

## Qualification before enabling the policy

1. Read and document the inherited PEK/off/restart configuration, including bootloader ownership and the separate sixteen-second reset. Confirm the effective eight-second setting, auto-off enable and no-restart policy without whole-register overwrites.
2. Save repeatable gesture tests for short release, either side of the two-second threshold, menu-once behaviour, release after a long hold, cancellation after failed sleep, and cleanup across shutdown/suspend. Ensure logind and the UI cannot both act on the same press.
3. With real sleep ready and an owner-observed recovery path, test short-press sleep/wake repeatedly, including release during sleep, a held wake key, USB attached/detached and battery operation. Demonstrate that the waking gesture cannot cause an immediate second action.
4. Qualify eight-second forced power-off with a deliberately unresponsive UI, independently of userspace gesture handling. Confirm actual off behaviour, clean next startup and absence of an unwanted restart with and without USB power. Test a blocked software path separately before claiming resilience to a kernel hang; a working PMIC design alone is not a completed hardware result.

Record actual timing tolerances, event traces and recovery results. Keep physical cutoff tests supervised and preserve the recovery card/image. Deferred activities are tracked in [FOLLOW-UP.md](../FOLLOW-UP.md).
