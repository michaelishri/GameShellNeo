# In-progress ticket completion audit

12 October 2026 NZDT. The owner requested working through the in-progress
Kaneo board until the remaining work requires physical actions. This is an
ongoing audit, not a declaration that all remaining work is physical.

The initial authoritative board query returned **20 in-progress tickets**,
one task page and one related-metadata page. Their descriptions and comments
were read alongside current source and retained evidence. A ticket is not
complete merely because its candidate compiles, a later test passed, or a
separate follow-up exists. Original failed results remain failed.

## NEO-100: battery sample freshness across sleep — complete

The original scope is BOOTTIME battery timestamps, sleep-aware observation
windows, compatible consumers, schema/boot/clock rejection, deterministic
tests, image integration and an installed stopped-clock/resume exercise.
Asleep physical protection, gauge accuracy and final sleep-controller
serialization were explicitly separate in [report 133](133-battery-boottime.md).

All of that scope now has evidence:

- The current producer and shared `battery_sample.py` age consumer retain
  BOOTTIME freshness. The current 20 battery runtime and seven battery-sample
  tests pass, including stopped MONOTONIC, short/long sleep, invalid reads,
  stale consumers, schema/boot/clock mismatches and transport/image identity.
- [Report 217](217-wfi-s2idle-image-integration.md) records full integration;
  [report 218](218-diagnostic24-installation.md) records the installed image,
  exact-source checks and 12 installed guard simulations. This audit read the
  original `20261008T103435.489075Z/battery-policy.txt`: all 12 pass against
  producer SHA-256
  `5f97cad9ad6f51668d97121c7adb56178aefd309eb6bef6264638e1cf759d62f`.
- [Report 219](219-diagnostic24-pm-qualification.md) supplies actual coordinated
  sleep. This audit re-read original result
  `20261008T112241.497557Z/result.json` in `work/cpi-wfi-integration`, verified
  its published SHA-256
  `d596ad2ede15a66fd0c25bc86c099440039aad203796e8a3f930e4dc27b78faa`,
  and reran the existing offline delivery/clock assessment successfully.
  All four WFI callbacks advance and independent timekeeping freeze is true;
  the recorded clock gap is 28.868556909 seconds.
- The saved post-return sample is valid schema 2 on the matching boot.
  Recomputing its BOOTTIME age with the current consumer gives
  **1.582302813 seconds**, equal to the recorded age. Both SSH proofs,
  process memory and policy restoration are true; no RTC, policy or control
  ownership is retained.

The separate audit receipt is
`.local/board-audit/qualification-review.json`. No original evidence changed
and no new device operation ran. NEO-192's subsequently discovered clock fault
is still unresolved, and its newer fault-handling changes still need their
own deployment. Closing the implemented BOOTTIME contract does not clear that
fault or admit another PM test. NEO-101 still owns awake-profiler interruption
qualification; NEO-117/182 and the battery follow-ups retain their own physical
criteria.

## NEO-94: first attended RTC-wake qualification — complete

This ticket's first diagnostic.17 attempt remains failed. Its original
`20261003T031337.546862Z/result.json` was re-read and still reports
`passed=false`. Closing the qualification task does not relabel that run.

The subsequent diagnostic.18 run in
[report 142](142-diagnostic18-first-rtc-wake-success.md) achieved the first
qualified functional RTC wake and unattended USB/Wi-Fi recovery after the
connection-lifecycle correction. This audit read the original
`20261003T165839.817277Z/result.json` in the main checkout and verified SHA-256
`e2d0873bccccb55d14d43edb0648686f6477585e1b152557960830b157b3a692`.
The current offline RTC/trace/clock assessment passes. The original result
has `passed=true`, both independent route proofs, memory verification and
policy restoration, with no retained RTC/control/policy ownership. Report 142
retains the owner's confirmation that the dim console returned untouched.

The absence of timekeeping freeze in that older image was explicitly separated
from functional RTC wake. The later diagnostic.24 original independently
rechecked above also proves all-core WFI participation and timekeeping freeze.
Thus neither of the original NEO-94 blockers leaves its first functional
qualification milestone unfinished. Subsequent repeats and cable profiles are
recorded in [report 239](239-musb-restart-integration-review.md).

Broader USB host/boot coverage remains NEO-95; idle energy remains NEO-96;
the newer clock fault remains NEO-192. Power-button wake and deep retention
were outside the first RTC test and are not being counted as complete.

## Remaining work at the initial audit

| Ticket | Remaining question or action to establish completion |
| --- | --- |
| NEO-5 | Reconcile cold-boot count and hardware checklist; retain independent charging/reserve gates. |
| NEO-10 | Integrate prepared owning-driver readback diagnostics; corroborate electrical voltage and exact unbranded-pack limits without guessed calibration. |
| NEO-26 | Reconcile original scan-isolation and later exact-A0 evidence with the diagnostic scope. |
| NEO-31 | Actual disappearance/reappearance of an associated AP, distinct from the accepted random-SSID simulation. |
| NEO-55 | Explain the original delayed authentication; passing later handshakes alone do not identify its cause. |
| NEO-58 | RX cleanup, clock-ready timeout, recovery ownership and integration of prepared fixes. |
| NEO-94 | Completed reconciliation above; historical failures remain unchanged. |
| NEO-95 | Host sleep/wake and remaining repeat-boot USB coverage; completed cable tests are already retained. |
| NEO-96 | Remaining awake overhead and battery energy comparison; supported WFI is implemented and functionally exercised. |
| NEO-98 | Wake-ownership candidate integration, remaining backend limits and hardware wake qualification. |
| NEO-101 | End-to-end awake-profiler sleep interruption/cleanup and observer-cost qualification. |
| NEO-102 | Startup candidate integration and matching hardware validation; complete teardown stays separate. |
| NEO-103 | Complete-kernel callback concurrency and matching integration/hardware qualification. |
| NEO-106 | Complete producer/backend retirement, including separate DMA mapping-lifetime leads. |
| NEO-117 | Direct charge acceptance during sleep with headroom and appropriate electrical qualification. |
| NEO-154 | Record the owner's explicit abandonment; do not restart the investigation or describe it as fixed. |
| NEO-182 | Clean 60-second battery trial after software admission clears, with physical unplug/reconnect. |
| NEO-191 | Camera-observed PM qualification after NEO-192 clears; human screen confirmation is no longer needed. |
| NEO-192 | Review/finish kernel-clock diagnostic correlation, prepare image and investigate the actual regression. |

Physical actions are not a reason to leave independent source or preparation
work unfinished. The camera cannot clear an unrelated health failure, and the
clock fault cannot be removed from admission by rebooting or resetting counters.
