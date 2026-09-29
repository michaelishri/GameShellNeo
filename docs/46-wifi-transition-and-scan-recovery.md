# Wi-Fi transition and scan recovery

Date: **29 September 2026 NZDT**. Work: **NEO-29** (network transition),
**NEO-26** (firmware crash). Target: owner's CPI v3.1, diagnostic.5.
Status: **network transition qualified; firmware recovery investigation continues**.

## Trigger and separation of faults

The owner changed from the earlier hotspot to a router network and updated
the credentials privately in `.env`. USB stayed connected to the Mac, whose
tailnet SSH endpoint remained available. The board's old network became
unavailable and the existing firmware crash/reprobe loop returned. Both
attempts to apply the new network also failed to associate, including after
the owner moved closer to the router. Signal strength has not yet been
measured, so weak reception is a hypothesis, not an established cause.

Kernel messages identify a **firmware halt**, followed by SDIO removal and
reprobe. Supplicant logs repeatedly report `Failed to initiate sched scan`,
approximately sixteen seconds apart. A host-driver kernel oops has not been
established. This extends the [earlier unavailable-hotspot finding](44-diagnostic5-hardware-validation.md);
it is not caused by changing the USB polling policy during this test.

The installed radio identifies as BCM43430 revision 0, using the owner's
`brcmfmac43430a0-sdio.bin`, whose embedded version is
`7.46.57.4.ap.r4`, dated 8 October 2016. Host driver source is available in
the locked Linux tree; the supplied radio firmware is binary, with separate
board NVRAM. Source availability and alternative firmware are investigated
separately in [report 47](47-wifi-firmware-options.md).

## Reusable network transition

```sh
# Save the new Wi-Fi credentials in .env; put the Mac on the same network.
# Leave USB attached. This always uses USB for control.
task device:wifi-config
```

The task refreshes private provisioning using the existing renderer, then
stages the new configuration by SFTP without putting secrets in arguments or
logs. A bounded device service saves the previous config, atomically installs
the candidate and restarts only `wpa_supplicant@wlan0`. Before committing, the
host must reach the new Wi-Fi address through the configured route and verify
the provisioned SSH key, same boot identity and Wi-Fi endpoint. Success updates
only `GAMESHELL_IP` in `.env`, rejecting concurrent edits and duplicate address
assignments. The task does not rebuild an image or reboot the board.

Without verification, the device restores its previous file and restarts the
supplicant. `ExecStopPost` also invokes restoration independently of the main
process. The previous AP may be unavailable even when rollback works. This
mechanism requires a running kernel/systemd and is not power-loss recovery.
Failed cleanup retains the private directory for recovery.

Host regressions cover successful commit, timeout without host confirmation,
stale-address rejection, service failure, interrupted-state restoration,
restoration retry, `.env` preservation and exclusive SFTP write/readback.

### Transition evidence

- `20260929T054656.345544Z/`: same healthy boot, USB configured and Wi-Fi down
  after the owner's network move.
- Initial staging attempt `20260929T055119.008242Z/` failed before any live
  configuration change: Paramiko exclusive mode `x` did not grant write
  access. Corrected to `wx`, added readback and a regression against
  Paramiko's actual buffered-file mode handling. Its private temporary
  directory was subsequently removed.
- `20260929T055211.357945Z/`: first actual transaction timed out; previous
  configuration restored, `committed=false`, `passed=false`, cleanup verified.
- `20260929T055330.601827Z/`: full private diagnostics during that attempt,
  preserving firmware crash and SDIO reprobe evidence.
- `20260929T055528.114913Z/`: repeat after moving closer also timed out;
  previous configuration restored, no commit, cleanup verified.
- Supplicant transition journal is private at
  `.local/build/neo26-wifi-transition-journal.txt`.

The failed attempts are not Wi-Fi qualification passes. No battery comparison
was started; [report 45](45-usb-polling-idle-comparison.md) remains pending.

## Scan-offload isolation

The supplicant exposes `disable_scan_offload`: it normally uses scheduled
scanning when the driver advertises support. Setting this to one requests the
alternative host-scheduled path. This is a testable hypothesis, not proof of a
fault in any particular firmware command. [Supplicant documentation](https://w1.fi/wpa_supplicant/devel/structwpa__config.html).

The locked driver's `brcmf_pno_config_sched_scans()` programs PNO parameters,
channels, buckets and network matches before enabling PNO. The host driver also
initiates a bus reset when firmware reports a halt. Read the actual locked
`drivers/net/wireless/broadcom/brcm80211/brcmfmac/pno.c`, `feature.c` and `core.c`
before attributing the problem to one operation; recovery messages alone do
not identify the crashing firmware instruction.

```sh
task device:wifi-scan-test SECONDS=120
# Only needed to recover an interrupted test with a retained restoration record:
task device:wifi-scan-restore
```

Both tasks use USB. The test saves the runtime flag, then measures original,
host-scanning and original-repeat phases. Each has ten seconds settling and
120 seconds of nominal ten-second samples. It records boot identity, the
verified flag, supplicant state, interface recreation and firmware/SDIO event
count deltas. It writes no credentials, firmware, NVRAM or persistent scan
policy. The saved flag is restored normally, on handled interruption and by
systemd's `ExecStopPost`; the service has a bounded runtime. Retain its helper
directory if it fails until restoration has been verified.

A temporary `reassociate` rejection during interface recovery is recorded
separately from successful setting readback. The comparison tests a runtime
control; association changes, incomplete captures and unknown AP availability
must remain explicit. It does not measure energy or prove that the firmware
internals have been repaired.

### Scan evidence

Initial capture `20260929T060148.444468Z/` failed during the original phase:
firmware recovery removed the interface during a sysfs read, returning EINVAL.
An immediate restoration reassociation was also rejected, while the flag was
already back at zero. The independent exit hook subsequently completed;
readback showed zero and the restoration record was gone. The recorder now
retains sysfs removal errors as data and separates reassociation acceptance
from setting restoration. Regression tests cover both observed cases.
Recovery confirmation: `20260929T060423.127639Z/`. The failed helper was removed.

Repeat comparison `20260929T060444.516561Z/` completed on the same boot. Each
observation window lasted approximately 120.15–120.18 seconds:

| Phase | `disable_scan_offload` | Firmware crashes | SDIO removals | Interface behavior |
| --- | --- | --- | --- | --- |
| Original | 0 | 8 | 8 | Recreated repeatedly |
| Host-scanning | 1 | 0 | 0 | Stable interface index 79 |
| Original repeat | 0 | 8 | 8 | Recreated repeatedly |

The original runtime flag was restored to zero, the bounded service completed
and its helper directory was removed. States stayed scanning or temporarily
interface-disabled; no successful association is inferred. This repeated
reversal strongly implicates the offloaded scheduled-scan path. It does not
identify a specific defective command or distinguish invalid host requests
from a firmware implementation defect. No firmware, persistent supplicant
setting, credentials or board NVRAM changed during this comparison.

The [newer exact-A0 firmware candidate](47-wifi-firmware-options.md) is the next
isolated comparison (NEO-30). It must retain the normal offload setting while
comparing binaries; combining both changes would obscure their effects.

## Subsequent candidate and visibility findings

[Report 48](48-a0-firmware-trials.md) records the completed candidate trials:
zero crashes/removals in 120 seconds of unchanged-profile scanning and in a
separate 300-second network-transition workload, with original-firmware
restoration after each. The network transaction in
`20260929T062716.330543Z/` still failed association and verified its rollback.
The target SSID was absent from the GameShell's seven cached scan entries.

The reusable read-only checks are `task device:wifi-visibility` and
`task mac:wifi`. The former privately matches the `.env` SSID and reports only
counts and matching frequency/signal/security; the latter reports the Mac's
band/security and SSID match only when macOS exposes the name. The Mac was on
5 GHz channel 48 with names redacted. This does not establish the AP lacks a
2.4 GHz version; the owner is checking its configuration. NEO-29's successful
commit and the battery comparison remain pending.

## Hotspot transition qualified

The owner re-enabled the mobile hotspot, updated `.env`, and connected the Mac
to it. The GameShell saw the exact private target at **2412 MHz**, advertising
WPA2-PSK/SAE, with a cached signal of -76 dBm
(`20260929T064252.684725Z/`). It associated using WPA2-PSK/CCMP and obtained an
IPv4 address. This resolves network visibility for the hotspot; it does not
establish the previous router's 2.4 GHz configuration.

The first transaction (`20260929T064226.253023Z/`) could not verify the host
route because `.env` selected direct Intel-to-GameShell Wi-Fi access
(`GAMESHELL_WIFI_VIA_MAC=0`). The Mac could reach the board's SSH port on its
local Wi-Fi subnet. The transaction rolled back after eleven verification
retries, with no commit and successful cleanup. A subsequent explicit stop
found the already-collected unit absent; it was not needed for rollback.

Restored `GAMESHELL_WIFI_VIA_MAC=1`, preserving the other private settings, and
reran the existing `task device:wifi-config`. Capture
**`20260929T064520.934822Z/`** reports `passed=true`, `committed=true` and
`cleanup_verified=true`. The task checked the pinned SSH identity, same boot
and actual Wi-Fi endpoint through the Mac, updated only `GAMESHELL_IP`, and
removed the private transaction directory. Private build provisioning also
contains the owner's hotspot credentials. No image was rebuilt or device
rebooted.

A separate Wi-Fi SSH read confirmed boot
`73a1cbd0-0b12-4137-bdb1-7965671bab5d`. `task device:status ROUTE=wifi` then
verified active services, no failed units, valid battery monitoring and a
configured USB link. The original firmware remains installed. Restarting the
supplicant returned `disable_scan_offload` to its configured zero, verified
over USB; the earlier temporary host-scanning workaround is no longer active.

NEO-29's successful commit and failure rollback paths are now hardware-tested.
The existing host regressions remain unchanged. NEO-26/NEO-30 firmware
qualification and NEO-22 battery-only comparisons remain separate work; this
connection does not establish that offline scanning is repaired.
