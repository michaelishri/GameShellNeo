# Diagnostic.24 connected-USB sleep repeatability

9 October 2026, Pacific/Auckland; capture timestamps are UTC. NEO-159 is complete.
All four attended actual RTC sleep/wake repeats pass on diagnostic.24/kernel
`6.18.54-gameshellneo23`, boot `44b698ad-7fef-46d4-9e0f-71153f6f81e9`.
The owner confirms clear long warnings and normal dim-console returns after
every cycle without touching the cable or controls. Both SSH routes recover
each time. Each run advances all four WFI s2idle callbacks once and records an
independent timekeeping-freeze pair.

Final PM success/fail is **12/0**: seven debug checks and five actual sleeps,
including the initial sleep in [report 219](219-diagnostic24-pm-qualification.md).
This qualifies the bounded connected-USB functional batch. Battery/cable
profiles, broader reliability, awake overhead, standby energy, normal wake
latency and CPU/DRAM retention remain separate work.

## Saved workflow

At source checkpoint `2e9ad82`, the owner confirmed readiness for all four
cycles. The read-only preflight at `.local/diagnostics/20261008T114302.294197Z`
passed full health and continuation validation at PM8/0, with all four s2idle
counters at 1. The existing task then ran once:

```sh
task device:sleep-batch \
  QUALIFICATION=.local/diagnostics/20261008T112241.497557Z/qualification-next.json \
  REHEARSAL=f96b80e84fd9449080f042a43c78a69f CYCLES=4 ATTENDED=1
```

Each successor was admitted only after the original preceding result passed
its validator and independent USB/Wi-Fi route proofs. No PM operation was
resubmitted. The task's 20-second awake gaps and 30-second recovery observations
are diagnostic intervals, not wake latency. No driver, source, charger,
audio-level or ordinary sleep-policy change was made during the batch.

Original log: `.local/neo159-sleep-batch.log`. Batch directory:
`.local/diagnostics/20261008T114344.024513Z/`. Its `batch.json` records four
requested and four accepted cycles, SHA-256
`140e67597728045234306a067b6e0bcffef61a5795d034732755c263af4c10f7`.
Each original result below is `cycle-N/result.json` in that directory.

| Cycle | Run ID | Alarm-to-return seconds | BOOTTIME–MONOTONIC gap seconds | PM afterward | All four s2idle counts afterward |
| --- | --- | ---: | ---: | --- | ---: |
| 1 | `951a73c568aa4c0f85c1662df748c096` | 31.877 | 28.708 | 9/0 | 2 |
| 2 | `935b0f2d1ba24a45af02e5a1c5e9237c` | 32.160 | 28.982 | 10/0 | 3 |
| 3 | `94909923394c4d83abf176ef2c6fa240` | 32.271 | 28.993 | 11/0 | 4 |
| 4 | `101c4f0799414a6ab6cda8aa99970100` | 32.260 | 29.075 | 12/0 | 5 |

All four original results verify RTC wake, process memory, original keypad
handle retention, one-second level-5 warning playback/control restoration,
and loss-free keypad/USB/Wi-Fi tracing. POWER is handed back after verified
logical release; no policy, drop-in, PM control, RTC or console owner is
retained. Adjacent full PM snapshots match and every failure counter stays
zero. SDIO usage remains 2 with unchanged active/on/forbidden runtime policy;
brightness/backlight power returns to 1/0 on the original boot.

Each trace contains the actual s2idle boundary, one timekeeping-freeze pair,
all four late/noirq phases and RSB noirq suspend/resume. Clock sampling
uncertainty is 20.08, 21.92, 29.39 and 20.04 microseconds respectively.
MONOTONIC trace durations exclude the frozen interval; they are not hardware
residency or wake latency. Callback participation and timekeeping suspension
do not establish CPU/DRAM power-off or battery savings.

Post-return schema-2 battery samples pass current-boot and freshness checks.
BOOTTIME ages are 1.408, 5.477, 9.136 and 1.470 seconds. This exercises valid
resumed readings across repeated clock freezes; it does not calibrate the
gauge or qualify physical battery protection during sleep.

## Offline checks and collection evidence

The existing tasks validate each original result without changing it:

```sh
task report:sleep-evidence \
  RESULT=.local/diagnostics/20261008T114344.024513Z/cycle-1/result.json
task device:ssh-timing-report \
  CAPTURE=.local/diagnostics/20261008T114344.024513Z/cycle-1
```

The same commands ran for cycles 2–4. All RTC/trace/paired-clock/WFI assessments
pass, with `overall_requalified=false`: the report never replaces the
original recovery result. Assessment directories under `.local/diagnostics/`
are `20261008T114547.652147Z`, `20261008T114743.095321Z`,
`20261008T114937.597033Z` and `20261008T115114.248743Z`.
Private summaries are `.local/neo159-cycle-{1,2,3,4}-timing.json` and
`.local/neo159-batch-evidence-summary.json`.

Each timing capture validates exactly one PM submission, ten collection
attempts and two failed attempts. All eight failures occur while opening the
Mac's forwarded USB channel: `SSHException: Timeout opening channel.`
No failed inner device-SSH setup is recorded in this batch. Nested route,
tunnel and collection error records describe the same attempts, not additional
failures. Every original result is later collected and both routes verified.
Capture durations are 92.517, 92.785, 92.473 and 92.708 seconds; these include
setup, sleep, recovery observation, collection and proofs.

Using [report 201's bounded clock-alignment method](201-diagnostic23-connected-sleep-repeatability.md#collection-failures-and-timing),
all eight failed attempts begin before the recorded PM return. Seven also end
before it; the last endpoint for cycle 1's second attempt lies between
0.492 seconds before and 0.080 seconds after return, so that endpoint's order
is indeterminate. Selected post-return clock-span IDs are 125, 113, 113 and 89,
with bracket widths 0.571, 0.645, 0.641 and 0.631 seconds. These are bounded
inferences assuming negligible clock drift over each short capture, not an
exact network-ready time or transport root cause.

The derived alignment is `.local/neo159-return-alignment.json`; original
timestamps remain authoritative. Packet/socket observers were not enabled.
This batch does not reproduce a new connection attempt starting after return
and failing at inner SSH setup. It does not explain or close NEO-154's earlier
post-return failure, and no deadline, retry or driver policy was changed to
hide the errors.

| Cycle | Result SHA-256 | Timing SHA-256 |
| --- | --- | --- |
| 1 | `636a1c0a13330d56ea53aaff666a98b3cae899a5a17a1b6eb9ba9c8d656f79f4` | `9b771c2d0bf27db1167c3c682a67f09d59cf0f24c1142650562991be6711b1fa` |
| 2 | `4c275c0650f1c826975167b48a8da18ddf27ecf24efb27f284423499e492e403` | `4716a41d67acd76585543e902e7773dea0c7a0f04e0aa07dd74534d2479c195e` |
| 3 | `0fcb423fc1384523348edf63871fef0b02cfa81fec25315a84a92a7b26c6ffb3` | `c90e7dfcd8d0421d63b98119fe4e177a1f7a568d9767d677e70b19b008d0fcba` |
| 4 | `00aa6c055492452e910ef6af6eb2f237789afc93191ab4cfa4b6974a48217f97` | `9832b0020ae78ac92dea359dc3b3067ae7f7a0e46218fb7771d5af05ddedfe09` |

## Final state and next gates

The owner confirms: “Yes—warnings clear and all four returned normally,
untouched.” A fresh read-only `device:pm-inspect` capture at
`.local/diagnostics/20261008T115117.076929Z` passes full health and source-bound
continuation validation of all seven debug results and five sleeps. It retains
PM12/0, all four WFI s2idle counts at 5 and normal dim backlight on the same boot.
Saved checks are `health-validation.json` in that capture and
`.local/neo159-final-receipt-check.json`.

The unused continuation is
`.local/diagnostics/20261008T114344.024513Z/cycle-4/qualification-next.json`,
SHA-256 `9eef5c88db9d893fbdb3e1291bea1102318bc2aed0ed7f9011bce99d3b24fd46`.
No further sleep or screen test is running.

Next, qualify the battery-only and cable-transition profiles on this image,
with separate current-state admission and coordinated physical instructions.
The awake-only measurement guards need a controlled interrupted-window check;
standby comparisons need unplugged measurements. Those results, rather than
callback counts alone, must establish any efficiency gain. Keep the product
power-button/idle sleep behavior and deep-retention work separate from these
diagnostic RTC tests.
