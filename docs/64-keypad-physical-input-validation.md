# Physical keypad events across driver suspend/resume (NEO-47)

30 September 2026. Follows [retained-input-handle qualification](63-keypad-retention-hardware-validation.md)
on diagnostic.9 / `6.18.54-gameshellneo8`, owner's CPI v3.1.

## Purpose and scope

A healthy evdev handle alone does not prove button delivery. This slice adds
`task device:keypad-input`: one owner-assisted devices debug stage, with ordered
physical taps before/after and a held A button across driver suspend/resume.
The image, kernel, keypad persistence, supply policy, brightness, radio and
normal sleep masks are unchanged. No actual sleep or USB timing modification
is involved.

The earlier [keypad qualification](29-hardware-qualification.md) established
A/B/X/Y as Linux J/K/U/I, codes 36/37/22/23. These expected mappings are fixed
in the saved test, not learned from whatever input happens to arrive.

## Saved sequence and evidence

Keep USB connected and the Mac on the GameShell's Wi-Fi network. The device
shows a ten-second countdown, then individual prompts:

1. Tap and release A, B, X, Y, waiting for each label.
2. Press and hold A. Continue holding through the briefly dark screen.
3. Release A only when `RELEASE A` appears.
4. Tap and release A, B, X, Y again, waiting for each label.

Each requested edge sequence has a 30-second deadline. Each accepted tap shows
a two-second recorded confirmation before advancing to the next button.
The device-owned
service has a seven-minute limit and independent cleanup; the host collects
the same run ID after connection loss and does not resubmit PM. Existing
`device:pm-collect RUN=...` and `device:pm-restore` tasks cover recovery.

`tools/keypad_input.py` reads the original fd yielded by the existing keypad
observer. A bounded reader thread drains native Linux `input_event` records,
including ARM32's 16-byte layout, using the monotonic event clock. It records
events, prompts and original-handle key-state checkpoints. Normal repeats are
accepted for held keys; queue overflow, invalid edges, an unexpected button,
disconnect or timeout fails the sequence. Up to 4,096 events can be retained.

An exclusive evdev grab prevents the test keys reaching the login console.
The separate power key is not grabbed; the existing temporary logind inhibitor
still covers power/sleep/idle handling. A boot-owned `/dev/vcsa1` snapshot
preserves screen cells, attributes and cursor. Cleanup restores it and releases
the grab; fd closure also releases the grab on process death. Independent
`ExecStopPost` attempts console recovery and always attempts PM recovery even
if another restoration step fails. No input events are injected and no getty
restart or brightness change is required.

The original PM health gates, bounded trace, memory check and independent
USB/Wi-Fi SSH proofs remain required. Device health is checked again after the
owner's initial input, before PM entry. The host also verifies the complete
ordered face-button sequence, held/released bitmaps, unchanged USB/input identity
and confirmed cleanup. Held-key behavior is separately classified as continuous,
cleared, or cleared/reasserted. Non-continuous modes require the release event
to fall inside the exact input device's successful suspend callback in the
complete trace. A release before that interval fails qualification. A cleared
key may produce no later physical-release event; the fresh post-resume A tap
still has to deliver a new press/release. Private evidence includes
`result.json`, `retention.json` and `physical-input.json` after full success.
Failed runs retain partial events and errors in the main result.

## Preparation and hardware status

The initial read-only inspection is saved at
`.local/diagnostics/20260930T072802.413692Z/inspection.json`; diagnostic.9 remains
on the same boot as NEO-45 with normal sleep disabled and PM controls restored.
Host regressions exercise ordered edges, repeats, queue loss, partial reads,
held-key release/repress rejection, original-fd recording, cleanup failures,
entry guards and rejected physical preparation preventing PM entry.

`task check` passed 246 tool tests (one optional skip), 13 runtime tests,
compiled current-limit/mount-guard checks and Bash/ShellCheck. The private log
is `.local/neo47-check.log`. Read-only console/ABI preflight confirmed a visible
40-column, 15-row tty1 and native 16-byte input events; its log is
`.local/neo47-console-preflight.log`.

## Initial owner-assisted attempts

The first run, `2df88cccb40a43969606dc121e1f041f`, correctly rejected a second A
press while B was requested. The owner confirmed pressing A again because the
first press was uncertain. No PM stage was entered; the grab, console and trace
were restored, with no trace loss. Evidence is at
`.local/diagnostics/20260930T073828.549567Z/cycle-1/`. Independent inspection at
`.local/diagnostics/20260930T073938.217477Z/inspection.json` confirmed the same
boot and restored PM controls. A two-second per-button recorded confirmation
was added so acceptance is visible before the next request.

The next attempt at `.local/diagnostics/20260930T074034.096197Z/cycle-1/` timed
out waiting for the first A press with no events and no PM entry. Both attempts
remain rejected observations, not completed suspend/resume tests. The initial
countdown was extended to ten seconds, button deadlines to 30 seconds and the
overall bound to seven minutes; owner readiness was requested again before
the next run. The 12 physical-input regressions passed after these prompt and
timeout changes.

## Held-key finding

The watched run `419bfca7424c477e93affe3197255b23`, at
`.local/diagnostics/20260930T074222.120284Z/cycle-1/`, recorded all four initial
taps and a held A immediately before PM entry. The devices stage returned after
7.433 seconds, including the deliberate five-second debug pause. The original
strict continuous-hold assertion then stopped the sequence: evdev had reported
A released at monotonic 2916.531518, although the owner confirmed holding A
until the failure prompt.

The trace brackets that release precisely within `input1`'s suspend callback,
2916.531501–2916.531529. The pinned Linux source,
`drivers/input/input.c:input_dev_suspend()` (line 1791 in Linux 6.18.54), calls
`input_dev_release_keys()` and emits a synchronization event before returning.
`input_dev_resume()` restores LEDs/sounds but does not reconstruct held keys.
This is deliberate generic input behavior; preserving an evdev connection does
not imply preserving the logical held-key state. No kernel change was made.

The initial test assumption was therefore too strict for stock Linux behavior.
The recorder now preserves this as a negative continuous-hold observation and
continues to qualify fresh post-resume taps, requiring trace correlation rather
than accepting arbitrary early releases. Continuous-hold evidence is never
inferred from a successful physical-input task.

This stopped run restored the grab, console and trace with no reader error or
trace loss. It did not reach the requested physical release or post-resume taps.
Independent inspection at
`.local/diagnostics/20260930T074403.238111Z/inspection.json` found the same boot,
PM success 8/failure 0, both network interfaces connected and all services active
without restarts. The updated checks passed 247 tool tests (one optional skip),
13 runtime tests and compiled/lint checks; log
`.local/neo47-hold-classification-check.log`.

## Completed physical sequence

Run `3cc86350d92d49929ae49cc898c00811` completed the revised sequence on the same
boot. Evidence is under `.local/diagnostics/20260930T074804.060638Z/cycle-1/`,
including `result.json`, `retention.json` and `physical-input.json`; the host log
is `.local/neo47-input-classified.log`.

- All four A/B/X/Y taps delivered their expected press/release edges before
  and after PM through the same original input handle.
- A was held immediately before entry. Its release at 3250.830972 falls inside
  `input1`'s suspend callback, 3250.830960–3250.830978. The resume bitmap was
  empty: the held state was cleared, not continuous or automatically reasserted.
- After the release instruction, no second evdev release was needed because
  Linux already considered A released. The new A tap and remaining B/X/Y taps
  worked, and the final held-key bitmap was empty.
- The keypad remained USB device number 2 with the same input sysfs identity.
  No keypad disconnect or supply-disable event occurred. The original handle
  and a fresh handle were healthy.
- All 3,738 trace events were retained, with no overrun, commit overrun or
  dropped events. The input recorder retained 229 events without queue loss.
  Grab, console, tracing and PM controls were restored.
- Both fresh USB and Wi-Fi SSH proofs passed. One transient collection error
  (`No existing session`) was retried against the same run; no PM resubmission
  occurred. No ULPI warning, PM failure or extra firmware load occurred.

The stage took 7.662 seconds including the five-second debug pause. Human
interaction and the extra recorder make this unsuitable for comparison with
NEO-45's latency observations.

Final independent inspection is at
`.local/diagnostics/20260930T075039.371914Z/inspection.json`. Boot identity is
unchanged, PM success is 9 and all failure counters are zero. This slice
executed two driver stages: the initially strict hold check and the completed
classified sequence. The earlier two attempts never entered PM. All services
remain active without restarts, taint is zero, no units failed and battery
telemetry reports 100% on USB power.

NEO-47 is complete for this four-button sequence and held-A observation.
Continuous held-key state was not preserved; this is distinct from connection
continuity and successful fresh button delivery. Other buttons/chords, release
while suspended, keypad firmware identity, actual sleep, wake latency and
retention energy remain separate work. Normal sleep stays disabled.

The owner requested an audible registration cue for the next test. The installed
kernel has `CONFIG_SOUND` disabled, with no ALSA cards, sound device nodes or
playback utilities; read-only evidence is `.local/neo47-audio-inspect.log`.
The requested cue is a separate follow-up; no sound was played by this sequence.
