# Diagnostic.12 physical input and USB qualification (NEO-69)

1 October 2026, Pacific/Auckland. Owner's CPI v3.1, installed image
`0.1.0-diagnostic.12`, kernel `6.18.54-gameshellneo12`, boot
`741d1c20-1ae2-4aec-85b4-b6b87f0dfcf4`. This continues the
[supervised PM debug qualification](87-diagnostic12-pm-validation.md).
The source-only [worker-error candidate](89-wifi-worker-error-handling.md)
is not installed and is not qualified by these results.

The speaker-assisted input test, four USB reconnects and final health checks
passed. The owner confirmed the buttons, tones and normal dim console, then
completed the cable sequence. All tests and recorders have finished.

## Baseline and owner readiness

Saved read-only tasks verified USB and independent Wi-Fi access and captured
the PM, keypad and audio state:

```sh
task device:status ROUTE=usb
task device:status ROUTE=wifi
task device:pm-inspect
task device:keypad-inspect
task device:audio-inspect
```

The existing PM validator accepted the inspection without entering a stage.
The board remained on the same boot as report 87, with six PM successes and
zero failures. The owner explicitly replied ready before the input test.

## Speaker-assisted physical input

```sh
task device:keypad-input AUDIO=1
```

Run `94b710468b314c9988bca4ff34a67ec5` passed. The owner followed the
on-screen A/B/X/Y tap sequence, held A through one ordinary `devices` debug
stage, released when prompted and repeated the four taps. The driver stage
took 7.671 seconds, including the deliberate five-second kernel debug pause;
this is not sleep or resume latency.

- All eight requested taps and the held-A press arrived through the original
  open keypad handle. USB device number and input path stayed unchanged;
  there were no keypad disconnects or supply-disable trace events.
- Linux cleared held A during the generic input suspend callback. The release
  event at monotonic 26637.201130 s falls within the traced callback interval
  26637.201119–26637.201138 s. This is a **cleared** hold, not continuous key
  retention. The later physical release did not generate a separate edge;
  fresh taps worked, and the final held-key bitmap was empty.
- Nine speaker cues completed. Both amplifiers were idle after each cue and
  before PM entry; the original mixer controls were restored. The known cue
  delay remains unchanged and is not measured as input latency here.
- Process memory, original-handle health, independent USB/Wi-Fi SSH and
  console, grab, tracing and PM-setting restoration passed. There was no
  trace overrun or collection error. PM successes increased from six to
  seven; every failure counter remained zero.
- The owner confirmed that buttons and tones worked as expected and that
  the normal dim console returned, then separately confirmed readiness for
  the USB checks.

The kernel delta contains the existing internal keypad reset, with no new
driver warning or error. Wi-Fi handshake metadata was not captured in this
physical-input run; successful SSH recovery does not resolve the earlier
intermittent authentication problem (NEO-55).

## USB reconnection

The saved recorder was started only after the owner's readiness response:

```sh
task device:usb-reconnects CYCLES=4
```

After its explicit `ready` record, the owner was instructed to unplug for
three seconds, reconnect for thirty seconds, repeat four times and leave USB
connected. The recorder samples nominally every 250 ms and requires each
observed `not attached` → `configured` transition plus a fresh USB SSH
connection to the same boot before counting a cycle. Requested hand timing
is not an electrical timing measurement.

All four cycles passed on the original boot:

| Cycle | Fresh USB SSH verified (UTC) |
| --- | --- |
| 1 | 09:17:15.914 |
| 2 | 09:17:52.348 |
| 3 | 09:18:19.147 |
| 4 | 09:18:56.888 |

The trace records exactly four removals followed by four configured states.
Two SSH attempts failed while the USB path was returning; subsequent fresh
connections passed and no cycle was counted without verification. There was
no reboot or incomplete cycle. The recorder stopped and removed its temporary
device capture at 09:18:58.990 UTC; the host retains the full trace. The owner
confirmed all four cycles and that USB remained connected.

## Final health

Repeated USB/Wi-Fi status, PM inspection and audio inspection passed. The
unchanged PM validator accepted the final snapshot. All seven inspected
services were active with zero restarts; there were no failed units or kernel
taint. PM success remained seven with zero failure counters, `pm_test=none`
and `pm_async=1`. The backlight was at brightness 1 with `bl_power=0`.

The firmware had loaded once. The saved journal contained no firmware-crash,
SDIO-removal, runtime-PM-underflow, unsupported USB-register, warning or oops
marker. Firmware/NVRAM and Wi-Fi configuration hashes, Wi-Fi power-save,
charger settings, CPU policy and backlight matched the post-input snapshot.
Audio controls matched the initial baseline, both PCMs were closed, both
amplifiers were off and the speaker-enable GPIO was low.

USB and AC input flags were present/online. Software battery monitoring was
valid at 92%/Charging; this is not a capacity or charging-accuracy measurement.
The device was left running with USB connected, and no test remained active.

## Evidence and limits

Private captures under `.local/diagnostics/`:

| Capture | Directory |
| --- | --- |
| USB status baseline | `20261001T085349.377500Z` |
| PM inspection | `20261001T085410.555543Z` |
| Keypad inspection | `20261001T085410.553058Z` |
| Audio inspection | `20261001T085410.655728Z` |
| Wi-Fi status baseline | `20261001T085411.813558Z` |
| Physical input / PM / audio | `20261001T091251.212048Z/cycle-1` |
| USB reconnection | `20261001T091536.299248Z` |
| Final PM inspection | `20261001T091916.388617Z` |
| Final audio inspection | `20261001T091916.486962Z` |
| Final USB status | `20261001T091917.142974Z` |
| Final Wi-Fi status | `20261001T091918.234424Z` |

The physical-input directory retains `before.json`, `run.json`, `result.json`,
`retention.json` and `physical-input.json`. The retention summary's generic
scope excludes physical-input evidence; the separate physical-input result
supplies that evidence for this run. Host logs are `.local/neo69-*.log`.
The USB directory retains `summary.json`, `usb-reconnects.jsonl` and
`device-states.jsonl`. The saved tasks were used without implementation changes;
no unrelated host test suite was rerun for this hardware/reporting slice.

Normal sleep remains disabled. These checks do not enter late/noirq stages
or actual sleep, test the intended power-button wake behavior, exercise every
button/chord, establish sleeping-battery protection, qualify injected radio
faults or measure energy. No image, driver or persistent policy was changed.
Next, retain diagnostic.12 recovery and prepare a separately versioned image
for patch 0018; its source-test success still needs image and hardware checks.
