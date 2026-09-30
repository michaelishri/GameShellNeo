# Keypad supply-retention diagnostic (NEO-44)

30 September 2026. Preparation for the owner's CPI v3.1, following the
[persistence comparison](61-keypad-persistence-comparison.md).

## Purpose and scope

Diagnostic.8 powers down the internal keypad supply during the devices debug
stage. USB persistence then waits unsuccessfully for a connection before
re-enumeration. Disabling persistence improved healthy-handle availability by
approximately 1.8 seconds, but both policies lost the original input handle.

Diagnostic.9 isolates supply retention. It keeps **exactly the same
`6.18.54-gameshellneo8` kernel binary and modules**, source patches, configuration,
firmware, NVRAM and bootloader as diagnostic.8. The image version deliberately
advances without advancing the kernel release. Reusing the completed kernel
stage avoids a rebuild and keeps the comparison focused on the device tree.

The only semantic device-tree difference is the empty `regulator-always-on`
property on `/regulator-keypad`. Its existing `keypad-vbus` identity, nominal
5 V configuration, active-high PL2 GPIO and USB PHY supply binding are checked.
The original compiled DTB is also retained in `/boot` as
`sun8i-r16-clockworkpi-cpi3-power-off.dtb`. This file alone is not a selected
rollback; the saved recovery task below selects the fully qualified image.

In the pinned Linux source, `sun4i_usb_phy_power_off()` still releases the
consumer's regulator reference. `drivers/regulator/core.c:_regulator_disable()`
does not switch an always-on supply off. This uses the existing regulator
lifetime accounting rather than driving PL2 directly or altering shared USB
code. The relevant source is the locked Linux 6.18.54 tree under
`.local/sources/linux-6.18.54/`; the board node is in
`arch/arm/boot/dts/allwinner/sun8i-r16-clockworkpi-cpi3.dts`.

USB host/controller and PHY suspend still run. Retaining supply therefore
does **not** guarantee USB connection or input-handle continuity. It also does
not add keypad wake, change persistence from its original `1`, enable runtime
autosuspend, or implement real sleep. Ordinary sleep stays masked, the power
button still shuts down, and Wi-Fi retains the previously qualified SDIO
capability without radio wake. Full PMIC poweroff remains a separate path.

## Repeatable build and verification

The source lock declares `suspend_diagnostics=true` and
`keypad_supply_retention=true`; other experiment combinations are rejected.
For the existing completed diagnostic.8 kernel stage:

```sh
task check
task check:dt
task build:image
task image:pack
```

For a clean environment, use the normal `task setup`, provisioning and
`task build` workflow documented in the README. Credentials remain in `.env`.

`tools/keypad_supply.py` transforms the checked baseline DTB using the pinned
builder's `fdtput`. Verification removes precisely the added property from a
temporary copy and compares sorted `dtc` representations of the complete trees.
Every other node and property must match. It records both DTB hashes and the
explicit experimental identity in `/etc/gameshellneo/image.json`. Offline image
verification repeats the semantic comparison and matches the baseline against
the completed kernel manifest. The installed kernel/modules retain their
existing byte-for-byte checks.

`task check:dt` checks both DTBs against the pinned schema set. It also exercises
six negative controls: missing/non-boolean retention, disabled OHCI, altered
regulator voltage, added Wi-Fi wake and added Wi-Fi power-off capability. An
explicit supply-binding check uses the locked A33 PHY node `/soc/phy@1c19400`.

## Recovery prepared before assembly

```sh
task image:checkpoint NAME=diagnostic8-before-keypad-retention
task mac:stage-recovery NAME=diagnostic8-before-keypad-retention
```

The checkpoint is private at
`.local/recovery/diagnostic8-before-keypad-retention/`. It contains diagnostic.8's
own verification, source, image, kernel, patch and transfer metadata, with
checksums. Its retained raw image SHA-256 is
`3df063ed9bee29ca8ec90af655b683aae3c9c7269234ba587955178eafa66b03`;
the gzip SHA-256 is
`f5bdf224c462e05358ec1eaa9703a189cde2a005883f91c72fe6bae1dbc43cb0`.

`mac:stage-recovery` verifies that checkpoint's metadata and both local artifact
hashes, independently of the current build manifests. It reuses an archive
already present on the Mac, checks compressed and decompressed hashes there,
then replaces the selected transfer manifest only after successful verification.
Missing archives require explicit `UPLOAD=1`, so recovery selection cannot
silently send a large file over the mobile hotspot. A wrong-size or corrupted
existing archive fails without selecting it. This task does not write a card.

To restore diagnostic.8, select this checkpoint, physically move the DEV card
into the reader, then use `mac:status`, a **fresh** `mac:inspect DISK=diskN`,
`mac:preflight`, and `mac:flash DISK=diskN`. Never reuse an old disk number
without identification. Full write/readback and safe ejection remain required.
Selecting recovery does not change the newest local build/transfer manifests.

## Hardware qualification sequence

After normal candidate transfer, guarded flash/readback and owner-observed boot:

```sh
task device:check ROUTE=usb
task device:pm-inspect
task device:keypad-inspect
task device:pm-test STAGE=freezer CYCLES=1
task device:keypad-retention CYCLES=1
# After reviewing the first result and checking normal display/input:
task device:keypad-retention CYCLES=4
```

The Mac and GameShell must share the configured 2.4 GHz network and USB must
remain connected. Existing PM gates check both independent SSH routes,
image/kernel/radio identity, battery/USB power, services, memory, fault counters,
normal sleep restrictions and restoration. The helper checks that the live DT
retention property agrees with the source lock before entering any stage.

The saved retention task runs traced devices stages and writes `retention.json`
alongside each complete result. It requires a complete, restored trace without
a keypad regulator-disable event. It records original-handle health, USB device
number and input sysfs continuity, disconnect count, stage duration and the
delay until a fresh healthy input handle is available. A recovered device that
still re-enumerates is recorded as a negative continuity result, not presented
as seamless input recovery. No button events are injected or consumed.

The intentional five-second debug pause remains in every stage. The same
256 KiB per-CPU trace setting and 30-second minimum recovery window are used.
`device:pm-collect RUN=...` and `device:pm-restore` retain their existing roles;
neither can recover a kernel deadlock. Persistence comparison remains scoped to
the power-off image, preventing accidental comparisons under retained power.

Physical press/release and held-key testing, electrical confirmation, actual
sleep, wake latency, repeated long-duration reliability and retention energy
cost remain unqualified. The five-second driver debug window cannot establish
week-long battery life. Retention is an experiment, not the selected production
policy; the faster power-off/persistence-off candidate remains available for
comparison and lower-power policy work.

## Preparation results

The host suite passed **233 tool tests** (one optional skip), **13 runtime
tests**, the compiled current-limit and Mac mount-guard tests, Bash syntax and
ShellCheck. Recovery tests include mismatched but rehashed metadata, corrupt
artifacts, path escape, verification failure before selection, archive reuse and
refusal to transfer a missing archive without the upload opt-in. Retention tests
separate healthy original handles from successful re-enumeration and reject
supply-disable events, missing retention and incomplete/unrestored traces.

The unchanged kernel passed all **145 Kconfig assertions** and its **15-file
artifact manifest**. Baseline and retention device trees passed schema checks
without diagnostics; all six candidate-tree negative controls were rejected.
Private logs are `.local/neo44-host-check-final.log`,
`.local/neo44-dt-check-final.log` and `.local/build/keypad-supply.json`.

The baseline DTB SHA-256 is
`ccb60ba5fb326a959f8d560417e7329669d3c48606e03620a3e0acd841b9835c`;
the retained-supply DTB is
`a9dc9e2bf208c3aa7a446cd2dd88e4722efa5febd9fa8bfe4e047e829dbabb45`.

The saved recovery task was executed against the Mac's existing diagnostic.8
archive. Compressed/decompressed checks passed and its matching manifest was
selected without retransferring the archive or writing a card. Evidence:
`.local/neo44-recovery-mac-verified.log`.

Read-only pre-install inspection at
`.local/diagnostics/20260930T063728.568361Z/inspection.json` confirmed the unchanged
diagnostic.8 boot, PM success count 14, all failure counters zero, taint zero,
and no live keypad retention property. The battery reported 100%.

Image assembly passed offline verification: partition/bootloader readback,
FAT16/ext4 checks, U-Boot checksums/load addresses, kernel/modules/radio identity,
both DTB contracts, private-file permissions and service/sleep policy. The
prepared raw image is
`.local/artifacts/GameShellNeo-0.1.0-diagnostic.9-cpi31-4c48c1bd110e.img`,
4,294,967,296 bytes, SHA-256
`4c48c1bd110eabb310b5fa608ea1e99f7eef7560c295700763dc30da91d15567`.
`kernel-completed.json`, `kernel.config` and `packages.txt` are byte-identical
to the diagnostic.8 checkpoint. Every recorded `runtime/` input hash also
matches. Build evidence is `.local/neo44-image-build.log` and
`.local/build/image-verify.log`; the baseline comparison is saved in
`.local/neo44-baseline-equivalence.json`.

The owner confirmed regular Wi-Fi before transfer. `task mac:stage` packed and
transferred the candidate, then verified its compressed and decompressed hashes
on the Mac. The gzip is **265,592,615 bytes**, SHA-256
`0892550dc47de9b0ba832286636a788903e121be4c88b84a4c32c65dee2f0c27`.
Evidence is `.local/neo44-stage-mac.log` and `.local/flash/transfer.json`.
The recovery archive remains on the Mac and can be reselected through the
checkpoint task. Preparation is complete; installation and hardware tests are
tracked separately as NEO-45.
No diagnostic.9 flash or hardware result is claimed by this preparation report.
