# Diagnostic.12 PM debug qualification (NEO-66)

1 October 2026, Pacific/Auckland. CPI v3.1, image `0.1.0-diagnostic.12`,
kernel `6.18.54-gameshellneo12`, boot
`741d1c20-1ae2-4aec-85b4-b6b87f0dfcf4`. This follows the passing
[installation and baseline](86-diagnostic12-installation.md) and qualifies
the normal paths through Wi-Fi patches 0014–0017.

One freezer check and five traced devices checks passed, including a separately
ready four-cycle batch. The owner confirmed the normal dim console after both
the initial driver cycle and the batch. These are kernel debug stages, not
actual sleep or power-button wake tests.

## Saved sequence and controls

After the owner explicitly replied ready, the saved tasks ran sequentially:

```sh
task device:pm-test STAGE=freezer CYCLES=1
task device:pm-test STAGE=devices CYCLES=1 WIFI_TRACE=1
```

The driver cycle began only after the freezer task passed. The existing
image, USB-power, network, service, radio, keypad and process-memory gates
were retained, as was the 30-second post-resume recovery wait. No stage was
resubmitted. The owner was instructed to leave USB and controls untouched.

Normal sleep remains masked. Only the `freezer` and ordinary `devices`
stages were selected; late/noirq, platform, processors, core and actual s2idle
were not entered. Each includes the kernel's deliberate five-second debug
pause. In the locked source, `kernel/power/suspend.c:suspend_test()` implements
that pause with `mdelay()`, so CPU activity across these tests is not sleep
power or an idle-energy benchmark.

## First results

| Stage | Run | Debug-stage duration | PM success count |
| --- | --- | ---: | --- |
| Freezer | `2902bdffdc6e48d5acc2914c70ad4b2b` | 5.265 s | 0 → 1 |
| Devices with Wi-Fi trace | `948b3bf1a4ea4b0eaab582fef4fb80db` | 7.565 s | 1 → 2 |

Both runs passed independent USB and Wi-Fi SSH checks against the same boot,
process-memory verification and restoration checks. All PM failure counters
remained zero. `pm_test=none` and `pm_async=1` were restored.

The original keypad handle remained connected, without held keys. USB device
`1-1`, device number 2 and input `event1` remained unchanged, with the retained
supply enabled and persistence set to 1. This is connection continuity; no
physical button presses were requested.

The driver trace has zero lost events and shows successful ordinary brcmfmac
suspend/resume callbacks. INFO/timestamp-off supplicant logging and the private
trace instance were restored. The kernel delta contains no new driver-error
message; the internal keypad's existing USB reset still occurs without losing
its identity or open input handle.

## Wi-Fi recovery observation

The first post-resume connection attempt reported association status 16 and
returned from `ASSOCIATING` to `DISCONNECTED`. A second attempt completed the
four-way handshake. The driver can synthesize status 16 for multiple failures;
this event alone is not proof that the access point rejected the connection.
See the existing [source audit](76-wifi-resume-authentication-source-audit.md).

| Logged event | Monotonic seconds |
| --- | ---: |
| Kernel PM exit | 3326.937459 |
| First attempt reports status 16 | 3327.806831 |
| Second attempt enters `ASSOCIATING` | 3328.934680 |
| Second attempt reaches `ASSOCIATED` | 3329.295698 |
| Handshake message 1 processed | 3330.015560 |
| Key negotiation completes | 3330.083675 |

Authentication completion was logged about **3.146 seconds after PM exit**.
The trace recorded three EAPOL receives and two transmit submissions. An
earlier userspace EAPOL receive was logged while still associating; the
allowlisted metadata does not establish why that frame did not immediately
complete the exchange. Payloads/keys are not captured.

Recovery passed the unchanged deadline and both SSH checks. The transient
first-attempt failure is retained for comparison; it neither resolves NEO-55
nor establishes a regression caused by these patches. No authentication
timeout or long backoff was observed in this first capture.

## Four-cycle batch

After confirming the first normal console return, the owner explicitly replied
ready for four more cycles. The saved task ran:

```sh
task device:pm-test STAGE=devices CYCLES=4 WIFI_TRACE=1
```

All four cycles passed on the same boot, with the existing 20-second spacing.
Each recovered independent USB and Wi-Fi SSH, retained the original keypad
handle/identity, passed process-memory verification and restored the owned
PM/logging/trace settings. All recorded device-PM callbacks returned zero,
all traces reported zero lost events, and firmware-load count remained one.
Network profile, firmware/NVRAM hashes, charger settings, CPU policy and
backlight matched their corresponding preflight snapshots.

| Cycle | Run | Debug stage | Authentication logged after PM exit | EAPOL RX / TX | PM success |
| --- | --- | ---: | ---: | --- | ---: |
| 1 | `2e8069f84332475d94c494dda7ea1b3c` | 7.688 s | 1.065 s | 2 / 2 | 3 |
| 2 | `54702956e8eb4f31b61f517021855225` | 7.533 s | 0.550 s | 2 / 2 | 4 |
| 3 | `3626f56fb32c44ba81720ccdfa1bbeff` | 7.618 s | 0.605 s | 2 / 2 | 5 |
| 4 | `645a2c47ca57443cab9aa2fa727f16cb` | 7.561 s | 1.508 s | 3 / 3 | 6 |

None of these four captures recorded association rejection or authentication
timeout. Cycle four logged handshake message 1 received and message 2 sent
twice, followed by message 3, message 4 and key-negotiation completion. The
metadata establishes that repeated exchange, not whether the first message 2
was lost over the air, unprocessed by the AP or delayed elsewhere.

Cycles one and two logged the previously observed `xmit rejected state=0`
message, yet completed authentication and both SSH checks. It remains separate
from proof of an authentication failure. No firmware-crash, SDIO-removal,
runtime-PM-underflow, unsupported-register, kernel warning or oops marker was
present in the final snapshot.

The first standalone devices run and every batch cycle encountered a transient
USB collection failure; the final cycle recorded two. These were channel
timeouts/connect failures or a closed SSH session during USB restoration.
The host also printed a banner-read exception in the final cycle. The recorder
retrieved the **same persistent run IDs**, never resubmitted a PM stage, and
subsequently verified both SSH routes. Recovery of collection does not change
the device's original postflight sampling time or its acceptance gates.

Final PM success count is six, including the freezer check; every failure
counter is zero. `pm_test=none` and `pm_async=1` are restored, normal sleep
remains masked, and the owner confirmed normal console/brightness. USB and AC
are present/online; battery monitoring remains valid at 100%/Charging. The
backlight is at brightness 1 with `bl_power=0`. No further test is running.

## Interrupt/CPU observation

The saved before/after `/proc/interrupts` and `/proc/stat` snapshots cover
39.850 seconds for the devices test, including setup, the debug pause, resume
and the post-resume wait. The Wi-Fi host's `GICv2 93` MMC interrupt increased
by 2,649 counts, about 66.5/s over that whole interval. There was no hang or
lost trace, but this coarse count does not isolate the IRQ-deferral gap or
prove that a brief interrupt burst did not occur.
The host is identified by the locked A23/A33 DTS's MMC1 `GIC_SPI 61` binding
(GIC interrupt ID 93), not solely by the shared `sunxi-mmc` display name.

Aggregate non-idle CPU accounting was about 13.53% across four CPUs, compared
with 13.38% over the freezer window. These different stages and tracing loads
are not matched energy or performance comparisons. The percentage uses the
first eight aggregate CPU counters, with idle and I/O-wait excluded from busy
time; guest counters are not added again. Sequential snapshots, debug busy
waiting, inspection and network traffic limit attribution.

| Batch cycle | Snapshot interval | Wi-Fi-host IRQ increase | Whole-window IRQ/s | Aggregate busy CPU |
| --- | ---: | ---: | ---: | ---: |
| 1 | 39.954 s | 2,528 | 63.27 | 14.54% |
| 2 | 39.846 s | 2,262 | 56.77 | 13.39% |
| 3 | 39.977 s | 2,519 | 63.01 | 14.27% |
| 4 | 39.921 s | 2,508 | 62.82 | 11.28% |

There is no large sustained increase in these aggregate counts across the
batch. Without matched diagnostic.11 counters or a trace focused on the brief
deferral interval, this does not establish an improvement, exclude short IRQ
bursts or prove every pending interrupt was serviced correctly. Successful
handshakes and both network routes do establish useful post-resume progress.

## Evidence and remaining work

Private evidence under `.local/diagnostics/`:

- Freezer: `20261001T024322.102736Z/cycle-1/result.json`.
- First devices cycle: `20261001T024450.641846Z/cycle-1/result.json`.
- Four-cycle batch: `20261001T025002.118799Z/cycle-{1,2,3,4}/result.json`.

Each cycle retains its before/run/result records and any collection error log.
`.local/neo66-summary.json` records the derived timing/counter observations.

Host task logs are `.local/neo66-freezer.log` and
`.local/neo66-devices-one.log`; the batch log is `.local/neo66-devices-four.log`.
All three tasks are finished, and both requested visual confirmations passed.

Hardware failure injection, reset/removal races, precise sleep-gap IRQ
behaviour, physical input/cable checks and actual sleep remain unqualified.
The subsequent physical-input and four USB reconnect checks passed in
[report 90](90-diagnostic12-input-usb-validation.md); the other limits remain.
The diagnostic.11 recovery checkpoint remains available as described in
report 85. No driver or policy change was made during this test slice.
The first-attempt status 16 and repeated final-cycle handshake remain useful
NEO-55 evidence, not a resolved cause or a demonstrated patch regression.
