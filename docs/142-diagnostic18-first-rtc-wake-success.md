# Diagnostic.18: first successful RTC wake and USB recovery

4 October 2026, Pacific/Auckland. NEO-95 and NEO-97.

One separately attended actual s2idle attempt on diagnostic.18 passed RTC
wake and device recovery, including automatic USB enumeration and independent
USB/Wi-Fi SSH. The owner confirmed the dim console returned without touching
the cable or controls. This is the first successful hardware result for the
MUSB system-sleep connection candidate. Repeated sleep and cable/host-state
qualification remain open; one successful cycle does not establish production
reliability or low-power efficiency.

## Identity and admission

| Item | Value |
| --- | --- |
| Kernel/image | `6.18.54-gameshellneo18` / `0.1.0-diagnostic.18` |
| Boot | `e419f334-0a16-4b04-96d2-d97a2e4d5d0b` |
| Actual-sleep run | `b32de0c57c474275b73ad5cf34a49b36` |
| Same-source awake rehearsal | `0120c40f292b4e1b96a89a051ae47986` |
| PM success/failure | 7/0 → 8/0 |
| SDIO runtime references | 2 → 2, active/forbidden |
| USB system-wake policy | Disabled throughout |

[Report 140](140-diagnostic18-card-installation.md) records the exact image,
guarded card installation, startup checks, seven sequential attended debug
prerequisites and same-source awake rehearsal. The owner then gave fresh
readiness for **one** actual sleep attempt. The saved task submitted it once;
no physical reconnect, gadget restart, lease renewal or PM resubmission was
used to obtain recovery.

The candidate is [patch 0025](../kernel/patches/0025-musb-system-sleep-pullup.patch)
with the explicit disabled USB wake policy described in
[report 128](128-musb-system-sleep-candidate.md). Later IRQ-wake, startup,
callback-lifetime, removal and CPU-idle candidates are absent from this image.
The earlier diagnostic.17 failures remain recorded in
[report 125](125-traced-rtc-wake-usb-failure.md).

## RTC wake and measurement limits

The experiment wrote `freeze` with `pm_test=none` and `pm_async=0`.
RTC IRQ 31 increased exactly 2 → 3; the character-device notification had
count 1 and flags `0xa0`. The recorded wake IRQ is 31. Alarm restoration passed.
The trace contains the actual s2idle boundary, all four late/noirq phases and
both RSB noirq callbacks, without a debug-delay return.

| Measurement | Observed value |
| --- | --- |
| Alarm arm to userspace return | 31.762 s |
| Submitted sleep interval, BOOTTIME | 30.931 s |
| In-loop s2idle trace interval, MONOTONIC | 28.582 s |
| Observed timekeeping-freeze pairs | 0 |
| Registered CPU-idle driver | `none` |

The BOOTTIME/MONOTONIC gap is about 0.00000075 s, below the roughly
0.00002313 s sampling uncertainty. No timekeeping-freeze observation is claimed.
These measurements establish functional RTC wake through the s2idle path,
not CPU retention, energy savings or user-visible resume latency. The current
image still lacks the later CPU-idle candidate; the week-long standby target
is not tested here.

## USB recovery evidence

Before and after, the same UDC reports configured, carrier 1 and the same
gadget binding. The trace provides the intervening controller/endpoint evidence:

1. The first non-SOF-only interrupt after s2idle records USB status `0x09`;
   a later interrupt records `0x04` (the MUSB reset bit). This differs from the
   failed diagnostic.17 capture's combined `0x2d` snapshot. These are interrupt
   status observations, not a decoded chronology of electrical bus events.
2. Endpoint teardown returns success, followed by gadget state DEFAULT (5),
   then CONFIGURED (7). Notification endpoint `ep2in` and bulk endpoints
   `ep1in`/`ep1out` are enabled again.
3. ECM diagnostics record deactivation, initialization, connection notification,
   activation and speed notification, without a queue/completion error entry.
   The speed value is a protocol notification, not measured throughput.
4. The known ECM notification endpoint records successful request queue and
   completion pairs of 8, 8 and 16 bytes. Endpoint identity and ECM lifecycle
   establish the notification context; payload bytes were not captured.
5. Fresh independent USB and Wi-Fi SSH checks reach the original boot. The
   collector's temporary channel/banner failures are preserved; it recovered
   the original run rather than submitting another test.

Both USB and Wi-Fi traces are complete and restored. The separate read-only
Mac capture sees GameShellNeo in its USB tree and the original active `en8`
route/address after recovery. Its saved sleep/wake history is unchanged from
the pre-test capture. No host network or power setting was changed.

This is positive hardware evidence for the candidate's intended connection
lifecycle on this board and host. It does not qualify every abort, role,
USB-wake policy, cable state or host-sleep condition.

## Other restoration checks

The original keypad descriptor and USB/input identity survive, with no hangup,
poll/ioctl error, disconnection or held key. The process-memory canary survives.
Display settings return to brightness 1/power 0, and the owner confirms the
normal dim login console. Idle audio state is unchanged.

Power-key policy and descriptor handback pass, with no recorded key event and
no retained diagnostic owner, drop-in, PM-control or RTC owner. PM controls
return to none/async 1/delay 5. Normal sleep targets remain masked. SDIO policy
and count are unchanged; kernel taint and failed-unit checks stay clear. The
kernel delta contains the expected keypad reset-resume and no new fault or
unsupported-register warning. Charging policy is unchanged.

## NEO-97 live endpoint formatting qualification

Both live endpoint formats reference the stored result, so
`endpoint_return_text_trusted=true`. This sleep capture contains four
`usb_ep_disable` and three `usb_ep_enable` events. All seven print `--> 0`,
with the corresponding disabled/enabled endpoint state. The previous
diagnostic.17 printer-status `--> 1` artifact is absent.

Together with [report 127](127-usb-endpoint-trace-format.md)'s 252 actual-source
native/ARM32 formatting scenarios, three negative controls, ARM UDC-core
compilation and the verified installed image, this completes NEO-97's stated
scope. Arbitrary failure returns were covered by source regressions, not forced
on the live board. This is an observability correction; NEO-95's connection
behavior and remaining repeatability checks are separate.

## Reproduction and saved evidence

```sh
# Historical submission: requires fresh owner readiness and an unconsumed
# current-boot prerequisite/rehearsal chain, not permission to replay this run.
task device:sleep-rtc ATTENDED=1 \
  QUALIFICATION=.local/neo95-diag18-reference-history.json \
  REHEARSAL=0120c40f292b4e1b96a89a051ae47986
task mac:usb-inspect
```

Original result: `.local/diagnostics/20261003T165839.817277Z/result.json`.
SHA-256: `e2d0873bccccb55d14d43edb0648686f6477585e1b152557960830b157b3a692`.
The directory also retains source identity, prerequisite receipt, submission
identity and collection errors. Host log: `.local/neo95-diag18-rtc-wake.log`.
Mac before/after captures: `.local/diagnostics/20261003T165608.941679Z/` and
`.local/diagnostics/20261003T165950.541126Z/`.

The seven debug prerequisites and rehearsal are now consumed by this actual
sleep attempt. Do not replay them as admission for another sleep request.
Next, establish repeatable RTC-wake recovery with explicit same-boot evidence
and attended sequencing, then qualify cable absence/reconnect and Mac sleep
separately. NEO-95 remains in progress. CPU-idle/energy work follows the reviewed
USB baseline; no further sleep attempt was submitted in this session.
