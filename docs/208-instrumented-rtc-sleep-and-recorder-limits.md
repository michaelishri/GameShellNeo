# Instrumented RTC sleep and recorder limits

8 October 2026; capture timestamps are UTC. NEO-145's attended actual sleep
passes functional RTC wake and device recovery. Both network routes recover;
the owner confirms a clear long warning and the untouched normal dim-console
return. The TCP metadata qualification fails separately: the Mac recorder
exits during sleep entry, and the GameShell recorder reports dropped packets.
The original results remain separate and no sleep is repeated to mask either
outcome.

Diagnostic.23/kernel `6.18.54-gameshellneo22` remains on boot
`cc26703f-d9ef-4d71-8da1-9d766f3efdbe`. PM advances from 8/0 to 9/0: seven
debug stages and two actual RTC sleeps on this boot. PM counters include the
debug stages; they are not a count of nine actual sleeps.

## Attended operation

After the owner supplied fresh watching/listening readiness, the saved command
ran once using [report 207's corrected observer ownership](207-ssh-observer-sleep-unit-integration.md):

```sh
task device:ssh-trace-sleep \
  QUALIFICATION=.local/diagnostics/20261008T010429.034673Z/qualification-next.json \
  REHEARSAL=e1afea155b864a79b04bb133496e4e26 ATTENDED=1
```

Capture `.local/diagnostics/20261008T054356.540135Z/` contains sleep run
`ad1c0702304944aaa193031cb74c0782` and recorder identity
`51f1e261b7434de79823e847016da180`. The original `result.json` passes complete
source, history, process-memory, keypad retention, restoration, RTC and trace
validation. Both independent USB/Wi-Fi proofs pass. SDIO runtime usage remains
2, with the original on/active/forbidden policy. POWER ownership, diagnostic
controls, RTC ownership and console ownership are released.

The one-second level-5 warning passes playback/restoration checks and the
owner confirms hearing it. Their observation is recorded separately in
`.local/neo145-owner-observation.json`, bound to the original result hash.

| Measurement | Result |
| --- | ---: |
| Alarm elapsed time | 32.492 seconds |
| PM call, BOOTTIME | 31.725 seconds |
| Traced s2idle boundary, MONOTONIC | 29.250 seconds |
| Observed timekeeping-freeze pairs | 0 |
| Functional RTC wake / both routes | Pass |
| CPU retention / energy savings | Unqualified |

The existing `report:sleep-evidence` task independently passes RTC/trace/clock
assessment and saves it under `20261008T054655.536898Z/`. That offline report
does not rewrite or requalify the original PM result.

## Host connection evidence

`device:ssh-timing-report` validates the complete host trace. There is exactly
one PM submission, eleven original-result collection attempts, and three
failed forwarded TCP-channel openings. All recorded Mac/device SSH protocol
observations are complete and authenticated; no SSH greeting timeout is
observed in this run. Eight collection attempts succeed, including in-progress
snapshots and the final result.

Using the same BOOTTIME/host-monotonic bracketing method as report 205, the
shortest post-return clock bracket is span 108, width 0.636772498 seconds.
The failed attempts lie wholly before PM return:

| Collection span | Duration | Start relative to return | End relative to return |
| --- | ---: | ---: | ---: |
| 56 | 10.477 s | −27.753 to −27.116 s | −17.275 to −16.639 s |
| 63 | 0.716 s | −12.275 to −11.638 s | −11.559 to −10.922 s |
| 70 | 1.741 s | −6.559 to −5.922 s | −4.818 to −4.181 s |

The first post-return attempt succeeds. Its start is 0.183–0.820 seconds after
return, and its clock command completes 9.427–10.064 seconds after return.
This includes connection and command work and instrumentation overhead; it is
not exact network-ready time, screen wake latency or evidence of a regression.
The successful device SSH setup in that attempt takes 4.161 seconds. Neither
it nor the earlier unavailable TCP channels establishes the cause of the
historical post-return greeting failure.

Bounds assume negligible short-term relative clock drift. The private
`.local/neo145-sleep-analysis.json` retains every collection interval and the
clock sample used, without changing the recorded events.

## Recorder outcome

Both original recorder outputs are retrieved, with matching content digests.
Collection success means that the files were obtained; it does not mean their
capture windows are complete. The strict offline flow report correctly rejects
these files, so no successful whole-window flow correlation is claimed.

| Recorder | Saved packets | Reads | Recorded bytes | Outcome |
| --- | ---: | ---: | ---: | --- |
| Mac | 1,773 | 1,773 | 572,856 | RuntimeError; no final capture statistics or final interface index |
| GameShell | 4,329 | 4,416 | 1,412,866 | Explicit stop; 538 socket-capture drops out of 4,954 reported received |

Both record zero rejected packet headers. The GameShell's interface index
remains 4. Its recorder process exits zero after writing its failure outcome;
the supervisor correctly records `passed=false` because recorder acceptance
failed, despite the original diagnostic command and recorder processes both
exiting zero. Supervisor cleanup reports no errors.

The Mac recorder ends after 23.715 seconds. Combining its original host/Mac
clock anchors with the device-return bracket places its end approximately
0.534–1.506 seconds after PM entry, or 31.191–30.219 seconds before PM return.
Those bounds include the existing 50 ms host/Mac allowance. It therefore did
not record the recovery window. The timing is consistent with a capture-handle
problem at USB suspend, but the precise libpcap error was not retained and the
cause is not proven. Do not describe this as a new USB driver failure.

The Linux drop count belongs to the diagnostic packet socket. It is not proof
that USB or TCP lost the corresponding network packets. Its aggregate counter
does not identify when or why it overflowed. The original PM result is
1,296,449 bytes, and repeated evidence transfers create substantially more
recording work than the small awake SSH probes. Capture/serialization pressure
and buffering deserve an awake reproduction; neither is an established cause
of the drops. A recorder that freezes with userspace also needs explicit
coverage limits during suspend.

No missing greeting, wire-loss claim or post-return cause can be inferred from
these incomplete captures. The recorder's drop/error gates were not relaxed.

## Final state and next work

Final inspection `.local/diagnostics/20261008T054655.581461Z/inspection.json`
passes full PM health and continuation validation at unchanged boot/PM9/0.
Both transient Linux services are inactive and no longer loaded. The Mac
recorder has exited with its original error and its files are retained. No
further display or sleep test is running.

The old continuation was consumed exactly once. The current unused receipt is
`20261008T054356.540135Z/qualification-next.json`, retaining original rehearsal
`e1afea155b864a79b04bb133496e4e26`. Recheck live state before any reuse and obtain
fresh observer readiness. No image, driver, firmware, SSH retry/timeout or
charging-policy change was made in this test.

The next recorder work needs no initial physical interaction:

1. Preserve fixed-label backend/error-phase information and explicit coverage
   gaps when the Mac interface or capture handle becomes unavailable. If a
   bounded reopen is implemented, keep segment identities and never imply
   continuous coverage across a gap.
2. Reproduce capture pressure with a repeatable awake transfer test. Measure
   filtering, effective per-socket buffering and handshake-focused record
   selection before choosing changes; avoid global network-policy tuning.
3. Validate bounded cleanup, original-result preservation and packet-loss
   reporting, then schedule one separately attended sleep. Successful PM and
   successful observation remain independent verdicts.

## Evidence identities

All paths below are beneath the actual-sleep capture unless otherwise noted.
Private addresses, ports, packet headers and raw logs remain ignored locally.

| Artifact | SHA-256 |
| --- | --- |
| `result.json` | `caf041bd42babf8bc40f2c4ef584b970e0f2bba8d52379e32349782182d3168e` |
| `host-timing.jsonl` | `a7be51d5afc47bb1964d4ee2640ddae2e6311798f22d1133d8e636de2e06fad2` |
| `qualification-next.json` | `c492d7f835b2c9f1f309874e39d6538d67ea09f68f03f0f2931be3a614128af8` |
| `tcp-run.json` | `cbacdb2418d83be9dad3806d4aa27ae4bca0523b4fb31d8b1f384209e7249c47` |
| `tcp-mac/result.json` | `c93c1695d63ea6085e8b9510d785f7d509c11a6098e640ddcfda0327d10c6317` |
| `tcp-mac/packets.jsonl` | `63084598166abc3bc596ac9c7e21fe622345e029b15e741410f01481a1473a6f` |
| `tcp-device/result.json` | `245112f47b714334c6ba5c52ff41572e3f6946649a71a194995f5dc5dd270bc1` |
| `tcp-device/packets.jsonl` | `b69b58f82d0ffe09dba0076183f5077f6f6c5c098a87b2c998fc42a8ae418dd8` |
| `tcp-device/supervisor.json` | `3647dd0c3fb3866d77bc0804292cef5436b50482788cd37e3aa15022452d1c6b` |
| Final PM inspection | `bb771ef8b1db2dee3c02075af35cb338f8ca1d3b87f575fcfcc6c0e85c0ff72c` |
| `.local/neo145-sleep-analysis.json` | `cc0f9902aaa1f8d12b5de5e446a67dfca9954840ff47cc37d188cd267a8fe6d3` |
| `.local/neo145-integrated-admission.json` | `4e98d7e1a9543970e6e54cf8f586bce8441988e29034fe0948dd77c842d4defd` |
