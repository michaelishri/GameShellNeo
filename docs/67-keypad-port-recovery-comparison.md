# Keypad USB port recovery comparison (NEO-49)

30 September 2026. Owner's CPI v3.1, installed diagnostic.10,
Linux 6.18.54-gameshellneo10. This follows the retained-input and speaker
qualification in [report 66](66-speaker-hardware-validation.md).

## Question and source evidence

Supply retention keeps the keypad connected and preserves its original evdev
handle, but the USB device resume callback still took approximately 1.1 seconds
in the earlier driver debug tests. This experiment tests existing Linux
per-port options before proposing a driver patch or reducing generic delays.

The locked Linux source documents the port `quirks` bitfield in
`Documentation/ABI/testing/sysfs-bus-usb`. Its implementation is in
`drivers/usb/core/port.c` and `drivers/usb/core/hub.c`:

- Bit 0 selects the old enumeration scheme. `hub_port_init()` skips the second
  reset performed by the new scheme, while retaining descriptor/identity
  verification and normal retry behavior.
- Bit 1 changes successful reset recovery from a nominal 50 ms `msleep()` to
  `usleep_range(10000, 12000)`. The two-reset baseline can incur this wait twice.
- Independently, a previously identified low-speed device selects the 200 ms
  reset-wait interval. Neither option removes this conservative interval.
- `finish_port_resume()` calls `usb_reset_and_verify_device()` for reset-resume;
  that function uses `hub_port_init()` and verifies the device descriptors.
  This makes the port options relevant to the retained keypad's resume path.

These are source-derived expectations, not measured savings. The trial does
not modify global USB enumeration defaults, the keypad's device quirks,
persistence, wake policy, runtime policy, kernel code or the image.

## Repeatable method

```sh
task device:keypad-inspect
task device:keypad-quirks QUIRK=old-scheme CYCLES=2
task device:keypad-quirks QUIRK=fast-recovery CYCLES=2
```

Each comparison runs two baseline cycles, two candidate cycles and two final
baseline cycles. `CYCLES=1..4` controls the count per phase. Each cycle has its
own device-owned recorder, original open input handle, bounded trace, five-second
PM debug pause and 30-second post-stage observation. The host also verifies fresh
USB and Wi-Fi SSH connections; a 20-second gap separates completed cycles.

The exact qualified topology is the 4242:e131 low-speed `rancidbacon.com
UsbKeyboard` on the internal 1c1a400 OHCI controller, port 1. The helper checks
both the keypad-to-port and port-to-keypad sysfs links, manufacturer/product/
revision, descriptors, original power policy and default global enumeration
settings. Initial live inspection found port mask zero, `old_scheme_first=N`,
`use_both_schemes=Y`, the keypad supply enabled and normal sleep still masked.

A mode-0600, boot-owned record is saved before mutation. Every cycle restores
its original mask and verifies readback; unrelated original bits are preserved.
There is no interval between cycles with a candidate deliberately left active.
`ExecStopPost` independently restores a terminated recorder, and
`task device:pm-restore` provides manual recovery. Unknown concurrent port
changes or changed device identity are rejected with the ownership record
retained. Other restoration operations still run if one fails. Global USB
settings are observed and checked, never rewritten during cleanup.

Host acceptance requires supply retention, unchanged USB and input identities,
a healthy original handle, zero keypad disconnects, complete restored tracing,
restored port policy and exactly one successful USB device resume callback in
the trace. A comparison stops on any failure, preserves partial results and
never retries a possibly accepted PM submission. Cross-phase checks require the
same boot, kernel, Wi-Fi profile, CPU/charger/backlight configuration and keypad
identity/policy.

`comparison.json` retains each observation and the three phase means. The
callback timing is distinct from the whole debug-stage duration and the later
fresh-handle observation. These are instrumented driver recovery measurements,
not actual sleep/wake latency, first physical key delivery or energy savings.

Physical verification, after reviewing the automatic comparison, uses:

```sh
task device:keypad-input QUIRK=old-scheme AUDIO=1
```

The owner must be ready for the existing on-screen A/B/X/Y and held-A sequence.
The candidate is restored at the end. Human interaction and speaker cues make
this a functional test, not a timing comparison. The previously reported
per-key audio delay is explicitly deferred and unchanged.

## Host validation

`task check` passed 266 tool tests (one optional skip), 13 runtime tests,
compiled helper checks, Bash syntax and ShellCheck. Nine new regressions cover
candidate application/restoration, interruption recovery, changed boot/device/
port, concurrent changes, global-policy interference, invalid topology,
existing ownership, write/readback rejection, broken continuity/trace evidence,
fixed comparison order and stopping after failure. `git diff --check` passed.

Private host log: `.local/neo49-check.log`.

## Hardware results

The single-reset comparison passed all six cycles on the unchanged boot
`5bac9cdf-d98f-42ec-a3f3-7454e0c6d92d`:

| Phase | Cycle 1 USB resume (s) | Cycle 2 USB resume (s) | Mean (s) |
| --- | ---: | ---: | ---: |
| Baseline before | 1.090980 | 1.105964 | 1.098472 |
| Old enumeration scheme | 0.742927 | 0.734932 | 0.738930 |
| Baseline after | 1.098914 | 1.095971 | 1.097442 |

Against the four surrounding baseline observations (mean 1.097957 seconds),
the candidate reduced the callback by **0.359028 seconds, about 32.7%**.
The two final baseline observations returned to the original timing range.
This is a small, controlled sample; it does not establish long-run reliability
or total wake latency.

Every cycle retained the original input handle, USB device number and input
sysfs identity, with zero keypad disconnects or supply-disable events. Both
SSH routes passed, tracing was complete and restored, and the original port
mask zero was restored. All PM failure counters remained zero, with no new
ULPI warnings, kernel warnings or oopses. PM success increased from 2 to 8.
Three cycles encountered a transient failed USB collection attempt; each
retrieved the same completed run on retry, without resubmitting the PM stage.

Private comparison: `.local/diagnostics/20260930T101555.542030Z/`.
Host log: `.local/neo49-old-scheme.log`.
Run IDs in phase order:

- `56f409373b6f4ca090e180b5a12dc557`
- `9819a9eedd014a8eb574584251959a24`
- `9bea857c1c8a4f32b98e49f637b7bc7e`
- `c19b17cd6ee94f3ca92b630dca922ce0`
- `3bddf32b2cbf4d00ad769e3cd7908199`
- `3505ccbc446149539f13ac20a5703fd1`

The separate fast-recovery comparison also passed all six cycles on the same
boot, with the old-scheme bit clear throughout:

| Phase | Cycle 1 USB resume (s) | Cycle 2 USB resume (s) | Mean (s) |
| --- | ---: | ---: | ---: |
| Baseline before | 1.106942 | 1.106967 | 1.106954 |
| Shorter reset recovery | 1.000901 | 1.006931 | 1.003916 |
| Baseline after | 1.083928 | 1.077918 | 1.080923 |

The candidate reduced the callback by **0.090023 seconds, about 8.2%**, relative
to the surrounding baseline mean of 1.093939 seconds. The final baseline was
about 26 ms faster than the initial baseline, so the reduction is approximately
77–103 ms depending on the comparison phase. Both candidate observations were
below every baseline observation, but this remains a small sample.

All continuity, trace, restoration and independent SSH checks passed, with all
PM failure counters zero. PM success increased from 8 to 14. Four cycles had a
transient failed USB collection attempt followed by successful collection of
the same run; no PM stage was resubmitted.

Private comparison: `.local/diagnostics/20260930T102415.535975Z/`.
Host log: `.local/neo49-fast-recovery.log`.
Run IDs in phase order:

- `4b8c59deb94e4668a7f431cc23f8e994`
- `44f0e09a715040d28477338f7cca1ea4`
- `fac613ac606e4c4b9d72d932ca6690a0`
- `a4584677cda847b2b8715d92955ce485`
- `cd0b50bdda80416bb46e3f038cd45b80`
- `3a938811e5fa43749895ae85146b666c`

## Physical qualification and remaining work

Independent post-comparison inspections confirmed the same boot, port mask zero,
default global USB settings, persistence enabled, runtime control `on` and no
keypad wake setting. `pm_test=none`, `pm_async=1`, PM success was 14 with every
failure counter zero, all seven services were active without restarts, no units
had failed and kernel taint was zero. Private evidence:

- `.local/diagnostics/20260930T103208.886998Z/inspection.json`
- `.local/diagnostics/20260930T103208.876387Z/keypad.json`

With the owner ready, `task device:keypad-input QUIRK=old-scheme AUDIO=1`
passed run `b7d855e62a4a46d08446529c86b9cfb7` on the same boot:

- All A/B/X/Y taps before and after the driver stage arrived through the original
  input handle. USB device number 2 and input sysfs identity were unchanged;
  there were no keypad disconnects or supply-disable events.
- Held A was cleared during generic input suspend, as in the previous
  qualification. The release timestamp, 3476.020919 seconds, falls inside its
  traced suspend callback at 3476.020893–3476.020925 seconds. Fresh presses worked
  afterward and the final key bitmap was empty. Continuous key-down delivery
  and a distinct physical release event were not observed in this cleared mode.
- All nine speaker cues passed, with both amplifiers off before PM and after
  each cue. Mixer, console, exclusive grab, tracing, port mask and PM controls
  were restored. All 217 input events and the complete PM trace were retained.
- USB/Wi-Fi SSH recovered, every PM failure counter stayed zero, and the owner
  confirmed correct buttons, tones and the normal dim login console.

The USB callback took 0.752973 seconds in this interactive run. Its whole debug
stage took 7.177799 seconds and a fresh healthy handle was observed 0.216157
seconds afterward. These figures are recorded separately from the automatic
comparison; human input and audio instrumentation differ.

Private evidence: `.local/diagnostics/20260930T103413.111602Z/cycle-1/`, with
`result.json`, `retention.json` and `physical-input.json`;
host log `.local/neo49-physical-input.log`.

Independent final captures confirmed the same boot, original port mask zero,
default global enumeration settings, `pm_test=none`, `pm_async=1`, all seven
services active with no restarts, no failed units or kernel taint, and PM success
15 with every failure counter zero. Both audio PCMs were closed, both amplifiers
were off and the complete mixer dump matched the preceding qualified idle state:

- `.local/diagnostics/20260930T103714.656605Z/inspection.json`
- `.local/diagnostics/20260930T103714.681680Z/keypad.json`
- `.local/diagnostics/20260930T103714.727927Z/audio.json`

NEO-49 is complete for these scoped driver-debug comparisons and single-reset
physical qualification. No candidate is installed as a permanent policy. The
fast-recovery option has automatic continuity evidence but has not received its
own physical button sequence. Normal sleep remains disabled; the audio-latency
investigation remains explicitly deferred.

These trials do not test both bits together. Their separately measured savings
must not be added: selecting the old scheme removes one reset and therefore
one of the recovery waits affected by the other option. Any combination needs
its own controlled comparison and physical-input qualification. Cold starts,
actual sleep, extended reliability and keypad retention energy also remain
separate qualification work.
