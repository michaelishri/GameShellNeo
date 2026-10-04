# Attended USB transitions during sleep: diagnostic preparation

4 October 2026, Pacific/Auckland. NEO-110; follow-up to NEO-95 and
[the first battery-only RTC-wake pass](150-battery-rtc-qualification.md).

The saved sleep runner now prepares two explicit cable-transition cases:
connected → disconnected, and disconnected → connected. Source tests pass.
No new image was built, no live helper uploaded, and no hardware setting or
sleep test was run during this preparation. Hardware qualification remains
open; the preceding diagnostic.18 results remain unchanged.

The later fresh hardware sequence stopped after the driver prerequisite lost
early journal history. No cable-transition sleep was submitted. [Report 152](152-diagnostic-command-log-volume.md)
records the failed original, normal owner-observed display, excessive helper
source logging and the verified transport correction. A later fresh boot now
passes all seven automated prerequisites with journal continuity and both SSH
routes intact; the owner confirmed normal display return. The removal awake
rehearsal below also passed. The subsequent attended removal attempt woke on
RTC and returned a normal console but failed with stale gadget connection state;
[report 153](153-usb-removal-sleep-state-failure.md) preserves the original and
opens NEO-112 for driver investigation. Cable-transition qualification stays open.

## What each case establishes

| Case | Starting condition and awake rehearsal | Required final recovery |
| --- | --- | --- |
| `usb-remove` | USB configured/powered; no cable change during rehearsal | External inputs absent, USB/carrier/PHY absent, valid battery discharge, independent Wi-Fi SSH |
| `usb-attach` | Physically unplugged, software-confirmed battery state; no cable change during rehearsal | External inputs present, USB configured/carrier/PHY attached, independent USB and Wi-Fi SSH |

Both are submitted over Wi-Fi through the configured route. A removal case
also verifies USB SSH before submission; an attachment case verifies it after
return. The original same-boot result is always collected over Wi-Fi. An
uncertain submission never becomes another PM command.

Ordinary USB and battery profiles keep their existing health requirements.
Scenario-specific before/after endpoints select those established validators;
they do not add a permissive common profile. Receipt, rehearsal and original
device record bind the scenario. A rehearsal for removal cannot admit attachment
or ordinary battery sleep. Transitions reject repeat histories, use the existing
durable single-successor claim, and never publish a continuation. Each scenario
requires its own fresh seven-debug baseline and same-source awake rehearsal.
No card reflash is needed for these uploaded diagnostics.

## Physical protocol and evidence limits

The actual test requires fresh observer readiness and a confirmed starting
cable state. On-screen instructions appear for ten seconds before RTC arming.
After darkness, the observer waits ten seconds, performs exactly one requested
action at the GameShell, then leaves the cable in that state. If the screen
returns before the action, the instruction is to stop and leave the cable
untouched. No buttons are used. The Mac stays awake on the same Wi-Fi.

The original visible tty1 contents are saved in a boot/run-owned record and
restored on success or ordinary exception. A separate service cleanup operation
can restore that same run after worker termination. Foreign console owners or
changed geometry are rejected without deleting their evidence. Power-key
ownership and inhibition begin before displaying the instructions.

Passive state/IRQ samples are captured before the attempt, before the
wakeup-count handshake, and after return/recovery. Any observed cable change
before entry rejects before a sleep write. The final state must match the
requested endpoint. Each AC/VBUS count must increase exactly once in the
requested direction, with the opposite counters unchanged. Additional,
missing, reversed or ambiguous IRQ evidence fails qualification.

These counts are not electrical instrumentation. PMIC interrupt handling can
be deferred until resume, and the documented PMIC behavior can miss events.
The recorder does not infer that a software IRQ timestamp identifies the
physical contact change inside `machine_suspend`. Display darkness likewise
does not identify that exact boundary. An independent, explicit observer
statement is required for the attended-case result, and precise edge timing
remains unqualified even when that case passes.

## Wake and failure interpretation

The thirty-second RTC deadline, single wakeup-count handshake, single sleep
submission and strict RTC-wake acceptance remain. On a transition return, the
RTC descriptor is checked once without waiting. The record distinguishes:

- No RTC event available at return: early or unattributed wake, not a pass.
- RTC event available but another wake IRQ: not an RTC-wake pass.
- RTC event and matching wake IRQ: still requires the normal count, flags,
  deadline, sleep trace, cleanup and device-health validation.

An early return is preserved while the existing recovery observations are
collected. It is never relabeled as a successful RTC wake because an alarm
arrives later while awake. No cable-wake cause is asserted from the observation
alone. Missing RTC delivery fails the same overall qualification. Owned RTC,
PM and trace cleanup still runs; the existing conservative diagnostic power-key
suppression can remain after failure until the original result is reviewed.
No reboot, gadget restart, alarm extension or automated retry is added.

The read-only original-result collector now also reports the console-owner
file, making interrupted console cleanup visible without changing it.

## Saved tasks and observer record

The [README](../README.md) gives the complete commands and physical sequence.
New tasks are:

```text
device:sleep-cable-remove-rehearse
device:sleep-cable-remove
device:sleep-cable-attach-rehearse
device:sleep-cable-attach
report:sleep-cable
```

`CABLE_ACTION=1` confirms readiness/instructions, not a completed action.
`UNPLUGGED=1` confirms the battery starting state, and `ATTENDED=1` is separately
required for actual sleep. Missing flags reject before loading credentials or
contacting hardware. Neither case has a batch task.

The offline report binds the observer's `during-dark`, `after-return`,
`no-action` or `uncertain` answer and `normal`, `abnormal` or `unknown` display
answer to the original result's SHA-256. It revalidates any claimed automated
success and requires the appropriate host route proofs. A positive attended
case requires both successful automation and an explicit normal/during-dark
observation. The original result and earlier observer statements are never
overwritten. A human answer cannot override an automated failure.

## Validation

`task check` passes 13 runtime and 533 tooling tests, plus the compiled AXP
current-selector/mount-guard checks and Bash/ShellCheck. The two existing skips
are the opt-in user-systemd test and the pinned Armbian helper test whose source
checkout is absent from the isolated worktree. Evidence is
`.local/neo110-check.log` in `work/sleep-cable-transition`'s worktree.

The twenty new methods cover endpoint/rehearsal separation, premature and
extra/missing/reversed events, boot/time/CPU mismatch, observer flags,
source/ownership/route rejection, single submission after lost transport,
immediate RTC observation, early/wrong-IRQ rejection, console restoration after
interruption, foreign/geometry protection, and immutable observer reporting.
Existing RTC deadline, memory, input, PM failure, trace and successor-history
tests continue to pass. These are simulated filesystems/transports and source
execution, not real physical edges or a live PM transition.

## Awake removal rehearsal

The owner confirmed all fresh prerequisite cycles looked normal and explicitly
gave readiness for the awake rehearsal, keeping USB connected and controls
untouched. The saved task ran once:

```sh
task device:sleep-cable-remove-rehearse QUALIFICATION=.local/neo110-removal-reference-history.json CABLE_ACTION=1
```

Run `4dad01f01eab4c40a3d2760c7a3a5174` passed on the same diagnostic.18 boot
`f2dfd67d-cf9a-4242-b9b7-58c1bc944357`. Its original capture is
`.local/diagnostics/20261004T090940.115092Z/result.json`, SHA-256
`eac1dc7ae024f0b084290ea69ec76cfe862108beae3bc7118e8c45cdf7ab90fa`.

The RTC delivered one alarm after 30.536 seconds, IRQ31 count 1 → 2, then its
owned state was restored. PM success remained 7 and every failure counter
remained zero: this was awake throughout. USB remained configured with carrier
and external power present at all three samples; every AC/VBUS transition count
remained zero. Independent USB and Wi-Fi SSH proofs passed. Original power-key
policy was restored and no diagnostic policy, control, RTC or console owner
remained. Memory/input, journal continuity and trace checks passed.

This qualifies the recording setup for a separate attended attempt. It does not
establish sleep, cable handling while asleep, CPU retention or energy savings.

## Remaining work

Resolve NEO-112's stale disconnect state and review the missing PMIC removal
events before planning another sleep case or attachment. A source,
boot or PM-history change must not silently reuse a consumed baseline.

Mac sleep/wake, another GameShell boot, CPU-idle/timekeeping, battery energy,
power-button wake and ordinary product sleep policy remain separate work.
In particular, full-off USB-triggered startup is not the same as wake from
s2idle; the owner's newly reported startup behavior is recorded separately in
`FOLLOW-UP.md` for PMIC/bootloader feasibility investigation.
