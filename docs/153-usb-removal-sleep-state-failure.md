# USB removal during sleep: RTC wake, stale gadget state

4 October 2026, UTC evidence timestamps. NEO-110 / NEO-112.

The first attended USB-removal attempt woke on its RTC alarm and returned to
the owner-confirmed normal dim console, but **failed USB recovery validation**.
The power supply and PHY detector recognized removal; the USB gadget still
reported `configured` and network carrier remained `1`. The failed original
is preserved. No repeat sleep, gadget restart or live driver change followed.

## Admission and physical observation

The unchanged diagnostic.18 image uses `6.18.54-gameshellneo18`, boot
`f2dfd67d-cf9a-4242-b9b7-58c1bc944357`. [Report 152](152-diagnostic-command-log-volume.md)
records the seven fresh debug prerequisites, journal continuity and owner-confirmed
display returns. [Report 151](151-usb-cable-sleep-diagnostics.md) records the
passing awake rehearsal `4dad01f01eab4c40a3d2760c7a3a5174`.

After a separate readiness response, the saved task submitted exactly once:

```sh
task device:sleep-cable-remove QUALIFICATION=.local/neo110-removal-reference-history.json REHEARSAL=4dad01f01eab4c40a3d2760c7a3a5174 CABLE_ACTION=1 ATTENDED=1
```

The owner subsequently confirmed one unplug after ten seconds of darkness,
before visible return, followed by a normal dim console. The separate observer
record uses `during-dark` / `normal`; it cannot override the automated failure
or timestamp the physical contact change inside the kernel's sleep interval.

## Original result

Run `5444c50735c04848846467980c65125e` is saved beneath
`.local/diagnostics/20261004T091444.726023Z/`. Its `result.json` SHA-256 is
`cee03c7fd667b4fd8ae36f9e66bae9d235790659dbffc1d5314eb5b7dfd8153b`.
`result-cable-observation.json` binds that exact original to the owner's answer.

| Check | Observation |
| --- | --- |
| RTC | One alarm event, flags `0xa0`, IRQ31 count 2 → 3; matching wake IRQ31 |
| Alarm elapsed | 31.731 seconds including entry/return overhead |
| Traced s2idle boundary | 1634.999177 → 1663.467390 monotonic seconds, 28.468 seconds |
| PM counters | Success 7 → 8; all failure counters unchanged at zero |
| External power after recovery | Both AC and USB `present=0`, `online=0` |
| PHY detector after recovery | `USB=0`, `USB-HOST=0` |
| Gadget after recovery | UDC `configured`, carrier `1` |
| AC/VBUS edge counters | All four remain zero, including removal counters |
| Input | Original keypad handle remains connected without ioctl/poll errors |
| Memory and journal | Process checksum passes; kernel journal retains the complete starting prefix |
| Cleanup | RTC, PM controls, console and traces restored; conservative power-key suppression retained after failure |

The first failing health predicate is `usb_absent`. It is not a PM callback
failure or a missing RTC event. Later checks in the health function do not run
after that exception, so unexecuted checks must not be described as passing.
In particular, unchanged removal IRQ counters also fail the transition test's
strict exact-edge requirement. Their absence must not be hidden by relaxing
that requirement or inventing interrupt events in software.

The USB trace reports no loss and contains PM boundary/callback records but
no recorded MUSB state, MUSB USB-status interrupt or gadget state/endpoint
events. The kernel journal delta has the sleep entry/exit and keypad reset-resume,
without a USB gadget disconnect/reconfiguration sequence. These observations
support investigation of an unprocessed logical disconnect; they do not prove
the precise register/interrupt ordering or a hardware interrupt delivery cause.

CPU-idle driver remains `none`, and no timekeeping-freeze pair was observed.
The s2idle duration establishes neither CPU/DRAM retention nor energy savings.

## Read-only postmortem

Collection temporarily encountered SSH channel timeouts, then recovered the
original result over Wi-Fi without another PM submission. Two subsequent saved
collections used:

```sh
task device:sleep-collect RUN=5444c50735c04848846467980c65125e ROUTE=wifi
```

| Capture beneath `.local/diagnostics/` | Snapshot monotonic time | State |
| --- | --- | --- |
| `20261004T091657.013020Z` | 1744.591 | Same boot; original result identical; UDC configured/carrier1 with absent VBUS/extcon |
| `20261004T091902.936169Z` | 1870.489 | Same stale state about 205 seconds after recorded return; original result still identical |

The second recovery snapshot SHA-256 is
`bf4db6a6b10c4269c4d59d461f5cab59b5ca47f79bfffbeb9d3202eb17ebc361`.
Its battery telemetry reports valid monitoring, 92%, discharging, 3.904 V.
This is a software reading, not a calibrated capacity or power measurement.
The unit's saved recovery record reports owned controls restored with no errors.
Only the conservative power-policy owner/drop-in remains; short POWER actions
are suppressed until deliberate recovery. Do not tell the owner to shut down
using the short button while that guard remains.

After these captures, the owner performed one separately requested reconnect,
waited thirty seconds and confirmed the console remained normal. USB collection
`20261004T092123.973272Z` and independent Wi-Fi status
`20261004T092124.876479Z` both succeeded. The former confirms the same boot,
identical failed original, external USB power present/online, extcon USB1,
configured UDC and carrier1. ACIN/VBUS plugin counts each become 1; removal
counts remain zero. Battery telemetry reports 94%, charging. This establishes
access after the owner's reconnect, not automatic recovery of the original
asleep-removal case. Power-key suppression remains; no reboot was requested.

## Source interpretation and next correction

The applied [MUSB sleep patch](../kernel/patches/0025-musb-system-sleep-pullup.patch)
clears the physical pull-up in `musb_gadget_suspend()` but deliberately leaves
logical disconnect handling to the usual interrupt/reset paths. Resume restores
controller readiness and applies connection intent. It does not call the gadget's
disconnect callback or reconcile a cable removed while those paths were quiescent.
This limitation was explicit in [report 128](128-musb-system-sleep-candidate.md).

The pinned Linux source's `musb_g_disconnect()` clears negotiated speed, calls
the bound gadget's disconnect callback, changes peripheral OTG state to idle,
sets `USB_STATE_NOTATTACHED`, and clears activity. The existing sleep path does
not call it. Meanwhile, the [PHY PM patch](../kernel/patches/0012-sun4i-usb-phy-suspend-work.patch)
schedules cable reconciliation after resume. The pinned Sunxi glue subscribes
to `EXTCON_USB_HOST`, not the device-side `EXTCON_USB` notification. Thus a correct
PHY detector result is not by itself proof that the gadget receives logical
disconnect handling. The observed mismatch is consistent with this gap, but a
corrected image still needs hardware evidence to establish the cause.

NEO-112 tracks the correction. Audit disconnect callback ordering, queued endpoint
requests, IRQ concurrency and driver unbinding before adding a call: the existing
disconnect callback drops the controller lock, so placing it blindly inside a
PM critical section is insufficient. Evaluate retiring the old USB session when
the driver intentionally detaches for sleep, or explicit resume reconciliation,
while preserving requested connection intent and the role/wake/quirk scope.
Test no-cable resume, unchanged cable, later-device suspend abort, duplicate
disconnect events, callback-triggered intent changes and unbinding. Never merely
write a fake carrier/UDC state or restart the userspace gadget to pass the test.

Missing PMIC removal counters are a second unresolved observation. Distinguish
disabled/non-wake interrupt handling from the known board edge-detection behavior
before assigning a cause. A truthful state reconciliation need not manufacture
a hardware edge, and this original strict qualification remains failed either way.

No new image has been built. Attachment-while-asleep and further actual sleep
remain pending review/correction. Any subsequent physical reconnect is a separate
recovery observation and cannot retroactively pass this run.
