# Diagnostic.17 prerequisites for USB resume reproduction (NEO-95)

3 October 2026, Pacific/Auckland. All seven current-boot debug prerequisites
passed: freezer, driver and five late/noirq cycles. The owner confirmed the
normal dim console after the driver and first late/noirq checks, then readiness
for four late/noirq repeats. Final visible-console confirmation after those
repeats is pending. No actual sleep request was submitted.

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
setting restoration is supported by the owner's driver and initial late/noirq
screen confirmations; the final four-cycle visual report remains pending.

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

Next, record the final visible-console confirmation and run the new-source
awake rehearsal. Any actual RTC-wake reproduction requires a successful matching
rehearsal and separate fresh observation; no automatic retry of the original
failed sleep run is authorized by this debug sequence.
