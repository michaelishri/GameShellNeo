# Diagnostic.24 SSH stalls: awake investigation and observer integration

9 October 2026, Pacific/Auckland; artifact timestamps are UTC. NEO-160 completes
this bounded investigation and host-tool improvement. NEO-154's underlying
intermittent SSH cause remains open. The owner was away: no sleep, screen
blanking, reboot, cable action, driver change or network-policy change ran.

Two newer diagnostic.24 failures narrow the evidence: each forwarded channel
accepted the client's 24-byte identification write, but no bytes were returned
to the client's reads before SSH setup timed out. They lack Mac socket
snapshots. The existing opt-in observer now works in ordinary PM/RTC tasks as
well as dedicated SSH tests, so a future independently planned run can retain
that missing evidence without requiring a special packet-capture workflow.

## Original failures and what their timestamps establish

The two original late/noirq results in
[report 219](219-diagnostic24-pm-qualification.md) remain successful PM recovery
results with retained failed collection attempts. Their capture paths beneath
`.local/diagnostics/` are `20261008T105516.806486Z/cycle-1` and
`20261008T110455.946275Z/cycle-1`. Both are on diagnostic.24/kernel
`6.18.54-gameshellneo23`, boot `44b698ad-7fef-46d4-9e0f-71153f6f81e9`.

| Original observation | Initial late/noirq | Fourth late/noirq repeat |
| --- | ---: | ---: |
| Failed inner SSH span | 49 | 49 |
| Inner setup duration | 10.028 seconds | 10.021 seconds |
| Forwarding send calls / accepted bytes | 1 / 24 | 1 / 24 |
| Returned receive bytes | 0 | 0 |
| Receive calls / timeouts at observation | 100 / 100 | 100 / 99 |
| Greeting, initial key exchange, authentication | all false | all false |
| Channel active / closed / received EOF | true / false / false | true / false / false |

The caller records `No existing session`; its background transport later logs
a banner timeout. [Report 216](216-ssh-greeting-source-audit.md) explains that
caller/background race from the pinned source. These counters now exclude an
incomplete first API write and received-but-unparsed identification for these
two snapshots. They do not prove that the 24 bytes reached the GameShell TCP
stack, that the server emitted a reply, or where a reply was delayed. Counters
are sequential observations of a live thread, not atomic packet measurements.

Unlike the RTC collector, these debug captures have no `device_clock` events.
Use their already saved **preflight** snapshot to form a wider clock bracket:
take the host start of the first `command.channel` and end of the first
`command.response`, enclosing the command that generated `before.json`.
Subtract that snapshot's `monotonic_seconds` from both host MONOTONIC endpoints.
For a later host event, subtract the resulting offset bounds and the device's
`power_key.resume_seconds`. The latter is sampled directly by `after_entry()`
immediately after the PM write returns. All values must belong to this boot;
this method assumes continuous clocks through the debug stage and negligible
relative drift over the short capture. These runs did not enter real sleep.

| Relative to device PM return | Initial late/noirq | Fourth repeat |
| --- | ---: | ---: |
| Preflight clock-bracket width | 4.133 seconds | 4.291 seconds |
| Failed collection starts | −4.426…−0.293 seconds | −4.871…−0.579 seconds |
| Forwarding open starts | −4.091…+0.042 seconds | −4.441…−0.150 seconds |
| Inner SSH setup starts | +4.032…+8.165 seconds | +2.847…+7.139 seconds |
| Inner SSH setup fails | +14.060…+18.194 seconds | +12.869…+17.160 seconds |

Thus the **inner negotiation starts after PM return**, while the enclosing
collection already started before return. The second forwarding open also
starts before return; the first overlaps the bracket uncertainty. Do not call
either a proven fresh TCP request initiated after recovery, or infer precise
network-ready time. This distinction matters when considering a connection
that began while USB was unavailable. It does not identify a faulty layer.

## Retained journal review

Two read-only boot-bound queries save 930 and 737 journal records, including
33 SSH-process records in each window. The windows are 10:55:10–10:57:00 and
11:04:50–11:06:40 UTC on 8 October. The saved task is reusable:

```sh
umask 077
task device:exec ROUTE=usb -- sudo -n journalctl \
  --boot=44b698ad7fef46d49e0f71153f6f81e9 \
  --since='2026-10-08 10:55:10 UTC' --until='2026-10-08 10:57:00 UTC' \
  -o json --no-pager -n 5000 > .local/neo160-platform-first-journal-v2.jsonl
```

The initial queries used a rejected boot argument; their error artifacts remain
separate. The explicit compact boot-ID queries succeed. All returned records
match the expected boot. Bounded searches find no `MaxStartups`, penalty,
login-grace/timeout-before-authentication, fatal, fork-failure or allocation
failure messages. Later preauthentication closures are present, but there is
no independently bound Mac endpoint for either failed setup. Assigning one
of those closures to a host request by timing alone would overstate the data.
Absence of a log match is not proof that an admission or worker branch never ran.

Private assessment `.local/neo160-failure-assessment.json` preserves source
hashes, first byte/state observations, clock bounds and journal categories.
It does not rewrite the original results, close NEO-154 or justify a timeout,
retry, DNS, admission or driver-policy change.

## Existing observer available to ordinary PM workflows

`host_timing.timed_capture()` now enters
`socket_observation.workflow_capture()` before a PM cycle's existing work.
The adapter honors `SOCKET_STATE=1`; default-off creates no socket artifacts
or extra Mac commands. It reuses an outer observer for the same capture, as
used by the dedicated SSH trace workflow, and rejects an observer belonging
to another capture before running the workflow. An invalid flag also fails
before work begins.

Each batch cycle owns its own bounded observer and evidence directory; four
cycles do not share the 32-setup limit. An inherited observer is finalized
only by its outer owner. The awake `device:ssh-timing` task uses the same adapter.
Existing before-forwarding and after-SSH snapshot ordering, first-error/byte
preservation, private files, watchdogs and unchanged ten-second connection
timeouts remain intact. Nothing is inserted between channel opening and the
inner greeting exchange. There is no new device-side PM code or image change.

For the next **separately admitted and attended** PM/RTC test, append
`SOCKET_STATE=1` to the usual task command. A batch's socket report runs against
each `cycle-N` directory. This flag does not enable packet capture or waive
readiness, current-state or original-result checks. Instrumented totals include
observer overhead and are not ordinary connection-latency measurements.

## Validation without sleeping the device

Five new regressions cover ordinary-workflow opt-in and original error
preservation, default-off behavior, outer ownership, independent per-cycle
limits and invalid/foreign capture rejection. All 17 socket-observer tests pass.
The full `task check` passes **16 runtime tests and 804 tooling tests** (one
optional skip), both compiled checks, Bash syntax and ShellCheck.

The first full run encountered five existing local socket fixture failures:
the sandbox denied `socketpair()` send operations with `EPERM`. An isolated
socketpair probe confirmed that restriction. Rerunning unchanged checks with
local socket access permitted passes; no test acceptance or timeout changed.
Both check logs remain private.

The owner-authorized awake check uses the shared adapter:

```sh
task device:ssh-timing CYCLES=3 SOCKET_STATE=1
task report:ssh-socket-state CAPTURE=.local/diagnostics/20261008T120551.541399Z
task device:ssh-timing-report CAPTURE=.local/diagnostics/20261008T120551.541399Z
```

All six USB/Wi-Fi samples pass on the same boot at PM12/0. Including initial
discovery, seven inner setups authenticate with no recorded phase errors.
All seven socket records validate as unique worker candidates; they are not
promoted to independently confirmed failed-flow identities. This healthy
workload qualifies the awake adapter path, not the intermittent fault or the
modified wrapper through actual suspend. Future attended tests retain that gate.

Preflight health at `20261008T120516.780673Z` and final read-only health at
`20261008T120812.683399Z` both pass full validation and the unused continuation.
The GameShell stays on the original boot, PM12/0, all four WFI s2idle counts 5,
brightness 1 and backlight power 0. No new sleep claim is consumed. The next
physical work remains battery/cable qualification with the owner present;
the existing connected continuation remains the one recorded in report 220.

## Evidence hashes

| Artifact | SHA-256 |
| --- | --- |
| First journal window | `44101235692ba0461f4a88ab397085d425a89f7f78c9acfd82deafa5a43fd648` |
| Fourth-repeat journal window | `6e10caa5cc676c87a2072e1d622e20500c7faf7e13d05f08fa1d2de119308711` |
| Failure assessment | `742880b0f9264a2a1d1c5e3875036a00ad7d5982c43434d849231498e5087fe6` |
| Awake `awake-ssh.json` | `58635f40e4f7d938cc7c4fe19dc6a3e45ee587fb36fb4e248124667d7103ed9f` |
| Awake `host-timing.jsonl` | `b2ef96cd983dded16df64e36dfc03f40cd44caf7d3224de7a05450ea133fe03f` |
| Awake `socket-observations/index.json` | `a21ab39fc1ede7958947073a4557cc04ea9caa259e6f597eaf6f3f15f66bbb32` |
| Passing full check log | `c1435c4c68e73e45bc78df4191b15b77222fb2f3c8333097d3557baf7edc8be7` |

Journal files are `.local/neo160-platform-{first,repeat4}-journal-v2.jsonl`;
check logs are `.local/neo160-check{,-unsandboxed}.log`. Original failure-result
and timing hashes remain in report 219 and the derived assessment above.
