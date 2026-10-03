# USB resume metadata recorder (NEO-95)

3 October 2026, Pacific/Auckland. Focused USB tracing now works on the installed
diagnostic.17 image without a kernel rebuild. Passive awake qualification checks
setup, filtering, bounded capture, restoration and both SSH routes. No driver
correction, additional sleep attempt or automatic USB-resume pass is claimed.

[Report 120](120-first-rtc-sleep-findings.md) records the original RTC-wake failure;
[report 121](121-usb-reconnect-and-clean-boot.md) separates subsequent cable
recovery and Mac sleep from that original failure.

## What the next trace can distinguish

The board originally returned from sleep with its gadget bound but UDC state
`not attached`. Later, after intervening cable handling, it reported `configured`
while the Mac's ECM interface was inactive. These require observations at
different layers rather than assuming one cause.

| Capture | Question it helps answer |
| --- | --- |
| MUSB state and nonzero USB bus interrupts | Did the controller see reset, disconnect, suspend or resume activity? |
| Gadget state/connect/disconnect and endpoint enable/disable | Did enumeration advance, and were endpoints enabled successfully? |
| EP0 and short request queue/completion metadata | What happened to control requests and candidate ECM notification requests? |
| Ten audited ECM dynamic-debug sites | Did ECM request link-up/link-down or speed notification, encounter a queue/error completion, or enter its lifecycle callbacks? |
| PM callback and suspend/resume events | Where do these events fall relative to device and system PM stages? |
| Existing read-only Mac collection | Did the host enumerate the device, activate its network interface and obtain the USB route? |

The trace retains endpoint names, request identifiers, lengths and return/status
codes. It does not copy packet payloads. The request filter includes EP0 and
8-/16-byte requests: those lengths match ECM's connection/speed notifications,
but **length alone does not identify a notification endpoint**. Correlate with
ECM messages, endpoint lifecycle and the controller trace; do not infer a lost
notification from one unmatched request.

The audited `f_ecm.c` notes that an initial notification may legitimately wait
in the FIFO until the host listens. Also, the queue tracepoint runs after the controller queue operation: a
completion on another execution context can race ahead of that tracepoint.
The API forbids an inline completion callback inside the queue operation;
request reuse and asynchronous ordering still matter when interpreting traces. Successful
device-side completion would still not establish that macOS configured its
network interface correctly.

## Implementation and ownership

[`tools/usb_trace.py`](../tools/usb_trace.py) checks that there is one bound UDC
and one ECM-only gadget, verifies required live event formats, and uses its own
`gameshellneo-usb` trace instance. It sets a 256 KiB buffer per CPU and the `mono`
clock, verifies filters/enables and inserts exact-run start/end markers. Per-CPU
overrun/drop counters and marker continuity must pass.

Bulk-only interrupt traffic is excluded with `int_usb != 0`. Raw MUSB register
read/write events, arbitrary MUSB debug output and network packet capture are
not enabled. No extra USB register reads are introduced.

Global dynamic-debug changes are restricted to ten exact audited `f_ecm.c`
messages. The journal prefix is derived from the live gadget device and driver
identity (`configfs-gadget.gameshellneo gadget.0` on this boot), rather than
assuming the configfs directory name is the kernel device name. Their selectors
and original flags are saved before mutation; existing
enabled diagnostics or changed site catalogues are rejected. Journal collection
requires the original cursor to remain present, rejects an overlong interval,
and extracts only typed ECM messages with monotonic timestamps. It does not save
unrelated free-form journal messages in the USB record.

Cleanup validates the boot/run owner, removes its trace instance and restores
the original logging flags. A trace cleanup error still attempts logging
restoration. Foreign logging changes are preserved and reported. The owner
record remains if cleanup is incomplete. Signal/exception tests exercise partial
setup, trace loss, missing journal continuity and failed cleanup.

The passive sample runs in a device-owned systemd unit with a 60-second bound
and exact-run `ExecStopPost` cleanup, under the existing PM-experiment lock.
Its result and helper-source hashes are saved on the board. SSH failure does
not cause an automatic resubmission. A hard kill before the result is written
can leave no complete result; cleanup alone is not a successful capture.

The real-sleep controller now includes this recorder in its source identity,
capture, health and run-scoped recovery paths. This invalidates old rehearsals
for future submissions. No sleep admission or CPU-idle/timekeeping acceptance
criterion was relaxed. The integration has source regression coverage; its
combined live PM path still needs a fresh qualified sequence and rehearsal.

## Repeatable commands

```sh
# Ten passive seconds while awake; leaves interfaces and PM settings alone.
task device:usb-trace-sample
# Read the unchanged original result, including failed results.
task device:usb-trace-collect RUN=<run-id> ROUTE=wifi
# Save the Mac side before any reconnect or network change.
task mac:usb-inspect
```

These commands use `.env` and the existing pinned SSH paths. The sample verifies
both SSH routes on the same boot after cleanup. Collection never starts tracing,
performs recovery or resubmits a diagnostic. See the README for the separate
attended sleep workflow; this task does not enter sleep.

## Awake evidence and limits

Final-source passive run `325abfd44a3e41468960af400208a2ad` passed on clean boot
`4ffd75dc-2dae-4164-8bd2-90ad08ed1885`. Private capture:
`.local/diagnostics/20261003T090120.954680Z/`.

UDC remained `configured`, USB carrier stayed at 1 and the boot did not change.
PM successes and failures remained 0/0, `pm_test=none` and `pm_async=1`. Both SSH
routes worked, logging and tracing restored, and all four CPUs reported zero
trace loss. The quiet sample contained only its two boundary markers, with no
ECM lifecycle or notification event: this qualifies recorder setup and cleanup,
**not real notification delivery, sleep recovery, latency or energy savings**.
The ECM parser's live message coverage remains to be demonstrated during the
next controlled lifecycle event; its prefixes and formats have source and sysfs
checks, with parser regression coverage.

Earlier setup samples are retained at `20261003T085805.068546Z` and
`20261003T085916.176042Z`; the first sample's original result was separately
retrieved over Wi-Fi at `20261003T085838.232266Z`. The final version additionally
enforces boundaries for shared PM captures and derives the correct live gadget
logging prefix. Earlier idle captures did not exercise the ECM message parser.

`task check` passes: 13 runtime tests, 441 tooling tests (one intentionally skipped),
the compiled current-selector and Mac mount-guard regressions, Bash syntax and
ShellCheck. Fifteen new USB tests cover metadata privacy, audited sites,
ownership, partial setup, cleanup and collection; the existing sleep recovery
test now also checks exact-run USB cleanup.

Audited local sources are the pinned Linux 6.18.54 files
`drivers/usb/musb/musb_trace.h`, `drivers/usb/gadget/udc/{core.c,trace.h}`,
`drivers/usb/gadget/function/{f_ecm.c,u_ether.c}` and
`include/trace/events/power.h`. The saved result contains the live trace formats
and ECM site catalogue for comparison with those sources.

NEO-95 remains open. Next, resolve NEO-96's sleep-measurement criteria and prepare
the new boot's prerequisite sequence and same-source rehearsal before an
observed reproduction. Keep the Mac awake and capture both ends before changing
the cable. Choose a driver correction from that evidence, then qualify it with
the cable untouched; a reconnect recovery remains a separate result.
