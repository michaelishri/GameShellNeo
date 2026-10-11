# brcmfmac RX packet cleanup and worker qualification

12 October 2026 NZDT. NEO-195, continuing
[report 275](275-brcmfmac-rx-recovery.md). The packet tests reproduce both
previously identified source defects. Candidate 0047 repairs them alongside
0046's recovery-error ownership. Both remain isolated from diagnostic.26.

## Reproductions and corrections

The original 31-case packet run with candidate 0046 passes 27 cases. Both
glom-without-descriptor cases leak their allocated packet, whether FIFO recovery
succeeds or fails. Both bad-superframe-checksum cases attempt to pull the packet
using parser outputs after parsing failed. The exact assertion logs and original
binary are retained under
`.local/build/brcmfmac-rx-callers/attempts/4dd05b7c6e204d8aa0f37cf9904d37bd/`.

[Candidate 0047](../kernel/candidates/0047-brcmfmac-rx-packet-errors.patch)
frees the unowned packet before the missing-descriptor branch continues. In
`rxglom`, it publishes the next-frame length and removes the superframe header
only after a successful parse. Failed parsing proceeds through the existing
error cleanup, which frees the entire chain. It does not merely initialize
invalid outputs and continue using them. Successful packet handling is retained.

## Repeatable qualification

```sh
task test:brcmfmac-rx-callers
task check:brcmfmac-rx-callers-drivers
```

The first command runs the packet and worker suites natively, with native
AddressSanitizer/UndefinedBehaviorSanitizer, and on ARM32 through QEMU user
emulation. The second adds full board/debug ARM driver builds, then repeats
qualification with the prepared mailbox candidate 0039. Docker networking is
disabled and the locked builder is used. Each invocation retains its original
attempt directory, inputs, generated sources, compiler logs, binaries, case
logs and hash manifest. Neither command contacts the GameShell.

The actual `readframes`, `read_control`, `rxglom`, header parser, abort and
recovery function bodies are extracted from the verified full kernel patch
queue. Packet allocation/list operations and synchronous SDIO transfers are
controlled boundaries. The buffer model records ownership, freeing, bounds and
host-lock balance; invalid superframe tests prohibit packet pulls after a failed
parse. A two-packet case rejects a malformed second header before delivering
either packet. Descriptor allocation failures exercise partial-chain cleanup.

The **53 packet cases** cover normal/header-first and readahead data,
control responses, missing descriptors, malformed superframe and subframe
headers, successful one/two-packet gloms, descriptor allocation/length failures,
and a pre-existing fatal error. Recovery failures preserve their errno, clear
partial/next-frame state and issue no subsequent SDIO operation. Successful
recovery remains recoverable. Four deliberately broken packet variants must
fail assertions: missing free, missing parse-result gate, continued receive
after fatal recovery, and uncleared next-frame state.

A second harness runs the actual ISR, status reader, DPC, worker, failure
cleanup and IRQ-quiesce bodies. Its receive boundary simulates completion with
or without a fatal recovery result; packet cleanup itself is covered by the
separate actual-caller harness. Sixteen additional worker cases combine success
or three errors with OOB/in-band ownership and hard/process IRQ dispatch.
Control and data transmission are pending in every case. Fatal recovery must
reclaim the SDIO host, stop the watchdog, retire IRQ delivery, complete waiting
control operations with the original error, and prevent further TX/IRQ work.
Already-queued work cannot repeat cleanup. Success must actually transmit the
pending control and data work, rather than achieve safety by always stopping.

The normal/debug worker suites contain **65/67 cases** without candidate 0039,
and **147/149** with its complete mailbox coverage. There are **33/45** rejected
worker negative controls respectively, including removal of the RX-to-worker
error exit and its host reacquisition. These are ordered boundary tests, not a
claim of complete-kernel scheduler or hardware concurrency coverage.

## Evidence and remaining scope

The first corrected native run passes all 53 packet cases. Its sanitizer stage
cannot run under the sandbox's ptrace environment: LeakSanitizer reports its
own fatal environment error in all cases. That failed attempt remains intact
at `bb7fee5549a04f839eec8260ab58e233`. The subsequent permitted offline run
passes all native sanitizer cases without disabling leak detection.

Both configurations pass all native/ARM and sanitizer cases, all negative
controls, and their complete board/debug ARM `brcmfmac.o` builds. No compiler
warnings or errors were recorded. Final attempt directories under the same
`.local/build/brcmfmac-rx-callers/attempts/` root are:

| Configuration | Attempt | Evidence SHA-256 |
| --- | --- | --- |
| 0046 + 0047 | `33f22187170146b6af56963ee5bc3c78` | `5252201fee78d2864164183e22ffa80255b695538176ee918a0feb168f3ba383` |
| 0046 + 0047 + 0039 | `458f443ac3694d9f80edb087b27cde3b` | `bd732e3d3ff61fdbe7bd88a5b732e8e69bb5d268d228544d65774451ed55f485` |

All 346/394 retained artifacts respectively, test inputs and four driver
objects were rehashed successfully. The abort/recovery function bodies and
register definitions are byte-identical to the separately qualified helper
suite in report 275: its 44 native/ARM scenarios and 13 negative controls remain
the operation-level evidence, not a replaced or newly repeated matrix.

| Full ARM object | SHA-256 |
| --- | --- |
| RX board | `4ff04e5ffb1204de7000981b776ed90d17a2033e102c1f2038f672127afeea2f` |
| RX debug | `648d6d011e3aaa077c13c6d895bb658e8931224b7bfb1f07129b53daf7d0fec7` |
| RX + mailbox board | `8d082b08e2b58ebc6e69339a9e65a1b58cdee81e5b55fa42639989e48e8947c7` |
| RX + mailbox debug | `b4a2a88e0f51dd58b6d2d4037f236602fde04efe085bba2c7b73288a92101dee` |

After testing, only 0047's patch-message prose was wrapped to satisfy
checkpatch; its complete applied diff is byte-identical. The tested patch is
retained, and `.local/build/brcmfmac-rx-callers/final-verification.json` records
the old/final hashes and payload equality. That receipt has SHA-256
`195a306dfae36782216be01f0cbab5896c16001eab0700df35270809f22e1432`;
the final patch hash is
`2d601a9dce7493bfd07a8b5baec39c8c4303888982c54611e8c199e3a24eeafb`.
Checkpatch reports zero errors and warnings. No driver code changed after
qualification. NEO-195 is ready for review, with image/hardware work distinct.

NEO-196 separately tracks control-buffer allocation failure after the frame
header has been read. The current scripted frame boundary does not prove FIFO
byte-position recovery for that path. `CLK_PENDING` deadlines, transmit-error
cleanup, reset/reprobe ownership and the original NEO-55 authentication delay
also remain separate. No RF robustness, energy saving, installed-image behavior
or resolution of the clock fault is inferred from these source tests. Review,
image integration and matching hardware qualification remain necessary.
