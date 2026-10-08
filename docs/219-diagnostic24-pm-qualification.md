# Diagnostic.24 staged suspend/resume qualification

8–9 October 2026, Pacific/Auckland; evidence timestamps are UTC. NEO-158 is in progress.
The freezer, driver and all five late/noirq debug checks pass on diagnostic.24/kernel
`6.18.54-gameshellneo23`, boot `44b698ad-7fef-46d4-9e0f-71153f6f81e9`.
Both SSH routes recover and the original keypad connection is retained.
PM success/fail is **7/0**. The owner confirms the initial driver and first
late/noirq warning/display returns. Observation of the four-repeat batch,
awake RTC rehearsal and actual RTC sleep remain pending.
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
keypad and Wi-Fi traces. Playback/control restoration passes; the owner
separately confirms the warning was audible and the dim console returned normally,
and accepts proceeding to the first late/noirq check.

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

## First late/noirq check

`task device:pm-platform WIFI_TRACE=1` ran once after the owner's confirmation.
The original result passes, with both SSH routes recovered on the same boot.
Capture: `.local/diagnostics/20261008T105516.806486Z/cycle-1/`.
Run ID: `962d8d0f5a5e4525a48e54dfda1bcd2a`.

The stage interval is 7.915 seconds, including the five-second debug delay.
PM advances 2/0 → 3/0 with every failure counter zero. Process memory, original
keypad handle/device identity, zero disconnects/supply-disable events, POWER
handback and loss-free trace restoration pass. The one-second level-5 warning
passes playback/control-restoration checks. Brightness/backlight power returns
to 1/0. All four s2idle callback counts remain zero; no actual sleep was entered.

The three-result SDIO history passes with usage fixed at 2 and unchanged policy:
`.local/neo158-three-reference-history.json`. Adjacent PM result counters are
0/0 → 1/0 → 2/0 → 3/0. The owner confirms this stage's warning and display
return and readiness for four repeats, recorded below.

The validated timing capture records one PM submission and five collection
attempts, one unsuccessful. The failing inner USB SSH setup lasts 10.028 seconds;
the caller records `SSHException: No existing session`, and Paramiko's background
thread logs an SSH-banner timeout. The original completed result is subsequently
retrieved and both independent route proofs pass. The 63.440-second capture
includes setup, test, collection and proofs; it is not wake latency. This matches
the previously observed error shape, but does not establish its timing relative
to device readiness or its cause. NEO-154 remains open; no PM resubmission or
speculative SSH policy change occurred.

- Result SHA-256: `46b5a55d5334486bcf4dfbd127ee110ac95abc8e664b38a755b2742321cdf579`.
- Timing SHA-256: `1003fb4ae451312f5d5f2a2dea4d55208a5f3c51a4acaa5b5351bcd3ca2dfe85`.
- Original log: `.local/neo158-platform-initial.log`.
- Offline timing summary: `.local/neo158-platform-initial-timing.json`.

## Four late/noirq repeats

On 9 October local time, the owner confirmed the first late/noirq observation
and readiness for four repeats. Each used `task device:pm-platform WIFI_TRACE=1`;
the original completed result, route proofs, keypad retention and counter
continuity were reviewed before starting the next. All four pass.

| Repeat | Capture under `.local/diagnostics/` | Run ID | Stage seconds | PM afterward |
| --- | --- | --- | ---: | --- |
| 1 | `20261008T110024.746108Z/cycle-1` | `232ec1ebfecb4647b2b3e267ebcc2de9` | 7.911 | 4/0 |
| 2 | `20261008T110151.843178Z/cycle-1` | `75ae9506f8954941a9bd366facec2903` | 7.897 | 5/0 |
| 3 | `20261008T110322.223991Z/cycle-1` | `dad5be34027847b6a0d8c9ba5fd7aaef` | 7.980 | 6/0 |
| 4 | `20261008T110455.946275Z/cycle-1` | `638985758c224768ab06024d0e332c01` | 7.955 | 7/0 |

Each verifies both independent SSH routes, process memory, original keypad
handle/device identity, zero disconnects/supply-disable events, POWER handback,
long-warning playback/control restoration and loss-free keypad/Wi-Fi traces.
Every PM failure counter stays zero, SDIO usage stays 2 with unchanged runtime
policy, and brightness/backlight power returns to 1/0. All four CPU s2idle
callback counts remain zero. These debug stages do not enter actual sleep;
their intervals include the five-second delay.

Result SHA-256 values for repeats 1–4:

- `a46681875149bc58686354eff95b62ed26551539ac1019c9fff0dbb41d4dbfb2`.
- `150bcb07f310c2c09454be9ab25c58f2df706f256211fd21c54b720f8a9ae75f`.
- `3855fc63951728dc947cf02322a0cdefb9e9bd77eea17366cfd23a4a42f52858`.
- `11e207c33757134d602d15cf637a2cf87a6d0f9476ca1e7cd0b32e69201d91ec`.

All four offline timing reports validate with one PM submission each. Repeat 1
has no recorded errors; repeats 2 and 3 each retain one failed USB forwarding
attempt (`No route to host` / `ChannelException`). Repeat 4 retains one inner
SSH setup timeout (`No existing session`, with a background banner timeout);
that inner span lasts 10.021 seconds. Each original result is subsequently
collected and both routes independently verified; no PM operation was
resubmitted. Capture durations are 61.913, 65.871, 66.184 and 61.739 seconds;
these include setup and collection, not just the PM interval. No transport
root-cause or recovery-latency claim follows from these observations.

Timing SHA-256 values for repeats 1–4:

- `9ea9ba7096400ea9ce2a6d0c29682e670b982408ac980a8dfdf8d959b3c5d4b4`.
- `ecac49847d4f5cc2d786b93c7e11bd5a1f8746dc8a2d6e0c44c289aec4d65b60`.
- `43b7aeef4eab050e8d41d50b519169a2c98693d3489282ab7015472d564fc031`.
- `fa7f1a4658dd958fc62048dc30ea58c68b1cf53f4875398989e076783b3205df`.

Original logs are `.local/neo158-platform-repeat-{1,2,3,4}.log`; validated
timing summaries are `.local/neo158-repeat-{1,2,3,4}-timing.json`.

## Completed debug admission

`task check:sdio-ref-history -- --require-stable` accepts all seven explicit
result paths in chronological order. Adjacent full PM counter snapshots match,
with successes progressing 0 → 7 and no intervening cycle. The stable history
is `.local/neo158-reference-history.json`, SHA-256
`498c75c8beed86d33f2d71cfcdeef8e08c09dccdf04d53dd32165f824d4f34be`.

A fresh read-only `device:pm-inspect` capture at
`20261008T110759.803909Z` passes full health and the existing sleep controller's
seven-debug admission against that history. It retains the same boot/image,
PM7/0, unchanged dim backlight and zero s2idle callback counts. Saved checks are
`health-validation.json` in the capture and `.local/neo158-debug-receipt-check.json`.
The awake rehearsal must still perform its own fresh admission.

Two host-only invocation errors were corrected without changing any evidence
or device test: the first repeat-4 timing report used an incorrect directory,
then succeeded using the controller's actual capture path; an attempted
combined admission used the final cycle's own snapshot instead of a newer
current snapshot, correctly failing the strict timestamp gate. The fresh
read-only capture above meets that requirement. No gate was weakened or PM
cycle repeated because of these errors.

The owner has been asked to confirm all four audible warnings and normal
display returns. No further screen test is running.

## Next gates and efficiency limits

Await the owner's four-repeat warning/display observation, then run the awake
RTC rehearsal using `.local/neo158-reference-history.json`. Fresh watching
readiness must precede actual sleep. Do not reuse diagnostic.23's qualification.

The intended efficiency opportunity is coordinated clock-event and timekeeping
suspension when all CPUs enter s2idle, avoiding timer-driven wakeups. WFI itself
already existed in the ARM idle fallback. A registered driver and successful
debug return do not establish lower current. Ordinary awake framework overhead,
actual all-CPU sleep participation, independent timekeeping freeze, reliable
resume and eventual unplugged battery comparisons remain distinct evidence gates.
