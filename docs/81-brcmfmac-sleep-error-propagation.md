# brcmfmac sleep and clock error propagation (NEO-60)

1 October 2026, Pacific/Auckland. Linux 6.18.54; first implementation slice of
NEO-58's [retained-power suspend audit](80-brcmfmac-suspend-failure-audit.md).
Patch 0014, repeatable native/ARM tests and isolated ARM compilation are
complete. No image was built or installed and no device command was issued.
Diagnostic.11 and its recovery artifacts remain unchanged.

## Problem and resulting behaviour

The original KSO helper can run out of attempts without observing the requested
sleep/wake bits and still return zero. Several clock and sleep helpers also
discard register-access failures or overwrite them with subsequent results.
For example, a failed clock-off write previously updated the cached clock
state before checking its error, and its caller could then report success.

[Patch 0014](../kernel/patches/0014-brcmfmac-sdio-sleep-errors.patch) corrects
these low-level contracts before the freezer transaction starts relying on
their return values. This brings the audit's hardware-helper work forward:
implementing PM rollback first would leave it trusting misleading results.
The policy permitting driver-level fixes is recorded in the
[base requirements](06-base-requirements.md#engineering-guidelines-and-long-term-experience).

| Area | Change |
| --- | --- |
| KSO polling | Exhausting attempts without a verified match returns `-ETIMEDOUT` when the final access itself returned no error. Existing nonzero access errors remain errors. Retry limits and delays are unchanged; a verified match after a transient access failure remains successful. |
| Special 43012 sleep path | Preserve the chip's early exit without status reads, but pass through common cleanup so CRC-retune suppression is balanced on both write success and failure. This is modeled compatibility coverage, not a hardware result for another chip. |
| Backplane clock operations | Check pending-interrupt-filter reads/writes and each polling read. Keep the existing `-EBADE` translation for clock access failures/timeouts. Publish clock-off state only after its write succeeds. |
| Clock-control caller | Return the clock helper's error and stop before claiming the SD clock is off if backplane clock removal failed. Pending requests clear their clock-available-only interrupt filter before transitioning down. |
| Bus sleep/wake | Check the preliminary clock-register read and ALP-request write before attempting KSO; propagate clock-control errors; skip the success-state update and watchdog-start request on failure. |
| Partial transitions | Mark the clock or sleep cache uncertain after a failed transition. A subsequent request cannot skip hardware reconciliation solely because it matches the old cached value. Clear uncertainty only when the corresponding operation succeeds. |

The last case matters for rollback: a KSO sleep write can reach the card even
if the following read fails. Leaving only `sleeping=false` would let a wake
request falsely take the already-awake shortcut. `sleep_state_unknown` forces
that next request through KSO. The corresponding `clkstate_unknown` flag
prevents an old AVAIL/SDONLY value from bypassing clock recovery. When clock
state is uncertain, the helper also clears a possibly applied interrupt
filter, even if the cached state never reached PENDING.

The flags live in the driver's private bus structure. They use the existing
SDIO-host-serialized clock/sleep paths; no worker, timer, polling loop, public
interface or userspace workaround is added. The zero-initialized flags retain
the original initial-state assumptions. This does not establish those initial
hardware assumptions independently. The new checks do not shorten hardware
settling delays or change the requested clock rates.

The successful scenarios below retain the original I/O and delay sequences.
Additional boolean bookkeeping has not been benchmarked for CPU or energy
cost; no speed, standby-endurance or battery-power saving is claimed.

## Reproducible verification

```sh
task test:brcmfmac-sleep
task check:brcmfmac-driver
task check
```

The [checker](../tools/check-brcmfmac-sleep.py) verifies the locked Linux
archive, extracts the original source and supporting constants, applies the
patch with zero fuzz, and compiles the actual five C helpers. It preserves the
source's `#undef`/replacement of `PMU_MAX_TRANSITION_DLY`, so the tests use the
driver's one-second nominal limit, not the shorter header default. The KSO
limit bounds polling attempts; SDIO transfer and scheduling time means it is
not a hard one-second wall-clock guarantee.

The [harness](../kernel/tests/brcmfmac_sleep_test.c) scripts individual register
reads/writes and their errors, advances modeled time, and checks retune and
watchdog calls. Unexpected or missing transfers fail the test. It executes
the real helper bodies rather than a separate copy of their intended logic.
Private structure/API shims replace kernel and hardware facilities.

**95 scenarios pass natively and on emulated ARM32**, also passing a native
build with the helper's DEBUG branches enabled:

- 43 original successful scenarios match the candidate's transfer, delay,
  cleanup and final-state transcript (`a2658cef`). These include immediate,
  retried and last-attempt KSO matches; recoverable transient failures; ALP/HT
  clocks; deferred clock availability; synchronous transitions; unsigned
  jiffies rollover; and SR/non-SR sleep/wake and cached calls.
- 41 error and cleanup scenarios cover exhausted KSO polling, repeated read
  errors, terminal write errors, the 43012 no-read exit, each checked clock
  transfer, poisoned values from failed reads, clock timeout, error propagation
  through both caller layers, preliminary sleep failures and suppression of
  successful state/watchdog publication after failure.
- 11 multi-operation recovery scenarios cover failed sleep followed by wake
  and the inverse, repeated recovery failure, restored fast paths after a
  successful retry, uncertain clock-off/on, pending-filter cancellation and
  a filter write that may have reached hardware before reporting failure.

**Twelve native negative controls fail by assertion**, including the original
error paths and independently removed timeout, retune cleanup, caller error,
clock-state ordering, pending-write, polling-read, preliminary-read,
sleep-cache, clock-cache and uncertain-filter protections. The checker rejects
controls that fail to mutate their source or accidentally pass. Compiler
errors are not accepted as successful negative controls.

The complete changed `sdio.c` translation unit also compiles to an ARM object
using the full project patch queue, locked builder and checked kernel
configuration in isolated scratch. This checks the real kernel structures,
headers and APIs; it is not a complete kernel/image build. Existing diagnostic
sources, kernel objects, modules and image artifacts are not reused or replaced.

The final shared check passes **13 runtime tests, 276 tool tests (one optional
skip), compiled current-selector/mount-guard checks and shell lint**.

## Evidence and limits

Private evidence is retained under `.local/build/brcmfmac-sleep-tests/`:

- `evidence.json` and `compile-evidence.json`: archive, input, source, builder
  and result hashes, plus the ARM object's path/hash for the compiler run.
- Per-variant text results and the extracted original/patched helper inputs.
- The isolated `kernel-f3379e5d179e5031/` source/output and ELF/compiler details.

Task logs are `.local/build/brcmfmac-sleep.log`,
`.local/build/brcmfmac-driver.log` and `.local/build/neo60-check.log`.
The original SDIO file hashes to
`9b35fe8d215b76c3f2e95acf37aff46e9623ff9ba35911cc732ffedb0dae5b78`;
the patched file hashes to
`288f43e89118750b0c6fb4936fd4a5523a14a8d3f0d6190a84deb36cbb1ef9e6`.
The archive and toolchain identities are in the
[source lock](../build/sources.lock.json). Primary baseline:
[locked SDIO implementation](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/sdio.c?id=1b357ecb321392158d507b04672ffee57bfa071d).

These tests do not execute the MMC controller, physical register side effects,
Linux PM scheduling or radio firmware. The watchdog shim records the request
to start; it does not prove the actual watchdog can restart while the SDIOD
bus is DOWN. That ordering issue remains part of NEO-58.

Higher-level PM callbacks still discard some errors. Worker collection remains
unbounded, freezer accounting and completion reuse need repair, and failed
wake still needs an explicit I/O-gating and recovery contract. This patch makes
a subsequent helper recovery request meaningful; it does not schedule that
request, guarantee reset/reprobe or stop every caller that currently ignores
failure. Callback ownership across F1 suspend/F2 resume and hardware
qualification remain open in report 80 and [FOLLOW-UP.md](../FOLLOW-UP.md).

There is no demonstrated causal connection between these source defects and
NEO-55's intermittent authentication delay. The patch is not a claim to fix
that outage. Normal sleep and the current power-button policy stay unchanged.
Remove this downstream patch once the selected upstream source supplies
equivalent checked transitions, cache reconciliation and cleanup, verified
with these regressions and subsequent board qualification.
