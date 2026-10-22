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

Attempt `ca1346bdb1644638a17ff5ad00a780fc` completed successfully: all 2,088
startup cases pass natively, with ASan/UBSan and under ARM32 emulation. All
41 startup mutations compile and fail the intended assertions. The same
applied source also passes 109 output, 194 shared diagnostic, 95/202
normal/debug watchdog, 95 normal/debug sleep, 215 TX, 115 RX and 263/289
normal/debug worker cases. All 13 output, 18 diagnostic, 28 watchdog, 23 TX,
four packet, five control FIFO and 51 worker mutations expose their intended
assertion or sanitizer failures.

The managed ARM run `d35e408a039f47438e2e87594998ae67` exited zero with no
OOM or requested stop. Its receipt, durable log/result and all 9,922 attempt
artifacts are pinned in the completed manifest. Checkpatch using the patch
on standard input with `--no-tree --strict --no-signoff` reports zero errors,
warnings or checks. An earlier file-argument invocation examined the patch
file as source and reported its diff-context spaces; that command's output
is retained separately and is not a production-patch finding.

Full-driver attempt `8322b1393d8e4b4e9bd69d6f38f2a24e` completed successfully,
repeating those suites and compiling complete board/debug ARM brcmfmac objects.
Both configurations pass 183 assertions, with no compiler warnings or errors.
Its ARM run `579ced986acd47fca40a174748dba047` and object runs
`c2159a6988fd45c6978b9bb6d0e774b7` / `893fec2aeab3412189f04b92b5288620`
all exited zero, without OOM or a requested stop. Passing isolated tests does
not select an image queue or establish board PM admission.

The complete host `task check` also passes: 24 runtime and 1,283 tooling tests
(nine expected skips), both C fixtures and Bash/ShellCheck. It ran in the
normal authorized host context so local socket fixtures could execute.

## Independent review

The fixed review diff is
`98aff1fe86689c916cd930f2b5c5a8bb218088f0...f4146a7b3d23d7290f96b585c666460165e8d35d`.
Both peer reviewers worked read-only and did not author this candidate.

Standards found **zero documented violations and zero required fixes**.
One optional maintainability note concerns positional chip selectors shared
by the Python case generator and C fixture: future additions/reordering must
update their tables together. Named chip metadata could simplify that later;
the eleven current branch mappings and mutation targets are explicitly
covered. The note is retained without changing the active run's frozen inputs.

Spec found **zero actionable findings**. The review checked first-error
propagation, every guarded setup boundary, input and driver cleanup, actual
source extraction, negative controls and the explicit offline scope. The
then-pending full-object/final-check evidence remained an acceptance gate,
rather than being inferred from source review; those checks subsequently
completed as recorded above.

## Final verification

After both original Tasks exited, all 38 recorded inputs and all 9,922
artifacts in each completed attempt were rehashed. Both object/configuration
identities and the full applied source inventory match. Every startup result
and mutation assertion marker was checked again. All four managed ARM/object
runs have retained successful terminal results and matching durable-log
hashes, with no OOM or requested stop.

Only documentation changed after fixed source review `f4146a7`. The production
patch queue, source lock and project configuration remain byte-identical to
base `98aff1f`; candidate 0055 is not selected by the image exporter. Private
verification and the complete evidence index remain under
`.local/build/brcmfmac-startup/` in this preserved worktree.

| Artifact | SHA-256 |
| --- | --- |
| Candidate 0055 | `658520e7471eca3bcbfe86b34550dab7b6a816ef2ea582976b79343880419d37` |
| Complete source-suite manifest | `0c00fabe5bcd317317a27cf8664051cbc0669ab5c1207f58a0cc8ab5a7acf83b` |
| Complete driver-build manifest | `d140835c41554c2ca01eb1200714688a9dc1d433006532513298a354919d87f9` |
| Applied source inventory | `03825b8491e59815fef8bd739bd922bacae31bf13d63a9e5c55a904b40990e52` |
| Board object | `52e467bab591a5ed036c348201e362127a38e616f62035062b7b637a22545dac` |
| Debug object | `ff5568fc9dbac0aa06a0a9479c9c5d3e14c44c019c7d6960d29c9159b537dcf1` |
| Complete host-check log | `2095bc5b7bbc90dbb77c38732d04fd993de33f1f54bdceeb17abb79b56eb0e6f` |
| Final input/artifact/source verification | `08f4f96e5d1a9fd5101fb2d0f239834f95c6b7055c977daa77c9e0be800a8024` |
| Complete evidence index | `866518f5b3193ed244b95b1e9ee4ffb8cfe60941a3f29bc3a556b732a2215317` |

NEO-212's specified offline candidate scope is complete. Source publication
and ticket closure follow independent final evidence/documentation review.
The next probe slice will separately reproduce settings-allocation/deferred-
probe cleanup and lost originating probe errors; no such fix is included here.

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
