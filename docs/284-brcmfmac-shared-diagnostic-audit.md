# brcmfmac shared-memory diagnostic admission audit

12 October 2026 NZDT. NEO-201 follows the completed
[clock-deadline candidate](283-brcmfmac-clock-deadline.md), under NEO-58.
This records the initial source audit and test contract. The subsequent
candidate and completed offline qualification are in
[report 285](285-brcmfmac-shared-diagnostic-errors.md).

## Source identity

Locked Linux 6.18.54, image patch queue plus isolated mailbox/RX/TX/watchdog
and clock candidates through 0052. The verified applied source inventory is
`dd6f0c88c73b5dd2459757cf9add69fa9a7c7e7277dc495432db029fc011eba6`,
from NEO-200 attempt `a6c3292c8ea3413ba22262ece80b32e1`. Source locations below
refer to that applied tree, principally
`drivers/net/wireless/broadcom/brcm80211/brcmfmac/sdio.c`.

## Confirmed source behavior

The DEBUG-only `brcmf_sdio_readshared()` claims the SDIO host, discards the
return from `brcmf_sdio_bus_sleep(bus, false, false)`, then performs a RAM
read. A failed wake therefore does not stop this diagnostic path. There is
also no prior-I/O/PM-failure admission check under this host claim.

It reads the final RAM word to locate `sdpcm_shared`, applies the existing
address predicate, then reads the structure. Transfer failures are returned.
Fields are copied to the caller's output before the shared-version check;
an unsupported version therefore returns failure after modifying the output.
Console discovery only publishes `console_addr` on a successful return, but
the general output contract is not transactional.

The actual `brcmf_sdiod_ramrw()` recursively claims the same host. NEO-199
corrected its packet allocation failure to `-ENOMEM`; this must remain a
local resource error. Window/transfer failures retain their transport errno.
Its lower primitives are not a replacement for caller-level wake admission.

## Caller ownership

| Caller | Context and current error behavior |
| --- | --- |
| `brcmf_sdio_get_console_addr()` | Called from `hostmail()` under the DPC's outer host claim after firmware-ready status. It returns void and ignores failed shared discovery; the DPC can continue servicing traffic. Non-DEBUG builds use an empty stub. |
| `brcmf_sdio_checkdied()` | Returns a failed shared read; used by control-response timeout/unknown-wake diagnostics, which discard its return. A trap read's return is also discarded. |
| `brcmf_sdio_died_dump()` | Debugfs diagnostic path; propagates shared/assert/trap/console errors. The later helper reads use separate host acquisitions, so each boundary needs consideration. |
| Firmware callback failure labels | `checkdied()` also runs after startup failure, with an outer host claim. The path may precede successful function-2/IRQ registration, or follow allocation/attach failure. It eventually releases the host and both device drivers. |

The startup caller matters: a new diagnostic helper cannot silently assume
that every call belongs to an established data bus with the same cleanup
owner. The probe initializes work, wait queues and the watchdog before the
firmware callback, but later registration and interface ownership vary by
failure label. Existing first-error and once-only retirement must be traced
through those states before reusing active-worker cleanup there.

## Implementation and qualification still required

1. Reproduce failed wake, prior error and PM rejection with actual shared-reader
   source and controlled lower transport/allocation results. Include a failure
   arriving at host acquisition and nested host ownership.
2. Keep metadata/allocation errors separate from transport faults. Define
   cleanup ownership for the active DPC, standalone diagnostics and startup
   unwind; preserve the originating failure and avoid repeat retirement.
3. Stop reads after rejected admission or failed wake, and publish shared or
   console data only after successful validation. Preserve successful reads,
   address handling, save/restore RAM offsets and the non-DEBUG stub.
4. Cover the actual callers, including the initial reader and later diagnostic
   host acquisitions. Reuse packet/worker/clock/watchdog regression Tasks,
   native sanitizers, ARM emulation, full board/debug objects and independent
   reviews. Candidate integration and physical qualification remain NEO-58.

## Separate leads to retain

`brcmf_sdio_dump_console()` reads a firmware-provided index and uses it for
`conbuf + console_index` and `console_size - console_index`, without an explicit
index-versus-size check in this function. `brcmf_sdio_assert_info()` reads up to
80 bytes into each fixed string buffer and later formats them with `%s`,
without explicitly reserving a terminating byte after the read. These need
their own malformed-metadata fixtures and bounded-output audit. This source
observation is not a claim that the owner's firmware produced such data.

The firmware callback also discards several clock/setup transfer results.
That belongs in the remaining NEO-58 startup/reset ownership audit, not an
assumption that the shared-reader fix completes initialization hardening.

No live device, image, charger or PM setting has changed. NEO-192's clock
qualification remains a live-test prerequisite. NEO-154 remains abandoned;
none of these findings establishes a cause for NEO-55's observed delay.
