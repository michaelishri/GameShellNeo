# brcmfmac RX recovery error ownership

12 October 2026 NZDT. NEO-195, continuing NEO-58's remaining RX cleanup lead
from [report 251](251-brcmfmac-suspend-failure-audit.md). This is an isolated
candidate and partial validation, outside the verified diagnostic.26 image.
No GameShell, firmware, network configuration or PM setting was changed.

**Follow-on:** [report 276](276-brcmfmac-rx-caller-qualification.md) now records
reproduction/fixes for both packet findings and completed native/ARM caller,
worker, sanitizer and combined-mailbox driver checks. The pending statements
below describe this initial helper-only milestone.

## Source defect and candidate

The locked Linux 6.18.54 receive-error path can lose errors during its own
recovery. `brcmf_sdiod_abort()` ignores the function-zero CMD52 result and
always returns zero. `brcmf_sdio_rxfail()` ignores abort and frame-terminate
errors, and its low-byte FIFO-count read overwrites the preceding high-byte
read's error. It can consume 65,535 poll pairs despite a failed register
transaction, or request retransmission without establishing that the FIFO
was emptied. A successful low-byte read is not proof of a successful pair.

[Candidate 0046](../kernel/candidates/0046-brcmfmac-rx-recovery.patch) preserves
the abort result, checks every terminate/count/NAK operation, and latches the
first recovery error in the existing `io_error` field. Duplicate cleanup
after that latch performs no more I/O and preserves the original error.
Only a verified flush permits NAK and `rxskip` publication. Poll-budget
exhaustion becomes `-ETIMEDOUT`; the established 65,535-pair successful-hardware
budget is unchanged. This is not an elapsed-time or freezer deadline guarantee.

The original failed receive is still recoverable: a successful abort/flush/NAK
does not quarantine the device. It is failure of recovery itself that latches
the fatal condition. The draft stops the receive loop, clears partial/next-frame
length state and returns to DPC. DPC reacquires the SDIO host before calling
the existing fatal-worker cleanup, before further interrupt rearming, control
transmit or queued transmit work. Packet-owning callers retain their cleanup
responsibilities; the helper does not free their buffers or synchronously stop
its own worker. The current lifecycle requires a fresh device lifetime after
quarantine; automatic reset/reprobe ownership is still separate work.

All `rxfail` calls originate in `hdparse`, `rxglom`, `read_control` or
`readframes`, with the SDIO host claimed at that boundary. The abort helper's
other caller is `txfail`, which still ignores the returned error; this candidate
does not claim to repair transmit recovery.

## Repeatable helper checks

```sh
task test:brcmfmac-rx-recovery
task check:brcmfmac-rx-recovery-drivers
```

The runner verifies the locked archive, applies the full image patch queue plus
the isolated candidate, and extracts the actual abort/recovery function bodies
and register definitions. Synchronous SDIO transfers are scripted boundaries.
Every script and candidate input is hashed; each attempt retains its generated
sources, binaries and logs privately under `.local/build/brcmfmac-rx-recovery/`.
The ARM compiler container has networking disabled. The image queue rejects
accidental inclusion of this candidate by name before running the suite.

The first helper run passes **44 scenarios natively and on ARM32**, plus
**13 deliberately broken variants** rejected by assertions. Successful cases
cover abort/retransmit combinations, immediate and delayed flush, and success
on the last permitted poll. Failure cases cover abort, terminate, high/low
reads and NAK, three errno values, zero/nonzero failed-read data, exhaustion
and duplicate cleanup after an existing error. Assertions check access counts,
the original errno, no later I/O, retransmission admission, statistics and
partial-length clearing. These are helper results, not packet-lifetime or
hardware results. The receipt explicitly records `caller_checks_complete=false`.

Initial helper evidence:
`.local/build/brcmfmac-rx-recovery/attempts/096756763b7c4d8cbab8561a77bceda9/`.
The complete ARM brcmfmac object then compiled in both board and `BRCMDBG`
configurations. After fixing patch-header formatting, the exact final inputs
were rerun through all helper checks and both full object builds. That final
attempt also passed without compiler warnings or errors:
`.local/build/brcmfmac-rx-recovery/attempts/5cc20fbe509a42df94dea14991bc0094/`.
All recorded inputs, retained artifacts and driver-object hashes were verified
afterward. Checkpatch reports zero errors and warnings for the final patch.

| Final artifact | SHA-256 |
| --- | --- |
| Helper/compile evidence | `08deddb64daa6a47020dd8a8ccf92139f1178ea0617afd151b88fb7331b63f64` |
| Candidate patch | `cdfce4e8262d569d33d73ed9f26b443839ee0196505ce63f0b3d238aea0dc577` |
| Board `brcmfmac.o` | `2bb752ed0c691456605377c46bcb72f68bd172168200ad0c5ef069f9d2c6c882` |
| Debug `brcmfmac.o` | `52b839c92ab3b231ed099fbe512de50a1d03fa9c01a37fac5e5b490278fe1645` |

## Remaining caller validation and separate findings

Before integration, exercise the actual DPC path and the control, normal-frame,
readahead and glom callers with tracked buffer ownership, host-lock balance,
duplicate recovery and pending TX/control work. The helper tests alone do not
prove that a caller cleans up correctly or avoids publishing invalid metadata.
Test the candidate alongside the prepared mailbox fix and preserve existing
successful behavior. The initial patch-header formatting errors are corrected;
they were not compiler or runtime driver errors.

Two existing packet-handling findings surfaced during the audit and need
focused reproduction rather than being hidden by this helper pass:

- In `readframes`, the `SDPCM_GLOM_CHANNEL` branch without `SDPCM_GLOMDESC`
  calls recovery and continues without visibly freeing or transferring `pkt`.
  Confirm with allocation accounting and fix the missing ownership handoff.
- In `rxglom`, only `rd_new.seq_num` and `.len` are initialized before parsing
  a superframe. The caller consumes `.len_nxtfrm` and `.dat_offset` before
  checking `errcode`, although early header errors do not fill those fields.
  Reproduce malformed-header handling and prevent use of unvalidated outputs.

These are source findings, not attributed failures on the owner's GameShell.
NEO-55's authentication delay, missing `CLK_PENDING` deadline, transmit-error
recovery and generic reset/reprobe ownership remain separate. This work does
not establish measured performance, RF robustness, sleep reliability or energy
savings, and NEO-195/58 remain in progress.
