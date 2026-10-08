# RTC wake with a recovered segmented observer

Subsequent clarification: [report 211](211-forwarded-ssh-observation.md) treats
the unique host-span overlap below as a timing candidate, not verified socket
ownership, and adds a later same-peer/port server closure. Original measurements
and private artifacts below remain unchanged.

8 October 2026; capture timestamps are UTC. NEO-147 runs one separately attended
RTC sleep with [NEO-146's revised recorder](209-ssh-recorder-burst-and-gap-recovery.md).
Functional sleep/recovery passes. The Mac recorder now identifies a real
interface-disappearance error and automatically reopens within its existing
bound. Both recorders report zero drops, and five later SSH handshakes match
inside clean segments. The explicit recording gap still fails continuous
coverage qualification.

One post-return SSH setup failure also recurs. Its saved flow does not establish
a complete handshake, so the evidence does not yet identify a USB, TCP,
forwarding or SSH-server cause. No second sleep is submitted to replace either
the gap or the failed connection.

## Attended operation and PM result

The owner supplied fresh watching/listening readiness before the saved task ran.
The preflight inspection `20261008T062531.679132Z/inspection.json` passes full
PM health and the current unused continuation's history/source checks.

```sh
task device:ssh-trace-sleep \
  QUALIFICATION=.local/diagnostics/20261008T054356.540135Z/qualification-next.json \
  REHEARSAL=e1afea155b864a79b04bb133496e4e26 ATTENDED=1
```

Capture `.local/diagnostics/20261008T062557.111288Z/` contains sleep run
`f831c717c5074977a3be76c169b09048` and recorder run
`a74fe896a8594dbd88c4ad1e82927f83`. Diagnostic.23/kernel
`6.18.54-gameshellneo22` stays on boot
`cc26703f-d9ef-4d71-8da1-9d766f3efdbe`. PM advances from 9/0 to 10/0: seven
debug checks and three actual sleeps, not ten actual sleeps.

The original PM result passes full delivery, process-memory, keypad, trace,
source, history and restoration validation. Independent USB/Wi-Fi proofs pass.
The original keypad handle remains connected, with no hangup, poll error or
held key. Its input/USB identity is retained. SDIO retention and the existing
power policy pass; POWER ownership is handed back, and diagnostic controls,
console/RTC ownership and temporary policy files are released.

The one-second level-5 warning passes playback and restoration checks. The
owner confirms hearing it and seeing the normal dim console return without
touching the cable or controls. Their confirmation is recorded separately in
`.local/neo147-owner-observation.json`, bound to the original PM result hash.

| Measurement | Result |
| --- | ---: |
| Alarm elapsed time | 32.563 seconds |
| PM call, BOOTTIME | 31.691 seconds |
| Traced s2idle boundary, MONOTONIC | 29.261 seconds |
| Observed timekeeping-freeze pairs | 0 |
| Functional RTC wake / both routes | Pass |
| CPU retention / energy savings | Unqualified |

The saved `report:sleep-evidence` task independently passes RTC/trace/clock
checks and writes `20261008T062820.942694Z/sleep-evidence.json`. It does not
rewrite or requalify the original PM result.

## Real recorder recovery

Both uploaded recorders match source SHA-256
`c8955be0394db97feead557bb4c19b307a6d7c0cd811ab9a3274e3b1103c86c6`.
The Mac records a read error classified `interface-disappeared`, status −1,
errno 6, and closes segment 0. The exact error classification was unavailable
in [report 208](208-instrumented-rtc-sleep-and-recorder-limits.md); this run
establishes it for the current event, not retrospectively for that older failure.

The Mac opens segment 1 after 29 attempts, within the global 60-attempt bound.
Its gap spans 29.907 seconds between recorded boundaries, with interface index
27 on both sides. The recorder changes only its own capture handle; it does not
cycle USB, change networking or retry the PM operation. No injection is enabled.

Using the original Mac/host anchors and the shortest post-return device-clock
bracket, gap start lies 30.213–31.169 seconds before PM return; its recorded end
lies 0.306–1.262 seconds before PM return. The bounds include a 50 ms allowance
in the host/Mac mapping and assume negligible short-term relative clock drift.
The reopened recorder is therefore available for the post-return collection
attempts. These boundaries are not a wire-delivery or exact network-ready time.

| Recorder | Saved packets | Reads | Metadata bytes | Received / dropped | Qualification |
| --- | ---: | ---: | ---: | --- | --- |
| Mac | 175 | 5,416 | 72,621 | 5,505 / 0 | Segment 1 usable; whole window gapped |
| GameShell | 151 | 4,414 | 60,510 | 4,414 / 0 | Complete under recorder criteria |

Both record zero rejected headers. Mac interface-drop counters are zero;
Linux has no separate interface-drop value. Segment 0's read error excludes
its packets from positive correlation even though its counters report no drops.
Segment 1 has known clean statistics. The Linux observer keeps interface index
4 and known clean statistics. Zero reported drops do not prove zero wire loss,
and the Linux userspace recorder still shares the system's freeze interval.

Original collection succeeds. Both Linux supervisor children exit zero, the
supervisor accepts its device recorder/command lifecycle, and cleanup reports
no errors. The strict overall task nevertheless exits nonzero because the Mac
window is discontinuous. Its separate `tcp-partial-report.json` correctly keeps
`metadata_valid=false`, qualifies only Mac segment 1 and Linux segment 0, and
matches five later handshakes/greeting prefixes to unique USB tunnel spans.
This qualifies bounded recovery and those positive observations for this run;
it does not convert the gap into continuous coverage or prove repeatability.

## Post-return SSH setup failure

The validated host timing has one PM submission and ten collection attempts.
Three unsuccessful forwarded-channel attempts lie wholly before PM return.
The first post-return attempt also fails, this time during device SSH setup.

The shortest device-clock bracket is span 104, width 0.635527333 seconds.
Relative timing below uses BOOTTIME/host-monotonic bracketing; it does not
assume identical clocks or report these observations as wake latency.

| Observation | Start after PM return | End after PM return |
| --- | --- | --- |
| First post-return collection, span 77 | 0.648–1.284 s | 14.163–14.798 s |
| Failed device SSH setup, span 83 | 4.146–4.782 s | 14.162–14.798 s |
| Next collection, span 85, succeeds | 19.165–19.801 s | 22.349–22.985 s |

Within span 77, the Mac's forwarded-channel operation finishes successfully in
3.170 seconds. The following device SSH setup lasts 10.016 seconds and exits
with the original `No existing session` error. Its pre-cleanup state reports
no server greeting, no completed initial key exchange and no authentication,
while the transport still reports active. This is a setup timeout before an
observed greeting, not an explicit banner-parser error or a proven server fault.

The flow uniquely associated with tunnel span 82 contains two client SYN
observations at each endpoint, with the same client sequence identity. Neither
side establishes a server sequence identity or greeting for that flow in the
saved report. The five later matched flows associate with spans 90, 102, 114,
126 and 147. Matching the failed flow's client requests does not supply its
missing handshake; the report leaves it unqualified.

This narrows the next investigation to the relationship between forwarded
channel completion, TCP establishment and the captured observations. It does
not demonstrate that a complete connection existed but sshd withheld its
greeting, nor that a specific driver lost packets. Capture completeness and
forwarding semantics require further scrutiny before selecting a fix. No SSH
timeout/retry settings or network policy are altered.

Private `.local/neo147-timing-analysis.json` preserves the relative bounds and
clock sample. The original host timing, errors and packet metadata remain
unchanged. Raw network identities and credentials are not included in this report.

## Final state and next work

Final read-only inspection `20261008T062820.928290Z/inspection.json` passes full
PM health and continuation validation at PM10/0. Both temporary Linux services
are inactive/not-found. The Mac recorder has finalized. The owner confirms the
normal dim console; USB stays connected and no further display test runs.

The predecessor continuation is consumed once. The current unused successor is
`20261008T062557.111288Z/qualification-next.json`, retaining rehearsal
`e1afea155b864a79b04bb133496e4e26`. Validate live state before future reuse and
obtain fresh readiness before any new PM test.

NEO-147's single-run recorder recovery qualification is complete. NEO-148 tracks
the remaining SSH setup investigation: audit forwarding and capture semantics
offline, correlate saved server evidence, and prepare minimal socket/forwarding
observations with awake controls. The next investigation can begin without
physical input. Repetition, host sleep, CPU retention and energy qualification
remain separate; this slice changes no image, driver, firmware or runtime policy.

## Evidence identities

Paths are beneath the attended capture unless stated otherwise.

| Artifact | SHA-256 |
| --- | --- |
| `result.json` | `eaaa369a8120b58fb785aa440684a216f1efe14bfad00b30354e1426b9bbbab1` |
| `host-timing.jsonl` | `2b90b2a77806bd182f3eb536b15ef666eb5ab880300e686dbd6be2bedb2b32fe` |
| `qualification-next.json` | `20af0278add9c515d1de05b32b661068d649efb33f4aee949b33918002ff2327` |
| `tcp-run.json` | `543b852681e952c64fc85ecc9f8668da937835c2ac58500a093353c29c720b80` |
| `tcp-mac/result.json` | `d786f787dae805da905867e7156aec12027117fcb6eaf941c9432512d6e5102c` |
| `tcp-mac/packets.jsonl` | `27401fdd39ccafe5ea5faa3b12059bec6820228caa71e8c97ab5682e12bfb18f` |
| `tcp-device/result.json` | `4f9cdcfa22e3f0cc72bca64a43099787577d27d95c25dce056457e1233b8ad57` |
| `tcp-device/packets.jsonl` | `c7d05677b8cca38dfd832075246b60f17ce7eec1486d5d57aa56a129bab5f3d3` |
| `tcp-device/supervisor.json` | `9b299ca234c1ef7322dc0999ff0bdb2fc799ca5c15e33773dd5fbcc5835143eb` |
| `tcp-partial-report.json` | `3237949626b74ec61ca48b702471c9788b593eff3da8f0f868ca1d36ce5c0b21` |
| Final PM inspection | `387dd50e92394ed3829129ed6c666ed081b84d28804435bb0e6cbd1a25e49f2b` |
| `.local/neo147-final-admission.json` | `227f84568aed0828240502ec7bc76d9723443a1a0a4d7455871fb12f95d567ea` |
| `.local/neo147-owner-observation.json` | `1d53e463c61a94fe8ea97100ed73aca96eac08eb6e3cf6a3f65699fe68024e0a` |
| `.local/neo147-timing-analysis.json` | `ad481fdbb3c5b19d74d5259429baf17431022e30b6d8bf6ae869f6f70202f2dc` |
