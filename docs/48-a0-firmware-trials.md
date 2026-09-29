# BCM43430 A0 firmware trials

Date: **29 September 2026 NZDT**. Work: **NEO-30**, with NEO-26 scan isolation
and NEO-29 network transition. Board: owner's CPI v3.1, diagnostic.5,
Linux `6.18.54-gameshellneo5`; boot `73a1cbd0-0b12-4137-bdb1-7965671bab5d`.

## Finding

The upstream May 2017 A0 candidate loaded and completed a 120-second
disconnected scan observation with **zero firmware crashes and zero SDIO
removals**. The original October 2016 firmware produced eight of each in both
120-second baseline windows. The candidate is promising, but these short
observations do not establish long-term reliability, energy savings or support
for an unseen access point. No persistent firmware adoption or image update
has occurred.

| Workload | Firmware | Scan offload | Crashes / SDIO removals |
| --- | --- | --- | --- |
| Original baseline, 120 s | October 2016 vendor | Enabled | 8 / 8 |
| Host-scanning isolation, 120 s | October 2016 vendor | Disabled | 0 / 0 |
| Original repeat, 120 s | October 2016 vendor | Enabled | 8 / 8 |
| Candidate observation, 120.20 s | May 2017 upstream | Enabled | 0 / 0 |

Baseline details and limitations are in [report 46](46-wifi-transition-and-scan-recovery.md).
Candidate source, license, exact silicon mapping and alternative-distribution
research are in [report 47](47-wifi-firmware-options.md). Preserve GameShell
board NVRAM; Raspberry Pi A1/B0 files are not substitutes for this A0 binary.

## Reproduction and recovery

```sh
# Keep USB connected; use the pinned original diagnostic firmware as baseline.
task device:wifi-firmware-test SECONDS=120
```

The [manifest](../build/wifi-firmware-candidate.json) pins source commit,
download/license hashes, size, binary metadata and independently observed
runtime identity. The host downloads and verifies the candidate and license,
then stages a private helper. The device verifies CPI v3.1, original firmware,
exact board NVRAM, normal scan-offload policy and USB configuration. It stops
the supplicant, unloads/reloads the radio modules around an atomic firmware
replacement, then requires a fresh matching kernel identification message.
Counter differences separate reload events from the observation interval.

The helper restores original bytes, mode and a freshly loaded original identity
in `finally`; the bounded systemd service independently runs restoration in
`ExecStopPost`. Recovery state remains under `/run/gameshellneo-firmware-trial`
until restoration succeeds. Keep failed helpers for recovery until verified.
This requires a running kernel/systemd; it is not power-loss recovery. No PMIC,
charging, governor, USB-policy or board NVRAM writes occur.

## Failed identity check and corrected trial

Capture `.local/diagnostics/20260929T061752.314323Z/` failed its identity gate.
The candidate had actually loaded: its runtime `ver` response is:

```text
Firmware: BCM43430/0 wl0: May 29 2017 00:03:43 version 7.13.53.9 (r664949) FWID 01-130000
```

Its binary footer instead reports FWID `01-93c3a6da`, with a build timestamp
00:05:32. The first gate incorrectly treated that footer as the runtime reply.
Rollback succeeded; independent firmware/NVRAM hash readback matched the
originals. The corrected manifest pins both representations separately and a
regression rejects stale loads and the wrong chip revision. The failure is
preserved, not counted as a completed scan comparison.

Corrected capture `.local/diagnostics/20260929T062416.878052Z/` loaded SHA256
`ad85074b7919517d7e1a7e463e0176d46e7b312216bd7aa372e4aee2bfe8e07a`, observed
120.195 seconds, recorded no reload or observation crashes/removals, then
verified restoration of the original firmware and runtime identity. Its states
were disconnected/scanning; no association is implied.

## Separate network-transition workload

```sh
# Terminal one; wait for candidate_loaded before the second command.
task device:wifi-firmware-test SECONDS=300
# Terminal two; Mac already on the intended network, credentials in .env.
task device:wifi-config
```

The network transaction has its own verification and rollback. A successful
network commit persists after the firmware restores, so recheck Wi-Fi with the
original firmware afterward. This deliberately changes the profile during a
separate firmware trial and must not be presented as an unchanged-profile scan
comparison. Do not overlap other radio tests or reboot.

Firmware capture `.local/diagnostics/20260929T062647.704056Z/` accompanies network
capture `.local/diagnostics/20260929T062716.330543Z/`. The new network did not
associate; its transaction restored the previous configuration, did not update
`.env`'s device address, and verified cleanup. Association remains unqualified.
The firmware observation completed in 300.215 seconds with zero crashes and
zero SDIO removals, including zero during reload. Original firmware restoration
passed again. These results cover profile changes and scanning, not a connected
network or long-term reliability.

`task device:wifi-visibility` compares cached results with the private target
SSID, exposing only counts and matching frequency/signal/security. Capture
`20260929T062939.275868Z/` found seven entries and no target match. This does not
prove the AP was off, hidden or beyond range; cached absence has multiple causes.

At the owner's request, `task mac:wifi` inspected the Mac remotely. Capture
`20260929T063032.439635Z/` reports channel **48, 5 GHz, 80 MHz**, WPA2-Personal,
802.11ac and -40 dBm signal. macOS redacted SSIDs, so the match remains unknown;
the Mac's current band does not establish whether the AP also offers the same
SSID on 2.4 GHz. The GameShell requires 2.4 GHz. Router configuration/visibility
must be resolved before connection and reconnection qualification.

The owner subsequently re-enabled a visible 2.4 GHz mobile hotspot. The
original firmware joined it and the guarded network commit passed; see
[report 46](46-wifi-transition-and-scan-recovery.md#hotspot-transition-qualified).
The upstream candidate has not yet been tested for association to that hotspot.

## Remaining work

After both completed firmware trials, the original binary was left installed.
While network visibility is resolved, a temporary host-scanning workaround was
selected and read back as one:

```sh
task device:exec ROUTE=usb -- sudo wpa_cli -i wlan0 set disable_scan_offload 1
task device:exec ROUTE=usb -- sudo wpa_cli -i wlan0 reassociate
task device:exec ROUTE=usb -- sudo wpa_cli -i wlan0 get disable_scan_offload
```

No persistent configuration was changed by these commands. A supplicant restart
returns the configured zero; to restore it explicitly, set the same flag to zero
and reassociate. Firmware comparison preflight requires zero, so restore that
setting before another unchanged-profile trial. This is the already tested
runtime workaround, not permanent candidate adoption.

The subsequent successful hotspot transition restarted the supplicant and
readback confirmed zero. The temporary workaround is therefore no longer active.

`task check` passed 13 runtime and 125 tool tests (one optional user-systemd
test skipped), current-limit and Mac mount-guard C checks, Bash syntax and
ShellCheck. Firmware regressions cover fresh identity, chip revision, rollback
bytes/mode/NVRAM, retryable failed restoration and stale log rejection. Scan
recovery stops any running comparison before restoring the saved flag. Visibility
tests preserve unknown/redacted identity and keep network names out of summaries.

Qualify association and repeated reconnection on a visible compatible network,
then cold-start loading before adopting this binary in a diagnostic image.
Keep `qualified=false` until the acceptance scope is explicit. Measure any
power benefit separately; eliminating recovery work suggests an opportunity
but is not a battery result. The original firmware's recurring reset path also
logged an MMC runtime-PM usage underflow; that separate driver audit is recorded
in [FOLLOW-UP.md](../FOLLOW-UP.md).
