# RTC wake with forwarding byte observations

8 October 2026. NEO-149 records one attended RTC sleep with the passive host
observations from [report 211](211-forwarded-ssh-observation.md). Sleep, warning,
display return, keypad retention and both network routes pass. The intermittent
post-return SSH setup failure does **not** recur. This is a healthy comparison,
not a resolved cause or a measured performance improvement.

The Mac packet observer again loses its interface during sleep and reopens with
an explicit gap. Seven later handshake/greeting flows match in clean segments;
continuous coverage remains rejected. A host-observer flag compatibility issue
found during review is corrected and checked awake, without another sleep.

## Attended operation

The owner supplied fresh watching/listening readiness after full PM health and
continuation validation of `20261008T070637.319380Z/inspection.json`.

```sh
task device:ssh-trace-sleep \
  QUALIFICATION=.local/diagnostics/20261008T062557.111288Z/qualification-next.json \
  REHEARSAL=e1afea155b864a79b04bb133496e4e26 ATTENDED=1
```

Capture `.local/diagnostics/20261008T070741.360669Z/` contains sleep run
`31c5f34145ed4123b793daf8d773bbc0` and observer run
`7c77e7babe7e46b78af5b64ee318976e`. Diagnostic.23/kernel
`6.18.54-gameshellneo22` remains on boot
`cc26703f-d9ef-4d71-8da1-9d766f3efdbe`. PM advances from 10/0 to 11/0:
seven debug checks and four actual sleeps on this boot.

The original result passes functional RTC delivery, process-memory, original
keypad, SDIO, trace, power-policy and restoration checks. USB and Wi-Fi SSH both
recover. POWER ownership and temporary diagnostic controls are released. The
owner confirms the clear long warning and normal dim-console return without
touching the cable or controls; the observation is bound to the original result
hash in `.local/neo149-owner-observation.json`.

| Measurement | Result |
| --- | ---: |
| Alarm elapsed time | 32.354 seconds |
| PM call, BOOTTIME | 31.447 seconds |
| Traced s2idle boundary, MONOTONIC | 29.059 seconds |
| Observed timekeeping-freeze pairs | 0 |
| CPU retention / energy savings | Unqualified |

The existing `report:sleep-evidence` task separately passes RTC/trace/clock
checks in `20261008T071033.535306Z/sleep-evidence.json`. It does not rewrite or
requalify the original result. No second sleep is submitted in this slice.

## SSH observations

All twelve observed forwarded device SSH setups authenticate. Each records
1,648 bytes sent and 1,657 received through the forwarding API, with zero
send/receive errors. Receive timeouts occur during successful negotiation too;
they are observations of bounded reads, not independently a failed connection.
The two failed channel-opening attempts occur wholly before PM return, during
sleep/resume. Neither reaches inner SSH setup.

The first post-return collection succeeds. Its forwarded channel opens in
8.4 ms and its SSH setup completes in 494 ms. The shortest post-return device
clock bracket is span 125, width 0.558 seconds. Relative to the saved PM return:

| Observation | Start after return | End after return |
| --- | --- | --- |
| First post-return collection, span 70 | 3.019–3.577 s | 6.709–7.267 s |
| Device SSH setup, span 76 | 3.762–4.321 s | 4.257–4.815 s |

These bounds assume negligible short-term relative clock drift. They describe
instrumented request timing, not exact network readiness or display wake latency.
Later collections continue reading the in-progress result until the existing
device recovery checks finish; that does not imply failed SSH connections.
The sanitized assessment is `.local/neo149-timing-analysis.json`.

The ten-second setup failure in report 210 remains unresolved. This run supplies
no failing inner channel whose byte state could explain that earlier event.
Forwarding byte counts still do not prove TCP delivery or independently identify
the Mac's outgoing socket. Timing overlap remains a candidate association.

## Packet recorder result

The Mac records `interface-disappeared`, read status −1/errno 6, closes segment
0 and reopens segment 1 after 29 attempts. The explicit gap is approximately
29.92 seconds. The read error excludes segment 0 from positive correlation.

| Recorder | Saved packets | Reads | Metadata bytes | Received / dropped |
| --- | ---: | ---: | ---: | ---: |
| Mac | 209 | 5,082 | 83,519 | 5,163 / 0 |
| GameShell | 186 | 4,099 | 71,856 | 4,099 / 0 |

Both have zero rejected headers. Mac interface drops are zero; Linux has no
separate interface-drop counter. The Linux recorder is accepted as complete
under its criteria. The positive-only partial report matches seven later flows
in Mac segment 1 and Linux segment 0, each with matching handshake identities
and greeting prefixes. Zero reported drops do not establish zero wire loss.

Both supervisor children exit zero, cleanup has no errors and the independent
PM operation passes. The overall strict task exits 201 because the Mac recording
is discontinuous. `tcp-partial-report.json` keeps `metadata_valid=false` and
`host_tunnel_identity_verified=false`; no acceptance condition is relaxed.

## Observer flag correction and awake validation

The attended capture uses host instrumentation from `cb72b32`. Its active/EOF
flags are unknown because `forward_state()` initially accepted only Python
booleans. Inspection of the installed Paramiko 4.0.0 `Channel` implementation
shows active set to integer `1`, EOF flags initially integer `0`, and later
assignments mixing integers and booleans. The byte observations remain usable;
the unknown flags in the original capture are preserved.

The observer now normalizes only actual booleans and exact integer `0`/`1`.
Other integers, floats, strings and unsupported values remain unknown. The
change neither reads channel payloads nor changes forwarding, retry, timeout or
device behavior. A new regression case covers both accepted representations
and rejects arbitrary truthy values. Full `task check` passes 735 tool tests
(one optional skip), 13 runtime tests and the compiled/shell checks.

```sh
task device:ssh-timing CYCLES=3
```

Awake capture `20261008T071201.703706Z/` passes the three USB/Wi-Fi pairs plus
initial USB discovery. All seven forwarded setups record `active=true`,
`closed=false`, both EOF flags false, bidirectional byte counts and zero I/O
errors. This validates the corrected flag representation while awake; no extra
sleep or screen change is needed. The original attended artifacts are unchanged.

## Final state and remaining work

Post-sleep inspection `20261008T070956.393402Z/inspection.json` passes full PM
health and continuation validation at PM11/0. The later awake probes pass, and
both temporary diagnostic services are inactive/not-found. USB remains connected.
The previous continuation is consumed; the current unused successor is
`20261008T070741.360669Z/qualification-next.json`, retaining rehearsal
`e1afea155b864a79b04bb133496e4e26`. Validate current state before future use and
obtain fresh readiness for any further PM test.

NEO-150 tracks independent socket attribution and the unresolved setup failure.
First establish a bounded passive Mac/board socket-state observation with awake
controls. It must distinguish the Intel-to-Mac transport/process from the
Mac-to-GameShell TCP socket and leave the forwarding behavior unchanged. A port
match, request time overlap or channel peer address alone is insufficient.
Do not repeat sleep solely to provoke another failure. Driver, firmware,
networking, charging and sleep policy remain unchanged in this slice.

## Evidence identities

Names below are relative to the attended capture unless prefixed otherwise.

| Artifact | SHA-256 |
| --- | --- |
| `result.json` | `076018440b93ad334c72f1b286f1001241d66ffebc921227e66ae6b07f53c6cd` |
| `host-timing.jsonl` | `d6f4f344ef2412a425d39d911cbe1c1300b5cd3c62b4572f42a2906532fda2ad` |
| `qualification-next.json` | `a97946445e9f028af7a9fca74d7466fcd2b8a0eabaf7ac5764fdc7418a1914a6` |
| `tcp-run.json` | `242c14ee3902fe1497f892fe559423ee1e48b8d29e4a5e157d3cfe46e1b31030` |
| `tcp-mac/result.json` | `1ceb694b14598d400e82b10f8857ca560179e3a08916035c2f98c43317ab6843` |
| `tcp-mac/packets.jsonl` | `9e15926f65056bd09a44c09a468f0ea2e5202a1db28965203712aaff9250cd95` |
| `tcp-device/result.json` | `d57d38e6361d093bb0c2ef267175de83906941b7b9ecd7631880efaf3c74ec06` |
| `tcp-device/packets.jsonl` | `3785f50a7f4dbeb75ff4af0d63d0f2615aea645bc372db4136cd4ca83d2c35b6` |
| `tcp-device/supervisor.json` | `8ecee498dd4d59f0b8fad7614f3c672c96b0054f207150ee97fc67ac4e1ea674` |
| `tcp-partial-report.json` | `269d2f718b29d8f8a556d338d83a8621e6695721865bfc78e1bd6a4703ee5365` |
| `.local/neo149-owner-observation.json` | `0a796e735f2c9ba40b7b8cf96976404e3c5d9d343a9e6b5feb3106fccdace6af` |
| `.local/neo149-timing-analysis.json` | `b921ae53f82e53bde3b400c496269873cfbd50fab14dc6f96494ce5b389968fa` |
| `.local/neo149-final-admission.json` | `f1f788a2dcb43d95496a8bc0204d1d40f5e7e8c58e50b68f4e29440ff0356fb0` |
| Awake `awake-ssh.json` | `a1fcb143ff0f48e5874f38e1240b1b4e00064f6e68f228a771e93b05fed97808` |
| Awake `host-timing.jsonl` | `79c074caff2fd4e53d14faa3114c10e7403817cb27efa704710f08578f955488` |
