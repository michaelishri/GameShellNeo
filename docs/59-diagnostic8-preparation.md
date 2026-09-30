# Diagnostic.8: USB PM fixes and keypad tracing (NEO-41)

30 September 2026. CPI v3.1 only. This report records preparation of the next
hardware-test image. Diagnostic.7 remains on the GameShell; diagnostic.8 has
passed offline verification and compressed/decompressed verification on the Mac,
but has not booted on the board. The owner confirmed regular Wi-Fi before the
transfer. No card has been written for this image.

Subsequent card installation and hardware results are recorded separately in
[report 60](60-diagnostic8-hardware-validation.md).

## Contents and boundaries

The image identity advances to `0.1.0-diagnostic.8` and the kernel release to
`6.18.54-gameshellneo8`. Linux, Debian, builder, bootloader and radio inputs
remain pinned to the previous source versions.

- Patch 0010 disables/drains AXP USB delayed polling across system suspend,
  restores it on resume/unwind and balances wake IRQ references. Report 56
  records the actual-source tests and remaining notification/supplier gate.
- Patch 0011 skips the absent Sunxi MUSB ULPI context register while retaining
  other controllers and invalid-access diagnostics. Report 57 records register
  equivalence and ARM builds.
- The keypad recorder preserves the original input handle across a debug cycle
  and inspects a fresh handle afterwards. Event/dynamic-debug support enables
  the opt-in supply/USB trace described in report 58. Function tracing, graph
  tracing and syscall tracing are disabled.
- The PM test now treats the specific unsupported-ULPI message as a failure.
  It must disappear on the new image; merely returning to SSH is insufficient.

Normal sleep remains masked. Only explicit freezer/devices debug stages are
available through the saved tasks. USB slow-poll/diagnostic experiments remain
off and excluded by the existing PM_SLEEP guard. Keypad rail policy, firmware
and wake behavior are unchanged. The input continuity problem remains under
investigation. No sleep-power or wake-latency improvement is claimed.

## Recovery and repeatable preparation

Before changing the lock, the new saved task verified diagnostic.7's raw and
compressed hashes and retained its matching metadata:

```sh
task image:checkpoint NAME=diagnostic7-before-usb-pm
task kernel:reset
task provision
task build:kernel
# After successful kernel completion:
task test:usb-policy-board
task check:dt
task build:image
task image:pack
```

The checkpoint is `.local/recovery/diagnostic7-before-usb-pm/`. It contains the
completed image's embedded source lock, resolved kernel configuration, patch
queue, kernel manifest, offline verification and transfer records with a
metadata-hash inventory. The raw/gzip image files remain in their original
artifact directories and must be retained with it. The previous kernel scratch
tree is archived separately by `kernel:reset`. Existing diagnostic.6 and
original-card recovery backups remain available.

The current source regressions passed before the full build: 2,052 AXP PM/IRQ
scenarios, 256 MUSB register-equivalence scenarios, negative controls and both
ARM driver builds. The combined USB policy/lifetime regressions also passed.
These are software checks, not physical supplier-bus or wake qualification.

## Full-build verification

The full ARM kernel build passed all 145 configuration assertions with zero
compiler warnings. Its completed manifest verifies 15 kernel/DTB/module files.
The compiled USB policy/PM board contract passed, including the missing
KEEP_POWER negative control. Device-tree schema validation reported no
diagnostics. `task check` passed 209 host tests (one optional test skipped),
current-limit regressions, Mac mount-guard checks, Bash syntax and ShellCheck.

The new configuration enables dynamic debug and event tracing. Function,
function-graph and syscall tracing remain disabled. The zImage is 6,414,608
bytes, 630,456 bytes larger than diagnostic.7. That is the observed build-size
difference for this diagnostic/configuration change, not a measured runtime or
power cost. Production tracing policy remains a follow-up.

Offline verification passed the MBR boundaries, bootloader byte comparison,
FAT16/ext4 checks, U-Boot CRC/address checks, kernel/DTB/module/radio hashes,
private identity permissions and service policy. The private 4 GiB raw image is:

```text
GameShellNeo-0.1.0-diagnostic.8-cpi31-3df063ed9bee.img
SHA-256: 3df063ed9bee29ca8ec90af655b683aae3c9c7269234ba587955178eafa66b03
Bytes:   4294967296
```

The transfer archive has the same filename plus `.gz`, is 265,543,852 bytes,
and has SHA-256
`f5bdf224c462e05358ec1eaa9703a189cde2a005883f91c72fe6bae1dbc43cb0`.
`task mac:stage` recompresses through the shared workflow; the repeated pack
produced the same archive hash and size.

Mac staging completed successfully over the tailnet after the owner's regular
Wi-Fi confirmation. The saved workflow verified the uploaded compressed archive
and all 4,294,967,296 decompressed bytes against the manifest. The Mac copy is
under the account's private `.local/share/GameShellNeo/` directory. Evidence:
`.local/neo41-mac-stage.log` and `.local/flash/transfer.json`. This was a source
verification only; no disk was selected or written.

The saved keypad trace now also records driver callback start/end events to
attribute recovery delays. The independent recovery command restores ordinary
PM controls even if trace cleanup fails; a regression exercises that failure.
The recovery checkpoint ran successfully for diagnostic.7, and its shared build
lock refused a concurrent checkpoint during kernel compilation without creating
a partial checkpoint.

Private evidence includes `.local/neo41-final-check.log`,
`.local/build/{kernel,usb-policy-board,devicetree,image,image-verify}.log`,
`.local/artifacts/{kernel-completed,verification}.json` and the retained
diagnostic.7 recovery directory. Personalized images and logs remain ignored.

## Next hardware sequence

1. The verified archive is staged on the Mac. Move the DEV card into its reader,
   then use the existing guarded flash/readback/eject workflow for that
   owner-confirmed card. Recheck its identity; do not reuse a disk number from
   an earlier flash.
2. Boot with USB connected and a working 2.4 GHz network. Run integration,
   keypad inspection and PM inspection; confirm exact diagnostic.8 identity.
3. Run one freezer test, then one ordinary devices test. Check the display,
   original/new input handles, both fresh SSH routes, restoration and absence
   of the old ULPI warnings. Repeat four devices cycles if the first is healthy.
4. Run one `STAGE=devices CYCLES=1 KEYPAD_TRACE=1` capture. Inspect regulator
   transitions and USB port-resume messages; require no overflow and restored
   trace/debug controls. Do not interpret instrumented duration as final wake
   latency or measure power with the recorder active.
5. Select a keypad retention/recovery experiment from that evidence. Retain
   power-button-only wake, and separately qualify held/released-button state.

Before deeper PM or real sleep, finish the asynchronous PMIC/PHY notification
ordering audit, power-key wake consumption and Wi-Fi suspend failure handling.
Those gates are recorded in `FOLLOW-UP.md`; this image does not bypass them.
