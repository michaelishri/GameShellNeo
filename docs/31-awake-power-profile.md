# Awake CPU, interrupt and radio profile

Date: **27 September 2026**. Work: **NEO-11**, with governor investigation
tracked separately in **NEO-12**. Board: the owner's CPI v3.1, diagnostic.2,
Linux `6.18.54-gameshellneo2`, boot
`b82a951a-31a3-4e7f-b4db-69a4fc5aa894`.

The strongest finding is substantial CPU time in **`sugov:0`**, the schedutil
CPU-frequency governor's worker: **35.79% of one CPU** in the first interval
and **33.94%** in a shorter follow-up. This makes the frequency-transition
path the first target for further diagnosis. It does not yet identify an
individual expensive function or quantify how many milliwatts a fix would save.

The [idle baselines](29-hardware-qualification.md#awake-idle-baseline) reported
approximately 1.04–1.05 W with brightness 1 and 1.02 W with the backlight off.
Both activity profiles below **preserved the restored brightness of 1**;
they are not another backlight-off power measurement. No governor, frequency
limit, voltage, radio power-save, charger or gauge setting was changed.

## Repeatable capture

```sh
task device:power-profile ROUTE=wifi SECONDS=120
```

The [helper](../tools/profile-power.py) settles for thirty seconds, reads
endpoint snapshots around the requested interval, and checks battery-only
conditions every thirty seconds. Raw counters remain in memory until the end
to avoid periodic SSH output. The ordinary battery guard continues running.
The task accepts multiples of thirty seconds in 30..300 and runs in a bounded
transient service. The [README](../README.md) documents conditions and limits.

Captured data includes `/proc/stat`, `/proc/interrupts`, `/proc/softirqs`,
surviving-process CPU ticks, radio power-save/signal and interface counters,
available frequency/idle data, and peripheral runtime-PM state. Clock,
regulator and active-timer debug snapshots are collected after the interval.
The follow-up also attempted twenty kernel-stack reads for each of the three
busiest surviving processes, after the measured interval. These are best-effort
diagnostics, not statistical samples. Process arguments, environment values,
SSID and BSSID are excluded.

The collector retains raw values and acquisition times. It excludes guest
CPU fields already included in user/nice time, checks process start time to
avoid PID-reuse errors, and rejects decreasing counters rather than inventing
rates. Short-lived processes missing from either endpoint are not represented
in the process ranking. `/proc` files are sequential reads, not an atomic
snapshot. The first pair of endpoint acquisitions took approximately 0.26 s
each. The health reader, Python process and kernel work caused by reads are
part of the observer overhead.

## Results

| Measurement | Initial profile | Follow-up |
| --- | ---: | ---: |
| Counter interval | 120.285 s | 60.343 s |
| `sugov:0` CPU time | 43.05 s | 20.48 s |
| `sugov:0`, one CPU = 100% | 35.79% | 33.94% |
| Surviving `events_power_efficient` workers, summed CPU time | 4.37 s | 2.06 s |
| Battery guard CPU time | 0.28 s | 0.17 s |
| Profiler CPU time within endpoint process accounting | 0.37 s | 0.35 s |
| SDIO IRQ thread CPU time | 0.16 s | 0.08 s |
| Broadcom data worker CPU time | 0.11 s | 0.06 s |
| Broadcom watchdog CPU time | 0.10 s | 0.04 s |
| Architectural timer interrupts, all CPUs | 216.20/s | 206.32/s |
| RSB controller interrupts | 38.01/s | 34.59/s |
| Wi-Fi MMC-controller interrupts | 22.70/s | 22.77/s |
| IRQ-work interprocessor interrupts | 67.31/s | 62.38/s |
| Function-call interprocessor interrupts | 63.98/s | 60.16/s |
| Scheduler softirq executions | 75.45/s | 74.11/s |
| Timer softirq executions | 33.55/s | 32.76/s |
| Context switches | 485.11/s | 453.77/s |
| Wi-Fi transmit packets during counter interval | 0 | 0 |
| Wi-Fi receive packets during counter interval | 220 | 109 |
| Gauge percentage at measurement endpoints | 68% → 67% | 67% → 66% |

Wi-Fi power saving was **off** throughout both profiles. Endpoint signal
readings were -77 dBm in both intervals. RX/TX error counters did not increase;
RX drop counters increased by 117 and 60 respectively. Those counters alone
do not establish packet-loss causes or connection failure. The same boot,
four online CPUs, brightness 1, unblanked display, `schedutil`, valid Discharging
guard and disconnected external power were preserved.

CPU-wide accounting needs special care. The initial `/proc/stat` aggregate
reported 6.59% busy and the follow-up 6.33%, as percentages of **accounted ticks
across all four CPUs**. However, CPU1 accounted for only 99.43 s of the initial
120.285 s interval and 50.53 s of the follow-up 60.343 s: **82.66–83.74% coverage**.
Aggregate coverage was 95.34–95.62%. Process CPU time and these CPU-wide tick
counters also do not reconcile closely on CPU1. The profiler now exposes
coverage directly. Treat these percentages as diagnostic accounting, not a
precise measurement of physical residency. The repeated governor CPU-time
increase remains the main finding; the accounting discrepancy is a follow-up.

## Available instrumentation and power state

| Facility | Observed state | Interpretation |
| --- | --- | --- |
| CPU frequency | `cpufreq-dt`, `schedutil`, 120–1008 MHz limits | Frequency scaling is configured; point readings are not residency |
| Governor update interval | Global `schedutil/rate_limit_us` = 366 µs | A permitted update interval, not a measured transition frequency |
| Advertised transition latency | 244144 ns | Matches the inherited A33 OPP entries; actual transition cost needs measurement |
| CPU-idle driver | `none`, governor `menu`, no per-state counters | No registered deep-idle driver; does not imply spinning instead of ordinary WFI |
| Tickless idle | `CONFIG_NO_HZ_IDLE=y`, `CONFIG_HZ_100=y` | Tickless idle is compiled in; interrupts/timers can still wake CPUs |
| Function tracing | `CONFIG_FTRACE` disabled; tracefs endpoints absent | Per-function/work-item attribution unavailable in this image |
| Frequency residency | `CONFIG_CPU_FREQ_STAT` disabled | No `time_in_state` counters |
| Kernel stacks | `CONFIG_STACKTRACE=y`, ARM unwinder enabled | All 60 attempted reads returned empty; no function attribution obtained |
| Power-efficient workqueue option | `N`; default config disabled | Eligible workqueues remain per-CPU; the name alone does not mean unbound operation |
| Wi-Fi firmware power saving | `off` | Candidate for a separate reversible connectivity/power comparison |
| Wi-Fi MMC host | Runtime `active`, control `on`, 50 MHz bus | Bus/runtime-PM state, not a direct RF power measurement |
| Wi-Fi SDIO functions | Runtime-PM `unsupported` | Does not determine whether firmware protocol power saving can work |
| External USB gadget controller | Runtime `active` while unplugged | Candidate for lifecycle investigation; preserve USB detection/reconnection |
| Keypad USB device / OHCI root hub | Active | Expected functional dependency; changes must preserve keypad behavior |
| EHCI root hub / storage MMC host | Suspended at endpoint | Some existing runtime power management is active |

The post-window clock snapshot showed the display backend and pixel clocks
enabled, as expected for an unblanked console. Turning off only the backlight
in the preceding test did not request full panel/controller power-down.
Clock and regulator summaries are state snapshots, not rail-current meters.

## Source trace and competing explanations

The inspected source is the locked Linux **6.18.54** tree under
`.local/sources/linux-6.18.54`; its selection is recorded in
[the source lock](../build/sources.lock.json). The installed configuration
was checked through `/proc/config.gz` after capture.

**CPU frequency transitions.** `kernel/sched/cpufreq_schedutil.c:sugov_work()`
calls `__cpufreq_driver_target()` on the slow path. The A33 CPU PLL uses
`drivers/clk/sunxi-ng/ccu_nkmp.c`, whose factor selection searches nested
N/K/M/P combinations. `ccu-sun8i-a33.c` registers a CPU-mux notifier that
temporarily selects the 24 MHz oscillator during PLL changes. These establish
an applicable path, not measured time in each function. The global 366 µs
governor interval follows the advertised 244144 ns latency and cpufreq's
50% margin after conversion to microseconds; its suitability here is unqualified.

An original-author LKML discussion describes excessive schedutil CPU use caused
by the same class of exhaustive clock-factor calculation. On 29 July 2026,
the author withdrew the early proposal to replace hardcoded A64 PLL constraints
with clock-specific settings. This corroborates a **hypothesis**, not a confirmed
GameShell root cause. No proposed patch was applied, and successor/merge status
was not established. Any optimization must preserve R16/A33 constraints and
existing rounding/factor selection unless a separately justified correction is
intended. [Original-author discussion, mirrored LKML archive](https://lists.openwall.net/linux-kernel/2026/07/29/810).

**USB-power polling.** `drivers/power/supply/axp20x_usb_power.c` gives AXP223
`vbus_needs_polling=true`. While USB is offline, its worker reads the PMIC and
reschedules with a 50 ms delay. This is a concrete timer/work source. It does
not explain all 34.6–38.0 RSB interrupts/s by itself: DVFS, ordinary monitoring
and other PMIC clients also use that bus. Nor does the worker-thread name
uniquely identify which callback consumed its CPU time. Preserve input-detection
requirements before changing polling or workqueue policy.

**Radio activity.** `brcmfmac/sdio.h` defines a 10 ms watchdog period, but
`brcmfmac/sdio.c` can stop that timer when the bus becomes idle. Do not claim
an unconditional 100 wakeups/s from the constant alone. The measured radio
threads used little CPU relative to `sugov:0`; that does not establish low
radio electrical consumption. `brcmfmac/cfg80211.c` implements firmware
power-management requests, making the observed disabled setting a separate
candidate to test. The sunxi MMC host already sets `MMC_CAP_SDIO_IRQ`; absence
of an explicit `cap-sdio-irq` property in this board DTS is not evidence of
missing host interrupt capability.

**Ordinary idle.** `arch/arm/kernel/process.c:arch_cpu_idle()` falls back to
`cpu_do_idle()`, and `arch/arm/mm/proc-v7.S:cpu_v7_do_idle()` executes WFI.
The absent cpuidle driver is consistent with the deliberate exclusion of
unqualified PSCI core-off states. Enabling those states is not a shortcut for
fixing the measured governor activity.

## Priorities and validation

1. **NEO-12: attribute and reduce governor transition overhead.** Use bounded
   instrumentation or an automatically reverted update-rate comparison before
   selecting a fix. Preserve OPPs, voltages and protection. If factor-search
   cost is confirmed, verify any optimization against the original selection
   algorithm and relevant clock limits, then repeat activity, power and load/
   responsiveness checks. Explain the CPU-accounting shortfall.
2. **Wi-Fi power saving.** Compare enabled/disabled operation with automatic
   recovery, checking SSH/reconnection and power under matched signal conditions.
   Low CPU usage does not eliminate this as an energy-saving opportunity.
3. **USB polling and peripheral lifecycle.** Attribute work before adjusting
   intervals or binding policy; retain tested plug/unplug behavior, keypad input
   and board rail dependencies. Full display power-down is separate work.

The collector's host regression checks cover guest accounting, IRQ columns and
IPI descriptions, reset/CPU-set rejection, process names containing parentheses,
PID reuse, units and accounting shortfall. The full host suite and shell checks
pass. Both hardware captures completed successfully. The final postcheck at
06:52:45 UTC confirmed all six expected services active with zero restarts,
no failed units, zero kernel taint and no new kernel messages since profiling
began. Both transient services exited successfully. Their total CPU usage was
1.208 s and 1.564 s, including setup/post-window work; those totals are distinct
from the endpoint process deltas above. Brightness remained 1 and USB remained
offline; monitoring was valid at 66% Discharging. No power setting changed.

## Private evidence

- `.local/diagnostics/20260927T064518.073838Z/power-profile.jsonl`: initial run,
  before accounting-coverage and post-window stack fields were added. Coverage
  above was computed from its retained raw counters.
- `.local/diagnostics/20260927T064952.689868Z/power-profile.jsonl`: follow-up with
  explicit coverage and stack reads. Governor latency/update-limit metadata was
  queried afterward and subsequently added to the shared task.
- `.local/diagnostics/20260927T064848.469657Z/status.txt`: first postcheck.
- `.local/diagnostics/awake-profile/{capabilities,counter-preflight,postcheck,governor-policy}.txt`:
  instrumentation discovery, installed configuration, final health and governor
  settings; `nkmp-discussion.html` retains the retrieved author message.

NEO-11 completes this profiling pass and reusable workflow. NEO-12 tracks the
next investigation; NEO-5 hardware qualification and NEO-10 electrical charging
qualification remain open. This pass does not claim improved battery endurance,
verified per-component watts, suspend support or an implemented driver fix.
