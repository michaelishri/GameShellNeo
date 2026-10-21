# Forwarded SSH setup: identity limits and byte observations

8 October 2026. NEO-148 completes the saved-evidence/source audit and prepares
additional passive diagnostics. It does not resolve the intermittent setup
failure. Diagnostic.23 stays on boot `cc26703f-d9ef-4d71-8da1-9d766f3efdbe`,
PM10/0, throughout the awake checks. No sleep, reboot, blanking or cable action
is performed.

The main findings are a later same-peer/port server closure, an explicit limit
on time-based packet/request correlation, and new forwarding byte observations
that can distinguish no received data from an incomplete SSH negotiation.

## Reassessment of the saved failure

[Report 210](210-rtc-wake-segmented-observer-validation.md) records a successful
RTC wake followed by one failed SSH setup. Its forwarded-channel operation
reports success; the following setup fails after 10.016 seconds with
`No existing session`, without an observed greeting, completed key exchange or
authentication. The packet flow overlapping that request contains two client
SYN observations at each endpoint but no matched server sequence identity.
Five later flows have matching SYN/SYN-ACK identities and greeting prefixes.

There is a distinction between matching the same TCP flow across the two
recorders and assigning that flow to a particular host request. The current
request association uses the first observed SYN's time bracket. A first
observed SYN could be a retransmission, including from an earlier request;
a recording gap makes that especially relevant. One overlapping request is
therefore a candidate, not independent proof of ownership. No claim is made
that this specific failure was actually misassociated.

`tools/tcp_report.py` now states this limit and adds
`host_tunnel_identity_verified=false` to each flow. Existing handshake matching,
ambiguity, source/hash, segment and drop checks remain intact. Reassessment of
the old capture retains its five matched greeting flows and rejected continuous
coverage. The revised derived view is saved separately in
`.local/neo148-tcp-reassessment.json`; original packets, results and report 210's
derived report are not overwritten.

## What forwarding completion means

The installed host uses Paramiko 4.0.0. Its `open_channel()` sends a channel
request and waits on a response event; the success parser sets the remote
channel identity and wakes the caller. This establishes an SSH channel-open
confirmation, not observation of the GameShell's greeting. Its synchronous
client setup can reach its timeout before initial negotiation completes; the
subsequent key lookup can then produce `No existing session`.
[Paramiko transport source](https://raw.githubusercontent.com/paramiko/paramiko/4.0.0/paramiko/transport.py),
[client source](https://raw.githubusercontent.com/paramiko/paramiko/4.0.0/paramiko/client.py).

The inspected OpenSSH implementation confirms an ordinary nonblocking direct
connection after socket writability and a zero `SO_ERROR`, then sends channel
confirmation. Apple's published source contains the same path. These are
source references, not verification of the exact running macOS server binary
or its kernel socket state during the failed attempt. An apparent disagreement
with the capture warrants more evidence; it is not proof of premature server
confirmation. [OpenSSH 10.0p1 channel source](https://raw.githubusercontent.com/openssh/openssh-portable/V_10_0_P1/channels.c),
[Apple published channel source](https://raw.githubusercontent.com/apple-oss-distributions/OpenSSH/main/openssh/channels.c).

The supplied `direct-tcpip` originator address/port describes the original
request, not a returned Mac-side TCP source port. Paramiko's
`Channel.getpeername()` delegates to the enclosing SSH transport, so it cannot
identify the Mac's outgoing GameShell socket. Recording it as that endpoint
would give misleading identity evidence.
[RFC 4254, section 7.2](https://www.rfc-editor.org/rfc/rfc4254.html#section-7.2),
[Paramiko channel source](https://raw.githubusercontent.com/paramiko/paramiko/4.0.0/paramiko/channel.py).

## Server journal evidence

Read-only retrieval preserves the 06:25:00–06:28:30 UTC interval on the same
boot: 40 SSH-service records and 914 records without the unit filter. Both
include a closure with the candidate flow's same source address and port.
The initial inspection focused on the first 26 seconds after return; examining
the rest of the bounded interval locates this later entry.

The `sshd-session` entry says the connection closed before authentication. Its
journal monotonic receipt is **59.817 seconds after PM return**. Its source
realtime stamp precedes journal receipt by only 373 microseconds. This reduces
the likelihood of a long delay solely between that syslog emission and journal
receipt; it does not timestamp TCP establishment, greeting transmission, socket
closure in the kernel or the host's request.

That event occurs well after the host setup failure ends at 14.162–14.798
seconds and after the packet recorders close. A later server process handled
a connection using that peer/port, but port reuse and exact request identity
are not independently excluded. The entry cannot fill the missing handshake
or show when the greeting should have reached the client. No successful
authentication entry is attributed to that candidate connection. The following
healthy connection logs an accepted public key at 20.033 seconds after return.

The private assessment stores fixed categories, clock values and file hashes;
network identities and raw journal text remain ignored locally. Retrieval is
repeatable using the existing task:

```sh
umask 077
task device:exec ROUTE=usb -- sudo -n journalctl -b \
  --since '2026-10-08 06:25:00 UTC' --until '2026-10-08 06:28:30 UTC' \
  -o json --no-pager -n 5000 > .local/neo148-boot-journal.jsonl
```

Use an appropriate saved boot identifier instead of `-b` if the device has since
rebooted. Log retention can limit later retrieval; preserve the originals.

## Passive forwarding observations

When host timing is enabled, `tools/host_timing.py` wraps the existing forwarded
channel's `send()` and `recv()` calls and counts their returned bytes/calls,
send/receive errors and receive timeouts. The wrapper retains no byte buffers,
packet contents, greetings, credentials, endpoint strings or exception text.
It neither reads ahead nor retries. Timeout, close and other channel methods
delegate to the original object. Without a timing capture, the original channel
is used directly.

Two fixed `forward_state` observations are saved: immediately after channel
opening and after the device's SSH setup returns or raises, before cleanup.
They include active/closed/EOF flags and whether receive data is buffered.
Unsupported flags stay unknown. The counters and flags are sequential
observations of a live connection, not an atomic state snapshot. The existing
event/byte bounds still apply; no per-packet event stream is added.

The useful distinctions are:

| Observation | What it establishes |
| --- | --- |
| Sent bytes greater than zero | The forwarding API accepted bytes from the inner SSH client |
| Received bytes greater than zero | Bytes were delivered through that API to the inner client |
| No received bytes, no greeting | No bytes were returned by observed reads before this snapshot |
| Greeting present, key exchange incomplete | Setup progressed beyond identification but not initial negotiation |
| Closed/EOF/unknown flags | Additional channel state at observation, not the cause of closure |

None proves acknowledgment by the GameShell's TCP stack or exposes the Mac's
outgoing socket identity. In particular, sent bytes can still be queued inside
the forwarding path. Counts are diagnostic evidence, not throughput metrics.

The existing tasks pick up these observations automatically:

```sh
task device:ssh-timing CYCLES=3
task device:ssh-trace-awake
task device:ssh-timing-report CAPTURE=.local/diagnostics/<capture>
```

No PM helper, admission source, image, SSH retry/timeout or device policy changes.

## Validation and remaining work

Seven new tests cover exact partial-I/O behavior, preservation of original
errors/timeouts, no-op behavior outside recording, unknown flags, observation
before cleanup, privacy and malformed/duplicate observations. Real local
Paramiko transports distinguish a silent peer (sent bytes, zero received) from
a greeting-only peer (received bytes/greeting, incomplete key exchange).
The complete `task check` passes 734 tool tests (one optional skip), 13 runtime
tests and existing compiled/shell checks. A focused TCP rerun also passes after
adding an assertion that temporal uniqueness never verifies socket ownership.

Awake capture `.local/diagnostics/20261008T064628.635597Z/` passes three fresh
USB/Wi-Fi pairs plus initial USB discovery, with all 14 Mac/device SSH states
authenticated. Seven forwarded device connections each report 1,648 bytes sent
and 1,657 received during setup, with no send/receive errors. Four uniquely
overlapping matched USB greeting flows remain timing candidates, not verified
host socket identities. Both packet recorders report zero drops and complete
capture acceptance. This healthy workload does not reproduce the intermittent
post-resume failure or prove reduced latency.

Final inspection `20261008T064752.766782Z/inspection.json` passes full PM health
and the current unused continuation validation at unchanged PM10/0. Temporary
diagnostic services are inactive/not-found. The continuation remains
`20261008T062557.111288Z/qualification-next.json`; no new claim was consumed.

NEO-149 carries the unresolved connection investigation forward. Preserve the
new observations at the next justified attended sleep, requiring current
admission and fresh readiness. Do not repeat sleep solely to provoke failure.
If this still leaves ambiguity, obtain a bounded, independently identified
Mac/board socket-state observation before another attempt. CPU retention,
energy and wider platform qualification remain separate.

## Evidence identities

Awake file names are relative to `20261008T064628.635597Z/`.

| Artifact | SHA-256 |
| --- | --- |
| `awake-ssh.json` | `ef18055f3ec32ed655f523251dd28deb18872ee613a529c1e32f2a0ae5f54b87` |
| `host-timing.jsonl` | `9bb4486cbc9b2b9e29ea98c5daceeccfc5e686e3e3e1c83d229bfee0e762a90d` |
| `host-timing-summary.json` | `1d79d372e56d5ecaef56e87b02025793189b9c549b6c0d84f7d624093c41f34a` |
| `tcp-report.json` | `7d39f88d6cbb5cfb996397e12fbf41eeb89b020c5840edd031ef92d67329dd86` |
| `.local/neo148-server-journal.jsonl` | `ae128bc16fa27958100cf8aac72410cabb9a4ae6389d6bef7f0ddab4e44c2ac0` |
| `.local/neo148-boot-journal.jsonl` | `48873c5b627fbd5811a36ee5c7ea8ec3fe109a0b5d079b9f63d29c80b5d3e97d` |
| `.local/neo148-journal-assessment.json` | `7c01914cb4af66bb66153c26b9a865849870c4fe9648753b6537feb539bebaef` |
| `.local/neo148-tcp-reassessment.json` | `9081f0b00dd1d40e9459b719420d14f5a1406b4da82a280df6ca1bc780438e8e` |
| Final inspection | `6a857d0f27c2cddf19fc452675f49ff50f97f512e26af4128c8fdbc41c567f08` |
| `.local/neo148-final-admission.json` | `227f84568aed0828240502ec7bc76d9723443a1a0a4d7455871fb12f95d567ea` |
