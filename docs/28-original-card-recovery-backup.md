# Original-card recovery backup — NEO-5

Date: 27 September 2026. The owner supplied the separate original card while
the development card remained running in the GameShell. This operation reads
the original card; it does not flash an image or change the development card.

## Card and procedure

The Mac reported one external physical USB card, temporarily `disk16`:

| Property | Observed value |
| --- | --- |
| Whole-card size | 15,931,539,456 bytes |
| Sector size | 512 bytes |
| Partition map | MBR / `FDisk_partition_scheme` |
| First partition | Linux, 43,838,976 bytes |
| Second partition | Linux, 15,883,304,960 bytes |

Disk numbers are temporary. This identifier is historical evidence and must
not be reused to select a card in a later session.

The reusable workflow is documented in the [README](../README.md#backing-up-the-original-card):

```sh
task mac:status
task mac:backup DISK=diskN
```

The Mac helper validates external physical USB media, unmounts it and checks
its identity/partition layout again. It opens the raw device with `rb` only,
captures the whole card into a private gzip archive and calculates SHA-256 over
every captured byte. It then decompresses the archive and compares its size
and SHA-256 with the complete original read. Successful verification publishes
the archive without overwriting an existing backup and ejects the card.

The Linux helper downloads the archive and verifies its compressed SHA-256 and
size. Mac copies remain under `~/.local/share/GameShellNeo/backups/`; Linux
copies remain under `.local/backups/`. Identity/checksum reports accompany the
archives; operation logs are retained in `.local/diagnostics/`. These files can
contain personal data and remain private, outside Git.

The original card's Linux filesystems have no macOS-recognized volume UUID.
Backup identification therefore records physical media and partition metadata;
it does not create or weaken the separate UUID-based authorization record used
by the destructive flash task.

## Verification result

The Mac's whole-card capture and complete decompression check passed, and the
card was ejected. The Linux copy passed the compressed size and SHA-256 check.
Both private copies and their reports are complete.

| Artifact | Value |
| --- | --- |
| Archive name | `original-card-20260927T002917.754749Z.img.gz` |
| Uncompressed bytes | 15,931,539,456 |
| Uncompressed SHA-256 | `6f1244305fa5844994197757196774b2c80d94cf954df6661da1d1bc70a196a6` |
| Compressed bytes | 6,515,307,882 |
| Compressed SHA-256 | `0a8140503ffc1a53113fea13329a3a66a14ef99bad39178b8641a196e5294be8` |
| Private capture directory | `.local/diagnostics/20260927T002917.754749Z/` |

The first 4 MiB and entire boot partition from the downloaded archive also
matched the files captured from the original running installation, byte for
byte. The private `baseline-comparison.json` records:

- First 4 MiB SHA-256: `612bb05276a1d0b5242dddcef9f5937b3623195acb4af290f67872e98f972f0e`.
- Boot partition SHA-256: `bde8eff0bf62801fc2d19e7819d1758500f72d9d7077e724d8c860067719612b`.

Host checks passed: 25 Python regressions, the compiled current-selector cases,
Bash syntax and ShellCheck. Backup-specific tests cover a Linux card without
a filesystem UUID, rejection of internal disks and invalid disk identifiers,
changed-card detection, read-only raw access, complete archive contents,
truncated reads, and failure to publish/eject a corrupt archive. Existing flash
guard tests continue to pass.

Archive verification establishes a consistent captured byte stream and intact
copies. It does not establish filesystem/application health or prove that a
restored card boots. The original physical card remains the immediate recovery
option. A future restore must use a separately identified spare with capacity
at least equal to the recorded whole-card size. `mac:backup` does not perform
restoration and `mac:flash` remains the diagnostic-image workflow.

NEO-5 remains open for repeated cold starts/reconnections, controls/display,
CPU/storage stability and supervised power tests.
