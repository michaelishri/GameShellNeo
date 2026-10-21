# Stay asleep when USB power is attached

5 October 2026. NEO-117; verified diagnostic.20 candidate, hardware pending.

The owner selected **stay asleep and charge** when USB is connected during
sleep. [Report 165](165-diagnostic19-usb-attachment-early-wake.md) preserves the
diagnostic.19 attempt that woke before the RTC. That result is still failed;
this candidate has passed offline image verification but has not been installed
or tested on the board.

## Policy and implementation

Three independent interfaces can select cable-related wake on this board:

| Interface | Diagnostic.19 observed | Diagnostic.20 startup policy |
| --- | --- | --- |
| MUSB controller `device/power/wakeup` | disabled | disabled |
| `axp20x-usb` supply `power/wakeup` | enabled | disabled |
| `axp22x-ac` supply `power/wakeup` | enabled | disabled |

The AC and USB drivers already use their supply's `device_may_wakeup()` value
to decide whether to arm insertion wake. The standard driver controls therefore
implement the requested policy without another kernel patch. Charging remains
under the PMIC's existing configuration; this change does not write charger
registers or change current/voltage limits. POWER, RTC and the shared PMIC parent
wake settings are not modified. Physical wake-button qualification remains open.

The existing `gameshellneo-usb` startup service now validates all three controls,
writes `disabled`, and checks each readback before binding the gadget or returning
from an already-bound start. Supply registration creates its wake control after
`device_add()`, so a bare udev add rule would have an ordering gap. Missing or
unexpected controls fail startup before any policy write; the existing service's
bounded startup and restart policy handles registration readiness. A failed
write/readback also fails startup. There is no new resident process, cable-event
handler or polling loop. A driver unbind/rebind after startup is not qualified;
diagnostic admission rejects any resulting enabled or missing wake control.

Installed-image integration and PM snapshots now verify both supply controls.
Each debug prerequisite snapshot and current admission must retain the same
disabled settings. The image explicitly declares
`power_supply_system_wakeup=false` alongside `usb_system_wakeup=false`.
Missing, malformed, enabled or provenance-mismatched settings cannot pass.

The image version advances to `0.1.0-diagnostic.20`. The kernel remains
`6.18.54-gameshellneo19`: source, configuration, DTB and modules are unchanged.
The existing completed-kernel manifest verifies the reused artifacts; it is not
regenerated to authorize different inputs. Image and kernel suffixes therefore
intentionally differ.

## Masked insertion evidence

Disabling supply wake masks insertion interrupts during suspend as well as
removal interrupts. AXP223's regmap `init_ack_masked` behavior can acknowledge a
pending masked event during another interrupt-mask synchronization, before the
event's nested handler runs. Exact handler counts cannot prove the electrical
edge or be required as though all events remain deliverable.

The new image selects the prospective `masked-cable-v2` policy. Only matching
CPI v3.1 image records with both supply wake controls disabled before and after
the test may use it. For the requested direction, each AC/VBUS handler count
may increase by zero or one. Opposite events, extra dispatches and regressing
counts still fail. Awake rehearsals still require no cable change.

The original `exact-v1` and diagnostic.19 `masked-removal-v1` behavior remains
unchanged, including exact insertion counts for diagnostic.19. No stored result
is rewritten. RTC delivery at return, elapsed-time checks, real endpoint state,
original-result hashes, source/boot lineage, independent route recovery and the
separate physical observation remain required. An early cable wake still fails.

## Reproducible verification

The implementation is isolated in `.local/worktrees/power-insertion-wake` on
branch `work/power-insertion-wake`; the installed diagnostic.19 and its saved
evidence are unchanged.

```sh
task check
task lint
python3 -m unittest discover -s tools/tests -p test_usb_wake_policy.py -v
task test:power-irq-mask
task check:kernel
```

- Runtime suite: 13 tests pass; tooling suite: 576 tests, two existing skips.
  The compiled current-selector and Mac mount-guard checks pass. The first
  combined check found one ShellCheck quoting warning in the new array; it was
  corrected, then shell lint and all seven actual-startup-script tests passed.
  Once the pinned Armbian checkout was prepared, all nine journal-policy tests
  also passed, including the previously skipped real-helper guard test. Only
  the opt-in user-systemd recovery test remains unexecuted in this host run.
- Startup fixtures execute the real shell policy against isolated controls:
  repeated starts, the supply-registration gap and retry, invalid settings,
  ineffective setters/readback failures, and untouched POWER policy.
- PM and cable regressions reject changed/missing supply settings, mismatched
  images, wrong endpoints, missing RTC delivery and invalid interrupt deltas.
- Actual Linux 6.18.54 regmap mask/synchronization functions pass ten scenarios
  natively and under ARM32 emulation. Insertion cases cover both supply resume
  orders with and without an intervening mask synchronization. Two deliberately
  broken implementations fail their assertions. Registers and nested interrupt
  delivery are simulated; this is source evidence, not electrical measurement.
- Reused kernel verification passes all 164 configuration assertions and all
  15 completed-artifact hashes, including the unchanged patch/config identity.

Private logs are `.local/neo117-check.log`, `.local/neo117-lint.log`,
`.local/neo117-startup-recheck.log`, `.local/neo117-journal-recheck.log`, and
`.local/build/power-irq-mask-tests/evidence.json` in that worktree.

## Verified image

The existing build/provision/verification tools were used, with a separate
Armbian checkout and output directory so diagnostic.19's retained artifacts were
not overwritten. Private provisioning reuses the existing device identity and
reads the current credentials from `.env`.

```sh
task provision
task check:kernel
task build:image \
  BOOTLOADER=/home/mishri/workspace/clockworkpi/GameShell/Code/Kernel/v0.2/u-boot-sunxi-with-spl.bin \
  RADIO_DIR=/home/mishri/workspace/clockworkpi/GameShellNeo/.local/hardware-baseline/2026-09-27/radio-reference
# After supplying the missing verification inputs described below:
python3 tools/bundle-image.py --latest
task image:pack
task image:checkpoint NAME=diagnostic20-stay-asleep-candidate
```

The changed features correctly invalidated the conservative rootfs cache key,
so the build bootstrapped a fresh signed-snapshot Debian root filesystem. Armbian
reported 19 minutes 36 seconds for assembly. The first automatic verification
then failed: the isolated workspace had the completed kernel artifacts but not
the kernel's regulatory signing certificates. The original log is retained as
`.local/build/image-verify-missing-certificates.log`. This was an incomplete
verification workspace, not a signature bypass or accepted image result.

The locked Linux archive hash was checked, its full source extracted into the
worktree, and the unchanged patch queue applied with `tools/kernel-inputs.py`.
The existing bundle tool then verified the **unchanged assembled image** with
the original certificate trust check intact. Layout, bootloader readback,
FAT/ext4 checks, kernel/DTB/module/radio hashes, regulatory CMS signature, private
identity permissions, service policies and the installed wake-policy script all
passed. The image remains explicitly `hardware_qualified=false`.

| Artifact | Value |
| --- | --- |
| Implementation commit | `97cbc11` on `work/power-insertion-wake` |
| Image | `GameShellNeo-0.1.0-diagnostic.20-cpi31-0f8763c74426.img` |
| Raw size | 4,294,967,296 bytes |
| Raw SHA-256 | `0f8763c744265e52b935abc0df8eb34cf0fc05ebd5492b15437211a4f773e52a` |
| Gzip size | 269,716,241 bytes |
| Gzip SHA-256 | `fc79f7f095c319819f0e47f8f8274a101ac23fbbd26fda931863a6fdb583959e` |
| Package inventory SHA-256 | `66dc03283bb690e55ab2b2540b0ffe43310dfb39f872672c4d6b3884ecc3358b` |
| Completed-kernel manifest SHA-256 | `77f2c3fddbcd86503840b646dc7a9c43e74f66a14610e7cadfd4ed3aad632807` |
| Regmap harness evidence SHA-256 | `20858db8d5ff84a985df15fe72d5b47e441fb731208d79660efeee86d5d2b584` |

The package inventory is byte-identical to diagnostic.19's. The raw image,
compressed archive and recovery checkpoint remain on the Intel host, under this
worktree's `.local/artifacts`, `.local/flash` and
`.local/recovery/diagnostic20-stay-asleep-candidate`. At build completion nothing
had been transferred to the Mac or written to a card. Verification workspace preflight and further
rootfs-cache dependency refinement are recorded in `FOLLOW-UP.md`.

## Subsequent Mac transfer

The owner confirmed regular Wi-Fi and explicitly requested transfer before
switching the Mac back to the PXL10 hotspot. From the candidate worktree:

```sh
task mac:stage
```

The task packed the same verified image, reached the Mac through its configured
tailnet route using the existing SSH host-key trust, uploaded the archive,
manifest and saved flash helper, and ran its `--source-only` check. It completed
successfully at **2026-10-05 04:20:09 UTC**. Both the 269,716,241-byte compressed
archive and the full 4,294,967,296-byte decompressed stream matched their recorded
SHA-256 values above.

The selected image is staged under the Mac account's
`~/.local/share/GameShellNeo/`, ready for a separately arranged card flash.
The private transfer log is `.local/neo117-mac-stage.log`, SHA-256
`d99509c020af496321a8e8111cc355cec1c6bb465cb9c12144d836db5a703763`.
No card access, device command, reboot or sleep test was performed. The owner
was told they could switch the Mac to PXL10 after both checks passed; this does
not claim that the network switch had happened at transfer completion.

The owner subsequently confirmed switching to the hotspot and requested remote
shutdown because the POWER button was suppressed. Using the installed image's
existing tools in the main checkout, the operator ran:

```sh
task device:audio-test ROUTE=usb
task device:exec ROUTE=usb -- sudo -n systemctl --no-block poweroff
```

The saved speaker test completed three level-5, one-second warnings and verified
mixer/amplifier restoration on the original boot
`2fa86697-ead3-4e6f-a295-44e6ad203983`. Main-checkout capture
`.local/diagnostics/20261005T042340.005303Z/result.json`, run
`6a7c8cef24d34b24bd85852d04a49faa`, has SHA-256
`f419227a55184d79811397e6278438618d492defa5da8870bea9c6b87b7b1604`.
This establishes successful playback execution and restoration; audibility was
not separately confirmed by the owner in this shutdown sequence.

Only after that success was one normal `poweroff` request submitted over USB;
the command returned exit status zero. The retained diagnostic guard was not
manually removed or used as a reason to re-enable uncertain button handling.
The owner was asked to wait for darkness, wait another ten seconds, unplug USB
and move the Samsung DEV card into the Mac reader. The owner subsequently confirmed card
placement, and guarded flash/full readback and ejection passed;
[report 167](167-diagnostic20-installation-and-awake-checks.md) records that
result and the pending first-boot confirmation.

## Remaining board qualification

A separately arranged installation must check
all three live wake settings, both SSH routes, charging telemetry, journal
continuity and the existing awake POWER/RTC ownership tests. Establish a fresh
same-image, same-source debug baseline and awake rehearsal before any actual
sleep. Keep the long speaker warnings and obtain fresh observer readiness.

First qualify unchanged-cable RTC sleep. Then separately test attachment during
sleep: start on battery, attach USB once after the requested dark wait, remain
asleep until the RTC, and recover correct external-power/USB state and both SSH
routes. Repeat the removal comparison under the new policy. Qualification must
distinguish external power being present from a battery actually accepting
charge; a full battery is not evidence of charging throughout sleep. Measured
charge accumulation, energy, deeper retention and production POWER wake remain
separate work.

At build completion diagnostic.19 remained connected with its failed run and
retained diagnostic power-key suppression intact; no live wake policy or device
test was changed during candidate preparation. The separately requested warning
and shutdown above followed the later successful Mac transfer. No additional
sleep or reboot test has been submitted.
NEO-117 remains open pending hardware qualification; ordinary sleep stays disabled.
