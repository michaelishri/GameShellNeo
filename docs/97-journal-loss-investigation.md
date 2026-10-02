# Journal displacement: cause, recovery and fix (NEO-77)

2 October 2026. **The earlier journal loss has a demonstrated cause:** the
enabled `logrotate.timer` invoked an Armbian service that called its RAM-log
helper directly. Masking `armbian-ramlog.service` did not prevent that call.
The helper moved the persistent journals to `/var/log.hdd/journal`, restarted
journald and requested volatile logging. The original early logs were
recoverable at the displaced location and confirm this sequence.

The two-file configuration fix is installed on the running diagnostic.13 and
in the runtime overlay for future images. A deliberate ordinary log rotation
passed without restarting journald, losing kernel history or modifying the
displaced journal inventory. This ticket also assesses first real sleep in
[report 98](98-shallow-sleep-readiness.md); no PM experiment was run here.

## Recovered sequence

The affected boot is `eafb7717-0cbc-46e8-9cc4-7666ab7ec086`. The complete early
kernel history, including its expected single radio firmware identity, was
found in `/var/log.hdd/journal`. Read-only `journalctl --verify` passed for all
three displaced journal files. They contain the affected boot and the
preceding diagnostic.13 boot, `b5e3abbd-775f-4004-9100-0c7a20dfb59b`.
Later entries left only in the earlier boot's volatile store cannot be
recovered after its power cycle except where the prior private captures saved
them. Recovering early logs is not a claim that the entire boot was recovered.

| Uptime (s) | Recovered event |
| --- | --- |
| 6.854 | Original journald PID 114 starts. |
| 7.701 | Early runtime entries flush successfully to persistent storage. |
| 18.936 | A backwards wall-clock correction causes journal rotation. This is distinct from the later relocation. |
| 80.378 | systemd starts `logrotate.service`. |
| 80.602 | `armbian-ramlog` reports that `/var/log.hdd` does not exist. |
| 80.619–80.773 | The helper continues; rsync creates that directory and copies ordinary logs. |
| 81.038 | Original journald stops. |
| about 81.2 | Replacement journald PID 384 starts, then receives the request to relinquish persistent storage. |

The saved timer state reports its last trigger at 05:45:02 UTC, matching the
recovered service start. Its installed configuration is daily with up to an
hour of randomized delay and `Persistent=true`. The short time after boot was
not a fixed 81-second GameShell timer. After the subsequent physical power
cycle, the next daily trigger was still in the future, explaining why one
passing fresh-boot session could not establish that the issue was fixed.

The original current-boot preflight was correct to reject missing firmware
evidence; the missing entry was not proof of a firmware crash. The recovered
logs establish a maintenance-policy defect, not owner maintenance or a PM
test failure. [Original refused baseline and subsequent qualification](96-diagnostic13-attended-validation.md).

## Root cause in the inherited configuration

The installed `/etc/systemd/system/logrotate.service` matches the pinned
Armbian service. Its pre/post commands call `armbian-ramlog write` and
`armbian-ramlog postrotate` outside the masked RAM-log unit. Meanwhile,
`/etc/default/armbian-ramlog` still had `ENABLED=true`. Both `/var/log` and
`/var/log.hdd` were on the root ext4 filesystem; the RAM-log mount setup had
never run. [Pinned service][rotation], [pinned helper][ramlog].

The helper's `write` path assumes its own storage arrangement. Its `isSafe()`
function places `exit 1` in a subshell and the caller does not check its result,
so a missing backing directory does not stop the outer script. The recovered
error followed by rsync activity demonstrates that continuation. The later
stop/move/start and relinquish operations account for the observed split
between hidden old journals and new volatile entries. GameShellNeo does not
need this helper when journald owns persistent storage. [Pinned helper][ramlog].

Systemd documents relinquish as switching future writes from `/var/log/journal`
to `/run/log/journal`; it does not mean deleting all prior entries. Consequently
the investigation inspected both normal stores and the Armbian backing store
before changing configuration. [Official journalctl reference][journalctl].

## Fix and scope

- [RAM-log configuration](../runtime/etc/default/armbian-ramlog) explicitly sets
  `ENABLED=false`. Direct calls from rotation, cron or other inherited entry
  points exit before their storage operations.
- [Log-rotation drop-in](../runtime/etc/systemd/system/logrotate.service.d/50-gameshellneo.conf)
  clears the inherited pre/post helper commands. The ordinary logrotate
  command, timer and its text-log retention policy remain active.
- [Offline verification](../tools/verify-rootfs.py) requires both installed
  policy files to match the runtime sources. Existing runtime installation
  copies these files into subsequent images.

This corrects which component owns log storage. It does not increase journal
limits, periodically force a flush, restart journald as a workaround, or
silently merge old files into the current store. Journald retains its existing
32 MiB persistent / 8 MiB runtime / seven-day limits. The inherited helper's
bad missing-directory guard remains a vendor-code hazard if RAM logging is
ever reintroduced; the disabled component is not claimed repaired.

The running device still identifies as `0.1.0-diagnostic.13`, kernel
`6.18.54-gameshellneo13`, now with this documented runtime policy correction.
No kernel, firmware, bootloader or charging setting changed. **No replacement
image was built or flashed:** retained image artifacts still contain their
original runtime, so reflashing one requires reapplying this fix or using a
subsequent verified build.

## Repeatable tasks and safeguards

```sh
task device:journal-inspect
task device:journal-policy
task device:journal-rotation
```

The inspector is read-only. It records unit properties, configuration,
normal/runtime/displaced journal inventories, journald's open journal files,
bounded current kernel history and logging-service events. Its successful
exit means collection succeeded, not that persistence is healthy. Evidence
is private under `.local/diagnostics/` and may contain device/network details.

The policy task saves the original two files in `before.json` plus source
content/hash evidence. It verifies the kernel and same boot, pauses the
rotation timer, refuses a running rotation, atomically disables the direct
helper before installing the drop-in, reloads systemd unit definitions, and
restores the timer's prior active state. It neither restarts journald nor
repairs an already displaced store. An interrupted task requires inspection
of its evidence and timer state before retrying; a successful application
must verify effective policy, an open persistent journal and continuity.

The rotation task first requires the exact policy and an idle loaded rotation
service, then runs normal `logrotate.service` without `--force`. It captures
the result even if the start command fails, never retries uncertain
submission, and requires unchanged boot/journald process, retained kernel
history and unchanged displaced inventory. The host PM lock serializes it
with saved PM diagnostics. [Controller](../tools/check-journal.py),
[collector and validators](../tools/journal_policy.py).

## Validation and private evidence

| Evidence | Private path under `.local/` |
| --- | --- |
| Current units/configuration and source candidates | `neo77-journal-initial.log` |
| Timer, enabled flag, alternate-store inventory | `neo77-logrotate-evidence.log` |
| Recovered early boot and exact maintenance sequence | `neo77-recovered-journal.log` |
| Three displaced journal integrity passes | `neo77-journal-verify.log` |
| Archived original journal files | `neo77-displaced-journals.tar.gz` |
| Initial saved inspector | `diagnostics/20261002T093122.688598Z/` |
| Two-file application and before/after evidence | `diagnostics/20261002T093206.351103Z/` |
| Refused rotation preflight, no rotation submitted | `diagnostics/20261002T093306.637264Z/` |
| Passing explicit rotation and final policy/continuity | `diagnostics/20261002T093420.243054Z/` |
| Both-route boot verification after policy installation | `diagnostics/20261002T093343.026671Z/` |
| Read-only PM state after policy installation | `diagnostics/20261002T093344.201307Z/` |
| Six passing integration groups after rotation | `diagnostics/20261002T093645.261498Z/` |

The compressed archive's SHA-256 is
`568f8de46c4ee6526677765a4746aad5e9c2f792aad1abac9b78af7105a24a63`;
all three member sizes and archive integrity were checked on the host. No
displaced journal was deleted or written back into the live journal tree.

Initial application completed, but its host validator rejected systemd's
omission of empty `ExecStartPre`/`ExecStartPost` arrays. A subsequent preflight
showed that `--all` alone does not make this systemd emit those arrays. The
corrected validator accepts absent empty arrays only on a loaded unit with
the expected files and retained logrotate command. A regression covers that
representation; the failed captures are retained. No failed PM operation or
blind repeat of a log-rotation command was involved.

The passing rotation kept journald PID 119 and its original start timestamp,
preserved the current kernel history, and left the displaced inventory
unchanged. Same-boot checks confirmed both SSH routes and PM counters still
at seven successes / zero failures. Host regression tests include the actual
pinned helper configuration guards with enabled negative controls, loss/
restart/displacement rejection, and persistent-file ownership checks.
Full `task check` results and final integration evidence are retained in
`neo77-host-check-final.log` and `neo77-final-integration.log`.
The final host run passed 13 runtime and 322 tool tests (one existing optional
test skipped), compiled C checks and shell lint; nine tool tests cover this
journal policy. All six final device integration groups passed.
The rotation validator also requires a new execution timestamp and a finished
service: a condition-skipped start, such as on battery, earns no execution
credit. It passed against the saved live rotation evidence.

This establishes the cause and validates the targeted correction on the
running system. Persistence through a new image's boot and future scheduled
rotations remains part of that image's qualification; the earlier workaround
of taking a clean boot is no longer treated as a resolution.

[rotation]: https://github.com/armbian/build/blob/488dc40c493ba7633e379dbcf5606d7d58ee4575/packages/bsp/common/etc/systemd/system/logrotate.service
[ramlog]: https://github.com/armbian/build/blob/488dc40c493ba7633e379dbcf5606d7d58ee4575/packages/bsp/common/usr/lib/armbian/armbian-ramlog
[journalctl]: https://www.freedesktop.org/software/systemd/man/255/journalctl.html
