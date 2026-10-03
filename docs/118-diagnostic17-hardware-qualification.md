# Diagnostic.17 hardware qualification (NEO-92)

3 October 2026, Pacific/Auckland. Diagnostic.17 has been written to the owner's
Samsung DEV card, verified by full 4 GiB readback and safely ejected. Boot and
hardware qualification are pending. No PM cycle has been submitted on this
image yet; NEO-92 remains in progress.

[Report 117](117-sdio-runtime-reference-ownership.md) records the SDIO
runtime-reference fix, source regression coverage, build provenance and
diagnostic.16 recovery. This installation uses that exact verified artifact.

## Card installation

The owner confirmed that the DEV card was in the Mac reader. Fresh status and
inspection found the external physical USB card at `disk16`, capacity
`64013467648` bytes, with its existing `armbi_boot` and Linux partitions. The
saved workflow was:

```sh
task mac:status
task mac:inspect DISK=disk16
task mac:preflight
task mac:flash DISK=disk16
```

The disk number describes this installation only; inspect the physical card
afresh before another write. Preflight and flash both verified compressed and
decompressed image hashes and the recorded card identity. The mount guard
started, the card was unmounted, and a blocked macOS mount attempt established
that the guard was effective before writing.

All `4294967296` bytes were written and read back. SHA-256
`7923af46c3e58bc85030adb2702bba9b822f61f25d03ed8573702040f7a31048`
matches `GameShellNeo-0.1.0-diagnostic.17-cpi31-7923af46c3e5.img`.
The saved result records `readback: passed`, `mount_guard_verified: true`,
`ejected: true` and `hardware_boot_tested: false`.

Evidence is
`.local/diagnostics/20261003T021523.043587Z/flash-result.json` and `flash.log`.
Host transcripts are `.local/neo92-mac-inspect.log`,
`.local/neo92-mac-preflight.log` and `.local/neo92-mac-flash.log`. The transfer
and image hashes remain recorded in report 117.

## Remaining qualification

The owner has been asked to reinsert the card, reconnect USB, power on and
confirm the normal login screen. Startup checks must establish the new image,
kernel `6.18.54-gameshellneo17`, both SSH routes, journal continuity, idle audio
and the new boot's awake power-key/RTC prerequisites.

With fresh readiness for each described observation batch, follow report 117's
freezer, driver and five late/noirq debug-cycle comparison. Preserve every
result and run the saved `check:sdio-ref-history -- --require-stable` comparison
on the accepted records from this boot, followed by a later read-only PM
inspection. Existing general PM passes alone do not establish reference
stability. Stop and investigate any drift or failed health gate.

Normal sleep remains disabled. This card readback does not establish boot,
suspend/resume, actual sleep, wake latency or an energy saving.
