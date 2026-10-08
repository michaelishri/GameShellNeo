# Diagnostic.24 staged suspend/resume qualification

8 October 2026; evidence timestamps are UTC. NEO-158 is in progress.
The freezer and driver debug checks pass on diagnostic.24/kernel
`6.18.54-gameshellneo23`, boot `44b698ad-7fef-46d4-9e0f-71153f6f81e9`.
Both SSH routes recover and the original keypad connection is retained.
PM success/fail is **2/0**. Owner confirmation of the warning and display return,
late/noirq qualification and actual RTC sleep remain pending.
[Report 218](218-diagnostic24-installation.md) records the installation and
passing awake prerequisites.

## Initial attended sequence

The owner confirmed readiness to watch. The saved tasks ran sequentially, with
the original freezer result reviewed before submitting the driver cycle:

```sh
task device:pm-test STAGE=freezer CYCLES=1
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
```

The freezer leaves the display on. The driver cycle plays the one-second level-5
warning before the dark interval, owns POWER input during the test, and records
keypad and Wi-Fi traces. Playback/control restoration passes; audibility and
the visual return still require the owner's separate observation.

| Stage | Capture under `.local/diagnostics/` | Run ID | Stage interval |
| --- | --- | --- | ---: |
| freezer | `20261008T104230.741069Z/cycle-1` | `746c9ebfa195417b85f27ecf9d886032` | 5.273 seconds |
| devices | `20261008T104342.857131Z/cycle-1` | `7b5a87b9984e462ab91442055ccd710f` | 7.806 seconds |

The intervals include the five-second debug delay and are not actual sleep or
wake-latency measurements. Both results verify process memory and independent
USB/Wi-Fi SSH on the original boot. PM advances 0/0 → 1/0 → 2/0 with all failure
counters zero. Original keypad handle, USB device number and input sysfs identity
survive, with zero keypad disconnects or supply-disable events. POWER is handed
back; keypad/Wi-Fi traces restore without recorded loss. Backlight brightness
returns to 1 with power 0.

All four WFI s2idle callback counts remain zero, as expected for these debug
stages. SDIO runtime usage stays at 2 with unchanged runtime policy. The saved
`task check:sdio-ref-history -- --require-stable <freezer-result> <driver-result>`
passes, producing `.local/neo158-initial-reference-history.json`. These two
results are not yet the seven-debug qualification needed for actual sleep.

## Collection evidence

Both offline `task device:ssh-timing-report CAPTURE=<cycle-directory>` reports
validate, recording exactly one PM submission each. The freezer capture lasts
53.763 seconds with six collection attempts and no errors. The driver capture
lasts 60.297 seconds with seven collection attempts, one of which fails when the
Mac cannot open the forwarded USB route (`No route to host`; the caller records
`ChannelException(2, 'Connect failed')`). The original result is later retrieved
and both independent route proofs pass. No PM operation was resubmitted.

This is a retained transport failure during collection, not evidence that the
previously investigated SSH greeting stall recurred or an exact measure of
post-resume readiness. NEO-154's underlying investigation remains open.

| File in the respective cycle directory | SHA-256 |
| --- | --- |
| Freezer `result.json` | `f8a577471a943068a989799f2532a40768a660b36b84c1a8fb02c48e00953ec1` |
| Driver `result.json` | `d5b346b6f3a7a24f507445d59d8dc85ce6dd1703e45bb1cdbc2fced91abc0232` |
| Freezer `host-timing.jsonl` | `8d17c9da8f98539872061d3b73c67161a72ba8ea8db6d7512c30a878daff2fcf` |
| Driver `host-timing.jsonl` | `bbee60a66372d48bb631abccad679ea3743389b79a64ff8e244cabce536a0f77` |

Original task logs are `.local/neo158-freezer.log` and `.local/neo158-driver.log`;
timing summaries are `.local/neo158-{freezer,driver}-timing.json`, all in
`work/cpi-wfi-integration`.

## Next gates and efficiency limits

Await the owner's warning/display observation and readiness for the first
late/noirq debug cycle, followed by four separately admitted repeats. Review
each original result and stop on failure. An awake RTC rehearsal and fresh
readiness must precede actual sleep.

The intended efficiency opportunity is coordinated clock-event and timekeeping
suspension when all CPUs enter s2idle, avoiding timer-driven wakeups. WFI itself
already existed in the ARM idle fallback. A registered driver and successful
debug return do not establish lower current. Ordinary awake framework overhead,
actual all-CPU sleep participation, independent timekeeping freeze, reliable
resume and eventual unplugged battery comparisons remain distinct evidence gates.
