# Sleep collection reply recovery

9 October 2026. NEO-183. Offline recorder fix following
[NEO-182's interrupted collection](244-first-60-second-battery-rtc-trial.md).

An active RTC experiment now preserves a malformed collection reply and
continues read-only retrieval of the **same original run** within its existing
deadline. It never repeats the sleep submission. A decoded but invalid
identity, envelope, event, clock or completed result still stops the workflow.
All 147 offline sleep-protocol tests pass, including ten new regressions.

## Defect and scope

NEO-182's host task stopped in `collect()` while decoding an unterminated JSON
reply. The device later completed its single sleep successfully, and separate
read-only collection recovered its original result. The failed reply's bytes
were not captured, so the cause of its incompleteness remains unestablished.

The local control-flow defect is independently identifiable:
`json.JSONDecodeError` is a `ValueError`, while the experiment's collection
loop handled transport exceptions but did not handle malformed JSON. Parsing
therefore escaped the bounded retrieval loop before validation or route proofs.
Broadly catching `ValueError` would also hide identity and evidence failures.

The fix is confined to [check-sleep-rtc.py](../tools/check-sleep-rtc.py). It does
not modify SSH transport, timing, connection behavior, firmware or device PM
helpers, and does not reopen the abandoned SSH-stall investigation. No live
device or Mac operation was run for this ticket.

## Behavior

`MalformedReply` classifies only JSON syntax and text-decoding failures. It
retains the returned bytes and a fixed error category/offset without including
reply content in the exception message. Successfully decoded replies must have
the expected `result`/`clock` envelope, a result dictionary, the requested run
ID and a known event. Clock validation remains mandatory.

For an active experiment:

1. Submit the one diagnostic service as before.
2. Read the saved evidence for that run ID.
3. If reply decoding fails, preserve private failure evidence and continue
   retrieval within the same original collection budget.
4. Only a complete, validated result followed by the existing independent
   recovery checks receives host route-proof fields or a continuation receipt.

Repeated malformed replies eventually exhaust the existing deadline. The
last successfully parsed record remains unchanged; partial bytes are never
written to `result.json`. Evidence-storage failure stops the workflow rather
than silently losing the rejected reply. There is no new service submission,
deadline reset, alarm programming, restoration action or automatic reboot in
this recovery path.

Manual `device:sleep-collect` remains one read-only retrieval. A malformed
reply is saved privately, then the command fails with a message identifying
the original run to collect. It neither resubmits PM nor automatically retries.

## Private failure evidence

Each capture can retain four `collection-bad-reply-N.bin` files, with at most
1 MiB from each reply. Existing captures are never overwritten. The associated
`collection-bad-replies.jsonl` records:

- Original requested run ID and route.
- Fixed decode-error category and offset, with character/byte units.
- Full received-byte count and SHA-256.
- Saved filename and byte count, plus explicit truncation status.

Replies beyond the four-file allowance retain metadata and full-reply hashes
but no additional raw file. Large replies retain a bounded prefix and identify
that truncation. Raw storage is therefore capped at 4 MiB per experiment;
metadata follows the existing bounded collection loop. Files are created mode
0600, independently of the caller's umask. Raw bytes can contain device logs
and remain private under the diagnostic capture directory. Routine output and
timing records do not receive the reply payload.

## Validation

The existing repeatable task discovers the new regression file automatically:

```sh
task test:sleep-protocol
```

It passes **147 tests**. The ten new tests in
[test_sleep_collection.py](../tools/tests/test_sleep_collection.py) cover:

- Invalid JSON, empty replies and invalid encoding: exact private bytes,
  hashes and payload-free exception messages.
- Capture size/count bounds, non-overwriting behavior and mode 0600 even
  under a permissive umask.
- Decoded envelope, run-ID, event and clock errors remaining fatal.
- Manual malformed collection saving evidence and failing without PM/upload.
- Malformed → started → complete retrieval on the battery route, even after
  uncertain submission, with exactly one service submission.
- Repeated malformed replies ending at the original 240-second collection
  deadline, preserving the last started record and publishing no acceptance.
- Wrong identity stopping further retrieval and recovery proofs.
- Completed-evidence validation failure retaining the unqualified original.
- Failed independent Wi-Fi proof publishing no route acceptance.
- Failure to preserve a bad reply stopping without resubmission.

These exercise real collection decoding and experiment control flow with fake
transport and clocks; no physical PM device or live network is used. Existing
30/60-second admission, duration, lineage, restoration and route checks remain
in the same suite. `git diff --check` and new Markdown links pass. All nineteen
device-helper hashes and the original NEO-182 completed result/admission hashes
remain unchanged.

## Next hardware step

NEO-183's recorder fix is complete offline. NEO-182 remains open for a fresh
seven-debug preparation, matching 60-second battery rehearsal and separately
attended actual attempt. The historical failed host workflow is not rewritten
or promoted to a continuation anchor. No image or card swap is required.
The 60-second cap, explicit unplug/readiness, long warning, endpoint checks and
separate reconnect instructions remain in force. This change makes no sleep
energy, endurance or live reliability claim.
