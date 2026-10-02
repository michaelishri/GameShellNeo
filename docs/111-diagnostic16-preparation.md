# Diagnostic.16 preparation (NEO-87)

3 October 2026, Pacific/Auckland. The complete build, offline verification and
Mac staging passed for the next Wi-Fi driver candidate. Diagnostic.15 remains
installed; no card write, device reboot or PM cycle was part of this unattended
work.

## Scope and recovery

Image `0.1.0-diagnostic.16`, kernel `6.18.54-gameshellneo16`, adds two patches:

- [0021: transmit suspend ownership](109-wifi-transmit-suspend-ownership.md)
  stops and drains active netdev transmitters before transport suspension,
  preserves independent stop reasons across bus recovery and releases suspend
  ownership after configuration restoration. A failed deferred country update
  or unavailable transport keeps carrier blocked. The existing warning and
  rejected-packet handling remain intact.
- [0022: band query errors](110-wifi-band-query-errors.md) checks required reads,
  propagates transport errors, retains legacy optional firmware-rejection
  defaults and completes scalar validation before channel mutation. Channel
  construction itself still needs separate transaction/error work.

The source lock changes only image version and kernel localversion. Firmware,
region provisioning, charging policy and power-key behavior remain unchanged.
Normal sleep stays masked; an ordinary short power press still shuts down this
diagnostic image. The product's short-press sleep/wake, two-second menu and
eight-second hard-off behavior remains future work.

The saved workflow is:

```sh
task image:checkpoint NAME=diagnostic15-before-tx-band-fixes
# Advance image version and kernel localversion in build/sources.lock.json.
task kernel:reset
task provision
task check
task build
# Only after offline verification, on the accepted regular Wi-Fi connection:
task mac:stage
```

Checkpoint `.local/recovery/diagnostic15-before-tx-band-fixes/` retains the
verified image and matching kernel, patch, package and transfer provenance:
`GameShellNeo-0.1.0-diagnostic.15-cpi31-3067fcbc9253.img`, raw SHA-256
`3067fcbc9253ccc414669188832889e3a8c6f7bd4a90222e89ed367dc9513e50`.
Its compressed archive remains available. Prior kernel source/output/install
and artifact metadata are archived in
`.local/previous-kernels/20261002T141410Z-920916/`.

The build extracts a fresh kernel and uses the locked builder with one job.
Provisioning reads private credentials from `.env` and preserves the established
device identity. Private transcripts are `.local/neo87-*.log` and
`.local/build/*.log`.

## Verification

The host checks passed 13 runtime and 346 tooling tests (one existing optional
skip), compiled current-selector/mount-guard checks, Bash syntax and ShellCheck.
The complete saved pre-kernel regression sequence also passed, including the
109 transmit-admission and 85 band-query scenarios on native and ARM32 builds,
with all 22 negative controls rejected by assertions.

The complete kernel, board DTB and ten modules compiled successfully. All ten
module vermagic strings identify `6.18.54-gameshellneo16`; the completed kernel
record covers fifteen files. Device-tree schemas and compiled USB/SDIO/speaker/
keypad-retention checks passed, including their negative controls.

The resolved configuration is byte-identical to diagnostic.15, SHA-256
`d370205bf2e4eed5e35483f15372a6785e7d96252d40c343dfee0b2dde37a017`.
All twenty prior patch hashes match the recovery checkpoint. The additions are:

| Patch | SHA-256 |
| --- | --- |
| `0021-brcmfmac-tx-suspend.patch` | `a4c38e5c9d2b3ddb5f9747db67155849f2f1f3420bebd7603f847da3f85ca644` |
| `0022-brcmfmac-band-query-errors.patch` | `f324dac4ce497da7c85238289e4c59fe35e30c4b2314270c4d355c92a952fefc` |

Base-rootfs creation ran again because the conservative cache key hashes the
entire source lock. This candidate keeps that cache policy; a narrower verified
key and safe kernel-object reuse are separately tracked build optimizations.

The package inventory is byte-identical to diagnostic.15, SHA-256
`66dc03283bb690e55ab2b2540b0ffe43310dfb39f872672c4d6b3884ecc3358b`.
All 224 recorded project-input hashes match the source files. The 4 GiB image
passed partition boundaries, bootloader readback, FAT16/ext4 checks, U-Boot
CRC/address checks, kernel/DTB/module/radio hashes, private identity permissions
and service policy checks. It remains marked as not hardware-qualified.

Evidence is `.local/neo87-artifact-inspection.json`,
`.local/neo87-baseline-comparison.json`, `.local/neo87-module-vermagic.json`,
`.local/artifacts/verification.json`, `.local/build/image-verify.log`,
`.local/build/kernel.log`, `.local/build/devicetree.log` and the saved host-check
transcript. No source test or offline inspection substitutes for the hardware
comparison below.

A read-only review during compilation also identified discarded firmware
results in existing Wake-on-Wi-Fi setup/cleanup. That separate audit is recorded
in `FOLLOW-UP.md`. Patch 0021 checks the deferred country-update result before
releasing transmit ownership; it does not add propagation for every existing
WoWL command. No observed board failure is attributed to that additional gap.

## Artifact

| Item | Value |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.16-cpi31-de531424ec88.img` |
| Raw bytes | `4294967296` (4 GiB) |
| Raw SHA-256 | `de531424ec88e55cbc991e757e295e49658a8991fb0058c5380bc969814d90c7` |
| Gzip bytes | `269818440` (about 270 MB) |
| Gzip SHA-256 | `c93ca2f5ea31ed2b63ca658474c162c93c8a1cef548a1f2046b614c205574776` |

`task mac:stage` uploaded the private archive and flash helper to the Mac,
then verified both its compressed hash and decompressed image hash. No card
was written. The transfer record is `.local/flash/transfer.json`; the transcript
is `.local/neo87-mac-stage.log`.

## Retention cleanup

After staging, the saved retention workflow reclaimed **8.21 GiB**, leaving
about **54.05 GiB** free on the Intel host:

```sh
task build:prune-retained KEEP=3
task build:prune-retained KEEP=3 APPLY=1
```

It verified all ten recovery checkpoints and the compressed replacements for
raw diagnostic.11/12/13 before removing those raw copies and three older kernel
snapshots. The three newest raw images (diagnostic.14/15/16), three newest
kernel snapshots, compact provenance and compressed recovery archives remain.
The original-card backup was untouched. Private evidence is
`.local/retention/prune-20261002T150445.947557Z.json` and
`.local/neo87-retention*.log`.

## Hardware comparison protocol

[Diagnostic.15's baseline](108-diagnostic15-hardware-qualification.md) has one
freezer, one devices and five observed late/noirq passes. Both network routes,
the retained keypad and normal display return passed. Country/control errors
did not recur, but the first late/noirq test logged `xmit rejected state=0`
inside its debug delay; the four repeats did not. Therefore a clean single
cycle on diagnostic.16 cannot establish that the intermittent warning is fixed.

1. With the owner present, identify the Samsung DEV card afresh, then use the
   saved preflight, flash, full-readback and ejection tasks. Confirm login after
   reinsertion. Keep diagnostic.15 recovery and the original card backup.
2. Check the installed image/kernel and both new patch hashes, integration,
   journal continuity, firmware identity, effective country and both SSH routes.
   Capture a raw kernel log before PM. Verify initial Wi-Fi association as well
   as USB access; patch 0022 can now return errors previously hidden by defaults.
3. Repeat the awake power-key ownership and RTC alarm checks on this boot.
   Prior-boot results do not satisfy the PM admission gate.
4. After owner readiness, run freezer and one traced devices cycle. Confirm
   normal dim console return and inspect radio/keypad/USB restoration before
   proceeding. Preserve any failed run and recover its original evidence.
5. After fresh readiness, run one late/noirq cycle. Review its complete trace,
   queue-related warnings, country/control queries, callback failures and both
   SSH routes. If clean, arrange four observed repeats, reviewing each result
   before starting the next. Do not treat a passing PM counter alone as success.
6. Capture the raw kernel log and final integration/PM/audio state. Separate
   printk timing from ftrace unless aligned. Record whether transmit warnings
   recur without claiming an energy saving or a proven packet-loss rate.

Use the existing tasks as separate reviewed steps, not an unattended PM batch:

```sh
task device:check ROUTE=usb ACTIVE_COUNTRY=AU
task device:pm-inspect
task device:exec ROUTE=usb -- sudo -n dmesg --time-format=raw
task device:power-key-smoke
task device:rtc-smoke
# After owner readiness:
task device:pm-test STAGE=freezer
task device:pm-power-key STAGE=devices KEYPAD_TRACE=1 WIFI_TRACE=1
# After result review and fresh readiness:
task device:pm-platform
```

`ACTIVE_COUNTRY=AU` reflects the owner's accepted AP announcement, not an
override or qualification of NZ operation. Re-evaluate if the AP changes.
Independent USB recovery is required if a deferred configuration error prevents
Wi-Fi from reopening. Do not add retries or silence the warning to make a run
pass. Initial boot, normal association and error-free staged PM recovery are
the candidate's immediate hardware gates.

These five-second PM debug tests stop before real sleep. They do not qualify
power-key wake, standby lifetime, actual resume latency, all brcmfmac transports,
firmware-country readback or the earlier NEO-55 authentication failure.
