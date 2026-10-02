# Diagnostic.15 preparation (NEO-84)

3 October 2026, Pacific/Auckland. The complete build, offline verification and
Mac staging passed for the Wi-Fi country-request fix in
[report 106](106-brcmfmac-regulatory-suspend.md). The running board remains
diagnostic.14 during preparation; no PM test or card write is part of this work.

## Scope and recovery

Image `0.1.0-diagnostic.15`, kernel `6.18.54-gameshellneo15`, adds patch 0020.
It defers country firmware commands between wiphy suspend and resume under
existing RTNL ownership, then applies the latest valid request after parent
transport restoration. A failed deferred update fails wiphy resume, which
causes cfg80211 to close the radio's interfaces. Independent USB access is
required for the hardware comparison.

Country mapping and configured region, firmware, charging policy, SDIO retained
power and keypad supply policy are unchanged. No product power-key gesture or
actual sleep is enabled. Normal sleep remains masked; ordinary short-press
shutdown remains the diagnostic behavior.

The prior image and matching kernel/patch/provisioning provenance were preserved
before changing the build identity:

```sh
task image:checkpoint NAME=diagnostic14-before-regulatory-fix
# Advance only the image version and kernel localversion in the source lock.
task kernel:reset
task provision
task check
task build
# Once the image has passed offline verification, on an appropriate network:
task mac:stage
```

The checkpoint is `.local/recovery/diagnostic14-before-regulatory-fix/`, retaining
`GameShellNeo-0.1.0-diagnostic.14-cpi31-3d42271705eb.img`, raw SHA-256
`3d42271705ebf21c74048655fd19145f94442acb585000b0e8985e9e6f3e7f6b`.
Its compressed recovery archive and metadata remain available. The previous
kernel source/output/install and artifact metadata are archived beneath
`.local/previous-kernels/20261002T121716Z-834315/`.

The saved build uses fresh kernel extraction with the locked builder and
single-job setting. It does not import prior object files. Provisioning reads
private credentials from `.env` and preserves the established device identity.
Private stage logs are `.local/neo84-*.log` and `.local/build/*.log`.

## Verification

The host checks passed 13 runtime tests and 346 tooling tests (one existing
optional skip), compiled current-selector/mount-guard checks, Bash syntax and
ShellCheck. The complete saved pre-kernel regression sequence also passed,
including the new country-request native/ARM32 scenarios and negative controls.

The resolved configuration is byte-identical to diagnostic.14, SHA-256
`d370205bf2e4eed5e35483f15372a6785e7d96252d40c343dfee0b2dde37a017`.
This preserves the configuration baseline for the hardware comparison.
All nineteen previous patch hashes match the recovery checkpoint; the only
addition is `0020-brcmfmac-regulatory-suspend.patch`, SHA-256
`01afc0758ba3df6acf16cb36dc9bd1d77f1b0d1e87ece73dca8dc9bd238ddb4f`.

The complete kernel, board DTB and ten modules compiled successfully. All ten
module vermagic strings identify `6.18.54-gameshellneo15`; the kernel artifact
check passed for all fifteen recorded files. Device-tree schemas and compiled
USB/SDIO/speaker/keypad-retention checks passed, including their negative controls.

Base-rootfs creation ran again because the conservative cache key hashes the
entire source lock. Comparing the saved and current cache inputs identified
only `build/sources.lock.json` as changed. A bounded cache-key optimization is
recorded in `FOLLOW-UP.md`; the current build does not weaken cache verification.

The package inventory is byte-identical to diagnostic.14, SHA-256
`66dc03283bb690e55ab2b2540b0ffe43310dfb39f872672c4d6b3884ecc3358b`.
All 218 recorded project-input hashes match the source files after assembly.
The 4 GiB image passed partition boundaries, bootloader readback, FAT16/ext4
checks, U-Boot CRC/address checks, kernel/DTB/module/radio hashes, private
identity permissions and service policy, including the persistent-journal files.

Evidence is `.local/neo84-artifact-inspection.json`,
`.local/artifacts/verification.json`, `.local/build/image-verify.log`,
`.local/build/kernel.log`, `.local/build/devicetree.log` and
`.local/neo84-host-check.log`. These are offline artifact checks; hardware
qualification remains outstanding.

## Artifact

| Item | Value |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.15-cpi31-3067fcbc9253.img` |
| Raw bytes | `4294967296` (4 GiB) |
| Raw SHA-256 | `3067fcbc9253ccc414669188832889e3a8c6f7bd4a90222e89ed367dc9513e50` |
| Gzip bytes | `269770920` (about 270 MB) |
| Gzip SHA-256 | `e6e207dac09d781f7ae2c06e5cd366c5aa0c54429e152b1011e6dc5e36589787` |

`task mac:stage` uploaded the private archive and flash helper to the Mac,
then verified its compressed hash and decompressed image hash. No SD card was
written. The transfer record is `.local/flash/transfer.json`; its transcript is
`.local/neo84-mac-stage.log`.

## Hardware comparison protocol

Diagnostic.14's comparison baseline is [report 105](105-diagnostic14-late-noirq-repeats.md):
five observed late/noirq passes on one boot, retained keypad and recovered
USB/Wi-Fi routes, but recurring country/control errors. A passing PM counter
alone will not qualify this fix.

1. Identify the owner-confirmed Samsung DEV card afresh, then use the saved
   preflight, flash, full-readback and ejection workflow. Confirm login after
   reinsertion. Retain diagnostic.14 recovery and the original card backup.
2. Verify the installed manifest/kernel, current patch hash, journal policy,
   service health, effective Linux country, firmware identity and both SSH
   routes. Linux's reported regulatory domain alone does not prove the
   firmware accepted a country command. Preserve a raw kernel log before PM.
3. Run the saved awake power-key ownership and RTC delivery checks on the new
   boot. Earlier same-board results do not satisfy the same-boot admission gate.
4. With explicit owner readiness, run the freezer check and one traced devices
   cycle. Keep USB connected and controls untouched. Confirm the normal dim
   console; inspect callback errors, radio recovery and restoration before
   proceeding.
5. With fresh readiness, run one `task device:pm-platform`. Inspect the full
   late/noirq trace, original keypad handle, both independent management routes
   and country/control errors. Only then plan the four-repeat observed batch.
6. Keep raw printk timing separate from ftrace time unless aligned. Preserve
   failed runs and collect the original run after transient SSH failure rather
   than submitting another PM cycle. Do not change country or add retries to
   hide an update error. Investigate any remaining channel-query, transmit or
   control-frame warnings separately.

The five-second debug return occurs before real sleep. These tests do not
qualify power-key wake, standby lifetime, real resume latency, all generic
brcmfmac transports or NEO-55's earlier authentication failure.

Use the existing saved tasks for that sequence; the PM commands are separate
attended steps, not a shell batch to submit in advance:

```sh
task device:check ROUTE=usb ACTIVE_COUNTRY=AU
task device:pm-inspect
task device:exec ROUTE=usb -- sudo -n dmesg --time-format=raw
task device:power-key-smoke
task device:rtc-smoke
# After owner readiness:
task device:pm-test STAGE=freezer
task device:pm-power-key STAGE=devices KEYPAD_TRACE=1 WIFI_TRACE=1
# After reviewing that result and obtaining readiness for late/noirq:
task device:pm-platform
```

`ACTIVE_COUNTRY=AU` reflects the owner's accepted access-point country
announcement; it checks the current policy without overriding it. Re-evaluate
that expectation if the access point changes. Capture raw kernel output again
after each PM result; the existing PM tasks retain their other evidence and
exact run IDs automatically.
