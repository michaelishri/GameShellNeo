# Internal keypad recovery and PM tracing (NEO-40)

30 September 2026. CPI v3.1, running diagnostic.7 / Linux
6.18.54-gameshellneo7. The keypad disconnect is confirmed; a retention fix has
not yet been selected. New trace support is prepared for the next image.

## Live findings

`task device:keypad-inspect` captured the following without changing policy:

| Item | Observed value |
| --- | --- |
| Device | `4242:e131`, `rancidbacon.com UsbKeyboard`, revision `0100` |
| Host | OHCI `1c1a400.usb`, USB path `1-1`, low speed 1.5 Mbit/s |
| USB persistence | `1`, already enabled |
| Runtime policy | Keypad `power/control=on`, no extra USB quirk |
| Remote wake | Configuration attributes `0x80`: not advertised; no device wakeup control |
| Supply | `keypad-vbus`, nominal 5 V, enabled, one regulator consumer reference |
| Input | `/dev/input/event1`, stable `by-id` and `by-path` links present |
| Current diagnostic kernel | Dynamic debug and event tracing unavailable |

Private inspection:
`.local/diagnostics/20260930T043741.898116Z/keypad.json`.
The supply reading is Linux state, not an electrical measurement.

One additional **devices debug stage**, with controls untouched and USB
connected, tested an open evdev handle. It passed the existing PM, memory,
configuration, service and independent USB/Wi-Fi SSH checks. This remained a
five-second debug pause before later PM stages, not actual sleep.

| Observation | Before | After |
| --- | --- | --- |
| USB device number | 7 | 8 |
| Input instance | `input6` | `input7` |
| Event filename | `/dev/input/event1` | `/dev/input/event1` |
| Original open handle | Healthy; no held keys | `POLLERR | POLLHUP`, `EVIOCGKEY` returns `ENODEV` |
| Newly opened handle | — | Healthy; no held keys |

The stable links returned, but they do not repair an already-open handle. An
application that only opened input at startup would need reconnection handling
if this disconnect remains part of the sleep policy. This is direct evidence,
not merely a possible consequence of re-enumeration.

The new input registration appeared **1.343356 seconds after PM exit** in this
cycle. That is a kernel-log interval for this debug run, not final wake latency
or the time of the first successfully delivered button press. The complete
stage took 9.575588 seconds, including the deliberate debug wait. One keypad
disconnect and two known MUSB ULPI warnings occurred. PM successes increased
from 6 to 7, failure counters remained zero, and `pm_test=none` / `pm_async=1`
were restored. The boot did not change.

Evidence:
`.local/diagnostics/20260930T044052.674424Z/cycle-1/result.json`,
run `863be5ad83dd4cfda92a3b1c9ddc9edc`.
The input observer never grabs the keypad or injects events. No held-button
sequence was requested, so that behavior is still unqualified.

## Source-supported explanation

The locked Linux source and board DT expose this path:

1. Both EHCI and OHCI reference USB PHY 1. The board assigns its VBUS supply to
   the PL2-controlled fixed `keypad-vbus` regulator.
2. `hcd_bus_suspend()` calls `usb_phy_roothub_suspend()` for system PM.
3. That helper calls `phy_power_off()`. PHY reference counting delays the
   underlying power-off until its users release it.
4. `sun4i_usb_phy_power_off()` disables its VBUS regulator. Both host controllers
   participate in a devices-stage test. The matching power-on enables it again.
5. `check_port_resume_type()` can reject a port with no connection even with
   USB persistence enabled. Its connection retries are only 200–300 microseconds
   each. Persistence is not a general wait-until-the-keypad-reboots policy.

This makes keypad power cycling a strong explanation for the observed removal,
but the exact regulator transition and port-status branch have not yet been
recorded on this board. OHCI's platform clock shutdown alone does not prove a
rail cut. The new trace is designed to distinguish those events.

The historical keypad source is available in
`GameShell/Code/Keypad/` at commit
`523cf591e2f955d001d257d7c850406f9fd917eb`. Its V-USB constructor deliberately
disconnects for 250 ms before initial USB setup. The sketch also contains timer
and delay code whose behavior depends on its Arduino build. Neither establishes
the installed firmware's exact behavior or a safe replacement image. Do not
infer a measured startup delay from that source, or flash the unconfirmed MCU.

Linux's HID driver already supplies resume and reset-resume callbacks. The
failure is not explained by a missing generic HID resume method. The separate
external MUSB controller warnings are addressed by patch 0011, not by this
keypad investigation.

Primary source paths in the hash-locked Linux archive are
`drivers/usb/core/{hcd,phy,hub}.c`,
`drivers/usb/host/{ohci-platform,ohci-hcd,ohci-hub}.c`,
`drivers/phy/{phy-core,allwinner/phy-sun4i-usb}.c`,
`drivers/hid/usbhid/hid-core.c`, and `drivers/input/evdev.c`.
The general persistence contract is also documented in the archive's
`Documentation/driver-api/usb/persist.rst` and the
[upstream USB persistence documentation](https://docs.kernel.org/driver-api/usb/persist.html).

## Saved diagnostics

```sh
task device:keypad-inspect
task device:pm-test STAGE=devices CYCLES=1
# After booting a kernel with the new diagnostic tracing support:
task device:pm-test STAGE=devices CYCLES=1 KEYPAD_TRACE=1
```

Ordinary PM tests now record keypad identity, stable links, the original open
handle and a freshly opened handle after recovery. A dead original handle is
reported separately from the existing stage pass; the latter proves recovery,
not uninterrupted input continuity.

The trace option enables only selected USB PM dynamic-debug callsites and a
private tracefs instance. It records the keypad regulator's enable/disable
events, the PM stage timeline and driver callback start/end times, using a
128 KiB buffer per CPU. Callback timestamps support attribution of recovery
delays without enabling function instrumentation. It saves
trace data and overflow counters in the same private result. Any overflow fails
the trace qualification. It does not enable global function tracing or change
power, persistence, wake or autosuspend policy.

The next kernel fragment enables dynamic debug and event tracing, with function
instrumentation disabled. The recording itself is opt-in and restricted to
`STAGE=devices`. Current diagnostic.7 refuses this option before entering PM
because the required facilities are absent. The diagnostic.8 full build passed
in [report 59](59-diagnostic8-preparation.md); hardware tracing remains pending.

An ownership file records the selected debug flags and boot ID before mutation.
Normal/error cleanup restores those flags and removes only the private trace
instance. The existing independent `ExecStopPost` also restores tracing;
`task device:pm-restore` retries recovery after an interruption. Existing/foreign
ownership is refused. No userspace cleanup can recover a hung kernel.

Host tests cover event-path reuse with a dead original handle, input-handle
observation, cleanup after exceptions, bounded callsite selection,
missing trace events, foreign ownership, failed restoration and overflow.
The current ordinary observer also passed the physical cycle described above.
The detailed trace has not yet run on hardware.

## Decision after the trace

If the trace confirms a rail cut followed by a missing connection, compare a
temporary retention experiment with the existing power-off policy. Retention
may improve continuity but keeps keypad circuitry powered; its energy cost
must be measured. Do not make `regulator-always-on` the permanent answer without
that comparison.

If keeping power still loses the device, investigate OHCI context/port recovery
and descriptor/control-transfer failures. If power removal is the eventual
policy, measure cold initialization and test reopening by stable identity,
including press-across-sleep and release-during-sleep cases. Clear stale pressed
state when a handle is removed and reconcile the newly opened device. These requirements
belong to the future input integration even though a launcher is out of scope.
Keep power-button-only wake. No source or live change here enables keypad wake,
improves measured sleep energy, or qualifies subsecond resume.
