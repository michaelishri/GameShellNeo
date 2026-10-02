# First shallow-sleep readiness (NEO-77)

2 October 2026. A bounded source/read-only assessment of diagnostic.13,
`6.18.54-gameshellneo13`. No alarm was armed, power key pressed, driver changed,
PM stage entered or sleep policy changed for this report.

## Decision

**The next milestone is a guarded `platform` debug test, followed by a first
attended suspend-to-idle experiment after the wake and recovery gates below
are implemented. The current image is not ready for that real-sleep experiment.**
The outstanding preparation is specific: make wake arming fail visibly and
unwind correctly, give the waking power-key gesture a safe owner, prepare and
qualify a hardware RTC deadline, cross the untested late/noirq boundary, and
preserve diagnostic evidence through recovery. Completing these gates provides
a justified first experiment, not proof that every sleep defect is eliminated.

The modern U-Boot/Crust, A33 DRAM retention and deep-sleep work in
[report 19](19-modern-suspend-integration.md) and
[the base plan](20-base-implementation-plan.md) is a separate milestone.
It is not a prerequisite for this Linux s2idle experiment. Normal sleep stays
masked throughout preparation; the first experiment needs its own explicit,
one-shot entry path.

## Evidence and terminology

The pinned upstream source is Linux `v6.18.54`, commit
`1b357ecb321392158d507b04672ffee57bfa071d`. Source line references below refer to
the patched `.local/sources/linux-6.18.54/` tree unless stated otherwise.
The build applies patches 0001–0018, including generated patch 0003;
the saved manifest is `.local/artifacts/kernel-patches/manifest.json`.
The build configuration SHA-256 is
`d370205bf2e4eed5e35483f15372a6785e7d96252d40c343dfee0b2dde37a017` and is
byte-identical to the configuration in the final device inspection.
[Source lock](../build/sources.lock.json),
[image preparation](91-diagnostic13-preparation.md).

The saved inspection
`.local/diagnostics/20261002T090102.356948Z/inspection.json` and the subsequent
read-only capture `.local/neo77-sleep-readonly.log` agree on boot
`fd480513-371b-4f00-8a69-db14bd7727d4` and expose:

| Interface/evidence | Meaning |
| --- | --- |
| `/sys/power/state`: `freeze mem` | `freeze` requests s2idle; `mem` uses the selected `mem_sleep` variant. |
| `/sys/power/mem_sleep`: `[s2idle]` | There is no advertised `shallow`/standby or `deep`/suspend-to-RAM state. |
| `/sys/power/pm_test`: `[none] core processors platform devices freezer` | This is a list of test names, not proof every test is valid with s2idle. |
| Seven successes, all failure counters zero | One freezer and six devices debug cycles passed. They did not enter real sleep. |
| Retained keypad supply and SDIO power; both SSH routes recovered | Established for those bounded debug cycles, not for a sleeping CPU or a physical wake. |

The completed hardware evidence, including original keypad identity and the
physical-input checks, is in
[report 96](96-diagnostic13-attended-validation.md). In this report, “shallow
sleep” means **s2idle**, not Linux's distinct `shallow` selector. Linux documents
the selectors separately. [Official sleep-state documentation][sleep-doc].

S2idle freezes processes, suspends devices through late/noirq, and waits with
CPUs in their idle loops. Its branch returns before secondary-CPU offlining,
`syscore_suspend()` and `suspend_ops->enter()`. It therefore does not exercise
PSCI `SYSTEM_SUSPEND`, Crust or the proposed DRAM power transition. This also
means the R_INTC **syscore** wake-mask handoff described for deep sleep in
report 19 is not the s2idle entry path. Ordinary IRQ routing and the Linux
IRQ wake machinery remain relevant. No energy or resume-latency result can
be inferred from this distinction. [suspend.c:91–158, 412–467][suspend],
[irq-sun6i-r.c:271–309][r-intc].

## The exact next debug gate

| `pm_test` with `state=freeze` | Actual boundary in this kernel |
| --- | --- |
| `freezer` | Processes/freezable work, followed by the debug return. Already exercised. |
| `devices` | Ordinary device suspend/resume. Stops before `suspend_enter()`, hence before late/noirq. Already exercised. |
| `platform` | Runs late/noirq and their reverse callbacks, then the configured debug delay and return **before** `s2idle_loop()`. This is the next unqualified boundary. |
| `processors` or `core` | Rejected with `-EAGAIN` for s2idle. They cannot be required as intermediate gates on this image. |
| `none` | Real s2idle. The five-second debug delay no longer supplies an automatic return. |

These are the pinned implementation's branches, not an extrapolation from
the generic hibernation/deep-suspend test ladder.
[suspend.c:338–353, 420–443, 516–527, 574–579][suspend]; compare the
[official PM debugging guide][debug-doc].

The saved helper deliberately accepts only `freezer` and `devices`, verifies
the five-second delay and directly writes `freeze`. It must gain a reviewed
`platform` mode with corresponding orchestration/trace checks before that
stage is submitted. Do not broaden its existing stage list to include `none`:
real sleep needs different admission and recovery controls.
[tools/test-pm-stages.py:19, 84–111](../tools/test-pm-stages.py).

## Wake path and concrete error-handling defects

The board describes AXP223 on RSB address `0x3a3`, with its interrupt routed
through R_INTC hardware IRQ 32. The AXP MFD supplies PEK nested IRQs; PEK
requests press/release handlers, reports `KEY_POWER`, and enables device
wakeup by default. The additional read-only capture
`.local/neo77-journal-verify.log` confirms the live PEK `power/wakeup` value
is `enabled`. [Board DTS:171–182][board],
[axp20x-pek.c:198–214, 250–275][pek].

For s2idle, the intended sequence is:

1. PEK arms the nested IRQs; regmap forwards wake references to the parent
   PMIC IRQ. The IRQ core arms that parent before noirq callbacks.
2. RSB's noirq suspend resets/gates the controller. A waking PMIC parent IRQ
   is caught by the IRQ core, which records the wake and defers the handler;
   waking the kernel does not require reading PMIC registers on the stopped bus.
3. All device noirq resumes, including RSB reinitialization, finish before
   device IRQ handlers are re-enabled. Regmap can then read/ack PMIC status
   and deliver the nested key event.

Sources: [regmap-irq.c:197–207, 278–296, 448–546][regirq],
[irq/pm.c:16–22, 65–140][irq-pm],
[sunxi-rsb.c:707–745, 824–827][rsb],
[drivers/base/power/main.c:868–873][pm-main]. This is a source contract;
the saved `devices` passes do not establish the noirq hardware transition.

| Defect | Consequence and bounded repair |
| --- | --- |
| PEK discards both `enable_irq_wake()` results and always returns success; resume discards the matching disable results. | A failed edge arm can be reported as successful suspend, with no partial-arm rollback. Check both results, roll back the first if the second fails, and retain accurate cleanup ownership. [axp20x-pek.c:330–361][pek] |
| `regmap_irq_set_wake()` returns success after changing a counter; its void sync-unlock later discards the parent's enable/disable result. | Checking only PEK's calls cannot detect parent failure. Repair the parent wake-reference transaction at the regmap layer with error propagation, balanced reference accounting and a locking/context review; logging an ignored error is insufficient. [regmap-irq.c:197–207, 278–296][regirq] |
| Sun6i RTC suspend/resume discard direct wake enable/disable errors. | The proposed independent deadline must not claim it is armed when its IRQ setup failed. Propagate failures and keep cleanup ownership explicit. [rtc-sun6i.c:714–732][rtc] |
| AXP AC insertion wake has the same unchecked child return. | Include this already-enabled PMIC client when validating the shared parent reference/rollback behavior, or explicitly constrain the test's optional AC wake policy. [axp20x_ac_power.c:285–314][ac] |

These are definite source-level error-reporting defects, **not observed failed
wake arming on this board**. R_INTC's current callback accepts direct IRQs
relative to NMI; the recorded PMIC IRQ 32 and RTC IRQ 40 fall within that
supported range. It returns `-EPERM` for unsupported mappings, not for these
normal assignments. This limits the evidence for present hardware impact;
it does not justify claiming a checked wake chain while errors are discarded.
[irq-sun6i-r.c:68–72, 159–171][r-intc].

Before relying on that chain, regress first/second child arm failure, parent
failure, shared PEK/USB/AC references, rollback/unwind, disable failure and
repeated cycles. Compile the affected ARM drivers and compare the normal
configuration. Tests must exercise actual failure ownership and observable
return values. Merely counting calls cannot prove correct rollback.

The asynchronous PMIC-client problems identified in
[report 68](68-pmic-suspend-ordering-audit.md) should not be carried forward as
if their fixes were absent: patch 0012 drains/disables PHY detection before
late/noirq, and patch 0013 puts supply notifications on the freezable queue.
Both are installed in diagnostic.13. They close the identified producers at
source level; the upcoming `platform` trace still needs to establish the
actual cutoff/restore behavior. [Patch 0012](../kernel/patches/0012-sun4i-usb-phy-suspend-work.patch),
[patch 0013](../kernel/patches/0013-power-supply-freezable-notifications.patch),
patched `phy-sun4i-usb.c:700–726` and `power_supply_core.c:150–166`.

## RTC deadline and power-key ownership

The read-only capture confirms `/dev/rtc0`, parent
`/sys/devices/platform/soc/1f00000.rtc` with wakeup enabled, and the
`alarmtimer.0.auto` wake source. The saved interrupts identify RTC hardware IRQ
40 on R_INTC. `CONFIG_RTC_INTF_DEV=y` and `CONFIG_RTC_DRV_SUN6I=y`, while
`CONFIG_RTC_INTF_SYSFS` and `CONFIG_RTC_INTF_PROC` are disabled. Consequently
missing `wakealarm`/`/proc/driver/rtc` attributes do **not** establish missing
RTC alarm support. [RTC Makefile:14–16][rtc-make], [SoC DTS:713–721][soc],
[official RTC interface documentation][rtc-doc].

The driver implements alarm read/set/IRQ enable and writes a hardware
countdown plus interrupt/wake-enable bits. A supported first-test fallback
is a small checked helper using `/dev/rtc0`: read time and the existing alarm,
reject conflicting ownership, set an enabled absolute deadline using
`RTC_WKALM_SET`, read it back with `RTC_WKALM_RD`, then clear/restore its own
alarm on every return path. That readback is the RTC core's logical alarm
state, not an independent register-level verification: `rtc_read_alarm()`
returns `aie_timer` fields. Never reset the RTC time merely to schedule a
test. First verify alarm delivery while awake; this establishes programming
and interrupt delivery for that awake test only.
[rtc-sun6i.c:415–457, 501–577, 671–677][rtc],
[drivers/rtc/dev.c:320–329, 370–385][rtc-dev],
[drivers/rtc/interface.c:387–406][rtc-interface].

An alternative is a checked `CLOCK_BOOTTIME_ALARM` timer with
`CAP_WAKE_ALARM`, held open through the experiment: alarmtimer selects a
wakeup-capable RTC and programs its hardware deadline during suspend.
Ordinary `sleep`, process timeouts and non-alarm timers do not supply that
contract. Select and qualify one implementation instead of mixing RTC owners.
The kernel rejects alarmtimer entry when a deadline is too close, so admission
must leave a measured preparation margin. [fs/timerfd.c:402–427][timerfd],
[alarmtimer.c:82–110, 232–285][alarmtimer].

Neither the presence of an alarm device nor its wake-source event counter
proves timed wake from s2idle. An RTC deadline can wake an otherwise functioning
sleeping kernel; it cannot repair a deadlocked resume path. A shell trap, host
SSH timeout or systemd service timeout cannot execute device-side recovery
while userspace is frozen or the kernel is stuck.

There is also a direct policy conflict: the running logind configuration has
both short and long power-key actions set to `poweroff`, with no inhibitors.
PEK's wake-event suppression is AXP288-only; AXP223 still reports the gesture
after wake. Thus a successful power-key wake can be followed by shutdown.
Normal sleep masks do not prevent that shutdown action.
[Current policy](../runtime/etc/systemd/logind.conf.d/50-gameshellneo.conf),
[axp20x-pek.c:364–379][pek], [systemd logind documentation][logind].

Before any attended key-wake test, the diagnostic controller must own the
key event and suppress logind's action using a verified low-level
`handle-power-key` inhibitor or an explicitly saved/restored diagnostic
policy. Retain that ownership until the waking press and release are consumed;
exiting immediately at resume can re-expose the release to another consumer.
Record held-key, aborted-entry and controller-cleanup behavior. This narrow
diagnostic ownership does not require implementing the entire future menu;
the production short/2-second/8-second gesture requirement remains
[report 79](79-power-button-policy.md). The PMIC's eight-second off/no-restart
configuration and physical behavior remain unqualified; do not describe them
as an already verified recovery guarantee.

## Wi-Fi, logging and recovery boundaries

The retained radio path checks its sleep/restore failures, parks workers,
requests `MMC_PM_KEEP_POWER`, and rejects a previously latched fatal state.
The MMC core stops SDIO IRQ work and preserves power when requested; the
sunxi host uses ordinary system-sleep callbacks to suspend/restore its
controller. These ordinary callbacks have some coverage in the successful
devices runs. Real-duration retention and the added noirq interval still
need qualification. [Patched bcmsdh.c:1339–1496](../.local/sources/linux-6.18.54/drivers/net/wireless/broadcom/brcm80211/brcmfmac/bcmsdh.c),
[MMC SDIO core:1046–1125][mmc-sdio], [sunxi-mmc.c:1498–1535][mmc-host].

Automatic recovery after a fatal checked worker error, nested packet/mailbox
error coverage, a missing clock-ready notification and NEO-55's original
authentication failure remain unresolved. They are not evidence that every
healthy retained-suspend attempt must fail, and a complete automatic radio
recovery subsystem is not a prerequisite for a single attended RTC/key-wake
experiment. They **do** preclude relying on Wi-Fi as the sole recovery channel
or claiming production sleep readiness. Stop on a radio failure, preserve the
run over USB if available, and use the established cold-restart boundary;
do not automatically retry PM or reset/reprobe the radio.
[Diagnostic.13 limits](91-diagnostic13-preparation.md),
[worker-error scope](89-wifi-worker-error-handling.md).

USB is a second recovery route after the kernel resumes, not an out-of-band
console while USB is suspended. Without serial and with `CONFIG_PSTORE` unset,
a hard lockup followed by power removal can lose the last kernel/trace records.
`panic=10` only helps an actual panic, not an arbitrary hang. Save boot/run
identity and an entry-intent record durably before PM, synchronize journal
evidence, retain bounded in-memory tracing for retrieval after return, and
copy the completed evidence promptly to the host. A pre-entry record without
a post-resume record identifies an incomplete experiment; it does not locate
the failing callback. The separate
[journal investigation](97-journal-loss-investigation.md) identifies a
logrotate hook invoking Armbian ramlog despite the ramlog service being
masked, relocating the earlier journal. Its two-file policy correction is now
installed and passed explicit ordinary rotation without a journald restart or
history loss. New-image boot and later scheduled rotations still need their
own checks. Report 96's one intact session alone did not resolve that cause.
[Configuration](../.local/build/kernel/.config),
[report 96](96-diagnostic13-attended-validation.md).

## Scoped implementation and test gates

1. **Prepare the candidate offline.** Repair and regress the wake-error paths
   above; add a separately guarded `platform` mode; implement RTC admission,
   ownership/readback/cleanup and power-key ownership. Add durable run records
   and settle the journal-preservation issue. Keep normal sleep masked. Do not
   add deep-state advertisement, Crust, WoWLAN, radio reset policy or the full
   launcher/menu to this slice.
2. **Qualify that candidate awake and at existing stages.** Verify its exact
   image/kernel/config/DT/firmware identities, both SSH routes, stable input,
   no latched errors and effective wake/key policy. Repeat the existing
   freezer/devices checks after changes, qualify the RTC alarm while awake,
   and exercise controller abort/cleanup. No sleep result is claimed here.
3. **Cross late/noirq with `platform` + `freeze`.** Use the prepared attended
   recorder; establish RSB cutoff/restore and IRQ order, no late client bus
   errors, no leaked wake references and complete console/input/network
   restoration. Stop at the first unexpected outcome. The five-second debug
   delay is a normal return mechanism, not protection from a callback hang.
4. **Run one separately admitted real `freeze` with `pm_test=none`.** Hold the
   key-policy owner, arm and read back a future RTC deadline, perform the
   `wakeup_count` handshake, and record the exact controls before entry.
   First use the RTC as the intended wake so timed return itself is qualified;
   after a clean result, a separate key-wake cycle can retain RTC as fallback.
   Do not retry an entry rejected by a pending wake event automatically. Keep
   the owner present with the agreed physical recovery path and recovery image.
5. **Accept only observed outcomes.** Distinguish a pre-entry abort/immediate
   wake from a genuine interval in s2idle; retain PM traces, wake IRQ/source
   evidence, elapsed-time evidence and the state-write result. Require the same
   boot/session, original input identity, a consumed wake gesture, usable
   display/input, USB and Wi-Fi recovery, no new PM/kernel errors and complete
   restoration of alarms, ownership and PM controls. Only then widen to
   repeated cycles, USB/battery cases or longer residence.

The wakeup-count handshake is provided by the kernel to reject stale event
counts; it does not replace worker drains or a hardware wake source.
[wakeup.c:873–901, 998–1011][wakeup]. Even a clean first test qualifies only
its recorded conditions. Energy, endurance, sub-second resume, automatic
inactivity, production gesture policy and deep sleep retain their own gates.

[sleep-doc]: https://docs.kernel.org/admin-guide/pm/sleep-states.html
[debug-doc]: https://docs.kernel.org/power/basic-pm-debugging.html
[rtc-doc]: https://www.kernel.org/doc/Documentation/rtc.txt
[logind]: https://github.com/systemd/systemd/blob/v257/man/logind.conf.xml
[suspend]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/power/suspend.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[r-intc]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/irqchip/irq-sun6i-r.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[board]: ../kernel/overlay/arch/arm/boot/dts/allwinner/sun8i-r16-clockworkpi-cpi3.dts
[soc]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/boot/dts/allwinner/sun8i-a23-a33.dtsi?id=1b357ecb321392158d507b04672ffee57bfa071d
[pek]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/input/misc/axp20x-pek.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[regirq]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/base/regmap/regmap-irq.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[irq-pm]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/irq/pm.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[rsb]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/bus/sunxi-rsb.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[pm-main]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/base/power/main.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[rtc]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/rtc/rtc-sun6i.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[ac]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/power/supply/axp20x_ac_power.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[rtc-make]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/rtc/Makefile?id=1b357ecb321392158d507b04672ffee57bfa071d
[rtc-dev]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/rtc/dev.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[rtc-interface]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/rtc/interface.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[timerfd]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/fs/timerfd.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[alarmtimer]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/alarmtimer.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[mmc-sdio]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/mmc/core/sdio.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[mmc-host]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/mmc/host/sunxi-mmc.c?id=1b357ecb321392158d507b04672ffee57bfa071d
[wakeup]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/base/power/wakeup.c?id=1b357ecb321392158d507b04672ffee57bfa071d
