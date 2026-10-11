# brcmfmac diagnostic output bounds

12 October 2026 NZDT. NEO-202 continues the output-bounds lead from the
[shared diagnostic audit](284-brcmfmac-shared-diagnostic-audit.md), on locked
Linux 6.18.54 plus isolated candidates through 0053. Candidate 0054 remains
outside the image queue; NEO-58 owns deliberate integration and matching
hardware qualification.

## Source finding and intended behavior

`brcmf_sdio_dump_console()` reads the firmware's buffer address, size and
cursor in three separate guarded transfers. Previously it checked only the
allocation ceiling, then used the cursor in host pointer arithmetic and an
unsigned output length. A cursor beyond the size therefore produced an
invalid pointer and an underflowed length. An oversized buffer was reported
as `-ENOMEM` despite being rejected metadata.

The console contract for this change is:

| Firmware metadata | Result |
| --- | --- |
| Size zero, cursor zero | Empty success, without allocation, payload transfer or output |
| Size 1–2024, cursor 0–size inclusive | Preserve the existing output and error behavior |
| Size above `CONSOLE_BUFFER_MAX` (2024), or cursor above size | Local `-EINVAL` before allocation, payload access or output |

The existing output is the tail from cursor to size, followed, for a nonzero
cursor, by `cursor - 1` prefix bytes. Cursor equal to size is memory-safe and
remains accepted; the periodic console reader also rejects only cursors
greater than size. This patch preserves that byte order and prefix length.
It does not claim to establish the firmware's historical reason for omitting
the preceding byte. The empty case preserves zero output while removing an
unnecessary allocation and zero-length RAM operation.

`brcmf_sdio_assert_info()` previously read up to all 80 bytes of each local
array before `%s` formatting. Firmware text need not contain a zero within
those bytes. [Candidate 0054](../kernel/candidates/0054-brcmfmac-diagnostic-bounds.patch)
retains the full 80-byte read and reserves an initialized 81st byte. Missing
addresses still produce the existing `?` and `<???>` defaults; short strings,
empty strings and all 80 nonzero bytes retain their expected output.

The new local metadata errors do not retire the transport. Existing guarded
read admission, first I/O/PM errors, allocation errors, host ownership and
buffer cleanup remain in place. Output-sink errors still stop output and
free the owned buffer. This changes DEBUG diagnostic output, not firmware
code, ordinary packet handling or production power policy.

## Reproduction and reusable commands

```sh
# Expected failures on the stack through 0053, without candidate 0054:
task test:brcmfmac-output-baseline

task test:brcmfmac-output-bounds
task check:brcmfmac-output-drivers
```

The initial attempt `3ad116686eea4f27a283f74637788abc` stopped at a signedness
warning in a fixture comparison. It did not exercise the driver. After that
fixture correction, baseline `99bab042fe924152b73e1f81064581a1` passed 95 of
109 native cases and 92 of 109 sanitizer cases. Invalid cursors reached the
bounded output seam; oversized metadata returned the wrong error; the empty
console performed unnecessary work. Three full-string cases failed native
output comparisons, and those cases plus all four full-string caller cases
reported stack-buffer overreads under ASan. The baseline Task's nonzero exit
is intentional; original attempts and per-case evidence are retained.

## Controlled boundaries and coverage

The 109 output cases execute the actual console/assertion/caller functions,
guarded diagnostic reads and RAM helper. Firmware memory, SDIO transfers,
allocation, host acquisition and retirement primitives are controlled seams.
No malformed metadata or text is sent to the GameShell.

The output seam checks pointer/length bounds before dereferencing console
data. Assertion formatting uses real `vsnprintf`, making missing string
termination observable by ASan. This is not the kernel's complete `seq_file`
implementation. It models bounded output and scripted write errors; it does
not model kernel seq-file pagination, scheduler concurrency or changing
firmware memory between transfers.

Coverage includes empty, one-byte, wrapped and maximum-size consoles; cursor
equal to size; oversized and UINT32_MAX metadata; buffer and RAM allocation
failures; first/second output-write errors; all four console transport reads;
host-admission rejection at every console acquisition; assertion flags and
address combinations; empty, short, unterminated 80-byte and last-byte-zero
text; assertion transfer failures; and actual `died_dump()` propagation.
The combined NEO-201 suites separately cover later assertion admission,
startup cleanup initialization and worker propagation.

Thirteen output mutations remove size/index checks, reject the valid end
cursor, misclassify metadata, remove the empty fast path, alter ring output,
discard payload/output errors or cleanup, remove either reserved terminator,
or truncate either 80-byte payload. Every mutation must compile. Eleven must
fail an assertion; the two restored unterminated-buffer defects must produce
an ASan stack-buffer-overflow report. A compile error is never accepted as a
negative control.

## Qualification status

The first candidate attempt, `4346d998bb3047de8cb58b465fa1ea89`, passed all
109 native and sanitizer cases. Its cleanup mutation then failed compilation
because removing the sole cleanup call left the fixture function unused.
That compile failure is not accepted negative evidence; the corrected
mutation keeps a dead call so it can compile and exercise the ownership
assertion. The saved full-driver Task is being rerun. ARM32, mutations,
combined regressions, full board/debug objects, independent review and final
artifact verification remain required before ticket closure. Checkpatch with
`--no-tree --strict --no-signoff` reports zero errors, warnings or checks.
Sign-off is excluded for this local candidate rather than inventing an
upstream submission attestation.

No live device or image changed. NEO-192 still gates live PM work, NEO-154
remains abandoned, and this source finding does not attribute NEO-55's
observed authentication delay. The separate firmware-startup/reset audit
remains with NEO-58.
