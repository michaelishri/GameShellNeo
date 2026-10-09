# Separating speaker confirmation timing

10 October 2026. NEO-185. Offline investigation and measurement preparation
for the [deferred confirmation delay](66-speaker-hardware-validation.md).
No audio, screen test, PM, reboot, device configuration or image operation was
performed. The audible behavior and the driver's amplifier startup wait are
unchanged. This slice adds measurement detail, not a latency fix.

## Where the delay occurs

The input test deliberately acknowledges a **completed tap**, not the initial
press. [keypad_input.py](../tools/keypad_input.py) waits for both press and
release, validates the held-key state and prints the confirmation before
calling the speaker helper. Its event-check loop sleeps 20 ms between checks;
that is a polling interval, not a guaranteed maximum detection delay. After
each cue it waits two seconds before checking for extra taps and presenting
the next prompt. The held-A step also waits one second after detecting the
press to verify that the button remains held.

[speaker_audio.py](../tools/speaker_audio.py) generates the waveform, checks
that playback is closed and both amplifiers are off, updates and reads back
the mixer level, then launches `aplay`. It waits for playback to finish and
verifies amplifier shutdown before returning. The owner-selected long tone
is now the default for these calls: a one-second waveform at level 5. The
original short-cue observations in report 66 used 80 ms waveforms, so their
approximately one-second total operation times are not directly comparable
to the current long warnings.

The board's [audio routing](../kernel/overlay/arch/arm/boot/dts/allwinner/sun8i-r16-clockworkpi-cpi3.dts)
feeds the external speaker amplifier from the codec's headphone output.
In the pinned Linux `6.18.54` source, `sun8i_headphone_amp_event()` enables
that amplifier and waits 700 ms during its DAPM power-up callback. The helper's
per-cue idle check means each new cue uses a powered-down path again. This
explains the repeated startup opportunity identified previously; it is not
evidence that precisely 700 ms separates a physical button press from sound.

Primary source inspected:
`.local/sources/linux-6.18.54/sound/soc/sunxi/sun8i-codec-analog.c`,
SHA-256 `f651c9a00f9ad91f6c557f03bd29d5b1681af8c6a72bfb00d723cfbaa20fda1b`.
The corresponding upstream web page was unavailable to the browser during
this review; the findings above use the pinned local source.

## New saved measurements

Each completed cue now includes seven `time.monotonic()` timestamps with an
explicit schema and clock name. They divide the operation into six intervals:

| Interval | What it includes |
| --- | --- |
| Waveform preparation | Generating and packaging the bounded PCM samples |
| Initial idle check | Finding the card and checking closed PCM / amplifier-off state |
| Mixer update | Setting the level and reading it back |
| Process creation | Starting the `aplay` child |
| Playback process | Input transfer, startup, playback/drain and process completion checks |
| Final idle check | Confirming both amplifiers are off, including any existing bounded waits |

The existing `started_seconds` field still marks the playback request just
before process creation. `completed_seconds` still marks successful final
idle verification. Existing playback bytes, volume, one-second duration,
five-second playback timeout, cleanup and six-second idle deadline remain
unchanged. Failed or interrupted playback does not publish a completed cue.
The screen warning still restores its mixer and adds the existing one-second
observer lead-in before blanking.

This introduces a fixed number of clock reads during an already requested
cue. There is no periodic sampler or background service. Its overhead has
not been benchmarked on the board. Session ownership/mixer setup, physical
input handling, screen prompts and deliberate caller pauses remain outside
the new cue interval. Process timestamps do not measure acoustic onset, and
the playback interval cannot isolate the driver's share of the elapsed time.

## Offline report task

```sh
task test:audio-timing
task report:audio-timing -- .local/diagnostics/<capture>/result.json
# For a saved PM stage:
task report:audio-timing -- .local/diagnostics/<capture>/cycle-1/result.json
```

The report accepts the explicit current-result audio containers, avoiding
embedded prerequisite histories. It reads at most 32 MiB and 128 completed
cues, hashes the unchanged input, emits numeric timings and fixed labels,
and preserves the original result's pass/fail flag. It never contacts a
device or plays sound. Unknown timing schemas, clock/order/endpoint errors
and malformed evidence reject the report. Legacy records have null phase
and whole-call measurements rather than invented values.

Applying it to two existing records demonstrates that compatibility:

| Historical capture | Original result | Waveform | Playback request to idle |
| --- | --- | --- | --- |
| `20261009T095711.475674Z/result.json` | Device sleep passed; host workflow incomplete | 1,000 ms | 1,798.997 ms |
| `20261009T102514.956719Z/cycle-1/result.json` | Failed journal-history validation | 1,000 ms | 1,779.017 ms |

Both records predate the new phase timestamps. Their waveform/mixer preparation
costs and acoustic onset remain unknown. The report does not convert either
historical result into a new qualification pass. Their original SHA-256 values
remain `71ad7b506b1b0dd912fa54614b529e9dc39bf104941e1281317f5f8b188c9543`
and `cb30a535e369393202fcf9245a003a915e49916da5690dc76d67a89082bb4d14`.
Private summaries are saved in `.local/neo185-battery-warning-report.json`
and `.local/neo185-failed-preparation-warning-report.json`.

## Validation and next investigation

All **29 speaker tests** pass, including eleven new deterministic timing/report
tests with fake clocks and playback. They cover stage attribution, unchanged
payload/arguments, idle retries/timeouts, playback failure, legacy records,
bad timing evidence, scope/size limits and unchanged private input files.
The full suite passes **16 runtime and 893 tooling tests**, with one existing
optional skip, compiled C checks and Bash/ShellCheck validation. Output is
saved in `.local/neo185-check.log`. No physical audio claim follows from these
offline checks.

At the next attended test, inspect the new phase records alongside the owner's
observations. The helper source hash has changed, so use fresh current-source
qualification; do not reuse an old rehearsal. The bounded kernel collector
and PM snapshot producer are unchanged. No card swap is needed.

The eventual optimization candidates remain separate decisions:

- Cache the two immutable waveforms if generation cost is material; verify
  identical bytes and measure the memory/time tradeoff.
- Avoid redundant mixer subprocess work only with retained ownership and
  reliable detection of external control changes.
- Compare per-cue shutdown against a bounded ready playback path for a button
  sequence, measuring both response time and the extra powered-audio cost.
- Revisit analog startup sequencing in the driver only with reliable-start,
  click/pop and noise evidence across repeated starts and resume.

The largest visible waits are partly intentional test sequencing. Removing
those pauses would change the physical test protocol, not prove a faster
driver. The owner-deferred audible fix stays open in `FOLLOW-UP.md`.
