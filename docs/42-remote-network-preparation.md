# Remote network access and diagnostic.5 provisioning refresh

Date: **29 September 2026 NZDT**. Host transport: **NEO-23**;
remote Wi-Fi/image refresh: **NEO-24**. Hardware qualification remains **NEO-22**.

## Purpose and access paths

The owner is away from the network used in previous tests. The Intel host
reaches the Mac over its tailnet address, while the Mac reaches the GameShell
locally. Credentials and addresses remain in `.env`.

| Task route | Connection path | Device SSH identity |
| --- | --- | --- |
| Mac tasks | Intel → tailnet → Mac | Previously verified Mac key |
| `ROUTE=usb` | Intel → tailnet → Mac → GameShell USB address | Provisioned GameShell key |
| `ROUTE=wifi`, `GAMESHELL_WIFI_VIA_MAC=1` | Intel → tailnet → Mac → GameShell local Wi-Fi address | Same provisioned GameShell key |
| `ROUTE=wifi`, flag absent/empty/`0` | Intel → GameShell Wi-Fi address directly | Same provisioned GameShell key |

`M2_MACBOOK_AIR_TAILNET` selects the Mac transport. The existing
`M2_MACBOOK_AIR_IP` remains its SSH identity alias, so moving between addresses
does not require trusting an unknown key. A tailnet-only configuration instead
requires a verified host entry for that address. Failed tailnet connections
do not silently retry LAN. Existing Mac status and USB device status tasks
succeeded using this path; NEO-23 was committed as `1f39b68`.

`GAMESHELL_WIFI_VIA_MAC=1` adds the independent Wi-Fi path needed to observe
USB disconnections remotely. The existing USB/power observers use the same
connection helper and inherit this setting. The board's current Wi-Fi address
belongs in `GAMESHELL_IP`; the separate USB address remains unchanged.
Neither device route falls back to the other, and host-key failures propagate.
Whether the new access point permits communication between Mac and GameShell
still requires a live check after boot.

## Repeatable preparation

1. Owner updates `GAMESHELL_WIFI_SSID` and `GAMESHELL_WIFI_PSK` in `.env`.
2. Set `GAMESHELL_WIFI_VIA_MAC=1` for remote Wi-Fi access.
3. Run `task provision`, `task build:image`, then `task mac:stage`.
4. Freshly identify the owner-confirmed DEV card and use the standard
   `mac:inspect`, `mac:preflight` and `mac:flash` tasks.
5. After boot, obtain the board's new Wi-Fi address over USB, update
   `GAMESHELL_IP`, and verify both routes before cable tests.

The new network changes private image provisioning, not the completed
`6.18.54-gameshellneo5` kernel or its USB policy. The image remains
`0.1.0-diagnostic.5` and has a new content hash. Device host keys and machine
identity are preserved by `task provision`. The previous provisioning,
artifact metadata and transfer manifest are retained privately under
`.local/network-refresh/20260929/`; existing raw images remain available.
Editor swap/backup files for `.env` are ignored as well as the file itself.

## Verification and status

Host checks passed **13 runtime tests and 77 tool tests**, with one optional
user-systemd skip, plus the current-limit regression and shell lint. The five
new device-route checks cover direct Wi-Fi, Wi-Fi through the Mac, separate USB
addressing, pinned device identity, failed-connection cleanup and invalid
configuration. They supplement NEO-23's six Mac transport/identity checks.
Private host evidence: `.local/build/neo24-check.log`.

Private provisioning was refreshed after the owner's confirmation. Image
assembly and offline verification passed, reusing the validated base cache and
the completed diagnostic.5 kernel. Checks include partition/bootloader bytes,
FAT16/ext4 integrity, kernel/DTB/modules/radio hashes, both policy scripts,
updated Wi-Fi provisioning, stable device identity and service policy.

- Image: `GameShellNeo-0.1.0-diagnostic.5-cpi31-263975ac1754.img`.
- Size: **4,294,967,296 bytes**.
- SHA-256: `263975ac17543acb59de4d33742976804016b18fc4f5da69d8d0ad8de1110bc8`.
- Private evidence: `.local/build/image-verify.log` and
  `.local/artifacts/verification.json`.

Mac staging passed compressed and decompressed checksum verification over the
tailnet. The archive is **264,525,029 bytes**, SHA-256
`d0ac572ecab0f4d12fb2c7d4ef53c41fccfd6391cd0de801a9194c88f1280405`,
and is ready in `~/.local/share/GameShellNeo/` on the Mac. Local evidence is
`.local/build/neo24-mac-stage.log` and `.local/flash/transfer.json`.

The owner moved the Samsung DEV card to the reader; fresh inspection found
external physical `disk16`, **64,013,467,648 bytes**, 512-byte sectors and boot
volume UUID `9F867CB0-4E3E-3913-8780-F2DC008AE06D`. The staged-image/card
preflight passed; evidence is `.local/build/neo22-mac-preflight.log`.
NEO-24's preparation is complete. Flashing, live Wi-Fi access and USB-policy
hardware results are tracked separately under NEO-22.

## Diagnostic.4 baseline finding

Before any flash, USB status through the Mac showed
`6.18.54-gameshellneo4`, six healthy monitored services, no failed units or
kernel taint, and a 96% battery at 4.2141 V. USB was configured at high speed.
Private status: `.local/diagnostics/20260929T041254.802651Z/`.

Wi-Fi was disconnected and repeatedly lost/recreated its interface. The
kernel logged `brcmf_fw_crashed`, SDIO removal/reprobe and firmware reloads
roughly every 16 seconds; wpa_supplicant reported failed scheduled scans and
transient `INTERFACE_DISABLED`. This occurred while the original network was
unavailable, but that does not prove the trigger. It predates diagnostic.5's
USB change and is recorded in `FOLLOW-UP.md` for connected/disconnected
comparison with the correct AP. No firmware or driver change was made during
this capture.

Full diagnostic archive: `.local/diagnostics/20260929T041657.093296Z/`.
Additional private logs: `.local/build/neo22-wifi-journal.txt` and
`.local/build/neo22-kernel-wifi.txt`. These failures remain part of the baseline
even if the board connects successfully on the new image.
