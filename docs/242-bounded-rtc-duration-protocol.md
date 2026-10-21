# Bounded RTC duration protocol

9 October 2026. NEO-180, following the
[backlight comparison](241-diagnostic25-backlight-power-comparison.md) and
[battery measurement plan](240-diagnostic25-battery-measurement-baseline.md).

The existing recorder now supports an explicit **60-second alarm** as the
first extension beyond its default 30 seconds. This is prepared tooling with
offline validation; no 60-second hardware trial has run. Longer durations are
rejected. There is no new image, driver, charger setting or ordinary sleep
policy in this change.

## Scope and duration contract

Use `ALARM_SECONDS=60` on a one-shot USB or battery rehearsal and the matching
one-shot actual-sleep task. The default remains 30 seconds. A 60-second attempt
requires the CPI WFI image and its existing all-CPU callback/timekeeping-freeze
checks. It cannot use a cable-transition profile, automatic sleep batch or TCP
observer. Cable batches explicitly reject an extended duration instead of
silently using their default. No SSH-stall investigation is part of this work.

The alarm interval starts when the RTC is read for programming, not exactly at
screen darkness or CPU idle entry. The existing allowance for work after arming
remains at most 15 seconds: the entry margin is 15–30 seconds for the default,
45–60 seconds for the extension. The recorder checks the margin again after
durable intent and key checks. A late entry fails rather than shortening the
test silently.

The requested duration is saved in the host run metadata, device result and
qualification receipt. Rehearsal, result and every accepted sleep predecessor
must match it. A 30-second rehearsal/history cannot authorize a 60-second
attempt. Switching duration requires a fresh, unconsumed seven-debug anchor
and a same-source, same-duration awake rehearsal. Source hashes include the
new `sleep_window.py` helper. Old captures remain historical evidence; their
missing duration field means their original fixed 30-second protocol only,
and does not bypass source checks.

The original single-successor claim is still consumed before alarm or sleep
mutation. A failed or uncertain attempt cannot be retried by replaying its
parent. No cleanup deletes that claim. Recover only the original run and its
owned controls.

## Timing and recovery

| Bound | Default | First extension |
| --- | ---: | ---: |
| RTC alarm interval | 30 s | 60 s |
| Minimum entry margin | 15 s | 45 s |
| Accepted alarm-start → return BOOTTIME | 28–40 s | 58–70 s |
| Awake rehearsal poll timeout | 35 s | 65 s |
| Transient service runtime allowance | 180 s | 210 s |
| Host collection budget | 210 s | 240 s |

The existing 30-second recovery observation and other awake setup/cleanup
allowances remain unchanged; the service and host budgets increase only by
the added alarm interval. The host's collection loop keeps its existing
individually bounded transport calls, so a final in-flight call can finish
after its loop deadline. None of these host/service timeouts is a wake source
for a frozen device. The verified RTC alarm remains the wake mechanism.

Actual sleep still makes exactly one wakeup-counter handshake and one `freeze`
submission. At return it requires an already-pending RTC event, the expected
RTC IRQ/count, the matching programmed interval, complete trace boundaries and
enough supported time inside s2idle. It never waits awake for a later alarm to
turn an early wake into a pass. The existing bracketed-clock and all-CPU WFI
checks remain mandatory for the extension. Callback counts and frozen
timekeeping do not establish hardware power-off or energy consumption.

## Battery admission and endpoint evidence

The first extension is capped at one minute because pack capacity and sleeping
low-battery protection remain unqualified. Recent awake measurements were
about 257–263 mA; at that *awake* rate one minute corresponds to roughly
4.3–4.4 mAh. This is scale only, not a prediction of asleep charge consumption
or proof of the remaining battery capacity. Do not select arbitrary longer
durations from the advertised 1,020 mAh rating.

For both rehearsal and actual sleep, direct sysfs observations are saved at
admission, immediately before entry/wait, and immediately after return. They
contain battery presence/status, gauge percentage, voltage, instantaneous
current, SoC temperature and both external supplies, alongside the guard's
cached sample. Reads are sequential and bracketed by BOOTTIME; they are not an
atomic measurement.

The 60-second entry rules require:

- More than 50% reported charge and at least 3.8 V on both admission and entry
  observations, with a present battery.
- A valid same-boot BOOTTIME guard sample at most 25 seconds old.
- SoC temperature below 60°C and a direct discharge reading no greater than
  500 mA in magnitude. This adds margin above the recent awake observations.
- The unchanged connection profile: both supplies absent/offline and
  Discharging on battery, or both supplies present/online on USB. Positive
  battery current is rejected in the battery profile.
- Integer readings within the diagnostic's broad plausibility bounds:
  percentage no greater than 100, voltage no greater than 4.3 V, current no
  greater than +1.5 A and nonnegative SoC temperature. These bounds do not
  qualify pack charging limits or resolve independent voltage accuracy.

Each endpoint's reads must complete within five seconds. The entry observation
must remain within five seconds of the immediate pre-submission clock;
durable-write or scheduler delay beyond that prevents the sleep request. The
post-return reads must finish within five seconds of the recorded return.
The nonblocking RTC-event check comes first so these new reads cannot defer
that check until a later alarm arrives. Endpoints are then saved before the
normal recovery wait and host collection, including on a rejected early wake.

The immediate return observation allows the guard cache to be stale because
userspace was frozen. It uses fresh direct reads instead. It requires more than
20% and at least 3.5 V, with the same connection and other plausibility checks;
the normal later postflight independently requires a refreshed healthy guard.
A failed return check preserves evidence and stops qualification, rather than
automatically submitting another sleep.

These thresholds are conservative **operating rules for this experiment**.
They are not calibrated state of charge, an electrical pack specification,
or protection while the guard is frozen. A sudden battery fault or missed RTC
wake is not made safe by an awake userspace timeout. No sleeping discharge
integral is calculated: current at either endpoint describes awake operation.
The result records gauge/voltage endpoints and their span with
`calibrated=false` and `energy_qualified=false`.

## Repeatable tasks and hardware sequence

Offline regressions, with no device access:

```sh
task test:sleep-protocol
python3 -m unittest discover -s tools/tests -p test_cpi_idle.py -v
```

For the first observed USB trial, establish a fresh seven-debug sequence using
the existing tasks, with owner readiness and long warnings before darkness.
Then run the new-duration awake rehearsal, keeping the cable connected:

```sh
task device:sleep-rehearse ALARM_SECONDS=60 QUALIFICATION=<fresh-history.json>
# After its success and fresh observer readiness for roughly one minute of darkness:
task device:sleep-rtc ALARM_SECONDS=60 QUALIFICATION=<fresh-history.json> REHEARSAL=<run-id> ATTENDED=1
```

Review the original result, unchanged boot/image, RTC timing, all-CPU evidence,
input/display/audio restoration, endpoint readings and both network routes.
Obtain the separate owner report of the long warning and normal dim-console
return. Stop on any automated or observed failure.

Only after the USB trial succeeds, qualify a separate battery trial. Prepare
its fresh debug anchor while connected; verify reliable Wi-Fi, request physical
USB removal, and confirm the reserve rules before the awake rehearsal:

```sh
task device:sleep-battery-rehearse ALARM_SECONDS=60 QUALIFICATION=<fresh-battery-history.json> UNPLUGGED=1
# After fresh readiness, with the cable left unplugged:
task device:sleep-battery ALARM_SECONDS=60 QUALIFICATION=<fresh-battery-history.json> REHEARSAL=<run-id> UNPLUGGED=1 ATTENDED=1
```

Preserve the unplugged result and health checks before requesting reconnection.
Keep the Mac awake and on the same Wi-Fi. Neither physical readiness nor USB
absence can be inferred from a timeout. The existing one-second warning and
restoration paths remain in use.

On uncertainty, collect the original run, without `ALARM_SECONDS`:

```sh
task device:sleep-collect RUN=<original-run-id> ROUTE=wifi
```

No card swap is required by these uploaded diagnostic-helper changes. Normal
sleep remains masked; power-key behavior and longer-term standby endurance
remain separate work. Durations above 60 seconds require another deliberate
extension after reviewing the hardware evidence and reserve, rather than an
environment-variable override.

## Offline validation

`task test:sleep-protocol` passes 137 tests. The separate CPI WFI suite passes
eight tests. New cases exercise duration/type/profile rejection before device
access, mismatched receipt/rehearsal/history/result durations, 60-second alarm
programming and restoration, unchanged setup allowance, direct sysfs reads,
invalid/low/stale battery observations, delayed entry and post-return readings,
early wakes, forged target intervals and same-run collection on uncertain
submission or host timeout, and import of the uploaded helper bundle outside
the repository. Existing default, cable, lineage, ownership and
restoration regressions also pass.

There is no live hardware, electrical, energy or endurance acceptance in these
offline passes. The first 60-second USB trial and subsequent battery trial
remain pending.
