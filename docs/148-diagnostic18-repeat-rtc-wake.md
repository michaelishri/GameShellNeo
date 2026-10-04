# Diagnostic.18: four consecutive RTC-wake cycles

4 October 2026, Pacific/Auckland. NEO-107 qualification and NEO-95 progress.

Four consecutive actual s2idle/RTC-wake cycles passed on the existing
diagnostic.18 image. USB and Wi-Fi SSH recovered independently after every
cycle, with no cable intervention or repair command. The owner watched the
sequence and confirmed: “Yes—all four returned normally, untouched.” The
screen and brightness were normal at the end.

Together with [the first successful cycle](142-diagnostic18-first-rtc-wake-success.md),
this gives five successful actual-sleep results across two attended sessions
on this boot. It completes the bounded hardware qualification of the
[repeat runner](143-repeat-rtc-wake-runner.md). Cable absence/reconnection,
Mac sleep, other boots and long-term reliability remain separate NEO-95
work. CPU retention and standby-energy qualification are still outstanding.

## Installed identity and admission

| Item | Value |
| --- | --- |
| Kernel / image | `6.18.54-gameshellneo18` / `0.1.0-diagnostic.18` |
| Boot | `e419f334-0a16-4b04-96d2-d97a2e4d5d0b` |
| Main repository at submission | `7fbdba3` |
| Awake rehearsal | `e8aebea64aa44020b8dc602031df5773` |
| PM successes / failures, whole session | 8/0 → 19/0 |
| SDIO runtime references | 2 throughout, active/forbidden |
| USB system-wake policy | Disabled throughout |
| Registered CPU-idle driver | `none` |

No image, driver, charging policy or Mac power/network setting was changed.
Later CPU-idle, battery-clock, IRQ-wake, startup, callback-lifetime and
controller-removal candidates remain absent from this image. Normal sleep
targets remain masked; all PM entries were explicit diagnostics.

The owner gave fresh readiness for the complete session: debug checks,
an awake rehearsal and up to four actual RTC-wake cycles, with the cable and
controls untouched. Read-only board/Mac inspection, awake power-key ownership
and RTC delivery/restoration checks passed before the debug sequence. A fresh
seven-debug baseline was required because the repeat runner's source identity
differs from the helper used for report 142; the earlier result was preserved.

Each debug result was reviewed before the next submission. All seven passed,
including original-keypad retention, independent route proofs, trace/control
restoration and unchanged SDIO references. Capture paths below are relative
to `.local/diagnostics/` and contain `cycle-1/result.json`.

| Stage | Capture | Run ID | PM successes |
| --- | --- | --- | --- |
| Freezer | `20261004T014946.485254Z` | `d4ca673b901b47f6a292165391473aab` | 8 → 9 |
| Devices | `20261004T015054.724130Z` | `bdd15373b87245389be3bda87da7eb9c` | 9 → 10 |
| Late/noirq 1 | `20261004T015214.556287Z` | `8399d0ad7be64ccab1c79cdb7e12b545` | 10 → 11 |
| Late/noirq 2 | `20261004T015337.523290Z` | `60c40066df6c42d79dd2c3c22bfba83a` | 11 → 12 |
| Late/noirq 3 | `20261004T015455.444908Z` | `8fb7d1adacc34c81ad85ca14e2c73248` | 12 → 13 |
| Late/noirq 4 | `20261004T015616.345960Z` | `3142c934a58c454f91702ce7f5e7973d` | 13 → 14 |
| Late/noirq 5 | `20261004T015738.190102Z` | `4a460809b3f546f7846cd5e94c3e97d0` | 14 → 15 |

`check:sdio-ref-history --require-stable` saved
`.local/neo107-reference-history.json`. The same-source awake rehearsal at
`20261004T015859.529643Z/result.json` passed without sleep or a PM increment;
RTC IRQ 31 advanced 4 → 5 and the alarm/policy were restored.

## Actual sleep results

The batch was submitted once. Each next cycle was admitted only after
validation of the original preceding result, both route proofs and clean
ownership handback. Persistent single-successor claims and complete source,
boot, PM and RTC ancestry were used on the live device.

| Cycle | Run ID | PM successes | RTC IRQ 31 | Submitted interval, BOOTTIME | In-loop trace, MONOTONIC |
| --- | --- | --- | --- | --- | --- |
| 1 | `2f0ea8c898344488b24a5e7e299389f2` | 15 → 16 | 5 → 6 | 31.008 s | 28.595 s |
| 2 | `40d2d78f7c924d4eac8c867674c27c82` | 16 → 17 | 6 → 7 | 31.432 s | 29.052 s |
| 3 | `c237e6e79d8743a884d96396728aecee` | 17 → 18 | 7 → 8 | 31.061 s | 28.671 s |
| 4 | `abaa4c826d1e489db6836959e2adafd3` | 18 → 19 | 8 → 9 | 31.736 s | 29.279 s |

Every result records actual s2idle boundaries, all four late/noirq phases,
RSB noirq suspend/resume, wake IRQ 31 and one RTC character event with flags
`0xa0`. Alarm restoration passed each time. PM failures remained zero.

USB returned to configured state and carrier 1, and both independent SSH
checks reached the original boot after every cycle. USB and Wi-Fi trace
buffers recorded no lost events and their settings were restored. Temporary
SSH route/banner errors during recovery are retained in the original
collection logs; the collector retrieved the same run rather than repeating
its PM submission. There was no physical reconnect, gadget restart or lease
repair to produce the result.

The original keypad descriptor and input identity survived every cycle,
with no hangup, poll/ioctl failure, disconnected handle or held key. Process
memory checks passed. Power-key policy and descriptor handback passed, with
no retained diagnostic owner, drop-in, PM-control or RTC ownership record.
Idle audio state and display settings were restored. The owner's final
confirmation supplies the physical screen observation that software settings
alone cannot establish.

## Final state and limits

A final independent read-only PM snapshot passed the existing validator.
Recomputing its receipt from the original seven debug and four actual-sleep
results passed source/image/boot matching, ancestry, counters, route evidence
and restoration checks. Final PM counts were 19/0, SDIO usage 2, brightness 1,
backlight power 0, `pm_test=none`, `mem_sleep=s2idle` and `pm_async=1`.
Kernel taint was zero and no failed unit was reported. USB power remained
present; the final battery sample was 100%, 4,160,200 µV. This is an observed
software sample, not a battery-capacity or charging calibration result.

The Mac saw GameShellNeo in its USB tree and the active `en8` route before
and after the session. Its saved sleep/wake history was unchanged. Thus this
session does not test Mac sleep or host-side power loss.

All four results recorded zero timekeeping-freeze pairs, with CPU-idle driver
`none`. BOOTTIME/MONOTONIC gaps remained below each observation's sampling
uncertainty. The intervals above establish functional RTC wake through the
s2idle path; they do not measure CPU retention, standby energy or user-visible
resume latency. The roughly 63–94 ms keypad-readiness observations begin
after userspace has returned and are not whole-system resume measurements.
There is no new week-long standby or sub-second wake claim.

## Reproduction and evidence

The historical workflow used the saved tasks:

```sh
task device:pm-power-key STAGE=freezer CYCLES=1
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
task device:pm-platform  # five separate, reviewed runs
task check:sdio-ref-history -- --require-stable <seven-result-paths>
task device:sleep-rehearse QUALIFICATION=.local/neo107-reference-history.json
task device:sleep-batch QUALIFICATION=.local/neo107-reference-history.json \
  REHEARSAL=e8aebea64aa44020b8dc602031df5773 CYCLES=4 ATTENDED=1
```

These commands document this session, not permission to replay consumed
admission. A future repeat needs fresh observer readiness and a currently
valid continuation. Changed sources, boot or intervening PM/RTC activity
invalidate continuation. The final accepted chain is
`.local/diagnostics/20261004T020100.813394Z/cycle-4/qualification-next.json`.
No further sleep was submitted after cycle four.

Batch directory: `.local/diagnostics/20261004T020100.813394Z/`.
Each `cycle-N/` retains its original `result.json`, submission identity,
qualification, successor continuation and collection evidence. Batch host log:
`.local/neo107-session-sleep-batch.log`. The result's complete `sources` map
is identical across all four cycles; key identities are:

| Artifact | SHA-256 |
| --- | --- |
| Uploaded `sleep_rtc` | `508f2aa056939b9e651103ffd5b7b7ca9eb27cb7248dd1de764e0de256a3c388` |
| Uploaded `test-pm-stages` | `0f610706dbfe041442494681f38cd3007cfbc16773a4a04b428b51649e5eae8e` |
| `batch.json` | `6c3d89b1305c9bf5e35861a7bfaffc941f3dd06509a37975202fbcc320246870` |
| Cycle 1 `result.json` | `9aa793deb770edb52dea70cd6dbbfc07c8f77619a316d467d9d5e4c67dd7b8c0` |
| Cycle 2 `result.json` | `5e03c961d81510685c8b53b9281409a700dbcac01de857955be66d03c6c13d3d` |
| Cycle 3 `result.json` | `d8abf89fbbf048f97a953ab09fe62f1a76459bcf936f829edce3fc65da03d809` |
| Cycle 4 `result.json` | `259978466a7e66726e5b6a20ff2034fdccb6bcab31b6bcdc780498ac425814fe` |
| Final recomputed receipt | `52c536eb980c453229a57ac2e267833b5c0857ad4aa8278aa592520fe5d0ba36` |

The final receipt is `.local/neo107-final-receipt.json`. Initial/final PM
inspections are `20261004T013708.335194Z/inspection.json` and
`20261004T020859.034774Z/inspection.json`. Initial/final Mac inspections are
`20261004T013721.951359Z/` and `20261004T020859.015649Z/`. Awake key and RTC
captures are `20261004T014902.362808Z/` and `20261004T014923.252400Z/`.
Raw network/configuration evidence stays private under `.local/`; secrets
remain in `.env`.

NEO-107's live admission and four-cycle qualification are complete. NEO-95
remains open for separately prepared cable/host-state coverage. The next
energy step still requires battery-clock integration and a newly identified
CPU-idle image with its own staged hardware qualification.
