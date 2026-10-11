# brcmfmac watchdog failure and late-work ownership

12 October 2026 NZDT. NEO-199 continues NEO-58 after the reviewed
[queued-TX polling fix](281-brcmfmac-tx-poll-errors.md). Source: locked Linux
6.18.54 with the image queue and isolated mailbox/RX/TX candidates through
0050. Neither the GameShell nor diagnostic.26 is changed.

## Source findings

`brcmf_sdio_bus_watchdog()` previously discarded the CCCR interrupt-pending
read's error, ignored a failed console wake before reading the console, and
discarded an idle sleep failure after stopping its timer. Its caller checks
`brcmf_sdiod_io_blocked()`, but another host claimant can report a failure
after that check and before any of the watchdog's later host acquisitions.
The outer check alone therefore does not exclude later hardware accesses.

Console errors need classification at their source. The same return channel
from `brcmf_sdio_readconsole()` carries RAM transport errors, allocation failure
and an invalid index in the console buffer. Treating every negative return as
a bus failure would disable Wi-Fi for local diagnostic failures. Conversely,
ignoring every return except to disable logging permits idle I/O after an
unverified transport operation.

There is also a publication boundary: a successful poll previously released
the host before publishing pending status and queueing work. A different
claimant can retire the bus in that interval, after which the watchdog can
publish stale pending status and enqueue unnecessary work. The existing worker
admission gate can prevent further I/O, but does not make this publication
ordering correct.

## Candidate and saved commands

[Candidate 0051](../kernel/candidates/0051-brcmfmac-watchdog-errors.patch)
rechecks admission under the host claim at each polling, console and idle
operation. New failures use the existing host-held error cleanup: preserve the
first error, stop the timer, retire IRQs and complete control/response waiters
once. An already-blocked admission returns without inventing a different
error or repeating another owner's cleanup.

Successful polling publishes pending status and queues work before releasing
the host, serialized with other claimants' failure cleanup. A release-boundary
fixture forces another claimant to retire the bus immediately afterward; this
must leave no stale pending status or post-retirement publication.

The console helper reports transport errors separately through an output
parameter. The RAM helper now reports its packet-buffer allocation failure
as `-ENOMEM`, rather than `-EIO`; console RAM resource failures leave that
transport-error output clear. Allocation/index failures retain the behavior of
disabling console polling while leaving healthy Wi-Fi operational. Successful
console reads, pending-work handling, save/restore mode and idle scheduling
remain part of the regression contract.

```sh
# Intentional assertion failures before the candidate:
task test:brcmfmac-watchdog-baseline

task test:brcmfmac-watchdog
task check:brcmfmac-watchdog-drivers
```

These Tasks reuse the existing TX/RX/worker runner and locked, network-disabled
builder. Source, inputs, per-case logs, generated driver bodies, binaries and
receipts are retained per attempt. The watchdog/console/cleanup/timer bodies
and their relevant structures/constants are extracted from the applied source.
The candidate must remain outside the image queue.

## Initial reproduction

Attempt `df9a65139eba4ca0be0a277487cff162` under
`.local/build/brcmfmac-watchdog/attempts/` passes **20/47 normal** and
**33/101 debug** cases. Poll failures, idle failures, prior-error/PM-failure
admission and debug console transport failures are rejected; successful paths
and local console failures pass. Original assertion logs are preserved.

The first candidate attempt is `3e58f67ec0124e169b169900affc6013`. It covers
those original cases, before extending qualification to the publication race
and a console failure after successful polling has already queued work.
Its results must not be treated as qualification of those later additions.
It passed the initial normal/debug native, sanitizer and ARM cases, the
original mutations, combined TX/RX/worker regressions and both full objects.
Its original patch is retained privately in `revisions/initial-0051.patch`.

The expanded baseline `62cafdf8b26f491493a6b8045b289933` passes **20/50 normal**
and **33/131 debug** cases. Its three new retirement-boundary cases and 27
console failures after already-queued polling work fail as expected. Successful
paths and local-error preservation still pass. The revised candidate's full
qualification will use these expanded counts.

## Expanded candidate qualification

Attempt `44796ea271694efc96f3e5fefd9da8d3` completed the full driver Task:

- All 50 normal / 131 debug watchdog cases pass natively, with ASan/UBSan and
  leak detection, and on ARM32. All 17 watchdog mutations fail assertions.
- All 215 TX and 115 RX cases pass in those three modes. The 23 TX mutations,
  four packet mutations and five control-FIFO mutations are rejected.
- All 211 normal / 213 debug worker cases pass in those three modes, with
  48 worker mutations rejected.
- Both complete ARM `brcmfmac.o` objects build successfully.

A checkpatch indentation correction was qualified by completed attempt
`2c21befc166d4cd99120569b33476bc9`, with the same full passing counts. Neither
of these attempts covers the later RAM-resource correction described below.

## Review finding and stronger reproduction

Independent review of `1898229...6066ede` found one Spec defect. The fixture
replaced the entire RAM helper, but actual `brcmf_sdiod_ramrw()` can return
`-EIO` when `dev_alloc_skb()` fails before its transfer. Classifying every
RAM-helper error as transport therefore quarantines a healthy bus under local
memory pressure. The prior passing tests did not cover this allocation.

The revised fixture extracts the actual RAM helper. It controls packet
allocation, window selection and SDIO transfers underneath it, uses real
native allocations, and models the helper's recursive host claim. Against
the reviewed pre-correction candidate, attempt `a61b81b417914f1382dec8f8ad135a6a`
passes **50/50 normal** and **143/157 debug** cases. The 14 assertion failures
cover both console RAM allocations, lower resource errors and the helper's
read/write allocation errno. The originals remain preserved.

The correction gives the helper allocation its proper `-ENOMEM` errno and
keeps this resource error out of console transport quarantine. Pinned MMC
scatterlist allocation and Sunxi DMA mapping also return `-ENOMEM` before
submitting the affected command. Earlier chunks may have succeeded; this
classification does not assert that no preceding I/O occurred. Console reads
use function-1 RAM, and the helper stops on the first failure. No packet-FIFO
recovery is inferred from this path.

New cases cover both allocations with idle/queued work, window failures,
lower allocation errors, balanced packet/host ownership and single/multi-window
read/write success and failure. Three new mutations restore the incorrect
allocation errno or either console misclassification. Corrected qualification
is running as `960ec2622d13417e93c29e836fd210a3`; it is not yet claimed complete.
Checkpatch reports zero errors, warnings or checks.

## Evidence boundaries

Packet primitives, window selection, SDIO transfers, bus-sleep internals,
timer operations, IRQ retirement and scheduling are synchronous controlled
seams. RAM-helper and console control flow are actual source. Host hooks force
specific ordering boundaries; they do not prove complete-kernel concurrency.
Console and RAM-buffer allocation use real native allocations and sanitizers, but
firmware RAM and its log contents are supplied by the fixture. Existing worker
and packet regression suites run separately against the same applied source.

No observed GameShell problem is attributed to these source findings. Image
integration, matching hardware validation, clock-ready timeout and reset/reprobe
ownership remain with NEO-58. The live clock fault is not bypassed, and
NEO-154's abandoned investigation remains abandoned.
