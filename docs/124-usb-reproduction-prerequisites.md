# Diagnostic.17 prerequisites for USB resume reproduction (NEO-95)

3 October 2026, Pacific/Auckland. All seven current-boot debug prerequisites
passed: freezer, driver and five late/noirq cycles. The owner confirmed the
normal dim console after the driver and first late/noirq checks, then readiness
for four late/noirq repeats. Afterward the owner confirmed: “Screen looks normal.”
No actual sleep request was submitted.

This continues [report 122](122-usb-resume-metadata-recorder.md)'s USB tracing
preparation and [report 123](123-sleep-measurement-criteria.md)'s corrected
measurement criteria. It does not resolve the original USB resume failure.

## Identity and sequence

- Image/kernel: diagnostic.17 / `6.18.54-gameshellneo17`.
- Boot: `4ffd75dc-2dae-4164-8bd2-90ad08ed1885`.
- Current-boot startup and both SSH routes passed before observation; the awake
  RTC delivery/restoration prerequisite is recorded in report 123.
- USB stayed connected. No button or cable interaction was requested during
  these debug cycles.

| Check | Run ID | PM successes before → after | SDIO references |
| --- | --- | --- | --- |
| Freezer | `2514d9ce61d743e3afcd70e42d036b01` | 0 → 1 | 2 → 2 |
| Driver callbacks | `4869c20bf13e4bfbb5bcd7aeb43b8ce2` | 1 → 2 | 2 → 2 |
| Late/noirq initial | `915ace20c1774cc886bfb533066dc2f0` | 2 → 3 | 2 → 2 |
| Late/noirq repeat 1 | `609b69913a404958982d249e5ad48a78` | 3 → 4 | 2 → 2 |
| Late/noirq repeat 2 | `ae5aed7c718a4db4a681648f7f4598c1` | 4 → 5 | 2 → 2 |
| Late/noirq repeat 3 | `4b451c8d3c0942dd97d65201c071bbbf` | 5 → 6 | 2 → 2 |
| Late/noirq repeat 4 | `1cc2af03237d432591019b2e445f9871` | 6 → 7 | 2 → 2 |

Each result was reviewed before the next test was submitted. All seven
completed on the same boot, with zero PM failures, independent USB/Wi-Fi SSH
proofs and clean power-key handback. No power-key event was recorded.

The driver and late/noirq tests additionally retained the original keypad handle,
USB/input identity and process-memory canary. Their keypad and Wi-Fi traces report
no loss/overrun and restored their settings. The keypad descriptor reports no
hangup, poll error, ioctl error or disconnection; no key remains held. The
kernel deltas contain no unsupported USB-register warning. The late/noirq trace
contains all four late/noirq suspend/resume phases and both RSB noirq callbacks.

The driver and each late/noirq cycle recorded one transient host collection
failure during recovery. Each collector retrieved its original complete result
and both independent SSH proofs then passed. It did not resubmit PM, reconnect
the cable or change the network. This is distinct from the original actual-sleep
USB failure that remained unrecovered at the end of its observation window.

Recorded stage durations were approximately 5.565 seconds for freezer, 7.892
seconds for drivers and 7.843–8.115 seconds for late/noirq. These include the
five-second PM debug delay and test overhead; they are not sleep
residency, user-visible resume latency or energy measurements. Automated display
setting restoration is supported by the owner's driver, initial late/noirq and
final four-cycle screen confirmations.

## Saved commands and evidence

```sh
task device:pm-power-key STAGE=freezer CYCLES=1
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
task device:pm-platform
# After review and fresh observer readiness, run the same platform task four
# more times, reviewing each result before submitting the next.
task check:sdio-ref-history -- --require-stable \
  .local/diagnostics/20261003T091716.057490Z/cycle-1/result.json \
  .local/diagnostics/20261003T091821.897570Z/cycle-1/result.json \
  .local/diagnostics/20261003T092037.532057Z/cycle-1/result.json \
  .local/diagnostics/20261003T092304.031662Z/cycle-1/result.json \
  .local/diagnostics/20261003T092423.871974Z/cycle-1/result.json \
  .local/diagnostics/20261003T092552.362950Z/cycle-1/result.json \
  .local/diagnostics/20261003T092714.258103Z/cycle-1/result.json \
  > .local/neo95-current-reference-history.json
```

The original complete results are saved at the paths above. The reference
history check passes with a stable count of 2 and unchanged active/forbidden
SDIO runtime policy. This history contains **all seven** required debug results,
with consecutive PM success counts and no intervening PM. It provides the
current-boot prerequisite input for the new-source awake rehearsal; it does not
by itself admit a new actual sleep test.

## Updated-source awake rehearsal

After the final screen confirmation, the saved rehearsal passed:

```sh
task device:sleep-rehearse QUALIFICATION=.local/neo95-current-reference-history.json
task mac:usb-inspect
```

- Rehearsal run: `9e2bcd2564154716b2ff141c8cdb8634`.
- Private result: `.local/diagnostics/20261003T094447.146415Z/result.json`.
- Sources matched the uploaded manifest and current committed helpers.
- The 30-second alarm delivered after 30.290 seconds while awake. RTC IRQ 31
  increased 1 → 2; its event reported count 1 / flags `0xa0`. Alarm restoration
  passed.
- No sleep state was written. PM counts stayed 7/0, SDIO usage stayed 2, and
  the original keypad, memory canary, audio and display settings survived.
- USB, Wi-Fi and keypad traces were complete and restored. The USB trace
  contained 1,162 MUSB interrupt entries and two markers, with no ECM notification
  events; this rehearses capture/cleanup, not notification delivery or resume.
- The original power-key policy was restored with a clean logical release and
  descriptor handback. No policy, RTC or PM-control ownership was left retained.
- Independent USB and Wi-Fi SSH checks passed on the same boot.
- CPU-idle inventory remained driver `none`, CPUs 0–3, governor `menu`,
  clocksource `arch_sys_counter`, with no registered state directories. This
  awake run establishes neither CPU retention nor energy savings.

The separate read-only Mac capture at
`.local/diagnostics/20261003T094557.564528Z` completed all six reads. The USB route
used `en8`, active with an IPv4 address, and the GameShell appeared in the USB
tree. No DHCP, interface or route settings were changed.

The prerequisites and updated-source rehearsal are now complete. A fresh
observer-readiness request for **one** actual RTC-wake reproduction is pending;
it has not been submitted. Preserve the cable and controls during that attempt
so the new USB trace and separate Mac snapshot can distinguish device recovery
from a physical reconnect. No automatic retry of the original failed sleep run
is authorized by this sequence.

The subsequent separately attended attempt is recorded in [report 125](125-traced-rtc-wake-usb-failure.md). It reproduced USB failure and consumed this baseline; the rehearsal and seven debug records must not be reused to submit another sleep attempt.
