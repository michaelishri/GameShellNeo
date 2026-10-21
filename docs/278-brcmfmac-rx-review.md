# brcmfmac RX candidate review and offline acceptance

12 October 2026 NZDT. NEO-195 and NEO-196. The two tickets' isolated software
candidate scope is complete. Image integration and matching hardware
qualification remain with NEO-58; neither the installed GameShell nor the
verified diagnostic.26 image was changed.

The combined review was pinned to
`git diff fa2a95dee2a694b8dd6cdda10e896a8843a8b9e7...a45d70ab06df0769e869fe48bd5ebfa77540d525`.
It covers commits `c42949e`, `9c4f16e` and `a45d70a`: candidate 0046's recovery
error ownership, 0047's malformed-packet corrections and 0048's control-response
retry framing, with their saved tests and reports. Two independent reviewers
checked repository standards and the current Kaneo ticket requirements.

## Standards

No documented-standard violations found. Changes address driver causes and
keep qualification claims within evidence, consistent with `AGENTS.md`.
Hardware qualification is explicitly pending.

The original review made two low-priority judgement calls:

1. Possible **Duplicated Code**: the packet and control negative-test runners
   repeated mutation, compilation, execution, assertion checking, restoration
   and receipt writing. Extracting one runner would avoid drift.
2. Possible **Primitive Obsession**: glom tests used unnamed scenario integers,
   for example `kind == 3 || kind == 4 || kind == 12`, with related arithmetic
   in CLI dispatch. Named scenarios would make coverage easier to audit.

Both are resolved in the follow-up. `run_negative_cases()` shares the mutation
runner while retaining separate receipts and unconditional source restoration.
An enum and named dispatch tables replace the glom scenario integers. A new
`test:brcmfmac-control-rx-mailbox` task exposes the existing combined suite
without requiring full driver recompilation. The standards reviewer checked
this follow-up and found no new violations or substantive smells.

**Standards total: zero hard violations; two low-priority suggestions resolved;
no outstanding finding.**

## Spec

No Spec findings.

- No missing or partially implemented requirement in the tickets' offline
  candidate scope. Recovery retains the first cleanup failure, stops later
  receive work, clears pending lengths and reaches worker quarantine after
  caller buffer cleanup. The successful flush budget remains unchanged.
- Control allocation failure requests recovery; successful retransmission
  forces a fresh header read. Existing response ownership and ordinary
  successful next-frame hints are preserved.
- No unrequested scope creep. The malformed-packet fixes address findings
  from the requested caller audit and remain isolated companion candidates.
- No apparently implemented requirement was found semantically incorrect in
  the complete applied source.

The harnesses support the documented offline claims. Packet operations,
transport, firmware replay and the worker receive boundary remain controlled
seams; they do not establish hardware behavior or full-kernel concurrency.
Reports 276–277 state those limits. Both tickets have sufficient offline
implementation and qualification for closure; integration/image/hardware
qualification remains separate as specified.

The follow-up review confirmed all CLI mappings, fatal/nonfatal variants,
packet mutations, delivery expectations and packet-pull guards are preserved.
Mutations still start from the original source, require assertion failures,
retain artifacts and restore generated source even after compilation/execution
failure. No production patch changed.

**Spec total: zero findings in either review; no outstanding finding.**

## Acceptance evidence

| Requirement | Evidence and result |
| --- | --- |
| First abort/terminate/count/NAK failure, exhaustion and duplicate cleanup | [Report 275](275-brcmfmac-rx-recovery.md): 44 native/ARM helper scenarios, 13 rejected mutations, established successful poll budget retained. |
| Parser/control/glom/readframes ownership and worker ordering | [Report 276](276-brcmfmac-rx-caller-qualification.md): reproduced packet leak/parser-output defects, isolated 0047 correction, 53 packet cases, worker quarantine and successful TX cases. |
| Control allocation/body-retry framing and successful response ownership | [Report 277](277-brcmfmac-control-rx-recovery.md): original 71/115 baseline retained; 62 additional byte-position FIFO cases and five rejected control mutations. |
| Native, sanitizer, ARM and mailbox combination | Both final follow-up runs pass 115/115 packet cases in each execution mode, four packet and five control mutations, worker suites and their 33/45 mutations. |
| Complete affected ARM objects | Four board/debug objects passed before the fixture cleanup. The complete applied source-tree identity, patch queue and kernel configuration are unchanged; all four objects were rehashed after the cleanup. |
| Review and reproducibility | Independent Standards/Spec reviews above; all commands are saved Tasks. Candidate patches remain outside the image queue. |

Run the follow-up suites with:

```sh
task test:brcmfmac-control-rx
task test:brcmfmac-control-rx-mailbox
```

Evidence lives under `.local/build/brcmfmac-rx-callers/attempts/`:

| Configuration | Follow-up attempt | Manifest SHA-256 |
| --- | --- | --- |
| RX candidates | `99f1990cd01f4d9dbf3fa0cc47d892ca` | `24d001310b931e30342ea585093e4d42807039d8a9a4d9ad4e19c317419ed259` |
| RX plus mailbox candidate | `660569c7a1344de0acf45cedcdfa3922` | `a365c94a6d3b96ddc7c55c1adecc977c94bb2f614e3e53f615fcebd1acd12b6c` |

The first cleanup attempt, `768edb07604142d8a86bf2df6a43a757`, stopped at native
compilation because the fixture lacked its new `ARRAY_SIZE` macro. That test
header omission was corrected before the final runs; the failed log remains
preserved. It was not a driver build or hardware failure.

The final verification rehashed all 553/601 artifacts in each old and new
attempt, checked every current input against the new manifests, and compared
all extracted production bodies. Exactly two recorded inputs changed: the
packet test harness and its Python runner. Source identities are still
`c200c0ce3353633c2dbf42dd8dcafeb040b51d8d70b8941a241f53b2ecf8f064`
and `ad3e06d853e81481c875b71af64cbaf9ab8ace174efefe5c311041395d7dd6bc`.
The four full objects and their `.config` hashes still match report 277.
This links the earlier object builds to unchanged production inputs rather
than claiming the fixture reruns rebuilt the driver.

The private `review-cleanup-verification.json` receipt has SHA-256
`6c8460b3e3aba3c6c9aaede0804600fdd7f1965b79fb8013d587815e0ad1036a`.

## Remaining parent work

NEO-58 remains open. The reviewed candidates need deliberate image integration
and matching board qualification, including the firmware retransmission
boundary. The separate transmit-recovery, missing clock-ready notification
and reset/reprobe ownership leads are not resolved by these RX fixes. No
claim follows about the earlier authentication delay, the clock regression,
measured power savings or RF reliability. NEO-154's abandoned SSH-stall work
has not been resumed.
