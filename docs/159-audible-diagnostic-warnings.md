# Audible warnings before planned reboots and screen blanking

5 October 2026, Pacific/Auckland. NEO-115.

The owner requested GameShell speaker warnings before reboots, then extended
the requirement to every planned screen blanking. The pending actual sleep
test was not started. The seven passing debug stages and original awake
rehearsal remain recorded in [report 158](158-diagnostic19-attended-debug-qualification.md).

## Behavior

The saved workflows now use the existing quiet ALSA speaker cue. No image
rebuild or card swap is needed; the diagnostic helpers are sent to the board
when their tasks run.

| Workflow | Warning and ordering |
| --- | --- |
| `device:reboot ROUTE=usb` or `ROUTE=wifi` | Three existing ascending tones after the existing ten-second lead-in; verify playback, mixer restoration and same boot, then queue one reboot after two seconds |
| USB idle comparison | Both automatic reboots use `device:reboot`; failed warning or uncertain submission stops the comparison |
| Devices/platform PM debug | One cue before each cycle that can darken the screen; one-second lead-in before the timed PM stage |
| Keypad input around PM | Existing input confirmations plus a separate `screen-blank` cue before PM; input still checked immediately before entry |
| Timed power-key release | Warning completes before the one-second hold prompt, preserving its release timing |
| Actual RTC sleep, including batches and cable scenarios | One cue and lead-in before arming the RTC; the warning does not consume the alarm's entry margin |
| Backlight visual test | One cue immediately before each of the three off-cycles |
| `device:idle-sample BACKLIGHT=off` | Warning completes before the backlight is disabled and before sampling begins |

Freezer-only tests, awake RTC rehearsals and read-only inspections remain
silent because they do not intentionally blank the display. Normal diagnostic
power-button and sleep policies are unchanged. These helper changes do not
intercept arbitrary raw reboot commands or physical power-button shutdown;
use the saved task for initiated reboots and carry the requirement into the
future production power policy/UI.

The screen warning uses the previously qualified 80 ms, 880 Hz stereo cue at
the existing conservative speaker level. It closes playback, checks both
amplifiers are off and restores mixer controls before proceeding. The existing
amplifier startup delay remains; this work does not fix delayed key feedback.
The one-second observer lead-in is excluded from the reported debug-stage and
energy-sampling windows, not claimed as production sleep latency.

## Failure and ownership behavior

Playback or audio-restoration failure prevents the planned blanking or reboot.
The backlight test now requires a lit starting display, so its final restoration
cannot silently create another unannounced dark interval.

Standalone backlight/idle helpers are staged with their speaker dependency.
Each gets a unique warning owner recorded in the private host capture and
passed to its bounded service. Independent cleanup checks that owner before
restoring audio. Actual-sleep warnings use the sleep run ID; sleep recovery
similarly rejects foreign audio ownership while attempting other owned cleanup.
It does not restore an uncertain power-button policy as a side effect.

The reboot task reuses the bounded audio worker and original-result collection.
It checks the boot again after successful audio recovery. A unique transient
timer queues a single reboot; `reboot.json` records the attempt before submission
and acceptance afterward. A lost response is retained as uncertain and never
resubmitted automatically. A queued request does not prove the subsequent boot.

## Verification and hardware boundary

`task check` passed 13 runtime tests and 560 tooling tests (one existing optional
skip), compiled C checks, Bash syntax and ShellCheck. Private output is
`.local/neo115-check.log`. New regressions cover:

- Warning playback/restoration failure, idle-before-lead-in ordering, and
  rejection of another owner's cleanup.
- No reboot after failed audio, changed boot or mismatched evidence; an
  uncertain submission is attempted only once and recorded.
- No devices-stage entry after a failed warning; freezer does not play one.
- The complete backlight shell sequence against a fake panel and real PTY:
  three warnings before three dark intervals, and no dark interval after a
  failed warning, with original brightness restored.
- Failed backlight-off warning leaves the display lit and prevents sampling.
- The power-key hold simulation still requires independent physical release;
  the extra cue happens while the key is released.
- Sleep recovery includes matching audio ownership and rejects a foreign owner.

No reboot or screen-blanking operation was performed to validate this change.
Audibility and physical sequencing need observation in the next attended test;
the reboot will be observed when one is otherwise required. This is not new
sleep, driver, latency or energy qualification.

Changed helper sources require a new awake rehearsal before actual sleep.
The original `22984d31403f44dea440a785c88e2295` rehearsal remains historical and
must not admit a different-source sleep attempt. The saved same-boot debug
baseline is revalidated by the normal admission code, without rewriting its
original results or relaxing any checks.

The refreshed `device:sleep-rehearse` passed using that debug history and the
updated helper sources. Capture `20261004T223659.622134Z/result.json`, run
`a627b646cc9a45bc8adc62f361ef9dda`, delivered its awake alarm after 30.492 seconds.
Both SSH routes, RTC restoration and original power policy passed, with no
retained diagnostic ownership and PM still 7/0. Result SHA-256:
`e763ee1110bf389bb5b66f7bb023f54e18f183bb073af3ed5d771cea8053efd7`.
The rehearsal intentionally remains silent; it establishes neither warning
audibility nor actual sleep. Fresh observer readiness is still required.
