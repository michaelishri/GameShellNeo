# Diagnostic.7: staged power-management tests

Date: 30 September 2026 (New Zealand). Kaneo: NEO-36.

## Scope and current status

Diagnostic.7 (`6.18.54-gameshellneo7`) is built, offline-verified, packaged and
checksum-verified on the Mac. It prepares explicit kernel PM debug tests and
read-only runtime-PM investigation. It is not a working sleep release.
The owner authorized unattended implementation/build work and left the board
USB-connected through the Mac. No live suspend/debug stage, card flash or
power-button test was performed overnight. Diagnostic.6 remains installed.

Normal systemd sleep targets remain masked and `AllowSuspend=no` remains in
place. A short power press still shuts down. The build enables `SUSPEND`,
`PM_DEBUG`, `PM_SLEEP_DEBUG` and `PM_ADVANCED_DEBUG`; it keeps hibernation,
autosleep, wake-lock autosleep, boot-time suspend tests and PSCI deep idle off.
The boot script selects `mem_sleep_default=s2idle`. This does not implement
PSCI system suspend, Crust integration or A33 DRAM retention.

## Source findings and configuration decisions

All source observations below refer to the hash-locked Linux 6.18.54 source
with the project's exported patch queue. Reproduce it with `task prepare` and
`task build:kernel`; the files are under `.local/sources/linux-6.18.54/`.

### Use small, automatically returning stages first

`kernel/power/suspend.c:enter_state()` exits after the freezer debug test and
thaws processes. `suspend_devices_and_enter()` exits after the devices debug
test, invokes recovery/resume callbacks, and returns without reaching
`suspend_enter()`'s late/noirq/platform path. The default debug delay is five
seconds, exposed as the built-in suspend module parameter.

The saved test accepts only `freezer` and `devices`, verifies the selected
debug stage immediately before writing `freeze` to `/sys/power/state`, and
requires exactly one five-second debug-wait message plus one successful PM
statistics increment. Success here means a completed debug cycle. It is not
evidence of sleeping power, wake latency or memory-controller retention.

### Keep USB experiments separate

The existing absent-poll experiment explicitly rejects `CONFIG_PM_SLEEP`.
The new source lock omits both USB experiment selectors; it does not merely
set them false. No alternate USB boot-policy scripts are emitted. Both driver
parameters default off and the staged test checks their live readback.
Kconfig and boot-script checks reject mixed experiment/suspend settings.

`drivers/power/supply/axp20x_usb_power.c` currently masks non-wake IRQs during
suspend and rearms polling on resume, but does not cancel its delayed worker
on entry. That work uses `system_power_efficient_wq`, which is not a freezable
queue. RSB's system-suspend callback runs in the noirq phase and resets/gates
the controller. Their interaction must be fixed and tested before exposing
late/noirq or actual s2idle tests. The first two debug stages do not reach that
RSB callback. No USB suspend-race fix is claimed by this image.

### Resolve the first SDIO suspend contract

`drivers/net/wireless/broadcom/brcm80211/brcmfmac/bcmsdh.c` requests
`MMC_PM_KEEP_POWER` when host card-power-off capability is absent. The existing
board described neither card power-off nor retained suspend power. In
`drivers/mmc/core/host.c`, the standard DT property `keep-power-in-suspend`
maps to that capability; without it, the driver's request is rejected and
logged as `Failed to set pm_flags`.

The diagnostic DTS now advertises retained power for the non-removable Wi-Fi
card. The radio rails remain enabled as in the earlier board configuration.
This matches the driver's first-stage behavior without introducing card
removal/reprobe into the first PM test. It adds neither `cap-power-off-card`
nor SDIO wake. `task check:dt` checks the **compiled** capability and rejects a
copy with the property removed. The live stage preflight also requires it;
PM-flag errors and resume/probe failures fail the result.

Power retention is a diagnostic choice, not the eventual lowest-power radio
policy. Full removal, shared supply/reset dependencies and firmware restoration
need their own qualification. Matching firmware reloads are recorded in the
kernel evidence; the staged checker rejects wrong identities and crash/fault
markers rather than treating every reload as a crash. The stricter existing
cold-boot test still expects a single firmware load on a fresh boot.

The same source audit found that `brcmf_ops_sdio_suspend()` ignores the return
from `brcmf_sdiod_freezer_on()`, and the resume helper ignores its bus-wake
result. The freezer helper uses an unbounded `wait_event()` before requesting
bus sleep. This image does not refactor that path. The recorder explicitly
rejects its known bus-sleep/clock errors in addition to checking PM statistics
and network recovery. Bounded failure propagation/unwind remains a follow-up;
a successful PM counter alone is insufficient evidence of radio sleep.

### Button, display and memory boundaries

`drivers/input/misc/axp20x-pek.c` enables wake on both key edges when permitted.
Its resume-noirq wake-edge clearing is specific to AXP288; it does not provide
that special handling for this board's AXP223. A future wake press must not
also reach logind as a shutdown request. The debug test uses a temporary
power-key/sleep/idle inhibitor; it does not qualify physical button wake.

The sun4i DRM driver has standard mode-config suspend/resume callbacks.
The project's panel lifecycle and OCP8178 backlight restoration therefore need
real observation after the devices stage, even when sysfs values return.
A 4 MiB process-memory checksum checks preservation across the debug cycle;
it does not exercise DRAM self-refresh or validate a retention implementation.

## RSB investigation made possible by the image

[Report 53](53-rsb-runtime-pm-comparison.md) found no bus runtime suspension
at 1,000, 100 or 20 ms delays with USB connected. The read-only inspection at
`.local/diagnostics/20260929T115022.168106Z/inspection.json` then found active
runtime-PM consumer links from RSB to the SD-card host, Wi-Fi host, main pin
controller and SPI panel. The SD-card host was suspended; the Wi-Fi host was
active with `power/control=on`. The panel/pin controller reported unsupported
runtime PM. Link activity describes binding/dependency state, not proof that
each link held a reference at that instant.

The source provides a concrete explanation for the Wi-Fi host policy:
`brcmf_sdiod_host_fixup()` intentionally calls `pm_runtime_forbid(host->parent)`
with the comment that runtime PM powers off the device. Its removal path calls
`pm_runtime_allow()`. The sunxi MMC driver also holds runtime references for
enabled SDIO interrupts. Linux runtime PM refuses suspension with a nonzero
usage count; runtime-enabled device links can retain supplier references.

**Inference:** that active Wi-Fi dependency is a plausible constraint keeping
RSB awake regardless of its autosuspend delay. The exact reference ownership
and contribution from other consumers remain unmeasured. Diagnostic.7 exposes
`runtime_usage`/`runtime_enabled` and saves the link graph for that next check.
It changes no runtime references, host policy, links or RSB delay. Any future
fix must preserve regulator/interrupt ordering and be measured separately.

## Repeatable tasks and recovery

```sh
task device:pm-inspect
task device:pm-test STAGE=freezer
task device:pm-test STAGE=devices CYCLES=1
# Only after the first two pass and the display returns normally:
task device:pm-test STAGE=devices CYCLES=4
task device:pm-collect RUN=<printed-32-character-hex-id>
task device:pm-restore
```

The helper requires the locked image/kernel/radio, healthy services, USB power,
Wi-Fi association, stock USB policy, normal sleep masks and a five-second
debug delay. A host flock and exclusive device ownership record prevent
overlapping saved tests. Driver callbacks run serially (`pm_async=0`) for
initial diagnosis. Both original debug controls are restored with readback
from `finally` and independently through `ExecStopPost`; malformed/foreign
ownership or failed restoration retains the record.

The device service runs independently of SSH, without an SSH-owned stdout
pipe. A temporary logind inhibitor surrounds the test. Before/result evidence
is atomically written and synced under private
`/var/lib/gameshellneo/pm-tests/<RUN>/`; the host stores copies and the lock
under `.local/diagnostics/`. It waits 30 seconds for peripherals/cache recovery
and requires fresh USB and Wi-Fi SSH on the same boot before reporting a pass.
Multiple cycles stop at the first failure.

Charger limits, CPU policy, Wi-Fi profile/configuration/power-save setting,
backlight and input inventory must also match after return. This is state
readback, not a substitute for observing the display or measuring electrical
charger behavior.

The service has a 120-second limit and independent stop-time restoration; the
host collects for up to 180 seconds plus individual connection/command timeouts.
These bounds require a functioning kernel and scheduler. They cannot recover
a driver deadlock or interrupted SD writes. Initial tests need the owner
present and a recovery image available. If evidence is missing, the task does
not retry the stage. Retain the run ID, helper and device records, recover
access, collect evidence, then decide whether physical power cycling or a
reflash is needed.

## Build and host validation

The completed checks were:

- `task check`: 13 runtime tests passed; 199 tool tests completed with 198
  passed and one existing opt-in user-systemd test skipped. This includes 11
  targeted PM-runner tests, four suspend-build isolation tests and the existing
  USB boot-policy regressions. C current-limit/mount-guard tests and shell lint
  also passed.
- Native and ARM32 clock-search and USB policy/lifecycle regressions passed.
  The compiled-board run passed 4,665 USB policy cases, 160 probe/unwind cases
  and 96 bounded-diagnostic scenarios on each architecture.
- The full kernel/module build passed 139 configuration assertions and
  recorded 15 kernel-stage artifacts. Device-tree schemas produced no
  diagnostics; the compiled SDIO contract passed and its missing-capability
  negative control was rejected.
- Offline image verification passed MBR bounds, original bootloader readback,
  FAT16/ext4 checks, U-Boot CRCs/addresses, kernel/DTB/module/radio hashes,
  private identity permissions and service policies. The new assertions checked
  isolated boot arguments, sleep masks, disabled idle sleep and button shutdown.
- All **145 image source-input hashes** matched the working files after the
  build. The image records only `suspend_diagnostics: true` and contains no USB
  experiment boot-policy manifest.
- `task image:pack` and `task mac:stage` completed. The Mac checked both the
  compressed archive and its decompressed image using source-only verification;
  no card was accessed or written.

The preliminary kernel build was deliberately stopped after finding the SDIO
capability gap. `task kernel:reset` archived scratch state, and the final queue
was rebuilt using `task build:kernel`, `task test:usb-policy-board`,
`task check:dt` and `task build:image`. Earlier unchanged native/ARM code
regressions had already passed. Standard logs are under `.local/build/`;
the final host suite is `.local/neo36-check-final-host.log`, and transfer
evidence is `.local/neo36-mac-stage.log`.

| Artifact | Value |
| --- | --- |
| Raw image | `.local/artifacts/GameShellNeo-0.1.0-diagnostic.7-cpi31-74c52a8f6fd0.img` |
| Raw size | 4,294,967,296 bytes |
| Raw SHA-256 | `74c52a8f6fd05abfb4e4ebd9c8261bd857a430892e235c2a98c3dc3fd30f99c8` |
| Transfer archive | `.local/flash/GameShellNeo-0.1.0-diagnostic.7-cpi31-74c52a8f6fd0.img.gz` |
| Compressed size | 271,350,239 bytes |
| Compressed SHA-256 | `2d838db1533f9e5dc6db84422a28061668a24bfc10b4be9bfa115cb66c641f0b` |
| Mac staging | Same archive plus `transfer.json` under the account's `~/.local/share/GameShellNeo/` |

The zImage is 5,784,152 bytes, versus the hash-verified retained diagnostic.6
zImage's 5,751,248 bytes: a 32,904-byte increase across this configuration/
version change. This is an artifact-size observation, not a boot-time or
runtime-memory measurement.

The diagnostic.6 recovery image is retained as
`GameShellNeo-0.1.0-diagnostic.6-cpi31-1e1f931ccf1a.img`, with its transfer gzip.
Its source lock, resolved configuration, completed-kernel manifest and
verification/transfer records are preserved under
`.local/recovery/diagnostic6-before-pm/`. The original-card backup is unchanged.

The read-only inspection task ran on diagnostic.6 and correctly reported an
empty power-state list and absent sleep/debug controls. Host regressions cover
unsafe-stage rejection, live-preflight policy isolation, failed readback,
foreign/existing ownership, signal-style unwind, actual child SIGKILL followed
by fresh-process recovery, statistics/journal checks and independent service
restoration. No host test writes real host PM sysfs.

Final read-only board evidence is
`.local/diagnostics/20260929T123022.921101Z/inspection.json`. Diagnostic.6 remained
on boot `6c38af94-5335-41a5-aa97-3d17a549be6d`, with USB configured, all checked
services active without restarts, no failed units, zero kernel taint, one
expected firmware load and no tracked radio/PM fault markers. Battery telemetry
reported 100% while charging; charger limits, CPU policy and the restored
1,000 ms RSB delay were unchanged. Independent Wi-Fi SSH reached the same boot.
No new hardware sleep qualification is implied by those awake checks.

## First owner-present sequence

Tracked separately as **NEO-37**; NEO-36 covers preparation and offline checks.

1. Shut down and move the Samsung DEV card to the Mac. Use the existing guarded
   flash/full-readback/eject tasks for diagnostic.7; retain diagnostic.6.
2. Boot with USB connected and the usual Wi-Fi available. Run integration and
   a fresh-boot capture, then `device:pm-inspect`. Inspect RSB usage/link state.
3. Run one freezer cycle. Stop on any fault or missing result.
4. Run one devices cycle. Observe display/backlight and verify both networks;
   then run four devices cycles only if the first cycle is clean.
5. Review all evidence before adding later stages, fixing the USB work/suspend
   interaction, or testing real button wake. No week-long sleep or subsecond
   resume claim follows from these tests.
