# Diagnostic.16 hardware qualification (NEO-88)

3 October 2026, Pacific/Auckland. Diagnostic.16 has been written to the owner's
Samsung DEV card, verified by full readback and safely ejected. First boot and
hardware qualification are pending. No PM test has run on this candidate.

[Report 111](111-diagnostic16-preparation.md) records the complete build,
offline checks, retained diagnostic.15 recovery and staged archive. The source
changes are [transmit suspend ownership](109-wifi-transmit-suspend-ownership.md)
and [band capability query errors](110-wifi-band-query-errors.md).

## Pre-flash state

The owner returned for testing. The Mac and diagnostic.15 GameShell were
reachable using the saved tasks. USB access showed
`6.18.54-gameshellneo15`, active inspected services with no restarts, no failed
units and kernel taint zero. The battery monitor reported 100%, Charging and
4.1866 V; this is a software reading, not a capacity or voltage calibration.
No charging setting was changed.

The initial read-only status capture is
`.local/diagnostics/20261002T181643.200822Z/`; host transcripts are
`.local/neo88-mac-status.log` and `.local/neo88-device-before-flash.log`.

## Card installation

After shutdown/card-move instructions, the owner confirmed completion. Fresh
Mac inspection found one external physical USB card at `disk16`, capacity
`64013467648` bytes, with the existing `armbi_boot` and Linux partitions,
matching the intended 64 GB DEV card. The saved sequence was:

```sh
task mac:status
task mac:inspect DISK=disk16
task mac:preflight
task mac:flash DISK=disk16
```

The disk identifier is this session's observation; always identify the physical
DEV card afresh before another write. Preflight verified the compressed and
decompressed image hashes and recorded target identity. The flash repeated
those checks, activated the mount guard, unmounted the volume and verified
that macOS could not remount it during the operation.

All `4294967296` image bytes were written and read back with SHA-256
`de531424ec88e55cbc991e757e295e49658a8991fb0058c5380bc969814d90c7`,
matching `GameShellNeo-0.1.0-diagnostic.16-cpi31-de531424ec88.img`.
The card was safely ejected. The flash result records `readback: passed`,
`mount_guard_verified: true` and `hardware_boot_tested: false`.

Flash evidence is
`.local/diagnostics/20261002T182154.163870Z/flash-result.json` and `flash.log`.
Host transcripts are `.local/neo88-mac-card-status.log`,
`.local/neo88-mac-inspect.log`, `.local/neo88-mac-preflight.log` and
`.local/neo88-mac-flash.log`.

## Remaining qualification

The owner has been asked to reinsert the card, reconnect USB to the Mac and
confirm the normal login screen. The next steps follow report 111: verify
installed image/kernel/patches, both SSH routes, integration/journal health and
same-boot awake power-key/RTC prerequisites. Only after fresh owner readiness
may the staged freezer, devices and late/noirq checks proceed.

The prior diagnostic.15 warning occurred in one of five late/noirq cycles.
Repeated reviewed runs and complete logs are required for comparison; successful
flashing does not resolve that warning. Actual sleep, product power-key gestures,
firmware-country readback, NEO-55 and energy savings remain unqualified.
