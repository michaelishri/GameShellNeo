# brcmfmac firmware startup and reset ownership

23 October 2026 NZDT. NEO-212 continues the startup audit under NEO-58, on
locked Linux 6.18.54 with the reviewed isolated Wi-Fi candidates through 0054.
The candidate remains outside the production image queue. No GameShell or
Mac command has been run for this work.

## Reproduced startup errors

The firmware callback discards its `CLK_AVAIL` return and supplies no error
destination to the firmware-protocol and host-interrupt-mask writes. Each
watermark branch also makes successive transfers without stopping on error;
a subsequent successful transfer replaces the preceding error. Save/restore
initialization returns void after failed transfers, allowing startup to
publish DATA and proceed to IRQ registration and common attach.

Firmware downloading similarly discards the initial clock request and the
final clock-drop return. It may transfer the image/NVRAM after failed clock
admission or report success despite failing to leave the requested clock
state. Every exit still owns the supplied code and NVRAM buffers.

The actual-source baseline, attempt `7be256f97a0844ec8d668c27bdac40b8`, passes
959 of 2,088 cases in both native and ASan/UBSan runs. The remaining 1,129
cases reproduce continued setup after a failure, lost exact errors, or
incorrect cleanup/clock-state reporting. The saved baseline Task deliberately
returns nonzero. Original inputs and individual case logs remain private.

The first sandbox attempt `0cdb57706bc6486aa71bca01e1e20b54` has the same
native result; LeakSanitizer was rejected by the sandbox's ptrace restriction,
so that sanitizer result is environmental failure, not source evidence. An
earlier compile-only fixture attempt lacked the `BIT` macro; its log remains
under `.local/audit/`. Neither is relabeled as a passing attempt.

## Candidate behavior

[Candidate 0055](../kernel/candidates/0055-brcmfmac-startup-errors.patch)
checks every callback clock/protocol/mask/watermark transfer before proceeding.
Save/restore initialization now returns its exact error and publishes
`sr_enabled` only after all four accesses succeed. The callback retains its
existing DATA/IRQ/common-layer ordering on success and its existing driver
release/free ownership on failure. A successful clock return with an
unexpected state becomes `-EIO` rather than a failure logged as success.

The download helper checks initial clock admission before reading code or
transferring the image/NVRAM, releases each input exactly once on every exit,
and preserves the first error across its final clock-drop attempt. If all
earlier work succeeded, a failed clock drop is returned. It does not add
retries, reset/reprobe, firmware changes or userspace delays.

Local allocation failure remains its original `-ENOMEM`; this patch does not
turn it into a transport-quarantine error or invoke the active-worker failure
owner. Existing callback unwind owns driver release. Transport failures also
unwind startup instead of reaching DATA/common attach. Best-effort diagnostic
and teardown operations remain separate from successful setup; their return
cannot overwrite the originating callback failure.

## Saved qualification

```sh
# Expected baseline failures; no device access:
task test:brcmfmac-startup-baseline

task test:brcmfmac-startup
task check:brcmfmac-startup-drivers
```

The fixture executes the actual download, save/restore and firmware-callback
bodies. It covers all eleven device-ID switch cases, non-SR/SR/ULP modes,
every applicable setup boundary with three errors, incoming loader failure,
unexpected clock state, and primary-error preservation across failed clock
cleanup. It verifies code/NVRAM/request release, ordered once-only F2/F1
driver release, attach-failure free, exact originating errno and prevention
of later setup, DATA publication and common attach after rejected setup.

Clock/SDIO, allocation, IRQ registration, diagnostics and driver release are
controlled synchronous seams. Register offsets, protocol bits and device IDs
come from the applied source. This does not simulate the complete driver core,
asynchronous firmware loader, real SDIO controller or kernel scheduler.
Existing actual worker, RX, TX, watchdog, sleep, diagnostic and output suites
run against the same isolated candidate source.

Candidate qualification, complete ARM driver builds and independent reviews
are in progress. Passing isolated tests will not select an image queue or
establish board PM admission.

## Separate reset/reprobe audit

The existing F2 lifecycle lock and nonblocking reset acquisition prevent the
documented remove-versus-reset lock inversion. Removal drains the packet
worker before canceling reset work. PM quarantine requires a fresh device
lifetime and cannot be bypassed by the debug reset path.

The locked MMC implementation documents three `mmc_hw_reset()` results:
negative error, synchronous zero, and asynchronously scheduled reset one.
`brcmf_sdio_bus_reset()` currently discards that result after removing its
bus. Ownership and reprobe behavior are being traced separately. This is an
audit lead, not a board failure or an accepted automatic-recovery policy.

NEO-58 retains the rest of startup/reset handling, deliberate integration
and matching hardware qualification. NEO-192 still gates live PM work;
NEO-154 remains abandoned. None of these source findings attributes NEO-55's
observed authentication delay.
