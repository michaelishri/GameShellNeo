# Diagnostic power-key ownership (NEO-79)

2 October 2026. Added opt-in diagnostic ownership and verified acquisition and
handoff on the awake board. No PM stage or physical power-key test was run.

## Product contract stays unchanged

The owner reconfirmed the intended behavior during this work: a short press
sleeps or wakes, a two-second hold opens power options, and an eight-second
hold forces power off independently of the UI. Changes to driver handling and
emitted events are authorized. [Report 79](79-power-button-policy.md) remains
the product specification. This helper is the temporary owner for experiments;
it is not an implementation of those gestures. Current ordinary diagnostic
short-press shutdown remains until the replacement policy is qualified.

## Ownership and admission

`power_key.py` verifies a root-owned blocking login1 inhibitor for
`handle-power-key:sleep:idle`, with the expected diagnostic identity and a PID
in the helper's ancestor chain. A generic sleep inhibitor or another process's
similarly named inhibitor does not qualify. It identifies the AXP PEK event
node by controller path and verifies the opened character device's major/minor
before taking an exclusive evdev grab. It rejects an initially held key,
records ownership, and checks inhibition and untouched input again immediately
before PM entry.

The same descriptor consumes events until cleanup, including a waking press
and its release. Cleanup waits at most eight seconds, requires an intact event
stream, an empty key bitmap and a short quiet interval, then rechecks the
inhibitor before releasing the grab. Descriptor closure happens even if cleanup
fails. Loss, disconnect, unresolved key state or inhibitor loss fails the run;
a retained ownership marker blocks another guarded diagnostic until a cold
restart. Started/result records capture the event sequence and handoff outcome.
The diagnostic emits no power action and never changes logind's normal policy.

Linux can clear logical keys during input suspension. Pre-resume release events
are recorded as such and are **not physical-release proof**. A logical handoff
pass must not be presented as an attended wake-gesture pass.

## Abnormal termination limit

SIGKILL, process/cgroup destruction or a stuck resume cannot be made safe by a
Python context manager. Kernel descriptor cleanup releases the grab, and the
outer inhibitor disappears when its owner exits. The retained marker prevents
another guarded test; it does not keep logind inhibited after process death.
The normal error path is bounded and recorded, but a persistent, independently
supervised gesture owner and physical held-key/forced-exit qualification are
still required before real sleep is enabled. No real-sleep command is added.
The later [NEO-89 policy guard](113-diagnostic-power-key-policy.md) adds a
boot-local ignore policy that outlives worker failure and passes an untouched
awake restoration check. Physical held-key/waking-event handoff remains a gate;
the original PM helper is not made into a real-sleep command by that addition.
The ordinary debug service retains its runtime limit and independent PM-control
restoration. A platform debug test must keep the power key untouched.

## Saved commands and evidence

```sh
task device:power-key-inspect
task device:power-key-smoke
# Attended debug only, after explicit readiness:
task device:pm-power-key STAGE=devices CYCLES=1
```

The first is read-only. The second owns the untouched key briefly while awake;
it does not access `/sys/power`, inject input or alter power policy. The third
adds ownership to the existing bounded PM diagnostic with device-owned results,
exact-run recovery, normal sleep masks and independent USB/Wi-Fi proof.

Nine new host regressions passed: wrong/missing inhibitor identity, waking
press/repeat/release, synthetic-clear distinction, lost input, held-key timeout,
entry and handoff rechecks, cleanup after PM error, failed cleanup retention and
stale ownership rejection. The existing sixteen PM orchestration tests also
passed. `task check` passed 13 runtime and 331 tooling tests (one optional skip),
compiled helpers and shell lint; log `.local/neo79-host-check.log`.

The awake board passed `device:power-key-smoke`; private evidence is
`.local/diagnostics/20261002T101054.762499Z/result.jsonl`. This exercises the real
login1 response, ancestor check, PEK identity, ioctl grab/state/clock operations
and clean handoff with no input events. The board stayed awake on diagnostic.13.
This does not establish wake delivery or the final gesture behavior.

Interfaces: [login1 inhibitor API](https://github.com/systemd/systemd/blob/main/man/org.freedesktop.login1.xml),
[Linux input event semantics](https://cdn.kernel.org/doc/html/latest/input/event-codes.html),
and the pinned Linux input UAPI in the local source archive.
