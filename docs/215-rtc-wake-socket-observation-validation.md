# RTC wake with Mac socket observations

8 October 2026. NEO-152 qualifies the opt-in socket observations from
[report 214](214-ssh-failure-socket-observations.md) across one attended RTC sleep.
The functional sleep/recovery checks pass, the owner confirms the clear warning
and normal untouched dim-console return, and both network routes recover. The
new socket report validates all fifteen forwarded connection attempts.

The earlier post-return SSH setup failure from
[report 210](210-rtc-wake-segmented-observer-validation.md) does not recur. This
qualifies the observation path, not a fix for that intermittent failure. The Mac
packet recording again has an explicit gap during sleep; continuous packet
coverage remains rejected independently of the passing sleep and socket reports.

## Attended operation and final device state

Fresh full health and unused-continuation checks pass against inspection
`20261008T082300.924417Z/inspection.json`. The owner then supplies explicit
watching/listening readiness. The historical invocation is below; its input
continuation is now consumed and must not be reused:

```sh
task device:ssh-trace-sleep SOCKET_STATE=1 \
  QUALIFICATION=.local/diagnostics/20261008T070741.360669Z/qualification-next.json \
  REHEARSAL=e1afea155b864a79b04bb133496e4e26 ATTENDED=1
```

Capture `.local/diagnostics/20261008T083013.709559Z/` contains sleep run
`6c7cdf9c7608479aba88f6d1d347e839` and packet-recorder run
`b602d28bcc85493d9e0f2b9b3e49b19a`. Diagnostic.23/kernel
`6.18.54-gameshellneo22` stays on boot
`cc26703f-d9ef-4d71-8da1-9d766f3efdbe`. PM advances from **11/0 to 12/0**:
seven debug checks and five actual sleeps on this boot.

The original result passes RTC delivery, process-memory, original-keypad,
SDIO, trace, power-policy and restoration checks. The warning sequence passes
and restores its controls. Temporary diagnostic ownership of POWER, the RTC and
console is released. Both USB and Wi-Fi SSH proofs pass. The owner's confirmation
is separately bound to the result hash in `.local/neo152-owner-observation.json`.

| Measurement | Result |
| --- | ---: |
| Alarm elapsed time | 31.719 seconds |
| PM call, BOOTTIME | 30.969 seconds |
| Traced s2idle boundary, MONOTONIC | 28.580 seconds |
| Observed timekeeping-freeze pairs | 0 |
| CPU retention / energy savings | Unqualified |

The saved `report:sleep-evidence` task passes the separate RTC/trace/clock
assessment in `20261008T083233.048599Z/sleep-evidence.json`, without rewriting or
requalifying the original recovery result. No second sleep is submitted.

## Original SSH outcomes and socket state

The opt-in observer records fifteen attempts and reports no record-limit,
write, source-identity or snapshot-collection failure. Offline validation passes
against the exact saved implementation sources, first SSH/byte observations,
timing events and worker identities.

| Attempts | Original outcome | Mac socket result |
| --- | --- | --- |
| Ten USB and two Wi-Fi setups | Greeting, key exchange and authentication complete | One new established worker candidate each |
| Three USB forwarding opens | Channel opening fails before inner SSH starts | Missing after failure; no invented endpoint |

Each successful setup retains 1,648 bytes sent and 1,657 received through the
forwarding API, with zero send/receive errors. Each of the twelve candidates has
an established TCP state and zero send/receive queue bytes at collection. These
point observations are not TCP delivery history or atomic kernel snapshots.
`independently_confirmed` remains false: this run does not separately retain
authenticated GameShell endpoint records for every socket as the awake control
did, and successful control evidence is not substituted for that corroboration.

All three failed forwarding opens end before the recorded PM call returns.
They never reach inner SSH negotiation and do not reproduce the original
post-return ten-second setup failure. Their missing post-failure sockets remain
missing; this is not proof that a connection could never have existed.

The first collection after PM return succeeds. Its SSH setup takes about
549 ms. The shortest subsequent device-clock bracket is span 156, width
0.479 seconds. Relative to the saved PM return:

| Observation | Start after return | End after return |
| --- | --- | --- |
| First successful post-return collection, span 91 | 2.677–3.156 s | 6.069–6.547 s |
| Its inner SSH setup, span 98 | 3.205–3.684 s | 3.754–4.233 s |

The three failed channel spans end at −22.567 to −22.088 seconds, −11.626 to
−11.147 seconds, and −2.669 to −2.190 seconds relative to return. These intervals
use the enclosing host/device clock sample to bound the clock offset and assume
negligible short-term relative drift. They describe instrumented attempts, not
exact network readiness, display wake time or a performance improvement.
The sanitized calculation is retained in `.local/neo152-timing-analysis.json`.
Baseline and post-outcome socket commands add their own separate timing spans;
no command is inserted between forwarding-channel opening and SSH negotiation.

## Packet evidence remains segmented

The Mac recorder reports `interface-disappeared`, read status −1/errno 6, closes
segment 0 and reopens segment 1 after 28 attempts. The explicit gap is about
29.009 seconds. Segment 0's error excludes it from positive flow correlation.

| Recorder | Saved packets | Reads | Received / dropped | Rejected headers |
| --- | ---: | ---: | ---: | ---: |
| Mac | 215 | 5,150 | 5,238 / 0 | 0 |
| GameShell | 189 | 4,149 | 4,149 / 0 | 0 |

Mac interface drops are zero; the Linux backend has no separate interface-drop
counter. Zero reported recorder drops do not establish zero wire loss. The
device recorder passes its completeness criteria. Its supervisor reports zero
command/recorder exit codes and no cleanup errors; both sides' saved metadata
are collected.

The partial report matches seven later handshake/greeting flows using Mac
segment 1 and Linux segment 0. It retains `metadata_valid=false` and does not
promote `host_tunnel_identity_verified` using socket candidates. The strict Task
command exits **201** because continuous packet capture is unqualified. No
acceptance criterion is relaxed to turn the gap into a pass. The independent
sleep result, socket report and positive-only packet evidence remain distinct.

## Handoff

Final read-only inspection `20261008T083255.376290Z/inspection.json` passes full
health and validates the new unused continuation:
`20261008T083013.709559Z/qualification-next.json`. It retains rehearsal
`e1afea155b864a79b04bb133496e4e26`. The prior `070741.360669Z` continuation is
consumed. No further sleep or screen test is running.

NEO-153 keeps the unresolved greeting stall open for a source/evidence audit of
the installed SSH implementations and the original failure. That work needs no
physical interaction or new image. Do not repeat sleeps merely to provoke the
failure, extend timeouts or add retries to conceal it. The now-qualified socket
option can preserve better evidence during future already-planned diagnostics.
Any further PM needs fresh admission and observer readiness. CPU retention and
energy qualification remain separate work.

No runtime or diagnostic implementation changes are made in this slice, so the
full regression suite is not rerun. The relevant saved socket, host-timing and
sleep-evidence reports pass, together with fresh final health and continuation
validation. Only the findings and handoff documentation change.

## Evidence identities

Capture paths are inside ignored `.local/diagnostics/`.

| Artifact | SHA-256 |
| --- | --- |
| `083013.709559Z/result.json` | `bade648cc578e0652137acc2c762a3d02c996d573793aa5b924e4699a4015e62` |
| `083013.709559Z/socket-observations/index.json` | `b212de7fd80bb2698cd7b9fbc4412820280f217a3d84b12a8336ad45780257ae` |
| `083013.709559Z/tcp-partial-report.json` | `c16b3fc13a88af16a10e7b7d39371f82b9ef20a2b6c9984eb1d27050bce3d1be` |
| `083013.709559Z/qualification-next.json` | `7c5798f3a2a56c63e943347861cdb213f5cd73bb3d1876289862c71f1fb48da6` |
| `083233.048599Z/sleep-evidence.json` | `caeb618cc93cc7384414fef4c395015c960d1fbed1550fc466de33bcfda817ad` |
| `083255.376290Z/inspection.json` | `057596d1c5d6ec6ca7a949fae461f6ad1d62bf57dd456d388483fa5320c8865a` |
| `.local/neo152-owner-observation.json` | `a1f26e1950a4caf152474b0bbc9291f1c5821a62256c9e1903f7b4a989fd9e35` |
| `.local/neo152-socket-report.json` | `76c8de87833c6a013ceecc066a80f27f87cdd28a721e557db63f2ee37979dda1` |
| `.local/neo152-timing-analysis.json` | `43ae135c7ffa5291fd79db72bc7d779205cb6ce1ac717bdce5d00474fe6b2bca` |
| `.local/neo152-final-admission.json` | `5216e35e11f20db08166c70d320a27aa5244a50c04ede98147587ab5f60506bb` |
