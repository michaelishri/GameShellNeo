# Bounded kernel evidence independent of journal retention

9 October 2026. NEO-184. Implementation and offline validation following
[NEO-182's stopped preparation](246-battery-repeat-preparation-journal-loss.md).
**Hardware qualification is pending.** No device connection, PM operation,
reboot, image build or card write was performed for this implementation.

PM snapshots now collect sequence-numbered records from `/dev/kmsg` and retain
a bounded protected checkpoint. The initial boot prefix supplies the observed
kernel firmware identity; exact before/after record prefixes establish each
test's interval. General-journal rotation no longer removes this evidence.
Missing printk records still fail admission. No previous failed result is
rewritten, and the 60-second sleep cap remains unchanged.

## Why this source

The pinned Linux `6.18.54` source documents independent `/dev/kmsg` readers,
one complete record per read, sequence numbers, `EAGAIN` at the end of a
nonblocking read and `EPIPE` after an overrun. Userspace writes cannot use the
kernel facility. These properties allow gap detection without clearing the
ring or changing journald. The implementation was checked against
`Documentation/ABI/testing/dev-kmsg` and `kernel/printk/printk.c` in the pinned
tree; the [published kernel ABI documentation](https://www.kernel.org/doc/Documentation/ABI/testing/dev-kmsg)
describes the same interface.

The new [kernel_evidence.py](../tools/kernel_evidence.py) performs bounded
reads only when a PM snapshot is requested. There is no background monitor,
polling service, additional wake source or change to system log retention.
This is a diagnostic correctness change; no power or latency saving is claimed.

## Provenance and continuity

The first checkpoint must contain a complete sequence starting at zero and a
kernel-origin firmware-identification message. It freezes an anchor count and
digest. The existing PM validator still compares the runtime identity against
the source lock and scans all retained kernel text for its existing fault
markers. On-disk firmware hashes alone cannot satisfy the runtime identity check.

Each checkpoint binds:

- Boot UUID and running kernel release.
- The complete image manifest digest and firmware/NVRAM file hashes.
- The exact source hashes of the collector and PM snapshot producer.
- The immutable initial anchor and all subsequent raw records.

Later captures verify every overlapping raw record and append only consecutive
sequence numbers. The ring may have discarded a prefix already preserved in
the checkpoint. It may also begin exactly at the next uncollected sequence.
An unrecorded gap, reordered/duplicate record, changed overlap, regressed or
empty stream, `EPIPE`, read error or changed source stops collection. There is
no seek-and-retry or journal fallback.

All records count toward continuity, including userspace-origin messages.
Only kernel-facility message text supplies firmware identity and PM/fault
checks. Kernel continuation fragments are deliberately rejected because
joining interleaved fragments could conceal a fault. Unknown extra header
fields and device metadata are preserved. Malformed headers, unexpected
encoding and truncated/oversized records fail.

The snapshot's `kernel_evidence` field contains the structured original
records, context, anchor and digest. Its existing `journal` field is retained
as a compatibility rendering of **those kernel records**, not data from
`journalctl`. Validation checks that the rendering and source identities match.
The digest detects inconsistent evidence; protected file ownership and the
kernel read path provide provenance, not the digest alone.

## Storage, bounds and interruption

The device keeps one checkpoint under
`/var/lib/gameshellneo/kernel-evidence/`, with mode 0700 for the directory and
0600 for its files. The parent must be root-owned and not writable by other
users. Descriptor checks reject unexpected ownership, types, permissions,
symlinks and hard-linked files; nonblocking opens also reject a FIFO without
waiting for a writer. An exclusive nonblocking lock prevents concurrent writers.

Limits are explicit: 64 KiB per read record, 65,536 records, a five-second read
budget and **4 MiB for the encoded checkpoint**. These bounds are diagnostic
limits, not an indefinite retention guarantee. The checkpoint retains the full
bounded sequence for its boot, with the anchor marking the initial identity
prefix. It never rotates away an old prefix to create space. Reaching a limit
stops qualification.

Publication writes `checkpoint.new` exclusively, flushes/fsyncs it, renames it
atomically and fsyncs the directory. An unchanged snapshot avoids another write.
Failed reads do not publish partial evidence. A failed write before rename
preserves the old checkpoint and leaves the staging file as an interruption
marker; later captures stop rather than deleting it. At most one checkpoint
and one staging file occupy 8 MiB, plus the lock file. Existing per-test result
archives retain their independent lifecycle and are not covered by this bound.

A different boot can replace the single old checkpoint only after collecting
a complete new sequence from zero. It never inherits earlier boot messages.
A corrupt checkpoint or interrupted staging file is not automatically repaired,
even after reboot. Preserve and review that evidence first.

## PM and sleep integration

The existing `device:pm-inspect`, debug-stage and RTC tasks use the helper
automatically; no new bespoke device runner is needed. PM inspection still
leaves hardware settings untouched, but now creates/updates diagnostic storage.
Both uploaded and stdin-packaged helpers carry their exact source identities.
The collector is included in the sleep helper bundle/source manifest.

Debug results, sleep health checks and cable lineage verify the structured
before/after sequence. New prerequisites must be prefixes of the same current
checkpoint with the same anchor and context. Legacy journal-only records remain
available for historical review, but cannot be mixed with new-format snapshots
or used to qualify a new live experiment. Existing sleep source-hash checks
also require fresh rehearsals and continuation evidence.

Historical results are not migrated or edited. Use their original source
revision when re-running a historical source-bound sleep assessment; a new
collector never manufactures acceptance for the old failed attempt.

## Validation

Repeatable offline tasks:

```sh
task test:kernel-evidence
task check
```

The full check passes **16 runtime tests and 874 tooling tests**, with one
existing optional skip, both compiled C checks and Bash/ShellCheck validation.
The 31 new kernel-evidence tests cover retained-prefix wrapping, exact interval
continuity, missing boot records, gaps, reordering, changed overlap, forged
userspace firmware text, real kernel faults, changed boot/image/source,
rendering/digest tampering, source packaging, legacy mixing, quotas, interrupted
writes, unsafe storage, competing writers and boot changes during collection.
They use synthetic kernel records and temporary files, with no host or device PM.

The first full run encountered three unrelated fixture failures from the system
temporary-directory quota. The final run uses a project-local temporary directory:

```sh
mkdir -p .local/host-tmp/neo184
TMPDIR="$PWD/.local/host-tmp/neo184" task check
```

Final saved output: `.local/neo184-check-final.log`. No shared temporary files
were deleted. The original NEO-182 failed debug and recovered battery result
hashes remain unchanged.

## Next qualification and recovery procedure

First qualify the new storage/read path on the board while awake, then obtain
fresh attended debug, rehearsal and sleep evidence. Prefer a fresh observed
boot for this qualification. No image/card swap is needed. If the initial ring
has already lost sequence zero, stop and arrange a warned, observed reboot;
do not seed from saved journal text. This implementation does not itself reboot.

On an interruption or capacity/continuity failure:

1. Stop further PM submissions. Preserve the original result and its source
   revision; recovery never changes its failed/incomplete status.
2. Save any checkpoint and staging file privately on the development machine,
   using the existing `device:exec` task, and verify their sizes/hashes. For
   example, with `umask 077`, redirect `sudo -n cat` of each exact file into a
   fresh `.local` evidence directory. Keep raw kernel messages out of public logs.
3. Establish that no diagnostic owns PM/RTC/input controls; recover such owners
   through their existing original-run tasks. Review the saved storage failure
   before removing any interrupted file. There is intentionally no automatic
   delete/reset command in the capture path.
4. After evidence preservation, an explicit maintenance operation may remove
   the failed checkpoint/staging files before a fresh observed boot. Retain the
   host copies. Leave ordinary journal files and limits unchanged. The new boot
   must supply a complete kernel sequence and fresh qualification; old
   prerequisites and continuation receipts are not reused.

Live printk format coverage, interruption recovery on the board, capture cost,
fresh debug acceptance and the clean NEO-182 battery workflow remain unqualified.
NEO-184 therefore remains in review; the next hardware work requires the usual
long warning, explicit observation readiness and separate unplug instruction.
