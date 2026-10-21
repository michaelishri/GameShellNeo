# SSH recorder burst pressure and explicit gap recovery

Date: 8 October 2026. Ticket: NEO-146. Board: owner's CPI v3.1, diagnostic.23,
kernel `6.18.54-gameshellneo22`. This is awake recorder engineering and validation.

The repeated awake transfer workload now passes with zero reported capture
drops on both machines, while retaining four matched SSH handshakes. A separate
test closes and reopens the Mac's capture handle, retaining a visible gap and
four matched handshakes in the clean reopened segment. The strict report rejects
that discontinuous recording as intended. Actual suspend-transition recovery
and the intermittent SSH greeting failure remain unqualified/unresolved.

The GameShell stays on boot `cc26703f-d9ef-4d71-8da1-9d766f3efdbe`, PM9/0:
seven earlier debug checks and two earlier actual sleeps. This work does not
enter sleep, reboot, blank the screen, change the cable or write charging policy.

## Why this slice was necessary

[Report 208](208-instrumented-rtc-sleep-and-recorder-limits.md) records a passing
attended RTC sleep and independently failed observation: the Mac recorder exits
during sleep entry with an unclassified RuntimeError, and the Linux packet
socket reports 538 drops. Neither observation proves a USB-driver failure or
network packet loss. The original failed files remain retained and rejected.

Two changes are evaluated together for pressure: save less bulk metadata and
increase only the observer socket's buffer. Mac handle recovery is evaluated
separately with a deliberate awake interruption. These are diagnostic-tool
changes; SSH connection timeouts/retries, the device admission guard, PM helper,
normal networking policy, kernel, firmware and installed image are unchanged.

## Reproducible awake workload

`task device:ssh-trace-burst` opens the original three fresh USB/Wi-Fi probe
pairs. Each USB session additionally returns exactly 2 MiB of synthetic zero
bytes through SSH, without creating a device data file. The host checks length
and SHA-256, then discards the bytes. Each expected digest is
`5647f05ec18958947d32874eeb788fa396a05d0bab7c1b71f112ceb7e9b31eee`.
Truncation or corruption stops the task without another attempt.

The Linux observer belongs to the existing sleep-test service with its read-only
smoke child, not a sleep operation. Existing ownership, source, cleanup and
boot/PM checks remain required. No RTC alarm or qualification claim is consumed.
The workload is fixed at three transfers, 6 MiB total, with a 30-second command
response bound per transfer. It does not alter SSH setup timeouts.

Baseline capture: `.local/diagnostics/20261008T055757.518087Z/`, with the original
recorder source SHA-256
`3dca63713efcb3925572357e37351fc9ec333fe1930d1e44d7c5c5fdfc15cac6`.
All six probes and all three data checks pass, despite 3,223 Linux socket drops.
The strict flow report rejects this capture. This reproduces a recorder problem
while the application receives the complete data; it does not reproduce sleep
or establish that every earlier drop had the same cause.

Final recorder capture: `.local/diagnostics/20261008T061105.468730Z/`, source
`c8955be0394db97feead557bb4c19b307a6d7c0cd811ab9a3274e3b1103c86c6`.
All six probes and three data checks pass, with four uniquely matched USB
handshakes and greeting prefixes at both observation points. Both complete
capture checks pass. A preceding selection/buffering candidate also passed in
`20261008T060215.394446Z/`; final figures below use the segmented recorder.

| Measurement | Baseline Mac | Final Mac | Baseline GameShell | Final GameShell |
| --- | ---: | ---: | ---: | ---: |
| Packet reads | 7,222 | 6,958 | 3,847 | 6,802 |
| Saved packet records | 7,222 | 96 | 3,846 | 113 |
| Metadata bytes | 2,321,621 | 34,851 | 1,250,290 | 40,984 |
| Reported received | 7,226 | 6,962 | 7,070 | 6,802 |
| Reported dropped | 0 | 0 | 3,223 | 0 |
| Complete capture accepted | Yes | Yes | No | Yes |

Final matching-packet counts are 6,958/6,801, with 6,862/6,688 intentionally
omitted by selection, respectively. One final Linux read is outside the decoded
SSH scope. No rejected headers are recorded. Mac interface-drop counters are
zero; Linux does not supply a separate interface-drop count. Packet accounting
differs between capture backends, and the baseline already lost observations;
these are whole-run measurements, not identical packet-by-packet comparisons.

Final recorder process CPU times are 0.366 seconds on the Mac and 3.486 seconds
on the GameShell. The old recorder did not measure this, so a CPU saving is not
quantified. No energy saving or wake-latency improvement is measured. Transfer
durations are 0.470–0.491 seconds initially and 0.470–0.573 seconds finally;
these three samples are insufficient to claim improved throughput.

## Selection and buffering

The recorder retains each flow's first 16 observed packets, all SYN/FIN/RST
controls, zero-window observations, positive SSH-prefix observations, and server
payload at the first sequence number after its SYN. Retransmissions of that
first payload remain eligible. Tuple reuse or ambiguous flow identity stays
unqualified in correlation. Omitted bulk is counted explicitly. The existing
128-byte snapshot and payload-free output contract are unchanged: only selected
header fields and an SSH-prefix Boolean are persisted.

Linux reuses its receive byte buffer and requests 4 MiB on this privileged
observer socket with `SO_RCVBUFFORCE`; `SO_RCVBUF` reports 8,388,608 bytes. Linux
doubles the requested value for bookkeeping, and this privileged option can
exceed the ordinary receive-buffer ceiling. The value is a socket limit, not a
measurement of resident memory. Closing the observer removes it; no global
sysctl is changed. [Linux socket documentation](https://man7.org/linux/man-pages/man7/socket.7.html).

The temporary memory allowance is a deliberate diagnostic tradeoff. Filtering
and buffering were changed together, so their individual contribution to the
drop reduction is not isolated. The Mac keeps its existing narrow libpcap
filter. Linux still receives interface-bound frames and selects decoded SSH
metadata in userspace; no new kernel BPF filter is claimed or needed for this
passing workload. Additional kernel filtering can be investigated if later
evidence warrants it. Linux `PACKET_STATISTICS` resets counters when read, so
the recorder obtains them once at finalization. [Linux packet-socket documentation](https://man7.org/linux/man-pages/man7/packet.7.html).

## Bounded capture-handle recovery

The Mac backend now records fixed error phase/category, status and errno instead
of retaining arbitrary backend text. Libpcap's BPF implementation maps read
errors ENXIO/EIO to an interface-disappearance message; this is one recognized
classification for reopening. That source correspondence does not recover the
missing error detail from report 208 or prove its cause.
[Libpcap BPF source](https://raw.githubusercontent.com/the-tcpdump-group/libpcap/libpcap-1.10.1/pcap-bpf.c).

Only a recognized read disappearance, or the explicit smoke-test injection,
enters recovery. The old handle closes; a new handle can open at one-second
intervals, with 60 attempts total, at most three gaps/four segments and the
unchanged capture deadline. Unknown errors fail without generic network
recovery. Nothing cycles the USB interface, resets the driver or changes routes.

Schema 3 records each segment's interface index, clock brackets, final capture
statistics and error, plus each gap's boundaries and attempt count. Missing
statistics remain unknown. A segment ending in a read error is excluded from
positive correlation even if its reported drops happen to be zero. Each new
segment starts a separate flow selection/correlation scope, so SYN before a
gap cannot be joined to a later greeting across that gap.

`task device:ssh-trace-gap-smoke` deliberately closes only the Mac recording
handle after 32 reads. Capture `20261008T061459.180532Z/` records one such gap,
one successful reopen attempt and about 1.050 seconds between its recorded gap
boundaries. The interface index stays 27. Six route probes pass; the GameShell
observer remains complete, with zero drops and unchanged boot/PM.

The Mac records two segments. Segment 0 carries the injected-error label and
is excluded; segment 1 has known zero-drop statistics. Four uniquely matched
handshakes survive in the positive-only report. Both supervisor children exit
zero, and cleanup has no errors. The deliberate-gap test passes because
recovery and strict rejection both work, not because coverage became continuous.
This does not model the USB hardware disappearing or qualify actual sleep.

## Report semantics and checks

`task report:ssh-trace CAPTURE=...` still rejects any discontinuous or otherwise
incomplete capture. `task report:ssh-trace-partial CAPTURE=...` writes the separate
`tcp-partial-report.json`, retaining `metadata_valid=false` for this gap test.
It uses only positive observations inside clean segments. Missing packets,
missing greetings and wire delivery cannot be inferred from a gap. Known drops,
unknown counters, mismatched hashes/source/identities, malformed boundaries,
unaccounted selection, clock discontinuity or ambiguous handshakes are never
turned into a complete pass. Original result/packet files remain immutable.

Host validation covers bounded reopening, unknown-error rejection, unavailable
statistics, payload privacy, late first payload/control retention, flow limits,
segment separation, aggregate accounting, malformed gaps and injection/sleep
exclusion. Transfer tests reject both truncation and same-length corruption.
The full `task check` suite passes 727 tool tests (one optional skip), alongside
the runtime/build checks and shell validation. Replaying the original failed
sleep, awake baseline and injected-gap captures retains all three strict
rejections. Replaying the final burst passes, while the gap's separate partial
report retains four matched flows.

## Final state and next qualification

Final read-only inspection is
`.local/diagnostics/20261008T061737.150457Z/inspection.json`. Full PM health and
current continuation validation pass at unchanged PM9/0. Both
`gameshellneo-sleep-test` and `gameshellneo-tcp-metadata` are inactive/not-found;
the Mac recorder has finalized. USB remains connected and no screen test runs.

The unused continuation remains
`20261008T054356.540135Z/qualification-next.json`, with original rehearsal
`e1afea155b864a79b04bb133496e4e26`. NEO-147 tracks the remaining attended check.
Revalidate current state and obtain fresh
observer readiness before one actual connected-USB RTC sleep. Preserve PM and
recording verdicts independently. If a recognized disappearance occurs, expect
a gap and require bounded recovery plus usable later observations; the normal
report must still reject continuous coverage. A nonzero strict-report result
does not authorize another sleep. The historical SSH greeting cause, CPU
retention and sleep-energy qualification remain separate work.

## Evidence identities

Paths are relative to the private diagnostics directory. Endpoints, credentials
and raw packet metadata remain ignored locally.

| Artifact | SHA-256 |
| --- | --- |
| Baseline `20261008T055757.518087Z/tcp-device/result.json` | `3782f9f825a81adda0ec5e1e8f43514c01fc39a8a9926175ad3d9bb814bebc44` |
| Final burst `20261008T061105.468730Z/tcp-run.json` | `da3d9a5e3782e61771e0925398429eda9a7a0a66983698628471e4a960b0397d` |
| Final burst `tcp-mac/result.json` | `1b690a8cec8c5ff51a58172ae3da2dac240cb339739006d9fddc8e07caec9d05` |
| Final burst `tcp-device/result.json` | `2b2c29b5881f0cb48396ef1fdcde4a4a04c56d33fb278468019e2a46e69bd2c1` |
| Final burst `tcp-report.json` | `dae92d0d5b9a586b7f2bf4927b6b1c51d9aa0130e7e9945ca7eb2dea8fcc19ed` |
| Gap smoke `20261008T061459.180532Z/tcp-mac/result.json` | `2cdd3d90c5276e2a92270ac7d293cc70513afc32aa7929190902bedf7b4234fb` |
| Gap smoke `tcp-partial-report.json` | `c93d8858dedb1a92f51958a2a3d0d9a3368d97c497be425dbb77f527d8ce51c4` |
| Gap smoke `gap-smoke.json` | `800c409530f0f3cdcec32afca58ca76ad2945464883bb4bba3fe53d321c84c7e` |
| Final PM inspection | `a025cca877d98b40f9122be950df26a9a49ea0a549aa50cf8ae636ad2d2dca17` |
| `.local/neo146-integrated-admission.json` | `4e98d7e1a9543970e6e54cf8f586bce8441988e29034fe0948dd77c842d4defd` |
