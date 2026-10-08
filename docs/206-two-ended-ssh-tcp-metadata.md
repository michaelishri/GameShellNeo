# Two-ended SSH TCP metadata recorder

8 October 2026. NEO-144 adds repeatable packet-header observations around the
existing SSH path. Awake validation passes on diagnostic.23/kernel
`6.18.54-gameshellneo22`, boot `cc26703f-d9ef-4d71-8da1-9d766f3efdbe`, with PM8/0
unchanged. The separately attended sleep test is pending. No image, installed
package, driver, SSH timeout/retry policy or charging setting changed.

## Question and design

[Report 205](205-diagnostic23-fresh-boot-ssh-qualification.md) captured one
debug-cycle SSH timeout before Paramiko observed a server greeting. It did
not establish whether the server sent the greeting, whether USB/TCP carried it
to the Mac, or whether the forwarding path delivered it to the client.

`tools/tcp_metadata.py` records each endpoint's view of untagged Ethernet/IPv4
TCP traffic involving the GameShell USB address and port 22. Only fixed header
fields leave the packet decoder: addresses/ports, sequence and acknowledgment
numbers, flags, window, IP ID, payload length and timestamps. `ssh_prefix` is
true/false only when at least four initial payload bytes are captured, otherwise
unknown. It describes the `SSH-` prefix in a single packet, not a complete
banner or assembled TCP stream. No payload, banner text, PCAP, credentials or
key material is saved. Endpoints and connection identities remain private.

The Mac uses its existing libpcap 1.10.1 on the interface selected by the USB
route. Capture is non-promiscuous, filtered, Ethernet-only and nonblocking.
The GameShell has no tcpdump/libpcap, so its helper uses an interface-bound
AF_PACKET socket without changing interface membership or promiscuity. It
filters metadata in userspace; unrelated interface packets count toward the
read limit but are not written. These are receive/transmit capture points in
the local stacks, not proof of physical wire delivery.

The Linux backend uses the fixed-width `SO_TIMESTAMPNS_NEW` ancillary ABI and
`PACKET_STATISTICS`. The Mac binding uses Darwin's 64-bit seconds/32-bit
microseconds timeval layout, preserving padding correctly. The respective
definitions are in the primary [Linux socket ABI](https://raw.githubusercontent.com/torvalds/linux/v6.18/include/uapi/asm-generic/socket.h),
[packet socket ABI](https://raw.githubusercontent.com/torvalds/linux/v6.18/include/uapi/linux/if_packet.h),
[Darwin timeval](https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/bsd/sys/_types/_timeval.h)
and [Darwin type definitions](https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/bsd/sys/_types.h).
The libpcap API documents [buffer ownership and datalink handling](https://raw.githubusercontent.com/the-tcpdump-group/libpcap/master/pcap_next_ex.3pcap),
[nonblocking reads](https://raw.githubusercontent.com/the-tcpdump-group/libpcap/master/pcap_setnonblock.3pcap)
and [platform-dependent capture statistics](https://raw.githubusercontent.com/the-tcpdump-group/libpcap/master/pcap_stats.3pcap).

Each recorder has a five-minute deadline, checked against both monotonic and
wall time, an 8,192-record packet cap, 32,768-read cap, 8 MiB output cap and
128-byte snap length. Temporary raw packet bytes exist only in memory while
decoding. A private lock prevents concurrent recorders on an endpoint. Linux
also has a 315-second systemd runtime limit with a five-second stop timeout.
The Mac process detaches from SSH and owns its bounded lifecycle. If a host
itself sleeps, code cannot run until it resumes; the wall deadline then stops
capture and clock continuity checks reject ambiguous timing.

Only an explicit matching stop with complete output, zero rejected headers,
unchanged interface index and zero reported drops can pass. A deadline, cap,
exception or missing artifact remains incomplete. Zero reported drops is not
proof that all traffic was captured. The helper closes its capture handle
before writing the final result; SHA-256 is accumulated from emitted metadata.
Output files are exclusive, mode 0600 and cannot overwrite existing files or
follow output symlinks. No recorder service is enabled persistently.

## Controller, recovery and correlation

`tools/check-ssh-trace.py` uploads the saved helper, records source hashes,
checks both ready markers and then calls the existing awake SSH probe or
single-sleep controller. It preserves host-key checks, connection paths,
timeouts and PM admission. It holds no GameShell control SSH session across
the experiment. Capture setup/collection introduce extra connections outside
the timed operation and add observation overhead; their timing is not an
uninstrumented performance measurement.

```sh
task device:ssh-trace-awake
task report:ssh-trace CAPTURE=.local/diagnostics/<capture>
task device:ssh-trace-sleep QUALIFICATION=<receipt> REHEARSAL=<run-id> ATTENDED=1
task device:ssh-trace-collect CAPTURE=.local/diagnostics/<capture>
```

Sleep still requires separate fresh owner readiness and the original RTC/PM
qualification. Collection independently attempts both endpoints so failure to
reach one cannot skip cleanup of the other. Launch intent is saved before
submission. An uncertain submission is not repeated. Recollection stops or
reads the original recorders, checks original artifact bytes and never starts
a new recorder or sleep. The original sleep result may also require
`device:sleep-collect RUN=<original-id>`; metadata collection cannot requalify it.
`ROUTE=wifi` can retrieve the device recorder if USB recovery is incomplete.

`tools/tcp_report.py` validates schema, bounds, hashes, counters and clock
continuity. It matches client endpoints and initial sequence numbers, then
requires matching server SYN/ACK sequence numbers. Tuple reuse, partial
handshakes and conflicting sequences cannot establish a unique connection.
Flows seen only on one side are retained separately. The first server payload
at server-ISN+1 supplies the greeting-prefix observation; no reassembly or
complete-banner inference is made.

Mac clock samples are bracketed by Intel monotonic timestamps before/after
the experiment. Their intersecting offset bounds allow a 50 ms slew margin.
The Mac SYN timestamp is associated only with overlapping recorded USB tunnel
spans. Exactly one candidate is required, and two flows cannot both claim one
span. Later recollection cannot replace the original clock anchors. Capture
clock steps over 100 ms reject timing interpretation. Offload, segmentation,
sampling uncertainty and ambiguous/missing flows remain explicit limits.

## Validation and awake evidence

The focused suite passes 22 tests covering payload exclusion, truncated data
versus headers, IPv4/TCP options, fragmentation, time64 and Darwin padding,
initialization failure cleanup, output collisions/symlinks, packet/byte/deadline
limits, drops, interface replacement, sequence wrapping/retransmission,
tuple reuse, wrong acknowledgments, clock steps, flow/tunnel matching,
readiness-before-contact and preservation of the primary failure during cleanup.
The full host checks pass 13 runtime and 701 tool tests, with one existing
optional skip, both compiled checks, Bash syntax and ShellCheck.

The final live awake capture is
`.local/diagnostics/20261008T012323.826808Z/`. All six USB/Wi-Fi probes pass;
four USB flows (discovery plus three probes) match uniquely across both capture
points and host tunnel spans, with an SSH prefix at both ends. One extra
Mac-side setup flow and one device-only collection flow are retained without
claiming they belong to a timed probe. Mac/device packet totals differ because
their setup/collection windows differ.

| Recorder | Saved packets | Reads | Metadata bytes | Reported drops | Interface index |
| --- | ---: | ---: | ---: | --- | --- |
| Mac | 365 | 365 | 119,215 | 0 socket, 0 interface | 27 → 27 |
| GameShell | 263 | 268 | 87,191 | 0 socket; interface unavailable | 4 → 4 |

Both stop normally with zero rejected headers. Recollection passes and preserves
the original packet/result bytes. The offline report passes. The final helper
SHA-256 is `c127f5d918f787002ad6d41b830a70ef3e6855b4b076ca666f3f481add19384f`.

| Artifact beneath the final capture | SHA-256 |
| --- | --- |
| `host-timing.jsonl` | `de7110c00825fc808619d797286657c39665b82fa10252f398221ee2fa02c489` |
| `awake-ssh.json` | `2908dabd1bf440787e17bd9bfe7932c4e61f5e518a34f05074f88ce0d1c20eec` |
| `tcp-mac/result.json` | `6326c54c25173c0b2da11caccaaadaf69226894c48353a22a9cde4b3ad8e49dc` |
| `tcp-mac/packets.jsonl` | `ffa8d609c87fe901e440886b160de34d362becc8ffdea69a6debd02bacb3404a` |
| `tcp-device/result.json` | `2ccb118d5b1b3d942f4d6c585a617ffbb87b85c6b14f0f0ee7ca1ce07642c503` |
| `tcp-device/packets.jsonl` | `4d54ec490d09a2792134d91a7a4c81d5c054480f501a4739a925e5bce1be8ca4` |
| `tcp-report.json` | `2e588067811ba4cae2e4f1b86252b2ecf34d2c7b873140c61df6003bdf2b0342` |

The post-check PM inspection at `20261008T012620.016585Z/inspection.json`
confirms the same boot, PM8/0, SDIO2 and healthy policy. The full sleep receipt
validator accepts report 205's unused continuation without repeating the seven
debug stages. No sleep has run in this slice yet. The next separately attended
attempt can retain both endpoint views if the greeting stall recurs. A passing
awake recorder does not resolve the historical post-return SSH fault.
