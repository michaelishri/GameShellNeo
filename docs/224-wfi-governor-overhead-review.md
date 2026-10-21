# WFI single-state idle-path review

9 October 2026, Pacific/Auckland. NEO-96 follow-up.

The installed `cpi_wfi` driver already avoids governor selection and feedback
on ordinary idle entry. Linux 6.18.54's scheduler has a single-state fast path:
`cpuidle_idle_call()` only invokes `cpuidle_select()` and `cpuidle_reflect()` when
`drv->state_count > 1`. Otherwise it applies the tick decision and calls state
zero directly. The CPI driver declares exactly one state. Seeing `menu` as the
registered governor therefore does not mean its prediction algorithm runs on
every idle entry.

The s2idle branch also bypasses the governor. It tries the coordinated s2idle
entry before ordinary selection. This is the path exercised by diagnostic.24's
five accepted actual sleep cycles in reports
[219](219-diagnostic24-pm-qualification.md) and
[220](220-diagnostic24-connected-sleep-repeatability.md).

No new governor or governor-bypass patch is justified for this configuration.
Changing to another governor would not remove a selection operation that the
scheduler already skips. If deeper CPU idle states are added later, this
conclusion must be revisited because the multi-state branch would become active.

This does not make the new CPU-idle driver free of software overhead. Normal
entry still passes through the core's idle-state bookkeeping, timestamp reads,
context-tracking boundary, tracepoints and residency counters before/after ARM
WFI. Those support coordination, correctness and observability. This review does
not measure their cost relative to the older architecture-only fallback, nor
justify removing them. The remaining practical comparison is awake and asleep
battery consumption with consistent clock accounting and controlled conditions;
the existing BOOTTIME and awake-window guards remain required.

## Evidence

This review reads the diagnostic.24 patched source and board overlay; it performs
no live profiling, PM operation, governor change or new hardware test.

| Source | SHA-256 |
| --- | --- |
| `kernel/sched/idle.c` | `afecdd36effcfe8634f81864d258271b6797029c83aef02f97b99f58656ab883` |
| `drivers/cpuidle/cpuidle.c` | `5817dae7e22a09d9d4182818342b7bf9bae8f59dd96094c0a863072218885faa` |
| Board overlay `drivers/cpuidle/cpuidle-cpi-wfi.c` | `06c0c638ccd531fd404b09a110c6017eb5c923249f51f32e0fd6a96ead8a4a3d` |

The existing [`scheduler_tests()` fixture](../kernel/tests/cpuidle_s2idle_test.c)
already checks this distinction with extracted actual scheduler functions:
ordinary single-state entry leaves the selector/feedback counts zero, while the
two-state case invokes both. `board_tests()` checks that the driver has one
state and uses `arm_cpuidle_simple_enter` for ordinary and s2idle callbacks.
`task test:cpuidle-s2idle` is the saved reproduction command; its earlier
validation is recorded in
[report 217](217-wfi-s2idle-image-integration.md). No redundant fixture or rerun
was added for this source-only review.
