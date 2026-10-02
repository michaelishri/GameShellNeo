# Awake power-key input and held-release handoff (NEO-90)

3 October 2026, Pacific/Auckland. Adds a saved, attended awake power-key
sequence following the [worker-failure policy qualification](113-diagnostic-power-key-policy.md).
Host checks and the owner-attended four-pair hardware sequence passed on
diagnostic.16. Original policy, console and idle audio were restored. No image
rebuild was needed. No actual sleep or product gesture is enabled.

## Purpose and limits

The prior test retained a continuously untouched power key. This slice records
physical press/release edges, holds the key briefly across the disposable
policy worker's termination, and verifies that policy restoration only happens
after an observed release on the same continuously owned event stream.

The parent recorder, exclusive evdev grab and ancestor inhibitor remain alive.
Terminating the disposable worker does not simulate losing the entire controller.
This test also does not cross PM or synthesize an input-core release. Those are
separate remaining wake gates. Driver event semantics, logind's ordinary image
configuration and the PMIC shutdown setting are unchanged. The desired short
sleep/wake, two-second menu and eight-second forced-off behavior remains
[the product specification](79-power-button-policy.md).

## Repeatable operator sequence

After confirming that the operator is watching the screen, with USB connected
and the headphone jack empty:

```sh
task device:power-key-input
# Recover evidence only after uncertain collection; never resubmit blindly:
task device:power-policy-collect RUN=<original-32-character-run-id>
```

The display counts down ten seconds, then requests:

1. Tap and release POWER once.
2. Tap and release POWER once.
3. Hold POWER briefly. The recorder kills the disposable worker and displays
   **RELEASE POWER NOW** approximately 0.8 seconds after the press. Release then;
   if the prompt fails to appear, release after **two seconds maximum**.
4. Tap and release POWER once.

Each completed pair receives a visual acknowledgment and a speaker tone after
release. The known tone-start delay is unchanged. The held interval does not
perform D-Bus, configuration or audio operations. Worker termination has a
0.2-second wait bound; its failure still attempts the release prompt. The
preflight reads the PEK's configured shutdown delay and requires at least
6000 ms. That readback is not physical qualification of hard-off timing.

The screen remains on. No `/sys/power` state is written. The service is bounded
to 180 seconds. If it stops, release POWER and leave it untouched while the
original result and retained policy are inspected. Do not delete ownership
records or restore shutdown by hand after uncertain input. Use the existing
orderly SSH shutdown and attended normal power-on recovery if continuous
ownership cannot be established.

## Implementation and handoff

[power_key_input.py](../tools/power_key_input.py) uses the existing input guard,
console restoration and speaker helpers. [The host wrapper](../tools/check-power-key-policy.py)
uploads hashed source, checks the running kernel against the source lock,
records a unique run ID and starts the bounded service. The host and device PM
locks exclude other managed experiments.

The validator requires exactly four ordered press/release pairs on KEY_POWER,
each after its own prompt. It rejects extra or duplicate edges, wrong key codes,
lost input, timestamp reversal and unpaired repeat events. A held-key repeat is
allowed without treating it as another press. Each press must last less than
2.5 seconds; the hold must span worker death and end after the release prompt.

Restoration uses a distinct awake handoff proof. It checks the complete
transcript, unchanged event count, released evdev bitmap, a quiet interval,
the still-owned inhibitor, unchanged boot, PM controls and all suspend counters.
It rejects a guard that has crossed resume. The proof is checked around the
existing policy restoration transaction, retaining NEO-89's ownership,
configuration, reload and process-identity checks. The untouched-key smoke
path retains its stricter untouched proof.

A same-boot, per-run UI record is acquired before changing the console or audio.
Stop cleanup restores only that run's UI/audio state and does not re-enable
power-key shutdown after unknown input. A foreign, malformed or older-boot
owner is not adopted. Failed input leaves the boot-local ignore policy for
inspection/recovery. Normal completion verifies the original effective policy,
input release/descriptor closure, exact audio state and console restoration.

## Source validation and preflight

The full host check passes **13 runtime and 384 tooling tests**, with one existing
optional skip, plus compiled helper regressions and shell lint. The seventeen
new tests exercise valid and invalid transcripts, a simulated full prompted
sequence, worker timeout, early release, extra input during confirmations,
lost/held/recent input, changed PM state, synthetic resume rejection, inhibitor
loss and UI ownership/restoration failures. Existing policy/ownership tests
also pass. These tests do not substitute for physical key qualification.

Logs: `.local/neo90-host-check.log` and `.local/neo90-focused-tests.log`.
Read-only baselines on diagnostic.16:

- Policy: `20261002T194258.135030Z`.
- Audio: `20261002T195358.298260Z`.
- PM: `20261002T195727.743166Z`.
- PEK shutdown readback: `.local/neo90-pek-shutdown.log` (6000 ms).

## Hardware result

After the owner's fresh ready response, run
`7009a05de82a412fa44f9d1928a21771` passed on kernel
`6.18.54-gameshellneo16`, boot
`edb5b83b-8de9-425b-91fe-afb8e66ee39f`. The owner confirmed that the prompts and
four tones were correct and the normal dim console returned. No retry was needed.

| Prompt | Recorded press-to-release interval |
| --- | --- |
| First tap | 149 ms |
| Second tap | 167 ms |
| Hold through worker termination | 1,235 ms |
| Final tap | 191 ms |

The recorder captured exactly eight key edges and eight SYN events. The worker
exited with SIGKILL (−9); its termination was observed 40 ms after the held press.
The release prompt was issued 807 ms after that press, and the release followed
428 ms later. These are software event/recorder timestamps, not measurements of
physical switch latency. Both effective logind actions remained `ignore` after
worker death, with the owned policy files present.

The successful awake handoff restored the complete original policy and
configuration. logind remained PID 298, start timestamp 15411683 µs. Logical
release, input handback and descriptor closure were verified; neither policy
owner nor drop-in remained. All four speaker cues left speaker/headphone
amplifiers off, and the full original audio state was restored.

Final independent inspections confirmed unchanged boot/kernel, PM controls,
seven suspend successes and zero failures, sleep masks, services, taint, USB,
input identities, backlight, charging/CPU policy, Wi-Fi configuration and the
complete kernel journal. Only live sampling counters and battery readings
changed. Both USB and independent Wi-Fi SSH reached the same boot. The transient
test unit was `not-found`, inactive/dead after completion.

Evidence retained privately:

- Test capture: `.local/diagnostics/20261002T200408.701981Z/`, including source
  hashes, run identity, transcript and full result. Uploaded hashes match the
  committed helper source. Host log: `.local/neo90-power-key-input.log`.
- Device result:
  `/var/lib/gameshellneo/power-policy-tests/7009a05de82a412fa44f9d1928a21771/result.json`.
- Final PM: `20261002T200536.530622Z`; policy: `20261002T200555.939154Z`;
  audio: `20261002T200632.994397Z`.
- Comparison and independent route/unit checks:
  `.local/neo90-baseline-comparison.json`, `.local/neo90-wifi-identity.log`,
  `.local/neo90-unit-final.log`.

## Remaining work

Next, account explicitly for input-core synthetic release
across PM and interrupted-controller handoff before combining this policy with
RTC fallback, the wakeup-count handshake and durable real-sleep evidence. The
first real-sleep experiment still targets RTC wake; physical key wake follows.
Actual sleep, whole-controller loss, product gestures and energy savings remain
unqualified.
