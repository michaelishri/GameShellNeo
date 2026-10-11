# brcmfmac control-response allocation and retry framing

12 October 2026 NZDT. NEO-196, continuing NEO-58 and the isolated RX candidates
in [report 276](276-brcmfmac-rx-caller-qualification.md). This work uses the
locked Linux 6.18.54 source. No GameShell, firmware or power setting changes.

## Two reproduced source defects

`brcmf_sdio_readframes()` reads `BRCMF_FIRSTREAD` bytes before calling
`brcmf_sdio_read_control()`. In this source, that initial read is **64 bytes**.
If the response-buffer allocation fails, `read_control()` formerly went
directly to its wake/free exit. It neither flushed the remaining response nor
requested a retry. Its caller then selected the following frame's advertised
length. In the modeled 96-byte response, the retained FIFO position is 64/96,
with no recovery operation, no NAK and an inappropriate next-frame length of 64.

A related existing problem occurs after a control-body read error. The abort,
flush and NAK can succeed, but `readframes()` overwrites the helper's cleared
current length with the hint for the *following* frame. When the firmware
retransmits the current response, the caller can enter readahead with that
wrong hint instead of reading its header afresh. The reproduction records a
fully flushed FIFO and successful NAK, yet the pending receive length is still
64 instead of zero.

The native baseline with 0046/0047 and without 0048 passes **71/115 cases**.
All 40 allocation/unavailable-buffer cases, two successful body-error recovery
cases and both repeated-allocation-failure cases reject the old behavior.
Ordinary successful control responses and the existing 53 packet cases pass.
Original attempts are retained under `.local/build/brcmfmac-rx-callers/attempts/`:
`b0a8fb18f14f4789bcf94681831fad63` is the initial reproduction, and
`ad84e8c2813943ac89f83907f03dd958` uses the final assertion order, checking
framing/recovery before the ancillary error counter. Neither is relabeled as
a passing qualification.

## Candidate and ownership

[Candidate 0048](../kernel/candidates/0048-brcmfmac-control-rx-retry.patch)
adds the established flush/NAK recovery on allocation failure and counts the
failed control receive. There is no failed in-flight transfer in that branch,
so it does not issue an unnecessary CMD52 abort. Failure during recovery still
flows through 0046's original-error latch and worker quarantine. An already
published response remains owned by its existing consumer.

When a control path requests retransmission, the caller now leaves its next
read length zero, forcing a fresh header read. It still retains the advertised
next-frame hint on a successful ordinary control receive. The correction also
covers the existing body-transfer-error retry, rather than fixing allocation
alone. No extra polling loop, sleep, userspace retry or firmware reset is added.

Requesting a retry even for a short, already-read control response follows the
existing driver's control readahead failure policy: that path also requests
NAK after receiving a complete response it cannot accept. The FIFO and replay
model tests this intended interface; it does not inspect proprietary firmware
implementation or establish physical FIFO/NAK behavior on the board.

## Saved tests and their boundaries

```sh
# Deliberately fails assertions against the source without 0048:
task test:brcmfmac-control-rx-baseline

task test:brcmfmac-control-rx
task check:brcmfmac-control-rx-drivers
```

The baseline command preserves its failing case logs. The candidate commands
include native, native AddressSanitizer/UndefinedBehaviorSanitizer and ARM32
tests. The driver command additionally builds full board/debug ARM brcmfmac
objects and repeats with candidate 0039's mailbox fix. The locked Docker
builder has networking disabled; these are offline commands.

The packet harness now has an optional byte-position FIFO mode rather than
treating a header read as consumption of the whole frame. It includes a control
response and a following data frame, advances by bytes transferred, models a
partially completed failed body read, and flushes the remaining current frame
only after a successful terminate operation. Failed recovery permits no later
I/O. A scripted firmware-replay/mailbox-acknowledgement boundary re-enables
reception; the actual header parser and receive caller must then recover the
control payload and deliver the following data packet correctly.

The **62 added cases**, alongside the existing 53, cover:

- 40 allocation/unavailable-buffer cases: short/full-body response, existing
  published response or none, allocation failure or zero `rxblen`, and success
  or failures at terminate, count-high, count-low and NAK.
- 12 partial body-transfer errors: with/without a published response, recovery
  success and each abort/terminate/count/NAK failure.
- Eight successful receives: short/full-body, busy/free response slot and
  present/absent next-frame hint. Successful readahead remains enabled.
- Two repeated shortages: three failed allocations with acknowledged retries,
  followed by a successful response and next data frame, for both lengths.

Assertions check FIFO position, payload, pending response identity/content,
allocation/free balance, host ownership, original fatal errno, no further I/O,
retry admission, next-read metadata and error accounting. Five new negative
controls remove allocation recovery, retry-header clearing, successful hints,
pending-response ownership or allocation-error accounting. Existing packet and
worker fault suites are retained. Hardware transfer, allocation, packet-list
and firmware-replay operations remain controlled test boundaries; these tests
do not establish physical RF reliability or whole-kernel concurrency.

## Qualification status

Both the standalone candidate and its combination with mailbox candidate 0039
pass **115/115 packet cases** natively, under native ASan/UBSan with leak
detection, and on ARM32. Four packet and five control-FIFO negative controls
are rejected. Existing worker suites also pass: 65/67 normal/debug cases and
33 negative controls without 0039, or 147/149 cases and 45 negative controls
with it. Complete board/debug ARM `brcmfmac.o` builds pass in both combinations,
with no compiler warnings or errors. Checkpatch is clean for 0048.

| Configuration | Attempt | Evidence SHA-256 |
| --- | --- | --- |
| 0046 + 0047 + 0048 | `98efd5c6de884481ac66b6a320739489` | `f98df31703b7bf464177cd49f392680637336dc536e5baac44e65cc1524e5a85` |
| Same plus 0039 | `9a4407cfc485431fbe21afe390e6841c` | `23f10ff365e992e59faedcebaff5a7b0e0592d82c1902d43dab50f0111fe8a0c` |

The attempt root is `.local/build/brcmfmac-rx-callers/attempts/`. All recorded
inputs, 553/601 retained artifacts respectively, and four driver objects were
rehashed successfully after both commands finished. No code or candidate input
changed afterward. Candidate 0048 has SHA-256
`a8a21a9c6ee4804e697a3fdfb634ef01d26dc25248aa8ec000982a20313be53c`.
The additional `control-final-verification.json` receipt has SHA-256
`6bbb4c7929d580872cf6040a75faf48fd25bb8ec6670517b74d2aaa18617bab7`.

| Full ARM object | SHA-256 |
| --- | --- |
| Control RX board | `9a01bc65cba056d9892f4e9beca4628842fd645306bd53cf591e08f9a5cfb2d5` |
| Control RX debug | `40197ce805cb1ee0e8053d564a24b469d7c2a9fb1cb7f45d41abdd40d874499f` |
| Control RX + mailbox board | `c8f3edf1dd0847e9a3386133dd1c9fdcf6ee6910c2bbb1d4f01df4ed76236cf9` |
| Control RX + mailbox debug | `4aed3aef094126d4ff21fd99209a863c274e94b38e8b40143bde4723d7dcb992` |

The offline candidate scope is ready for review. The original baseline failures
remain preserved; the successful candidate runs do not alter their results.

This does not explain NEO-55's authentication delay or the clock regression.
Review, integration and matching image/hardware qualification remain separate.
