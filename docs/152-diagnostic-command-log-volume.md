# Diagnostic source logging and lost journal history

4 October 2026, Pacific/Auckland. NEO-111; discovered during NEO-110's
[USB cable-transition prerequisites](151-usb-cable-sleep-diagnostics.md).

The fresh sequence stopped after its driver check because early kernel journal
entries disappeared during the run. This is an evidence failure, with no matching
kernel/firmware fault string in either snapshot. The owner confirmed the normal
dim console returned. No late/noirq or actual sleep/cable test followed.

## Original hardware evidence

Both records are on diagnostic.18, kernel `6.18.54-gameshellneo18`, boot
`e419f334-0a16-4b04-96d2-d97a2e4d5d0b`. Captures are beneath
`.local/diagnostics/`, with results in `cycle-1/result.json`.

| Stage | Capture | Run | Outcome |
| --- | --- | --- | --- |
| Freezer | `20261004T072524.599029Z` | `fc95d5ec316c45eb96377229e3f45e79` | Passed, PM27→28/0, independent USB/Wi-Fi proofs |
| Devices | `20261004T072648.828510Z` | `1b05fb33428c4448a73804914b3d891d` | Failed journal health/continuity, PM28→29/0 |

The driver's before snapshot has 1,009 kernel journal lines, including the
firmware identity. The after snapshot has 532 lines starting at monotonic
34311.946628; the firmware boot message and earlier prefix are gone. Neither
snapshot matches a fault marker, and kernel taint is zero. Memory checksum,
original keypad handle, SDIO usage 2, backlight and power-key handback survive;
Wi-Fi trace reports restored logging and completed reassociation. Those individual
observations do not turn the overall failed record into a pass. The failed host
controller did not publish its normal postflight route proofs.

The subsequent read-only journal inspection is
`20261004T072905.794812Z/before.json`. It passes the existing policy validator:
RAM-log and cron remain masked, logrotate has no inherited pre/post hooks,
journald is still PID110 with its original start time, and persistent files
remain open. The displaced `/var/log.hdd/journal` store is absent. All ten
retained journal files pass `journalctl --verify`. The separately saved kernel
ring buffer still contains its boot and firmware messages. Neither journal nor
ring buffer was cleared, restarted, copied back into the live store or substituted
into the failed result.

## Excessive diagnostic logging

The read-only PM helper assembled its dependent modules and passed the whole
program through `sudo python3 -B -c <source>`. The usual sudo command audit
therefore stored many source fragments on every inspection/collection. This also
affected several other inline diagnostic readers.

The retained JSON-lines capture has 35,646 entries and 17,669,936 uncompressed
message bytes. Sudo accounts for 16,734,466 bytes (94.7%), across 18,347 entries;
205 of its 314 command records identify inline Python. The kernel messages
account for only 19,333 bytes. These are retained message totals, not a measurement
of compressed disk allocation or all historical logging.

Capture: `.local/neo111-retained-journal.jsonl`, SHA-256
`449726c3141259fbc5ed2ef56224c23a779e9a6fd0d1b7a041b9fd60549c8b8f`.
Saved summary: `.local/neo111-journal-volume-saved.json`. The raw capture is
private; the report emits fixed categories and totals without message/source text.

The configured persistent limit is 32 MiB with seven-day maximum age. The retained
inventory totals ten 4 MiB files. Systemd documents synchronous size enforcement
and deletion of archived files; active files can leave the observed total above
the configured limit. An age limit does not guarantee that much history under a
size limit. [Systemd v257 journald configuration][journald].

The observed loss is consistent with size-driven retention under this avoidable
logging load. There is no retained vacuum event identifying the exact deletion,
so this does not conclusively attribute that specific removal. It is distinct
from [the previously fixed RAM-log relocation](97-journal-loss-investigation.md).

## Correction and validation

`remote.python_command()` now supplies a short `sudo -n python3 -B -` command
and sends source as bounded SSH standard input. The interpreter consumes it
before execution; arguments preserve their original literal values. Empty/NUL
source, payloads above 1 MiB and simultaneous password/source input reject.
Command auditing remains enabled. Output capture, deadlines and single-submission
failure handling are retained. This is not an interactive stdin protocol.

The PM, journal, audio, keypad, boot, RSB recovery, USB idle/policy, awake guard
and sleep collection readers use this transport. Independent uploaded workers
remain unchanged. No runtime/kernel image, journal size, retention, charger,
network, RTC or sleep policy is changed. PM validators still reject missing
firmware history and incomplete continuity.

Host checks pass 13 runtime and 541 tooling tests (two existing optional skips),
plus compiled C and shell checks. Six new transport tests cover execution by a
real Python interpreter, the complete composed PM helper, exact Unicode/quoted
arguments, payload/EOF/output ordering, transport interruption without replay,
nonzero exits and rejected inputs. Two volume-report tests cover private source
fragments, binary messages, hashes, malformed input and the input size bound.
The real composed PM helper parses `--help` with an audited command below 100
bytes while its source payload exceeds 50 KB. No live suspend was used for these
tests. Host log: `.local/neo111-check.log` after integration.

## Awake hardware verification

Commit `304314f` is integrated into main and pushed. On the same unchanged boot,
the new transport passes these saved read-only tasks:

| Task | Capture beneath `.local/diagnostics/` | Observation |
| --- | --- | --- |
| `device:pm-inspect` | `20261004T074218.136914Z` | Original boot/image, PM29/0, input identity and settings unchanged; battery 100%, charging |
| `device:journal-inspect` | `20261004T074255.958305Z` | Existing policy passes; journald unchanged; remaining journal prefix retained |
| `device:pm-collect` | `20261004T074325.433638Z` | Original failed result is identical after collection with the new transport |

The independently captured sudo audit window contains exactly the three short
Python commands, twelve sudo records and 1,050 sudo message bytes. There are zero
helper-source fragments. The PM inspection command is 30 bytes before sudo's
executable-path expansion; its transmitted source is 104,772 bytes. Source still
travels over SSH and is parsed on the device, so no corresponding network/CPU
or energy reduction is claimed. This directly verifies removal of source-code
logging while retaining command auditing, rather than merely assuming that the
new transport avoids logs.

Private audit: `.local/neo111-stdin-audit.jsonl`; saved offline summary:
`.local/neo111-stdin-audit-summary.json`. Independent Wi-Fi status also passed
after the failed test (`.local/neo111-wifi-status.log`). No RTC alarm, PM entry,
reboot, journal setting or network setting was changed during this verification.

The original failed record remains failed. The fresh boot and prerequisite
sequence below establish a new baseline; the matching cable rehearsal and
actual-sleep readiness remain separate. Longer-term bounded boot-identity and
per-test log preservation should be designed separately; reduced logging cannot
guarantee indefinite retention on an arbitrarily old boot.

## Fresh boot and debug sequence

After fresh owner readiness, one remote reboot established boot
`f2dfd67d-cf9a-4242-b9b7-58c1bc944357` on the same diagnostic.18 image.
The first USB inspection preceded route recovery and failed to connect; the next
read-only inspection succeeded without another reboot or cable intervention.
Both network paths worked. The new boot passed the common firmware/image/PM
validator with PM0/0 and SDIO usage 2.

All six integration groups passed, including the previously accepted AU access-point
country state (`20261004T084919.427784Z`). Ordinary journal rotation preserved
the new boot history and journald identity (`20261004T084943.383796Z`). Awake
power-key ownership/handback passed (`20261004T085006.857520Z`), followed by
RTC delivery/restoration (`20261004T085028.387911Z`, run
`ffa36aa6037b4977b2700602dd7f032b`, 10.247 seconds). No actual sleep occurred.

The seven saved debug tasks were then run sequentially and reviewed before the
next submission. Each passed journal-prefix continuity, independent USB/Wi-Fi
recovery, its applicable input/memory/policy/trace checks and stable SDIO usage 2.
All PM failure counters remain zero. Transient USB collection failures in the
private logs were followed by collection of the original run, never resubmission.

Capture directories below are relative to `.local/diagnostics/`, each with
`cycle-1/result.json`.

| Stage | Capture | Run | PM successes |
| --- | --- | --- | --- |
| Freezer | `20261004T085055.456380Z` | `0a15ed12e43047af889926c145f5935c` | 0 → 1 |
| Devices | `20261004T085156.466955Z` | `e3f6ee19c76d4de5a63fd2c4bd1a7943` | 1 → 2 |
| Late/noirq 1 | `20261004T085318.298282Z` | `9699f01d4b8c4af5ac83e6e567d48bd5` | 2 → 3 |
| Late/noirq 2 | `20261004T085429.478658Z` | `984aa84728814e14b651ffe3e6b2f468` | 3 → 4 |
| Late/noirq 3 | `20261004T085536.036310Z` | `8f00c91977954f67822dfebf3a84b0dc` | 4 → 5 |
| Late/noirq 4 | `20261004T085638.736886Z` | `a685e9a79a77455f957656a27432ab67` | 5 → 6 |
| Late/noirq 5 | `20261004T085743.775407Z` | `fdbff4092e8243eaad6d3cbdfb6e7567` | 6 → 7 |

The saved `check:sdio-ref-history --require-stable` task produced
`.local/neo110-removal-reference-history.json`, SHA-256
`82acdcfd5bb569441f70cc0cd1281bf9742fdc0a464ab9fcb468d0bfe3dcd9f1`.
The final independent PM inspection (`20261004T085905.461268Z/inspection.json`)
passes the common validator. The complete seven-record admission was recomputed
against that snapshot for the future USB-removal scenario, with no PM submission.
Receipt review: `.local/neo110-removal-admission-review.json`.

The retained new-boot journal has 5,278 records, including 54 sudo command
records and **zero inline Python command records**. Sudo contributes 17,019
of 300,049 message bytes in this bounded window. This is not a matched-duration
comparison with the previous boot or an energy/write-amplification measurement.
Capture: `.local/neo111-fresh-boot-journal.jsonl`, SHA-256
`e66b4ba02f5cbc2568d7d375529ca09798676b4e84b5805f677b9cf45e9142e8`;
summary: `.local/neo111-fresh-boot-volume.json`.

The owner confirmed normal display return after the complete fresh sequence.
NEO-111's bounded command-logging correction is complete: source tests, awake
audit verification and the fresh hardware prerequisites pass. The separate
USB-removal awake rehearsal also passed, as recorded in [report 151](151-usb-cable-sleep-diagnostics.md);
actual cable-transition sleep still requires fresh readiness and its own evidence.
The earlier failed boot's result and evidence remain unchanged; this fresh
sequence does not retroactively pass it. Wider boot-identity/per-test retention
across arbitrary old boots remains a separate follow-up.

[journald]: https://github.com/systemd/systemd/blob/v257/man/journald.conf.xml
