# SSH observer ownership during sleep qualification

8 October 2026. NEO-145's first instrumented attempt stops before sleep:
the existing admission guard correctly rejects the independent TCP recorder
service. The integration is corrected and passes awake hardware validation.
The actual-sleep check was pending at this checkpoint. Diagnostic.23/kernel
`6.18.54-gameshellneo22` remains on boot
`cc26703f-d9ef-4d71-8da1-9d766f3efdbe`, PM8/0.

Subsequent [report 208](208-instrumented-rtc-sleep-and-recorder-limits.md) records
the attended RTC pass at PM9/0 and separate capture failures. Its continuation
supersedes the unused receipt recorded at the end of this report.

## Original rejection

The owner authorized one attended connected-USB RTC sleep with the new
[two-ended recorder](206-two-ended-ssh-tcp-metadata.md). The saved command was:

```sh
task device:ssh-trace-sleep \
  QUALIFICATION=.local/diagnostics/20261008T010429.034673Z/qualification-next.json \
  REHEARSAL=e1afea155b864a79b04bb133496e4e26 ATTENDED=1
```

Capture `.local/diagnostics/20261008T041647.229807Z/` preserves original sleep
attempt `cd655bd026bf48138a8cbaf8bf995907`. Its error is
`Another diagnostic is running; stop before the sleep experiment`.
The recorder had started as `gameshellneo-tcp-metadata.service`, outside the
sleep diagnostic's permitted active-service set. Awake recording had not tested
this interaction; this was a gap in the recorder integration tests.

The result contains no admitted qualification, successor claim, warning,
entry intent, entry clock or return. All policy, control, RTC and console-owner
retention flags are false. It is a rejected diagnostic attempt, not a failed
kernel sleep or a new example of the historical SSH fault. Both recorders
stop and their originals are collected. The original offline metadata report
passes with two matching greeting flows, while the operation remains failed.
No second sleep is submitted automatically.

The subsequent PM inspection at `20261008T041730.495170Z/inspection.json`
passes health and continuation validation at unchanged PM8/0. The parent
continuation is still unused. Failed attempt `result.json` SHA-256:
`3bd12fd97fba6eb21af9857e82d2eaa48dc0397c77412e3078eaff91efa5bf04`.

## Corrected ownership

`tcp_supervisor.py` owns the passive recorder and the original inhibited
diagnostic command inside `gameshellneo-sleep-test.service`. This is a real
shared lifecycle, not a renamed independent diagnostic or an admission exception.
The existing device-side `sleep_rtc.py`, its source-qualified dependencies,
PM admission, predecessor ledger, warnings, power ownership and cleanup are
unchanged. The host command still carries the original inhibitor, arguments,
single submission, ExecStopPost recovery and 180-second runtime limit.

The supervisor checks both helper digests and rejects stale output files. It
starts exactly one recorder and requires its matching run, source, PID,
interface, address and ready marker within five seconds before starting the
original command. Both processes must belong to the existing sleep service's
cgroup. Failure before readiness cannot launch the PM command. No process is
detached into a separate service for this path.

After the command exits, the recorder remains available through host result
collection and independent route checks. The host stops it and collects its
original output and supervisor outcome. Recorder deadlines and the enclosing
service deadline bound controller loss. Child cleanup attempts are independent;
a cleanup failure cannot suppress the primary exception or skip the other
child. Failed command, recorder or cleanup outcomes cannot pass the supervisor
report. The original PM result remains separate from metadata success.

The host's optional observer path is restricted to connected-USB actual sleep.
Ordinary sleep commands are unchanged. Recollection does not launch, submit PM
or replace original bytes. Standalone awake recording retains its own bounded
service; the new smoke task exercises the integrated ownership path:

```sh
task device:ssh-trace-smoke
task report:ssh-trace CAPTURE=.local/diagnostics/<capture>
```

The smoke child only reads cgroup and active-unit state. It does not run the
sleep helper, claim its continuation, program an alarm, change display state
or enter PM. Three USB/Wi-Fi probe pairs exercise the observation window while
the same supervisor owns the recorder. This validates ownership and collection;
it does not substitute for an actual sleep test.

## Validation

The focused metadata/supervisor suite passes 33 tests. It covers readiness and
source rejection before command launch, foreign cgroups, stale artifacts,
symlink refusal, single-command execution, command failure/timeout, independent
cleanup preserving the original error, lifecycle report rejection, and retention
of the unchanged inhibited command and recovery properties. The full host suite
passes 13 runtime and 712 tool tests, with one existing optional skip, both
compiled checks, Bash syntax and ShellCheck.

Final live awake smoke:
`.local/diagnostics/20261008T042417.839657Z/`, recorder identity
`8bd07a2ced5b49c4926301c2e251722a`. All six SSH probes pass, with four unique
USB handshake/greeting matches across both endpoints and host tunnel spans.
The child and recorder share the sleep-test cgroup, and the active service set
contains only USB, ready, battery and the sleep-test service. Both children exit
zero, with no cleanup errors. PM remains 8/0 on the same boot.
The final `systemctl show` check confirms both `gameshellneo-sleep-test` and
`gameshellneo-tcp-metadata` are inactive and no longer loaded.

| Recorder | Saved packets | Reads | Metadata bytes | Reported drops | Interface index |
| --- | ---: | ---: | ---: | --- | --- |
| Mac | 415 | 415 | 135,273 | 0 socket/interface | 27 → 27 |
| GameShell | 262 | 264 | 87,127 | 0 socket; interface unavailable | 4 → 4 |

Different capture windows account for unrelated setup/collection traffic;
packet totals are not a packet-loss estimate. Both recorders stop normally with
zero rejected headers. Their overhead still prevents uninstrumented latency or
energy claims. The historical post-return SSH cause remains unresolved.

Recorder source SHA-256:
`3dca63713efcb3925572357e37351fc9ec333fe1930d1e44d7c5c5fdfc15cac6`.
Supervisor source SHA-256:
`65e095df82519dfb607b2a09b1aabbab085af67cf585a02d7770bbdc116c5d16`.

| Artifact beneath the final smoke capture | SHA-256 |
| --- | --- |
| `tcp-run.json` | `a9bdfb65fe7dfc15e8368e71c52e086896fb763dc6e54c141579ff1cf0d4ba51` |
| `host-timing.jsonl` | `cffe66e44b98b073d56ef3487b1752d19a762c1828f802f98c7a8392707bd7d3` |
| `tcp-mac/result.json` | `dfc2a6e041bfb896a69c31db34f3873e4ddd506cac907deed3cf3a78d0b4b2af` |
| `tcp-mac/packets.jsonl` | `bacbef1485ca2cdb7d0e3bbf563cf2d182b040c2fb2c94621ef553c3186583b9` |
| `tcp-device/result.json` | `0943b1a4f0c7badaadb195b8f810929a2ca3df0b7539d0373e5c5bd3ed4a5a32` |
| `tcp-device/packets.jsonl` | `995c501dbd528c508432d0ca0c447b9ecc842e6a1f4c1dfda63a3510402e331a` |
| `tcp-device/supervisor.json` | `d9af3a20737d14d57e4f665d96c21345ecc427c2e4ace977849fc0d465588f3b` |
| `tcp-device/smoke.json` | `88fb4e1f85f8097346f9def41ec55f08fd1790778440c9a071e13ce92dcee80d` |
| `tcp-report.json` | `5941972ef38ecfbed7882de17001edc79b1dbf4d107c54528224c8fecbac0d60` |

Final inspection `20261008T042502.420224Z/inspection.json` passes full PM
health and unchanged-source continuation validation. The current receipt is
still report 205's `20261008T010429.034673Z/qualification-next.json`, with
original rehearsal `e1afea155b864a79b04bb133496e4e26`. Fresh watching/listening
readiness has been requested before another actual sleep. No image rebuild,
card swap, driver, timeout, network or charging-policy change is involved.

Final inspection SHA-256:
`c423e7b86224c3b9e08525348433815f6629f248a04acc0b842e73a95a3ff8b3`.
Private `.local/neo145-final-admission.json` SHA-256:
`956ddc2a87ecb7bd2d66d5613f7f64afcc472d62e3ae77fb3f2af0ee1cb2c1cc`.
