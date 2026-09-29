# macOS card verification and temporary mount suppression

Date: **29 September 2026 NZDT**. Recovery/tooling ticket: **NEO-25**.
Diagnostic.5 hardware qualification remains **NEO-22**.

## Failure and evidence

The first flash of the [refreshed diagnostic.5 image](42-remote-network-preparation.md)
wrote the complete 4 GiB image but failed the complete readback checksum.
The task reported failure and did not eject the card. The owner-confirmed
Samsung DEV card remained in the Mac's reader throughout diagnosis.

The physical target was external USB `disk16`, **64,013,467,648 bytes**, with
512-byte sectors. Its boot-volume UUID changed to
`C2FB8BE4-548E-3626-9135-04CDD6452BD4` after writing the new image. A fresh
inspection recorded that identity before further operations; disk numbers
must always be rechecked for subsequent sessions.

Two independent read-only comparisons hashed all **4,294,967,296 bytes** and
located differing sectors without printing their contents:

| Capture | Differing sectors | Card SHA-256 |
| --- | --- | --- |
| `20260929T043216.691810Z` | 418 | `7b91a636a35104a0355b795e90377c47f52392b7058a0a4bc49143a9c30fbd5b` |
| `20260929T043447.173591Z` | 424 | `b85a053f5d9de04a81b619668427d100c337a559bbd04d3a9bd2613d03782aa7` |

Expected image SHA-256:
`263975ac17543acb59de4d33742976804016b18fc4f5da69d8d0ad8de1110bc8`.

All differences were inside the FAT boot partition; the remainder of the
image matched. On the second comparison, the first differing sector began at
byte **16,779,264**, and the final differing sector ended at **24,474,111**.
The boot partition starts at byte **16,777,216** and spans **134,217,728 bytes**.
The comparison records at most 64 ranges, but its total count, first/last
locations and SHA-256 still cover the entire image region.

The boot volume was mounted at `/Volumes/armbi_boot` before and after the
second comparison. Inspection found `.Spotlight-V100` and `.fseventsd` on it.
Changing hashes, confined FAT differences and mounted-volume metadata support
macOS filesystem writes as the explanation. These observations do not identify
the writer of every changed sector or establish that the card has a hardware
defect. The original failed attempt is retained as a failure.

Private evidence under `.local/diagnostics/`:

- `20260929T042612.936810Z/flash.log`: original failed write/readback.
- `20260929T043216.691810Z/card-compare.json` and log: first comparison.
- `20260929T043447.173591Z/card-compare.json` and log: second comparison,
  including actual mount details and first/last difference locations.

## Repeatable correction

`task mac:flash DISK=diskN` now compiles
[`macos-mount-guard.c`](../tools/macos-mount-guard.c) with the Mac's
`xcrun clang`, Disk Arbitration and Core Foundation frameworks. Its approval
callback rejects mounts only for the selected whole disk and its numeric
partition names. For example, guarding `disk16` does not match `disk160`.
Apple documents the callback's returned dissenter as the mechanism for
rejecting a mount. [Disk mount approval callback](https://developer.apple.com/documentation/diskarbitration/dadiskmountapprovalcallback?language=objc),
[Disk Arbitration API](https://developer.apple.com/documentation/diskarbitration/diskarbitration-h).

The flash sequence now:

1. Verifies compressed/decompressed source hashes and the inspected physical
   card identity, then starts the target-specific guard.
2. Unmounts the card, attempts to mount its known partition, and requires both
   a failed mount and the guard's matching veto response. It also checks that
   the partition has no mount point. Any failure stops before writing.
3. Revalidates identity, writes the image and reads back the entire image
   region, checking guard liveness during both operations.
4. Requires the expected SHA-256 and ejects with the guard still active.
5. Ends the guard when the operation exits. No persistent mount settings are
   changed; parent-pipe closure ends the helper and a 15-minute alarm bounds
   an orphan's lifetime.

This requires installed Apple command-line developer tools. Compilation or
mount-veto failure stops the flash; there is no unguarded fallback. A guard
failure during writing or verification leaves an unverified card and a failed
task. Hardware boot remains a separate acceptance step.

For diagnosis, `task mac:compare DISK=diskN` is a separate read-only operation.
Reinspect after a failed write because the image may have changed the volume
UUID. Comparison neither unmounts nor ejects and preserves its JSON/log on
mismatch. It reports hashes, sector locations and mount state without image
contents. See the [routine workflow](../README.md#staging-and-flashing-the-spare-card).

## Validation

Host checks passed **13 runtime tests and 89 tool tests**, with one optional
user-systemd skip, plus current-limit regressions, native C disk-name/slice
matching checks and shell lint. New cases cover full-region comparison,
bounded difference reporting, short reads, truncated images, conflicting
operation modes, actual-veto requirements, unexpected successful mounts,
unrelated partitions, guard death and residual mount points.
Private host evidence: `.local/build/neo25-check.log`.

On the real Mac, the helper compiled, announced readiness and rejected the
explicit `disk16s1` mount probe before writing. The guarded retry then wrote
and read back all **4,294,967,296 bytes** with the exact expected SHA-256:
`263975ac17543acb59de4d33742976804016b18fc4f5da69d8d0ad8de1110bc8`.
The card was safely ejected with the guard active, and the helper exited.
The report records `readback: passed`, `ejected: true` and
`mount_guard_verified: true`.

Successful recovery evidence:
`.local/diagnostics/20260929T044529.062568Z/flash.log` and `flash-result.json`.
This completes NEO-25's tooling/recovery work. The owner has been asked to boot
the card; live connectivity and USB-policy acceptance remain NEO-22.
