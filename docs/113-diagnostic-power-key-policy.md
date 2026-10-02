# Diagnostic power-key policy across worker failure (NEO-89)

3 October 2026, Pacific/Auckland. Added an opt-in, boot-local logind policy
guard and qualified its worker-death/restoration path while diagnostic.16
remained awake. The original shutdown policy is restored. No image rebuild,
key press, PM stage or actual sleep was part of this slice.

## Problem and scope

[Report 101](101-diagnostic-power-key-ownership.md) identified a policy gap:
process/cgroup death releases evdev grabs and inhibitor descriptors. Its
recovery marker blocks another experiment but cannot stop logind interpreting
the waking power-key press as shutdown. The completed
[late/noirq comparison](112-diagnostic16-hardware-qualification.md) did not
exercise this case because the owner left the key untouched.

The new guard keeps logind's short and long power-key actions at `ignore` using
an owned drop-in under `/run`. This file and logind's effective policy outlive
the experiment worker. Normal sleep stays masked. The parent recorder retains
the existing exclusive key grab and ancestor-owned low-level inhibitor while
the disposable policy worker is killed.

This is diagnostic action ownership, not a workaround for a defective hardware
driver and not the product gesture controller. Short sleep/wake, a two-second
menu and eight-second hardware off remain the specification in
[report 79](79-power-button-policy.md). No driver event or PMIC setting changes
in this slice. The temporary mechanism can be replaced by the product's single
gesture owner once that controller and its recovery/held-key policy are qualified.

## Ownership and restoration

Implementation: [power_key_policy.py](../tools/power_key_policy.py),
[host wrapper](../tools/check-power-key-policy.py), and the unresolved-policy
admission check in [power_key.py](../tools/power_key.py).

- Acquisition requires the diagnostic ancestor's verified low-level inhibitor,
  the expected boot, both existing actions set to `poweroff`, and no prior owner
  or drop-in. It records intent before installing the file.
- The guard uses only
  `/run/systemd/logind.conf.d/zz-gameshellneo-pm-guard.conf`, with a unique run
  token. It neither rewrites the ordinary `/etc` policy nor overwrites an existing
  file. The private ownership record is `/run/gameshellneo-power-policy.json`.
- A SIGHUP reload must produce the expected effective login1 properties within
  five seconds. The helper checks the logind PID/start identity and all twelve
  recorded key/lid/idle action settings. It rejects a restart or unrelated
  configuration change. File, owner and unowned configuration checks repeat
  before restoration.
- Restoration is available only inside the continuously held **untouched awake
  key guard**. It rechecks the inhibitor, event stream and logical bitmap around
  policy handback, reloads the original settings and verifies the baseline.
  No CLI flag bypasses that requirement.
- Failed acquisition/handoff retains evidence. If restoration fails after
  removal, the helper attempts to reinstall its ignore policy without
  overwriting a foreign replacement. Failure to reload suppression also fails
  the operation; an ownership file alone is never reported as effective policy.
  An orphaned drop-in or marker blocks a fresh key diagnostic.

There is deliberately no `ExecStopPost` that blindly re-enables shutdown after
the recorder dies. Both files are boot-local: a cold restart clears them and
loads the normal image policy. Configuration conflicts, missing ownership or
lost event continuity require inspection/recovery, not an automatic rerun.
Do not delete these files by hand to bypass a failed diagnostic. If continuous
ownership is lost, use the established orderly SSH shutdown and supervised
normal power-on recovery; do not assume the unqualified eight-second gesture
is already a reliable recovery mechanism.

This is a conservative bounded diagnostic contract. It does not protect against
an unrelated administrator deliberately replacing policy, a logind/configuration
failure, a kernel hang or hardware-enforced power-off. Changed effective policy
is rejected at the next check. A future real-sleep caller must integrate this
guard and its own admission explicitly; existing PM commands are not silently
upgraded to enter real sleep.

## Repeatable tasks and evidence

```sh
task device:power-policy-inspect
# Awake only; leave the power button untouched throughout:
task device:power-policy-smoke
# Retrieve evidence after uncertain SSH; use the original printed ID:
task device:power-policy-collect RUN=<32-character-run-id>
```

The smoke task uploads hashed helpers, records a unique run ID, and launches a
bounded systemd service under the existing inhibitor. The parent owns the key
and shared PM experiment lock; a disposable child applies the ignore policy.
After the child's readiness message, the parent sends SIGKILL, verifies the
policy still applies, then restores it while retaining key ownership. No key
event is injected and no `/sys/power` state is written. The host PM lock prevents
overlapping orchestrated diagnostics. The collect task retrieves evidence only;
it neither restores state nor repeats a submission.

Original results and worker stderr are stored on the device under
`/var/lib/gameshellneo/power-policy-tests/<run-id>/`. Host captures preserve the
source hashes, preflight, transcript, run identity and complete result. If the
whole service dies before writing a result, preserve its `started.json` and
inspect the retained policy; a missing final result is not success.

## Qualification

The complete host check passed **13 runtime and 367 tooling tests**, with one
existing optional skip, plus compiled helper regressions and shell lint.
Twenty-one new policy regressions cover effective-policy parsing, reload
timeout/restart, ownership/configuration/boot conflicts, permissions/symlinks,
untouched-key admission, restoration failures and races, orphaned drop-ins,
and a real subprocess killed after filesystem policy acquisition. The latter
uses simulated login1 responses; it does not stand in for the board result.
Transcript: `.local/neo89-host-check.log`.

Read-only live inspection first confirmed both power actions were `poweroff`
and no policy owner existed. The final helper version then passed on boot
`edb5b83b-8de9-425b-91fe-afb8e66ee39f`, kernel
`6.18.54-gameshellneo16`:

| Check | Result |
| --- | --- |
| Run | `1caf9f5e68d74b0c879736743a8ed4f6` |
| Disposable worker | Terminated by SIGKILL, return code −9 |
| Policy after worker death | Both actions still `ignore`; owned files present |
| Recorder | No key events; inhibitor and exclusive input ownership retained |
| Restoration | Both original `poweroff` actions, all recorded settings and configuration restored |
| logind | PID 298 and start timestamp 15411683 µs unchanged |
| Handoff | Logical release verified, grab handed back, descriptor closed |
| Leftover owner/drop-in | Neither remained |

Final helper hashes in the capture match the committed source. Evidence:
`.local/diagnostics/20261002T193247.940231Z/` and
`.local/neo89-policy-smoke-final.log`. An earlier successful run before the
additional restoration checks is retained at
`20261002T192825.022774Z`, run `b1088499cb6c4f77baf0f8e0e50b57d0`.
Read-only baseline: `20261002T192711.545038Z`.

Final PM inspection `20261002T193525.012650Z` matched the previous hardware
baseline's boot/kernel, masks, PM controls/counters, services, taint, USB,
charging/CPU policy, inputs/backlight, Wi-Fi profile and complete kernel journal.
PM successes remained seven and failures zero. Independent Wi-Fi SSH verified
the same boot after the first awake run; final USB collection remained usable.
The transient smoke unit was `not-found` / inactive after completion. Saved
evidence is `.local/neo89-baseline-comparison.json`,
`.local/neo89-pm-final-version.log`, `.local/neo89-wifi-identity.log` and
`.local/neo89-unit-final.log`.

## Remaining wake gate

This qualifies **untouched awake restoration after worker death**. The parent
recorder/inhibitor was intentionally kept alive in the board test; whole-cgroup
death was not injected on the board. Persistence of the drop-in does not itself
establish observed physical-button behavior after loss of every recorder.

The next slice is the supervised power-key event/held-release handoff, including
synthetic input-core release and interrupted-controller recovery. Only after
that gate should a separately guarded `pm_test=none` experiment combine key
ownership, the qualified RTC deadline, a wakeup-count handshake and durable
evidence. The first real-sleep experiment should use the RTC as its intended
wake source; a physical key wake with RTC fallback comes afterward. These are
the boundaries in [report 98](98-shallow-sleep-readiness.md), not an assertion
that actual sleep or product gestures already work.

## Interface basis

The image package inventory records systemd `257.13-1~deb13u1`. Upstream
[v257.13 logind reload handling](https://github.com/systemd/systemd/blob/v257.13/src/login/logind.c)
resets/reparses configuration on SIGHUP. The
[login1 property implementation](https://github.com/systemd/systemd/blob/v257/src/login/logind-dbus.c)
exports the effective key-action settings; the helper queries them afresh rather
than treating the file's contents as proof of application. The
[v257.13 button handler](https://github.com/systemd/systemd/blob/v257.13/src/login/logind-button.c)
uses these actions for power-key dispatch. Hardware qualification above tests
the actual installed package's reload/readback behavior without restarting it.
