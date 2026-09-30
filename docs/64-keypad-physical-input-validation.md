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
shows a five-second countdown, then individual prompts:

1. Tap and release A, B, X, Y, waiting for each label.
2. Press and hold A. Continue holding through the briefly dark screen.
3. Release A only when `RELEASE A` appears.
4. Tap and release A, B, X, Y again, waiting for each label.

Each requested edge sequence has a 15-second deadline. The device-owned
service has a four-minute limit and independent cleanup; the host collects
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
ordered nine-press/nine-release sequence, healthy held/released bitmaps,
unchanged USB/input identity and confirmed cleanup. Private evidence includes
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

The owner-assisted hardware sequence is pending. This test will not qualify
all buttons/chords, a release while the device is suspended, keypad firmware
identity, actual sleep, wake latency or retention energy. Its human interaction
means it must not be used as a latency comparison against NEO-45.
