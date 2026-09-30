# USB PHY detection across suspend (NEO-50)

30 September 2026. Linux 6.18.54, CPI v3.1. Patch 0012 is implemented and
cross-compiled in isolated scratch. It is **not installed on the GameShell**;
diagnostic.10 and its completed image artifacts are unchanged. This slice did
not access the hardware, rebuild an image or enter a deeper PM stage.

The complete PMIC ownership audit is in
[report 68](68-pmic-suspend-ordering-audit.md). It distinguishes the PHY worker
fixed here from the power-supply core's remaining notification work.

## Source defect and repair

The baseline `sun4i_usb_phy0_vbus_notify()` schedules delayed detection on
`system_wq`. The worker reads the USB supply's `PRESENT` property, which can
reach the AXP223 over RSB. MUSB system suspend only disables controller
activity; it does not call PHY exit or clear `phy0_init`. The PHY provider has
no system-suspend callbacks in the locked baseline. A queued detection scan
therefore remains an asynchronous PMIC client after controller suspension.
The source and precise PM-core limits are traced in [report 68](68-pmic-suspend-ordering-audit.md).

[Patch 0012](../kernel/patches/0012-sun4i-usb-phy-suspend-work.patch) adds ordinary
provider suspend/resume callbacks:

- Suspend calls `disable_delayed_work_sync()` for detection. It cancels pending
  work, waits for an executing scan and keeps the work disabled so IRQ,
  notifier or self-requeue attempts cannot restart it while suspended.
- Resume balances the disable and requests a fresh scan using the existing
  50 ms debounce interval. This reconciles the final cable state even when
  notifications arrived while the worker was disabled. The same resume path
  handles unwind after a later device rejects suspension.
- The callback waits without holding `phy0->mutex`, because the worker itself
  takes that mutex. All ordinary suspend callbacks finish before RSB noirq
  shutdown; all noirq resumes finish before ordinary provider resume.

The workqueue API's disable/drain and balanced-enable contract is documented
by [Linux](https://docs.kernel.org/core-api/workqueue.html#c.disable_delayed_work_sync)
and implemented in the pinned `kernel/workqueue.c`. Cancellation alone does
not reject a new producer arrival. The regression includes that negative case.

The worker also moves its ID/VBUS getters under its existing PHY mutex, after
checking `phy0_init`. Generic `phy_exit()` uses that same mutex, so an exited
PHY can now reject the scan before reading GPIO/PMIC state. This is a separate
lifecycle correction: moving the getters alone would not fix system suspend,
because normal MUSB suspend leaves the PHY initialized.

There is no new periodic timer, per-scan lock or cached cable-state substitute.
Active detection, extcon publication, debounce and polling intervals remain
unchanged. The patch changes neither charger settings nor IRQ wake policy.
It does not power down the PHY or prove a standby-current reduction.

## Repeatable verification

```sh
task test:usb-phy-suspend
task check:usb-phy-driver
```

[The checker](../tools/check-usb-phy-suspend.py) verifies the archive SHA-256 in
[the source lock](../build/sources.lock.json), extracts the actual PHY driver,
applies patch 0012 without fuzz, checks PM callback registration and compiles
the actual scan, IRQ, notifier, suspend and resume functions into
[the harness](../kernel/tests/usb_phy_suspend_test.c). Workqueue, mutex,
property and MMIO-facing helpers have deterministic API shims; the test does
not execute a kernel scheduler or physical bus.

The candidate passed **148 scenarios natively and on emulated ARM32**, covering:

- Missing/uninitialized PHY and exit completing before the scan obtains its
  mutex: no property reads or register updates.
- ID/VBUS changes, stable repeated scans, peripheral/OTG branches and optional
  polling, preserving expected extcon notifications.
- Pending/running work, IRQ and matching-supply notifier arrivals during drain,
  arrivals while suspended, rejected self-requeue, repeated suspend/resume and
  a fresh cable-state update after supplier availability returns.
- Unrelated-supply and non-property notifier events remaining ignored.

Six native negative controls compiled and failed the intended assertions:
original source, cancel without disable, omitted suspend drain, omitted
re-enable, omitted resume rescan, and property reads before the init/mutex
check. These make the regression sensitive to lost exclusion and recovery,
not merely successful compilation.

The complete ARM driver then compiled with all project patches and the locked
kernel configuration in isolated scratch. The object SHA-256 is
`38421d59b579fecb7c23becfd1e103b307d0ba319c29dc808f9489ef6096b4cf`.
`task check` passed 266 tool tests (one optional skip), 13 runtime tests,
compiled helper checks and Bash/ShellCheck. Kernel `checkpatch.pl --no-tree`
reported zero errors and warnings; `git diff --check` passed.

Private evidence:

- `.local/build/usb-phy-suspend-tests/compile-evidence.json`, including exact
  archive, patch, harness, checker, builder, config and object fingerprints.
- `.local/build/usb-phy-driver.log` and `.local/neo50-phy-driver.log`.
- `.local/build/usb-phy-suspend-tests/kernel-124a5daa5e5f328c/` for the isolated
  patched source, output, compiler version and ARM ELF information.
- `.local/neo50-check.log` for the normal host suite.

`task build` includes the new source regression. As with other patch-queue
changes, use `task kernel:reset` before the next full kernel build so the old
patched tree is archived and a fresh source extraction receives the new queue.
The isolated check does not reset or overwrite the current image workspace.

## Remaining boundary and next qualification

This closes the PHY worker path at the source/API level. USB/AC
`power_supply_changed_work()` still runs on an ordinary system workqueue and
can read the PMIC while building LED/uevent data. Its wake-source hold and the
PM core's runtime disable are not a universal bus-access barrier. Resolve
that independent producer/drain/resume contract before permitting late/noirq
or real sleep tests. Report 68 also records nested-to-parent wake-error
propagation and power-key/battery-alarm policy gaps.

On a future identified image containing this patch, first repeat the saved
freezer/devices tests and both USB/Wi-Fi recovery checks, record actual
provider/supplier callback order, and check cable-state reconciliation. Normal
awake USB attachment/removal should also be requalified because those events
use the affected worker. The current image has not run this patch and its
previous passing cycles do not qualify it. No real sleep, physical wake,
endurance or energy result is claimed.
