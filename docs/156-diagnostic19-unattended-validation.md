# Diagnostic.19 unattended awake qualification

5 October 2026, Pacific/Auckland; capture timestamps below are UTC. NEO-113.

Diagnostic.19 passed the complete unattended awake qualification in 11 minutes
1 second, followed by a passing passive USB trace. The owner authorized awake
testing and source investigation while away. This session used the
already-installed image and the saved
`task device:qualify-awake ACTIVE_COUNTRY=AU` sequence. It did not require a
card swap, physical controls or display observations. Installation and the
earlier awake startup gates are recorded in
[report 155](155-diagnostic19-installation-and-awake-checks.md).

## A preflight correction, with the rejected run preserved

The first attempt stopped at `guard-before`, before Wi-Fi, load or other test
steps ran. The captured boot was
`0751ae33-2930-4d73-a9c4-80b1f9660258`, there were no active diagnostic services,
and the only reported recovery record was
`/run/gameshellneo-pm-experiment.lock`.

The RTC/key/PM helpers deliberately retain that inode after releasing their
`flock`. Its existence does not mean an experiment still owns it. The older
awake guard treated every `/run/gameshellneo-*` path as unresolved recovery,
so the completed startup RTC check prevented subsequent qualification.

The corrected guard probes only that exact lock path with a nonblocking
exclusive `flock`, closes the descriptor immediately and never removes the
file. A held lock, open/locking error, symlink or nonregular file still rejects
the run. Unknown paths and actual recovery records remain blockers. This is a
point-in-time preflight check, not exclusion throughout the entire sequence;
concurrent diagnostics are still prohibited.

Two new regressions execute the device-side function with real Linux file
locks, covering an absent/unlocked/held/released lock, stable inode identity,
ordinary recovery state, unknown lock names, symlinks, directories and FIFOs.
The targeted awake suite passes all 20 tests. `task check` passes 13 runtime
and 550 tooling tests (one existing optional user-systemd skip), compiled C
checks, Bash syntax and ShellCheck.

The original failed capture remains unchanged at
`.local/diagnostics/awake-20261004T105812.774102Z/`. The fresh invocation after
the correction has its own evidence directory:
`.local/diagnostics/awake-20261004T110025.910916Z/`. It rechecks the complete
sequence rather than accepting results from the failed invocation.

## Hardware results

All 15 steps in the fresh run passed on the original boot. It started at
11:00:25.920 UTC and completed at 11:11:26.931 UTC.

| Check | Observed result |
| --- | --- |
| Wi-Fi recovery | Four software reconnections, unavailable-network and connected windows of 120.131 and 120.151 seconds, and seven independent Wi-Fi SSH proofs passed |
| Firmware | Original identity retained; zero recorded firmware crashes, SDIO removals or PM-reference underflows |
| Storage | 134,217,728 random bytes written and synchronized, then hash-verified using direct reads; temporary files removed |
| CPU/memory load | Four CPU workers and one verified 256 MiB memory worker ran for five minutes; stress-ng exited successfully |
| Temperature and recovery | Maximum sampled temperature 61.560°C, below the 80°C cutoff; frequency returned from 1,008 MHz under load to 120 MHz in recovery; no kernel taint |
| Battery policy | Nine installed-policy simulations passed without shutting down; software battery estimate remained 100% |
| Integration | All six groups passed, including the previously accepted AU announcement from the AP |
| Final state | Both SSH routes, original keypad identity, closed audio PCMs, amplifiers off and unchanged mixer/CPU/display/charging/USB policies |
| PM and ownership | All success/failure counters remained zero, original sleep masks retained, no active diagnostic or unresolved recovery record |

The fresh progress-record SHA-256 is
`19428234058dd4b53bf147ed89f0abcdfc5aa81039bb74ff8ef8321c12e3b8c4`.
Its generated `report.md` SHA-256 is
`553aced255b6e8a0e2ece615136990b58b1e477593132819d29d06b3d7bac418`.
Per-step captures, raw output and the exact controller source fingerprints are
retained beneath the qualification directory above.

After completion, `task device:usb-trace-sample` passed its ten-second awake
capture with no lost trace events, restored logging/tracing and unchanged PM
state. Both SSH routes were independently verified afterward. This qualifies
the recorder on this image, not USB suspend/resume or notification lifetime.

| USB trace identity | Value |
| --- | --- |
| Capture | `.local/diagnostics/20261004T111146.538368Z/` |
| Run ID | `137142de1b024549904a8c270793c89f` |
| `result.json` SHA-256 | `8455fa41b697f84d59ab8d2918012ac2039eb708d809a5eba44d381347a9811b` |

No diagnostic remains running after these bounded checks. The GameShell remains
on USB, on the same boot, with the normal diagnostic power policy.

## Scope

The installed kernel remains `6.18.54-gameshellneo19`. Ordinary automatic and
button-triggered sleep remain disabled. These checks do not establish energy
savings, battery capacity or charging accuracy, physical input/display/audio
quality, or reliable sleep/wake. The USB sleep-session fix still needs the
attended sequence in report 155, including original-result collection before
any cable recovery. NEO-112 remains open.

The separate source-only investigation of a deferred power-supply notification
race is recorded in [report 157](157-power-supply-unregister-lifetime.md). It
does not change this image or report a reproduced GameShell teardown fault.
