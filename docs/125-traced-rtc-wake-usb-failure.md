# Traced RTC wake reproduces the USB recovery failure (NEO-94 / NEO-95)

3 October 2026, Pacific/Auckland. One separately attended actual-sleep attempt
returned on the original boot and passed the RTC wake criteria, but failed USB
recovery again. The owner confirmed the normal dim console returned. The new
trace places the disconnect handling inside the MUSB resume callback, before
fresh USB enumeration or ECM link notifications. It narrows the investigation;
it does not yet establish the complete cause or qualify a driver fix.

No second sleep request, cable reconnect, interface restart, manual register
write or reboot was performed. The Mac's saved sleep/wake history did not change
during the attempt. This reproduction is distinct from the earlier Mac-sleep case
described in [report 121](121-usb-reconnect-and-clean-boot.md).

## Admission and result

The image remained diagnostic.17, kernel `6.18.54-gameshellneo17`, boot
`4ffd75dc-2dae-4164-8bd2-90ad08ed1885`. The seven accepted debug cycles and
updated-source awake rehearsal `9e2bcd2564154716b2ff141c8cdb8634` are recorded in
[report 124](124-usb-reproduction-prerequisites.md). The owner separately replied
“Yes” to readiness for one actual sleep test, with USB connected and controls
untouched. The submitted run was `f21203e0a1c14442b4acf412d1332792`.

| Check | Observed result |
| --- | --- |
| Entry | One `freeze` request, `pm_test=none`, synchronous device callbacks, wakeup-count handshake and a 30-second RTC deadline |
| RTC | IRQ 31 increased 2 → 3; immediate event count 1, flags `0xa0`; wake IRQ 31; alarm restored |
| Sleep path | Complete late/noirq and RSB callback trace; one s2idle loop lasting about 29.230 seconds in MONOTONIC time |
| PM bookkeeping | Successes 7 → 8, failures remain 0; original PM settings restored |
| SDIO | Runtime usage remains 2, with unchanged active/forbidden policy |
| Keypad and memory | Original USB/input identity and open descriptor retained; no held keys, hangup, poll/ioctl error or disconnect; memory canary intact |
| Display and idle audio | Saved settings restored; owner confirmed the dim console returned normally; idle audio state unchanged |
| Wi-Fi | Retrieved the original failed result and a separate live snapshot on the same boot |
| USB | UDC `configured` → `not attached`; carrier 1 → 0; USB SSH never recovered within the host collection window |
| Recorders | USB, keypad and Wi-Fi traces complete and restored; no trace overrun/drop; journal prefix preserved |
| Diagnostic power-key policy | Input descriptor handed back without recorded key activity, but boot-local ignore policy remains retained because overall health failed |

The saved error is:

```text
ValueError: Device must be healthy, USB-powered and connected to Wi-Fi; failed: usb_configured
```

Kernel PM success alone is not a successful device recovery. The full result
remains `passed=false`; obtaining it over Wi-Fi does not qualify USB recovery.

## What the USB trace adds

Times below are from the USB trace's MONOTONIC clock. The independently recorded
keypad/PM trace gives the 29.229848-second interval used by the RTC validator;
small differences between trace instances are not additional wake latency.

| Time (seconds) | Event |
| --- | --- |
| 4260.710156–4260.710227 | MUSB system-suspend callback completes |
| 4260.740300–4289.970133 | Actual s2idle loop |
| 4290.027811 | MUSB system-resume callback begins |
| 4290.027887 | MUSB interrupt snapshot: `usb 2d, tx 0000, rx 0000` |
| 4290.028039–4290.028139 | ECM bulk IN, bulk OUT and notification endpoints are disabled |
| 4290.028152 | Gadget state becomes `USB_STATE_NOTATTACHED` |
| 4290.028205 | MUSB system-resume callback returns success |

The pinned `musb_regs.h` decodes `0x2d` as SUSPEND (`0x01`), RESET (`0x04`),
SOF (`0x08`) and DISCONNECT (`0x20`). This is one combined status snapshot, not
four independently timed wire events. It does not establish when the host
issued a reset or the physical cause of the disconnect.

The capture contains 152 earlier SOF-status interrupt entries and this one
combined interrupt, with no later MUSB interrupt entry matching the configured
nonzero-USB-status filter. It records no subsequent endpoint enable, EP0 request
or gadget enumeration progress before the end marker. Pure endpoint interrupts
with zero USB status are filtered out; this is not a claim of absolute bus
silence. No ECM connection/speed notification or notification queue/completion
error was recorded. The ECM messages that were captured are `ECM Suspend` and
`ecm deactivated`.

The ECM parser now has live lifecycle-message coverage. It still has no live
notification-delivery qualification. Kernel-journal receipt timestamps are
later than the corresponding ftrace activity while console logging is deferred;
use ftrace for ordering within the resume callback rather than treating those
journal timestamps as the exact callback execution times.

This places the observed failure before successful enumeration and link-up
notification. A hypothesis limited to a lost ECM speed/connect notification
does not explain the absent enumeration in this capture.

One separate diagnostic defect was found while checking the endpoint lines:
the pinned `udc_log_ep` trace formatter prints bare `ret` instead of
`__entry->ret`. The generated trace printer has its own local `ret` from
`trace_raw_output_prep()`. The live event format confirms the same defect.
Consequently, the endpoint lines' trailing `--> 1` is not trustworthy as a USB
operation return code. The captured `enabled=false` field and subsequent gadget
state remain usable. The request and gadget event classes use the recorded
return field correctly. A small formatter correction is tracked in FOLLOW-UP;
it does not itself repair the USB recovery failure.

## Both ends after waking

The live read-only GameShell snapshot still reports USB supply present/online,
PHY extcon `USB=1` / `USB-HOST=0`, mode `b_peripheral` and the original bound
gadget. UDC remains `not attached`, with USB carrier 0. `current_speed` still
reports high-speed, which does not override the unattached state or prove a
working host connection.

The Mac capture before the test showed the GameShell in the USB tree and an
active `en8` USB network interface with IPv4 and the USB route. Afterward the
GameShell was absent from the USB tree, `en8` was inactive without IPv4, and
route lookup fell back to `en0`. Both captures completed all six reads. The
100-entry sleep/wake histories were identical; their latest wake was at
21:12:07 NZDT, before this approximately 22:48 test. No Mac sleep during this
attempt is recorded.

## Driver investigation now justified

The actual pinned source explains the observed software path:

- `drivers/usb/musb/sunxi.c:sunxi_musb_interrupt()` reads and acknowledges the
  status snapshot, then calls the core handler.
- `musb_core.c:musb_stage0_irq()` processes SUSPEND, DISCONNECT and RESET in that
  documented order. `musb_g_disconnect()` notifies the gadget driver, clears its
  connection state and selects `USB_STATE_NOTATTACHED`. A following reset can
  return the controller's OTG state to `b_peripheral` without completing fresh
  host enumeration. That explains why the later peripheral-mode reading is
  compatible with an unattached gadget.
- `musb_suspend()` disables interrupts and saves context. Its peripheral branch
  explicitly leaves forced disconnect as unfinished work. `musb_resume()`
  restores context and enables interrupts. The recorded combined status arrives
  during this resume callback.
- `musb_pullup()` controls `MUSB_POWER_SOFTCONN`; context restoration also writes
  POWER. The current metadata trace does not directly establish electrical
  pull-up transitions or distinguish an old latched host reset from a fresh
  enumeration attempt.

The next driver slice should audit peripheral detach/reconnect ownership across
system suspend: preserve the gadget's requested connection state, avoid
advertising an unresponsive peripheral while asleep, and reconnect only after
controller/PHY state is ready. Examine interrupt/context ordering and any
required supported-register observations before selecting a patch. The source
and trace make this a stronger lead than an ECM notification retry, but the
full hardware cause is still unproven.

Do not simply reorder SUSPEND/DISCONNECT/RESET handling: the core documents that
order as required by the controller manual. Do not discard pending status bits
or add a userspace gadget restart to make the test appear successful. A candidate
needs actual-source regression coverage followed by untouched-cable sleep/wake
qualification, with physical reconnect behavior checked separately.

## Evidence and repeatability

Commands used for this attempt are recorded below. **The sleep command is
historical evidence, not a request to rerun it:** the seven-cycle baseline is now
consumed and the failed run's power-key suppression remains active.

```sh
task device:sleep-rtc QUALIFICATION=.local/neo95-current-reference-history.json REHEARSAL=9e2bcd2564154716b2ff141c8cdb8634 ATTENDED=1
task mac:usb-inspect
task device:sleep-collect RUN=f21203e0a1c14442b4acf412d1332792 ROUTE=wifi
task report:sleep-evidence RESULT=.local/diagnostics/20261003T095154.319623Z/result.json
```

- Original submission and USB collection timeout: `20261003T094804.396010Z`.
  Its local `result.json` is only a started record.
- Final failed result and read-only recovery snapshot: `20261003T095154.319623Z`.
  Final-result SHA-256:
  `b95cd765f1b45c7e77b89ea813ffed108f5199a9c2c404216eed366898498f22`.
- Mac before/after: `20261003T094557.564528Z` / `20261003T094923.195336Z`.
- Offline RTC/trace/clock assessment: `20261003T095347.580874Z`. Its checks pass;
  it preserves the original failure and sets `overall_requalified=false`.

All capture paths are beneath the private `.local/diagnostics/` directory.
The source manifest matches the accepted rehearsal. No source or image changed
during this attempt. The original result and owned-cleanup record both retain
the policy owner/drop-in, while RTC/PM/trace controls were restored successfully.
Normal short-press shutdown is consequently suppressed until reviewed recovery;
Wi-Fi remains the working management route. No recovery was silently applied.

Alarm-to-return time was 32.518 seconds; the state-write interval was 31.692
seconds. BOOTTIME minus MONOTONIC was about 0.251 microseconds, within the 26.584
microsecond sampling bound, with zero timekeeping-freeze pairs. CPU-idle driver
remains `none`. These results prove neither stopped timekeeping, deep retention,
user-visible wake latency nor energy savings. NEO-94, NEO-95 and NEO-96 remain open.
