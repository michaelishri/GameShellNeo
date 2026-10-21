# SSH collection timing and awake session startup

7 October 2026, UTC capture timestamps. NEO-135 implements host instrumentation
and validates it without another sleep, reboot, cable action or display change.
Diagnostic.22 remains installed on the same boot as [report 196](196-diagnostic22-connected-sleep-repeatability.md),
with PM success/fail 13/0 throughout the awake probes.

## Findings

The historical channel and SSH-banner errors cannot be assigned to post-wake
recovery: their logs lack attempt timestamps. Collection begins while sleep may
still be active, retries after five seconds, and the device deliberately observes
recovery for 30 seconds after keypad readiness before completing the result.
The existing 20-second gap between accepted batch cycles is also an awake
observation interval. None of these intervals measures ordinary wake latency.

Three new awake probes each pass three fresh USB/Wi-Fi pairs, with a separate
initial USB session to discover the current Wi-Fi address. All 18 measured route
samples preserve boot `7884d229-2309-47df-9af0-b6fe500ad9ac` and PM13/0. The three
discovery sessions also succeed. There are no recorded transport failures.

Each initial discovery session waits about 4.7 seconds in `open_session`, before
the status command is sent. Subsequent USB channel openings are around 0.2
seconds. The third probe ran without the full host regression suite alongside
it, and the initial delay remained. This establishes an awake session-opening
delay independently of a new PM transition; it does not identify the cause of
the historical connection failures.

| Capture suffix | First USB channel opening | Subsequent USB channels | Complete Wi-Fi session range |
| --- | ---: | ---: | ---: |
| `20261007T085331.071810Z` | 4.677 s | 0.205–0.219 s | 1.986–2.655 s |
| `20261007T085532.200057Z` | 4.690 s | 0.214–0.258 s | 2.133–3.583 s |
| `20261007T085647.408995Z` | 4.792 s | 0.222–0.247 s | 1.707–2.441 s |

Complete session spans include setup, one command and cleanup; they are not
packet round-trip measurements. USB groups in the offline summary include the
extra discovery session. The first capture's Mac TCP connections take 5–7 ms,
Mac SSH connection/authentication 309–526 ms, and USB tunnel openings 7–15 ms.
The large initial delay is therefore in a later stage of that observed path.

## Session-startup lead

Read-only journal inspection shows the device's per-user systemd manager being
started and stopped around these short sessions. Its logged startups take
3.882–3.924 seconds; finished instances report about 4.3 CPU seconds consumed.
The only entries in a separate `systemd-analyze --user blame` capture are
`dbus.socket` at 171 ms and `ssh-agent.socket` at 169 ms. These entries do not
account for the manager's earlier initialization work.

A separate `systemctl --user show` capture gives these monotonic microseconds:

| Property | Value |
| --- | ---: |
| UserspaceTimestampMonotonic | 12816247818 |
| GeneratorsStartTimestampMonotonic | 12816304718 |
| GeneratorsFinishTimestampMonotonic | 12816424577 |
| UnitsLoadStartTimestampMonotonic | 12816424712 |
| UnitsLoadFinishTimestampMonotonic | 12819850560 |
| FinishTimestampMonotonic | 12820173274 |

That is **3.426 seconds loading units**, 0.120 seconds in generators and 3.925
seconds from userspace start to finish. User-manager startup is a plausible
contributor to the awake session delay. The exact SSH-to-manager dependency and
the expensive operation inside unit loading still need profiling. The startup
observations alone do not establish a kernel/USB defect or an energy saving.
Effective SSH settings include `UsePAM yes`, `UseDNS no` and GSSAPI authentication
disabled. No SSH, PAM, linger or user-service settings were changed.

## Reproducible tooling

```sh
task device:ssh-timing CYCLES=3
task device:ssh-timing-report CAPTURE=.local/diagnostics/<capture>
task device:sleep-collect RUN=65cc6d057ee8423bb2eb14e6dd3cec3e ROUTE=usb
task device:exec ROUTE=usb -- systemd-analyze --user blame
task device:exec ROUTE=usb -- systemctl --user show \
  -p UserspaceTimestampMonotonic -p GeneratorsStartTimestampMonotonic \
  -p GeneratorsFinishTimestampMonotonic -p UnitsLoadStartTimestampMonotonic \
  -p UnitsLoadFinishTimestampMonotonic -p FinishTimestampMonotonic
```

`tools/host_timing.py` records nested begin/end spans, UTC correlation labels,
host monotonic nanoseconds, fixed failure categories and bounded numeric error
codes. Stages distinguish Mac TCP/SSH, tunnel, device SSH, command channel,
request, response, single PM submission, collection waits/attempts and final
route proofs. A `started` result is distinguished from a completed result.
Mac/device SSH spans include TCP setup where the existing direct connection
path lets Paramiko create the socket. Route and parent spans are inclusive;
adding nested durations would double-count time.

The sidecar is exclusively created with mode 0600, refuses symlinks/overwrites,
and is capped at 8192 events. It contains no commands, arguments, SSH endpoints,
passwords, key material, source payloads, command output or exception messages.
Boot IDs and validated device BOOTTIME samples are retained for clock alignment.
Existing other evidence files remain private and may contain network details.
A recording I/O failure marks timing incomplete and lets original collection
continue, including when stderr is on the same full disk. An offline summary
rejects truncated or incorrectly nested traces.

Sleep collection reads the original result and a device clock in one read-only
command, records the clock separately, and returns the original result content.
The enclosing `clock.sample` begin/end bounds contain that remote sample. Host
and device clocks have different origins: never subtract their raw values. For
a matching boot and stable awake host clock, the host bracket minus device
BOOTTIME supplies an offset interval to compare nearby saved entry/return times;
allow for elapsed-time drift and the width of the entire command bracket. UTC
is only a correlation label and may be adjusted. These brackets are not exact
network-ready timestamps, electrical edge timings or resume-latency proof.

PM/sleep capture integration changes only host files. Device helper source
hashes, warning behavior, five-second collection spacing, SSH timeouts, host-key
verification and single-submission semantics remain unchanged. The current
channel timeouts are per operation, and the outer collection deadline is checked
between attempts; it is not an absolute end-to-end bound on an in-flight attempt.
The shared command helper now also closes an already-open channel if initial
channel configuration fails.

## Evidence and validation

All paths below are private under `.local/diagnostics/`. The three awake captures
above each contain `awake-ssh.json` and `host-timing.jsonl`. Timing SHA-256 values:

| Capture | Timing SHA-256 |
| --- | --- |
| `20261007T085331.071810Z` | `32b5971e9fab8674716724b1fababd027ab6a0aa75c9f1d6d30db5f7bbbc0854` |
| `20261007T085532.200057Z` | `bf9cfc6cb45cd120f1eb81471e0e2fec20cbffb05363a46a29e3458d3c716b3b` |
| `20261007T085647.408995Z` | `ef79608abdae27b5b37b85f617b39a4b21c535b53e5d849da8ea0edcdd445b34` |

The explicit read-only collection is `20261007T085557.943230Z`. Its original
device-result digest matches report 196 cycle 4, and the device helper source
hashes still match. No PM was submitted. Its timing SHA-256 is
`3f5441ee441848100d0f9781f20c281e94c4ad66c0ac923a2fc5f05c1331376f`.
Raw host copies differ because collection does not add the old host route-proof
fields; the device-content digest deliberately excludes those fields.

Private task logs use `.local/neo135-*`; session inspection evidence is
`neo135-session-journal.jsonl`, `neo135-sshd-config.txt`, `neo135-user-blame.txt`
and `neo135-user-manager-times.txt` there. The full `task check` passes 13 runtime
and 644 tool tests (one existing opt-in skip), both compiled host checks and
shell lint. Focused tests cover timing privacy and hierarchy, bounded/truncated
output, disk/short-write failure, cleanup, preserved single submission, distinct
routes, changed PM counters and original-result collection.

## Next qualification

NEO-135 completes the instrumentation and awake investigation. The historical
failure cause remains open. Capture one attended sleep with these spans before
assigning a post-wake transport delay, and profile user-manager unit loading as
an independent base-system optimization candidate. Both are in `FOLLOW-UP.md`.

The current continuation remains
`.local/diagnostics/20261007T082950.896020Z/cycle-4/qualification-next.json`,
with rehearsal `b1fef2d2d5cf4a149c39e496ee9c38ba`. No new sleep reference was
consumed, and a fresh observer-ready response is required for the next sleep.
