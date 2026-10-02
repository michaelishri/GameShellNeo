# Bounded power-key release during PM debugging (NEO-91)

3 October 2026, Pacific/Auckland. Implementation following the
[awake four-pair qualification](114-awake-power-key-input.md) and
[source analysis](115-power-key-release-semantics.md). Host/source checks and
one attended bounded hardware sequence passed. The owner confirmed the tones
and normal dim console. Physical release timing was approximate; the result
does not establish that the switch remained held through the suspend callback.
A separate repeated SDIO runtime-PM reference increase is tracked as NEO-92
below. Normal sleep and real sleep remain disabled. No driver, image or PMIC
setting changed.

## Why this sequence differs

The existing driver debug test includes a five-second wait and took roughly
eight seconds in the recent late/noirq comparisons. The PEK shutdown attribute
currently reports a six-second configured cutoff duration. The operator must
therefore **not hold POWER until resume**. This sequence uses an independent
one-second hold, with a two-second maximum, then waits for the debug return.
It does not change the PMIC timer to accommodate the test.

Linux's input-device suspend callback clears its logical held-key bitmap.
The AXP223 handler's later release can consequently be filtered as an unchanged
zero. An empty bitmap or a synthetic release alone cannot authorize handback.
The new test records that behavior and requires a **separate fresh awake tap**
after return before restoring ordinary logind shutdown actions.

The IRQ counters record accepted nested dispatches, not instantaneous button
levels or callback completion. PMIC edge latches can coalesce and impose a
software order different from the contacts' order. This diagnostic depends on
the specified single attended gesture; it is not a product state-recovery
algorithm for arbitrary input history or whole-controller failure. The detailed
source basis and alternatives are in [report 115](115-power-key-release-semantics.md).

## Saved commands and physical instructions

```sh
# No hardware: locked Linux C functions, native and ARM32, with negative controls.
task test:power-key-events

# Only after fresh owner readiness; USB connected and headphone jack empty.
task device:pm-power-key-input

# Evidence only after uncertain collection; never blindly resubmit.
task device:pm-collect RUN=<original-32-character-run-id>
```

The attended task performs one `devices + freeze` debug cycle. It cannot select
`none`, real sleep, late/noirq or a multi-cycle batch. The screen counts down
ten seconds and then requests four steps:

1. Tap and release POWER once.
2. Tap and release POWER once.
3. Press POWER, hold for **one second**, then release **even if the screen is
   dark**. Do not wait for a tone, another prompt or the console to return.
   Never hold longer than two seconds.
4. After the debug return, follow the new prompt to tap and release POWER once.

The first two taps, the recorded release interval after return and the final
tap receive speaker confirmations. The known tone-start delay remains; no tone
is used to time the hold. USB stays connected. No cable changes or other keys
belong in this sequence.

If the recorded logical release precedes the input-device clear, the intended
reproduction is inconclusive and fails qualification. Physical release itself
is not timestamped by this recorder. Do not lengthen the hold to force a
result. If a check fails, leave POWER released while the original evidence and
retained policy are inspected. Uncertain input leaves the boot-local ignore
policy installed; do not delete its files or assume a short press still shuts
down. The established orderly SSH shutdown and attended normal power-on path
remains the recovery route.

## Implementation and acceptance

[power_key_pm.py](../tools/power_key_pm.py) reuses the existing PM, key ownership,
policy worker, console and speaker helpers. The explicit mode in
[the PM host wrapper](../tools/check-pm-stages.py) checks the diagnostic source
lock and both network routes before submission, hashes the uploaded helpers,
and uses the existing durable per-run result collector. A lost SSH response
does not submit a second PM request. Service timeouts bound awake orchestration;
they cannot thaw a stuck kernel.

The operator's hold deadline is independent of kernel progress. Synchronization,
speaker work and inhibitor verification occur before requesting the hold.
After the press, the task checks the known IRQ mapping and held logical state,
saves the entry record, then uses the existing fixed-five-second `devices`
entry guard. PM settings restore on return. The original shared PM locks,
exclusive evdev handle and ancestor inhibitor remain held throughout.

The recorder requires:

- The identified AXP22x DBF/DBR mappings, with unchanged CPU columns and IRQ
  identities. Each sample retains its timestamp window and both original rows.
  Counter resets, missing rows and extra dispatches fail.
- Two ordinary initial tap pairs; one held press before PM; a logical release
  within the identified input child's **type suspend** callback; and a new
  prompted awake pair after return. It never relies on SYN_REPORT's value as
  a portable physical-release marker.
- A complete restored PM trace, no callback errors and no deeper or real-sleep
  boundary. From the held baseline, DBF +0 / DBR +1 supports the controlled
  release observation. It is explicitly not handback authority by itself.
- The separate final awake pair, matching DBF/DBR increments, continuous input,
  a quiet released bitmap, unchanged PM generation/boot and the still-owned
  inhibitor around policy restoration. The preceding PM transcript is retained.
- Exactly one successful debug cycle, unchanged failure counters, process
  memory, original input/backlight/power/network policy, the retained internal
  keypad handle/device, complete kernel evidence, restored audio and console,
  and both network routes afterward.

The disposable policy worker is terminated after the final input sequence,
while the parent retains ownership. Policy restoration uses the new checked
post-resume proof. Stop cleanup validates this run's UI ownership and restores
only its tracing, PM controls, audio and console; it does not blindly restore
shutdown after an uncertain gesture. The normal policy remains unchanged on
disk under `/etc`.

## Validation

`test:power-key-events` extracts the actual locked PEK IRQ handler, input event
disposition, release-all and suspend/resume functions. Six scenarios pass
natively and under ARM32 emulation, and three source mutations are rejected:
removed suspend clear, removed duplicate filtering and reversed release value.
The current patched tree's tested functions match the locked archive. Bitset,
delivery and lock shims make this a deterministic source test, not hardware
IRQ timing, concurrency or full evdev packet qualification.

Evidence: `.local/build/power-key-event-tests/evidence.json`,
`.local/build/power-key-events.log` and `.local/neo91-event-tests.log`.
Tooling tests cover mappings/topology/deltas, missing post-return input, early
release, callback attribution, trace loss, extra input, changed PM generation,
lost input/inhibitor, foreign cleanup, isolated-mode admission and the complete
simulated prompted sequence. Logs: `.local/neo91-pm-unit-tests.log` and
`.local/neo91-host-check.log`.

The complete host check passes **13 runtime and 397 tooling tests**, with one
existing optional skip, compiled helper regressions and shell lint. Read-only
preflight on diagnostic.16 passes the full PM baseline validation at
`20261002T203158.861901Z` and ordinary, unowned power policy at
`20261002T203412.250321Z`, on boot
`edb5b83b-8de9-425b-91fe-afb8e66ee39f`. No PM sequence was submitted for those
inspections.

## Attended hardware result

Run `bb6e666874e44d0cb47d30934256dd0f`, captured under
`.local/diagnostics/20261002T212624.336991Z/cycle-1/`, passed on diagnostic.16,
kernel `6.18.54-gameshellneo16`, boot
`edb5b83b-8de9-425b-91fe-afb8e66ee39f`. The task ran exactly once, after fresh
owner readiness. All eight uploaded helper hashes match the exercised source.
Host log: `.local/neo91-power-key-pm.log`. Durable board result:
`/var/lib/gameshellneo/pm-tests/bb6e666874e44d0cb47d30934256dd0f/result.json`.

The `devices + freeze` call returned after **7.505129178 seconds**, including
its fixed five-second debug wait. The PM success counter advanced from 7 to 8;
failures stayed zero. The memory digest and original internal keypad handle,
path and device number survived. All 1,898 callback return events reported
zero, with complete tracing and restoration. The 27-line kernel delta had no
new warnings, oops, suspended-transmit rejection, control timeout or firmware
fault. USB and independent Wi-Fi SSH both recovered.

Eight KEY_POWER edges and eight SYN packets describe the four requested
logical pairs. The first two taps lasted 182.049 ms and 148.970 ms. The third
press was recorded before entry, and its logical release falls inside the
identified `input0` type-suspend callback:

| Recorded event | Monotonic seconds |
| --- | ---: |
| Third KEY_POWER press | 10910.973820 |
| PM entry | 10910.977266693 |
| Input type-suspend callback starts | 10911.837581 |
| Logical KEY_POWER release | 10911.837591 |
| Input type-suspend callback ends | 10911.837598 |
| PM returns | 10918.482395871 |
| Fresh prompted awake press | 10923.278193 |
| Fresh awake release | 10923.413297 |

The 863.771 ms between the third recorded press and logical release measures
the input stream, **not physical hold duration**. The owner estimated a short
hold, possibly less than one second, and released just before visible
darkness. A physical release whose interrupt is delayed can still leave the
logical key held until the callback clears it. Therefore this run qualifies
the observed logical-clear path and subsequent handoff, without proving
physical hold through that callback. No longer hold or repeat was requested.

| IRQ sample | DBF press dispatches | DBR release dispatches |
| --- | ---: | ---: |
| Initial | 4 | 4 |
| After the first two taps | 6 | 6 |
| Held logical state before entry | 7 | 6 |
| After PM | 7 | 7 |
| After fresh awake tap | 8 | 8 |

These are accepted nested dispatch counts, incremented before the handler;
they do not timestamp contacts or establish a current physical level. The
third release packet used SYN value 1, but attribution rests on the callback
correlation and locked source, not that value alone. The final awake tap
lasted 135.104 ms and provided the separate fresh pair required for handoff.

The disposable worker ended with SIGKILL while the parent retained ownership.
The checked handoff restored the exact original policy and audio, removed its
owner/drop-in, restored the console and released input ownership. Logind kept
PID 298 and its original start time. The final diagnostic unit was inactive,
dead and no longer loaded. The owner confirmed correct tones and the normal
dim console. No further physical test was running at that confirmation.

Final evidence-only captures are PM `20261002T212854.771288Z`, policy
`20261002T212940.930723Z` and audio `20261002T213033.636543Z`.
`.local/neo91-baseline-comparison.json` records the restored settings, both
routes and unchanged subsequent kernel journal, **with the SDIO exception
below explicitly preserved**. This is not a blanket unchanged-baseline claim.

## Separate finding: SDIO reference growth (NEO-92)

The Wi-Fi MMC host `1c10000.mmc` reported `runtime_usage=8` before this cycle,
9 after it, and still 9 in the final inspection. Review of the six earlier
saved cycles on the same boot shows a consistent increment. No extra PM test
was performed to establish this history:

| Capture under `.local/diagnostics/` | Debug stage | Usage before → after |
| --- | --- | --- |
| `20261002T183428.008945Z` | devices | 2 → 3 |
| `20261002T185305.665142Z` | platform | 3 → 4 |
| `20261002T190057.578761Z` | platform | 4 → 5 |
| `20261002T190253.625880Z` | platform | 5 → 6 |
| `20261002T190445.281634Z` | platform | 6 → 7 |
| `20261002T190648.133179Z` | platform | 7 → 8 |
| `20261002T212624.336991Z` | devices | 8 → 9 |

Each original result is in its capture's `cycle-1/result.json`; the compact
index is `.local/neo91-sdio-reference-history.json`. The field is
`rsb_links["consumer:platform:1c10000.mmc"].consumer.power.runtime_usage`.
The MMC host remains active with runtime PM forbidden and `control=on`;
the RSB controller remains active at usage 1. Other recorded links and
settings are unchanged. Passing the existing bounded cycle checks did not
establish balanced reference ownership.

In the locked source, `sunxi_mmc_enable_sdio_irq()` in
`drivers/mmc/host/sunxi-mmc.c:974–998` unconditionally takes a runtime reference
on enable and drops one on disable. Repeated enable requests are a candidate
for the observed growth, pending a complete caller, IRQ-rearm, resume and
lifetime audit. `brcmf_sdiod_host_fixup()` deliberately forbids host runtime
PM in `drivers/net/wireless/broadcom/brcm80211/brcmfmac/bcmsdh.c`; do not force
autosuspend or remove RSB dependencies to hide the counter.

NEO-92 is the next priority before deeper sleep: establish ownership, correct
any driver imbalance, cover the relevant transitions with source tests and
qualify the result on hardware. The cause and energy effect remain unproven.
The earlier firmware-recovery underflow and NEO-55 authentication delay stay
separate unless evidence links them.

## Remaining gates

This test releases during the debug interval; it does not hold through the
entire return, wake the CPU with POWER, enter real sleep or destroy the parent
controller. Whole-controller interruption and unknown key-history recovery
remain distinct. The first real-sleep experiment still needs explicit RTC
deadline, wakeup-count admission and durable evidence integration; it should
target RTC wake before physical-key wake. Product short/2-second/8-second
gestures remain the accepted future behavior.
