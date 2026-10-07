# Diagnostic.23 connected-USB sleep repeatability

7 October 2026; capture timestamps are UTC. NEO-139 is complete.
All four attended actual RTC sleep/wake cycles pass on diagnostic.23, kernel
`6.18.54-gameshellneo22`, boot `7cc788ef-2070-4ab9-887a-1af70c074713`.
The owner confirms clear long warnings and normal dim-console returns after
every cycle, without touching the cable or controls. Both independent SSH routes
recover each time. Final PM success/fail is 12/0: seven debug cycles and five
actual sleeps, including the initial sleep in
[report 200](200-diagnostic23-pm-qualification.md).

This qualifies the bounded connected-USB functional batch. CPU retention,
standby energy, normal wake latency and other power/cable profiles remain open.
Timestamped collection failures are preserved below, including one attempt
that begins after the recorded PM return and fails during device SSH setup.

## Saved workflow and original results

At source checkpoint `75ab453`, after the owner's watching/listening readiness:

```sh
task device:sleep-batch \
  QUALIFICATION=.local/diagnostics/20261007T100552.286876Z/qualification-next.json \
  REHEARSAL=6dac26e6365247dea7ceeeb0d2664c7b CYCLES=4 ATTENDED=1
```

The owner kept USB connected, the headphone socket empty and controls untouched.
Each successor was admitted only after the preceding original completed result
passed its validator and independent USB/Wi-Fi SSH proofs. The runner stops on
failure; it does not resubmit PM. Its 20-second awake gap and each result's
30-second recovery observation are diagnostic intervals, not wake latency.
No source, driver, charging, audio-level or ordinary sleep-policy change was
made during this batch.

The original task log is `.local/neo139-sleep-batch.log`. The batch directory is
`.local/diagnostics/20261007T101111.308402Z/`. Its completed `batch.json` records
four requested and four accepted cycles, SHA-256
`3b30efd8288929ea05bd7c01f2c2399a65f2a0a86e3b36880d9378e01c2f875b`.
Each original below is `cycle-N/result.json` in that directory.

| Cycle | Run ID | Alarm-to-return seconds | Traced s2idle seconds | PM successes afterward | Result SHA-256 |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | `80315af247ae4b498e8e0a9f699b2c84` | 32.286 | 29.091 | 9 | `de1865027876acc7cb93c3a6e0997eb095659f6607523a6f808bd0774020d09c` |
| 2 | `294931453fe94526ae8f434813532a96` | 31.836 | 28.714 | 10 | `a77f3a7ca32e769cd6bb6731f5c11d9673ee34d274f0c80650a0cbe6ad745a5c` |
| 3 | `ba789b237faa43b6aefe4bc4983027be` | 32.164 | 28.909 | 11 | `ed3bd293d670e3915cbb1716a0f7952d0d2abb7828866f3b0ec7a4cc16bb027b` |
| 4 | `d83dfefb4ed643c48044b98a974a39e2` | 32.559 | 29.217 | 12 | `97e60fbd1392a10e93b608badaae86e665478fa53635eb9443dae699e06a31ef` |

All four original results verify functional RTC wake, process memory, original
keypad retention, long-warning playback/control restoration and loss-free
keypad/USB/Wi-Fi tracing. POWER and the original logind policy return, with no
retained policy, drop-in, PM controls, RTC or console diagnostic owner.
Every failure counter remains zero and adjacent full PM snapshots match.
SDIO usage remains 2 with active/on/forbidden runtime policy; brightness and
backlight power return to 1/0 on the same boot.

Each trace contains actual s2idle entry/exit, all four late/noirq phases and RSB
noirq suspend/resume. No timekeeping freeze pair is observed. The supported
trace durations and alarm intervals do not establish CPU residency, energy
consumption or ordinary wake latency.

## Collection failures and timing

The existing summary task validates all four completed host timing captures:

```sh
task device:ssh-timing-report \
  CAPTURE=.local/diagnostics/20261007T101111.308402Z/cycle-1
```

Repeat with `cycle-2` through `cycle-4`. Saved summaries are
`.local/neo139-cycle-{1,2,3,4}-timing.json`. Capture success means the original
result and route checks completed; nested failed attempts remain recorded.
There are 13 failed collection attempts among 39 attempts. Nested tunnel/SSH,
route and collection errors describe the same failed attempt and must not be
counted as independent failures.

| Cycle | Total attempts | Failed attempts | Device phase of failure | Entirely before PM return | Spanning return | Starting after return |
| --- | ---: | ---: | --- | ---: | ---: | ---: |
| 1 | 10 | 2 | 2 tunnel | 2 | 0 | 0 |
| 2 | 11 | 4 | 4 tunnel | 3 | 1 | 0 |
| 3 | 8 | 3 | 2 tunnel, 1 SSH | 2 | 1 | 0 |
| 4 | 10 | 4 | 3 tunnel, 1 SSH | 3 | 0 | 1 |

The last three columns are bounded clock-alignment inferences, not labels
supplied by the kernel. For each capture, match begin/end records by span ID,
check the device boot ID and select the shortest successful `clock.sample`
whose sampled BOOTTIME is later than `result.returned.boot`. If its host
monotonic endpoints are `Hbegin` and `Hend` and sampled device BOOTTIME is `C`,
the host-minus-device offset lies in `[Hbegin-C, Hend-C]`. For any host endpoint
`T` and recorded device return `R`, its relative interval is
`[T-(Hend-C)-R, T-(Hbegin-C)-R]`. Convert nanoseconds to seconds consistently.
This assumes negligible relative clock drift over the short capture. It does
not yield an exact network-ready instant or identify the cause of a failure.

The selected clock-span IDs are 125, 127, 97 and 116; bracket widths are
0.538, 0.613, 0.621 and 0.622 seconds respectively. Ten failed attempts finish
before return and two begin before but finish afterward. An attempt that started
while asleep and later timed out does not demonstrate a fresh post-wake
connection failure.

Cycle 4 provides the distinct case. Collection span 77 starts **1.111–1.732
seconds after return** and fails **13.681–14.303 seconds after return**. Within
it, Mac connection succeeds in 0.349 seconds and the device tunnel succeeds in
2.203 seconds. Device SSH setup then fails after 10.018 seconds, with
`SSHException: No existing session` in `collection-errors.txt`. These are nested
parts of the 12.570-second attempt, not additional delays. The first successful
post-return clock command completes 21.883–22.505 seconds after return, after
the existing five-second collection wait and a new connection attempt.

This rules out classifying all failed attempts as beginning before wake. It
does not isolate GameShell SSH scheduling, USB/TCP delivery, Mac forwarding or
another cause. The existing source of the error is SSH setup, not a proven
driver fault. Preserve the original trace and inspect the corresponding
device/host evidence before changing drivers, timeouts or retry policy.
No PM resubmission or physical reconnect was needed for any cycle.

Timing SHA-256 values (`cycle-N/host-timing.jsonl`):

- Cycle 1: `4fd32a93086833781b0bfd38f43e6d9220c7b4c3cc65d0f3940f971235a2c6f7`.
- Cycle 2: `0b395badeade5abd2703fad7c09b7d1a9e1ad4d88cb2f7bc11c89f3f8e5ee953`.
- Cycle 3: `6fc3b0216bcf81677e6312c6b61051e173e3383fa2c035d0e66c0dbfa13c9961`.
- Cycle 4: `a7150125a4fe9b056ddb9930bfc9b43d4c8388aa4aff1fc61651ef70ebe61f75`.

The derived clock alignment is `.local/neo139-return-alignment.json`, SHA-256
`c52afad0d91a4413718420e7ea8e78c045742e43d89c6b8147d2aae4efabfd79`.
Original timing/result files and the method above remain authoritative.

## Final observation and evidence chain

The owner confirms: “Yes—warnings clear and all four returned normally,
untouched.” No further sleep test is running. USB remains connected.

A subsequent read-only `task device:pm-inspect` saves
`.local/diagnostics/20261007T102245.447759Z/inspection.json`, SHA-256
`15b8e085d4e0283aa567a1d2be3c100e9558a5cdb96d33b1b6fd1f75f66fbeef`.
It confirms the same boot at PM12/0. The existing
`tools/check-sleep-rtc.py::receipt()` independently accepts the final continuation
against this later snapshot, recomputing seven debug and five sleep records.
Its proof is `.local/neo139-final-receipt.json`, SHA-256
`6bbddd15e46c9e3d760a3bb28b66999a66c80abe79cd2fe67b30120ca9762187`.
An earlier offline call supplied the last result's own after-snapshot and was
rejected because the current snapshot must be strictly later. No timestamp or
validation rule was changed; the fresh read-only snapshot resolves that input
error. This was not a new PM attempt or device failure.

The sole unused continuation in this chain is
`.local/diagnostics/20261007T101111.308402Z/cycle-4/qualification-next.json`,
SHA-256 `29585ef0ca93e08d395f5880305a99591d500956f766c9437c32b2c69ac26107`.
Earlier continuations, including report 200's first-sleep continuation, are
consumed. The original awake rehearsal remains
`6dac26e6365247dea7ceeeb0d2664c7b`. Further sleep requires fresh owner readiness
and admission against the then-current source, boot, state and age limits;
this saved continuation is not indefinite permission or a guarantee of admission.

Next work can examine the retained post-return SSH failure without physical
interaction. Broader reliability, power-button wake behavior, other cable
profiles, CPU retention, standby power and physical battery accuracy remain
separate qualification work.
