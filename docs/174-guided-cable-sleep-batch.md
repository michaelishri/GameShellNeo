# Guided alternating USB sleep batch

5 October 2026. NEO-118; supports NEO-110 and NEO-117.

Diagnostic.20 has one passing attended case in each cable direction, documented
in [report 171](171-diagnostic20-usb-attachment-sleep-validation.md) and
[report 173](173-diagnostic20-usb-removal-sleep-validation.md). The original
one-shot tool requires a separate seven-debug preparation for each case. The
new explicitly bounded workflow carries one validated debug baseline through
four alternating cases, retaining the checks and owner observations between
them. No connection to the GameShell or Mac, device test, reboot or sleep was
performed during this implementation. The owner is disconnecting the board
for about an hour.

## User workflow

The fixed sequence is removal, attachment, removal, attachment. USB begins
connected and finishes connected. There is no extra awake reconnect between
cycles. Each command runs one awake alarm rehearsal at the current cable
endpoint and one actual RTC-wake attempt, using the existing saved worker.
It then stops for the owner to confirm the cable action and display return.

New tasks:

| Task | Purpose |
| --- | --- |
| `device:sleep-cable-batch-start` | Copy a fresh baseline into a private session and run cycle 1 |
| `device:sleep-cable-batch-next` | Run the next step only after the previous observation passed |
| `report:sleep-cable-batch` | Bind the owner's first observation to the unchanged pending result; no device access |
| `report:sleep-cable-batch-status` | Inspect saved session state; no device access, also available after helper sources change |

The start task requires `QUALIFICATION`; the others require the printed `BATCH`
directory. Start and next both require fresh described readiness expressed by
`ATTENDED=1 CABLE_ACTION=1`. The observation task takes the existing `OBSERVATION`
and `DISPLAY` values. `during-dark`/`normal` is accepted only when the owner
reports those observations. Ambiguous, late, missing or abnormal action/display
reports are retained and end the session.

The GameShell shows `Cycle N / 4` with the direction-specific instructions.
It retains the ten-second instruction lead-in, long warning before darkness,
ten-second dark wait before the single physical action, and roughly thirty-
second RTC deadline. The original console is restored after each attempt.
Between cycles the user leaves the cable and buttons untouched and the Mac
awake on the same Wi-Fi. See the [README workflow](../README.md) for commands.

## Evidence and admission

`tools/sleep_cable_batch.py` contains the shared bounded-lineage validation.
It is included in the hashed/uploaded device helper set. The existing
`sleep_rtc.history` function delegates only when an explicit batch definition
is present; legacy one-shot and connected-sleep behavior is unchanged. The
definition contains a unique session ID and the exact four-direction sequence.
The current index follows from the accepted predecessor list, not an editable
counter used to choose a sleep action.

Both host and device revalidate the original debug anchor and every preceding
sleep/rehearsal. Checks include:

- Exact source, boot, image and SDIO identity, with diagnostic.20's disabled
  MUSB/supply wake policies and `masked-cable-v2` criteria.
- Fixed alternation, unique run/rehearsal IDs, original parent claims and
  unchanged observer ancestry. A batch cannot become a legacy sleep chain.
- A matching awake rehearsal for each individual cycle. Its PM generation
  matches the starting state; its RTC event follows the prior sleep event,
  and the actual sleep follows that rehearsal's RTC count exactly.
- Complete recovery, RTC-wake attribution, correct cable endpoints, input
  retention, trace integrity and policy/control restoration using the existing
  full result validator. Energy qualification is not inferred.
- PM/journal/time continuity and unchanged cable-handler counts between
  completed sleep, next rehearsal and actual entry. An extra awake cable
  change prevents continuation even if the final endpoint looks correct.
- Endpoint-specific route proofs: Wi-Fi for a removed cable, both USB and Wi-Fi
  for an attached cable. Original results remain unchanged when later actions
  occur.

Host observer reports bind to the SHA-256 of the original result, including
route proofs. The device receipt additionally binds the explicit human
attestation to the digest of the corresponding device-owned original. This
does not pretend that software independently observed the physical timing.
Existing durable one-successor claims still consume the debug parent or prior
sleep before alarm/PM mutation. Failed or uncertain successors cannot be
replayed by creating another session ID.

## Host state and failure handling

`tools/check-sleep-cable-batch.py` owns the host session. It persists `running`
before contacting the device and retains a numbered directory for the awake
rehearsal, sleep, and independent endpoint inspection. It hashes accepted
result/rehearsal/endpoint/observation files and pins helper source hashes.

The normal transitions are:

```text
ready → running → awaiting-observation → ready
                                    └→ complete (after cycle 4)
```

A failure or unqualified observer report ends the batch. A killed host command
leaves `running`, which cannot be restarted by `next`. Collection uses the
original saved run ID; it never resubmits PM. The underlying single-attempt
collector may reconnect to retrieve that same result within its existing
deadline. It does not retry the sleep operation. The local PM lock and device
ownership checks prevent concurrent sessions.

An independent Wi-Fi endpoint inspection is saved before asking for the owner
report. It must match the original final endpoint, boot and cable-handler
counts. This preserves the unplugged-state evidence before a later attachment.
Each observer report is created exclusively; observation and continuation are
separate commands so an answer never starts another screen test implicitly.

## Verification and remaining work

Offline tests exercise the four-step state machine, evidence/route/observer
failures, altered sources, interrupted submissions, durable successor claims,
matching per-step rehearsals, extra PM/RTC activity, intervening cable changes,
and rejection of legacy/consumed histories. All 118 focused sleep tests pass,
including 19 new batch tests. `task check` passes 13 runtime and 595 tooling
tests (one existing optional skip), the compiled current-selector and Mac
mount-guard checks, Bash syntax and ShellCheck. `task --list` exposes all four
new commands, and `git diff --check` passes. Private logs are
`.local/neo118-sleep-tests.log` and `.local/neo118-check.log` in the candidate
worktree. No hardware outcome is inferred from these host tests.

The hardware workflow remains unqualified. When the owner reconnects the board,
read-only access/health checks come first, then a freshly observed seven-debug
baseline and the described four-step session. No card swap is needed because
only uploaded diagnostic tools and documentation changed. Historical original
results, consumed baselines and failed runs remain intact.

This batch addresses repeat coverage. It does not measure charging current
during sleep, standby energy, deep CPU retention, Mac-host sleep or power-button
wake. Those remain separate qualification tasks. Normal product sleep is still
disabled.
