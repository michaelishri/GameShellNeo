# Diagnostic.5 initial hardware validation

Date: **29 September 2026 NZDT**. Hardware: owner's **CPI v3.1** and
Samsung DEV card. **NEO-22 remains in progress**; Wi-Fi crash investigation is
**NEO-26**. These are initial boot/integration results, not completed USB or
power qualification.

## Installed candidate

The [remote-network refresh](42-remote-network-preparation.md) produced
`GameShellNeo-0.1.0-diagnostic.5-cpi31-263975ac1754.img`, SHA-256
`263975ac17543acb59de4d33742976804016b18fc4f5da69d8d0ad8de1110bc8`.
[Report 43](43-macos-card-mount-guard.md) preserves the initial failed flash
and subsequent guarded write, exact 4 GiB readback and successful ejection.
The owner then confirmed the normal login screen.

USB SSH through the Mac/tailnet verified:

- Linux **6.18.54-gameshellneo5**, image **0.1.0-diagnostic.5**.
- Four CPUs, approximately 1 GiB RAM, no kernel taint or failed systemd units.
- Six monitored services active with zero restarts.
- USB configured at high speed; power-button and USB keypad input devices
  enumerate. Enumeration does not repeat the physical button tests.
- Valid battery monitoring, 96% charge and external charging at first capture.
  These are software readings, not a new charging/capacity qualification.
- Local userspace readiness at **16.7646 seconds** from kernel monotonic time;
  `systemd-analyze` reported **21.902 seconds**. Neither includes a measured
  physical power-on/bootloader interval or establishes the five-second target.

The actual driver's message accepted **experimental absent=250 ms, fast=50 ms**.
The read-only parameter was `Y`; verified next-boot scripts selected
`experimental`. This establishes activation, not actual on-board poll counts,
detection latency or energy savings.

The reusable integration check passed image/service identity, regdb policy,
journal ACLs, temporary BPF control/deny/allow-exception probes and the requested
NZ global regulatory domain. The radio's private domain label remains `99`;
firmware-country mapping is still unqualified. All nine simulated battery-guard
tests passed against the installed, hash-checked guard. No real shutdown or
charger change is part of that simulation.

## Hotspot and access-path findings

Initially `wlan0` was down and the radio repeatedly crashed/reprobed, with
failed scheduled scans. The deployed Wi-Fi configuration matched the current
`.env` byte for byte. The owner clarified that the hotspot had timed out and
turned off, then re-enabled it. The board joined with **WPA2-PSK/CCMP at
2462 MHz** and received DHCP. A reassociation request was issued while retrying;
no credentials, driver, firmware or scan policy were changed.

The last crash in the initial capture was at **04:51:14 UTC**. A later
two-minute kernel-journal window contained no crash/removal messages while
the interface reported `COMPLETED`. This is limited evidence of recovery
with an available network; unavailable-network stability remains open. The
same crash/reprobe pattern existed on diagnostic.4 before this flash, so it
cannot be attributed solely to the new USB polling policy.

`disable_scan_offload` read back as `0` and was left unchanged. Upstream
documents that setting as controlling automatic scheduled-scan offloading.
Its existence offers a future isolation experiment; no such experiment was
performed in this session and scheduled scanning is not yet proven to be the
crash trigger. [wpa_supplicant configuration reference](https://w1.fi/wpa_supplicant/devel/structwpa__config.html).

The board's current WLAN address was obtained over USB and saved only to
`GAMESHELL_IP` in `.env`. Wi-Fi SSH through the Mac initially timed out because
the Mac was on a different subnet and routed that address through its ordinary
default gateway. The Mac's ping also timed out. These failures are retained;
the owner was asked to connect the Mac to the same hotspot. Independent Wi-Fi
access must be verified before detailed cable tests or unplugged startup.

## Repeating the completed checks

Keep USB attached and the configured hotspot available:

```sh
task device:status ROUTE=usb
task device:usb-policy ROUTE=usb
task device:check ROUTE=usb
task device:battery-check ROUTE=usb
task device:logs ROUTE=usb
task device:exec ROUTE=usb -- cat /proc/bus/input/devices
task device:exec ROUTE=usb -- ip -brief address show wlan0
task device:exec ROUTE=usb -- sudo -n /usr/sbin/wpa_cli -i wlan0 get disable_scan_offload
```

After ensuring the Mac and board share a reachable network, set the observed
WLAN address in `.env`, retain `GAMESHELL_WIFI_VIA_MAC=1`, and run
`task device:status ROUTE=wifi`. A working USB route must not be mistaken for
a successful independent Wi-Fi check.

Private evidence under `.local/diagnostics/`:

| Capture | Evidence |
| --- | --- |
| `20260929T044922.324775Z` | First diagnostic.5 USB status |
| `20260929T044932.096520Z` | Actual USB-policy activation and next-boot verification |
| `20260929T044944.495339Z` | Full diagnostic archive including initial radio failures |
| `20260929T045045.388893Z` | Passing integration JSON |
| `20260929T045313.583755Z` | Nine installed battery-guard regressions |

The initial supplicant journal is also retained privately as
`.local/build/neo22-diagnostic5-wifi-journal.txt`. Credentials, network names,
private archives and image provisioning are not committed.

## Remaining acceptance

Verify independent Wi-Fi SSH, then complete attached/detached startup,
stock/experimental cable batches, rapid reconnection and separate matched
battery-only comparisons. Detailed event recording must not run during power
measurements. Direct poll-call instrumentation and error/IRQ coverage remain
requirements before broad enablement or measured-work claims. Keep the
diagnostic.4 recovery image and current charger/governor settings.
