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
after the owner connected the Mac to the same hotspot, Wi-Fi SSH through the
tailnet/Mac path passed. USB policy/status verification also passed over the
separate USB path. The running device remained on the same boot with healthy
services and both interfaces up. No Wi-Fi software change was needed to
restore these access paths.

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
| `20260929T045545.460820Z` | Successful Wi-Fi SSH/status through the Mac after network switch |
| `20260929T045545.310870Z` | Separate successful USB-policy check after network switch |

The initial supplicant journal is also retained privately as
`.local/build/neo22-diagnostic5-wifi-journal.txt`. Credentials, network names,
private archives and image provisioning are not committed.

## USB checks

### Experimental USB reconnection batch

`task device:usb-reconnects CYCLES=4` passed all four owner-operated cycles
with the experimental policy active. For each cycle the device recorder saw
`not attached` followed by `configured`, and a fresh USB SSH session through
the Mac verified the same boot. The initial attachment was excluded. The
recorder stopped and its temporary files were removed after the fourth pass.

Private evidence: `.local/diagnostics/20260929T045611.055298Z/`, including
`summary.json`, `usb-reconnects.jsonl` and `device-states.jsonl`. The result is
functional reconnection coverage; it does not measure the physical cable-edge
latency or poll-call rate. More detailed detection captures remain separate.

### Disconnected recorder check

With USB physically unplugged, Wi-Fi status verified the same boot, valid
97% battery monitoring, `Discharging`, `not attached` USB state and healthy
services. Capture: `.local/diagnostics/20260929T050007.931221Z/`.

`task device:usb-detect CYCLES=0 SECONDS=8` then passed with 399 samples over
8.002 seconds and a maximum observed sample gap of 28.79 ms. It recorded no
cable cycles and cleaned up successfully. Capture:
`.local/diagnostics/20260929T050013.957970Z/`. The recorder consumed 3.674 CPU
seconds during that window; this instrumented check is unsuitable for an
idle-power comparison and does not qualify physical detection timing.

### Experimental detailed detection batch

`task device:usb-detect CYCLES=4` passed all four attachment/removal cycles
with USB SSH verified on every attachment, continuous Wi-Fi control and the
same boot throughout. Both AC and USB supplies reported `present=1, online=1`
on attachment and settled to `present=0, online=0` on removal. Each cycle
recorded exactly one increment of each `ACIN_PLUGIN`, `ACIN_REMOVAL`,
`VBUS_PLUGIN` and `VBUS_REMOVAL` counter. These are named IRQ observations,
not USB poll-call counts.

The final cable remained connected longer than requested; the owner noticed
and unplugged it while recording continued. The four observed windows from
configured state to settled removal were approximately **23.10, 23.46, 21.93
and 84.64 seconds**, so this is not four equal-duration cycles. Fresh USB SSH
checks took 2.16–4.83 seconds including the tailnet/Mac forwarding path; those
durations are not hardware detection latency.

The capture contains 11,680 samples over 234.649 seconds, with maximum
observed sample gap 46.15 ms and 109.384 observer CPU seconds. Clean final
trace validation and recorder cleanup passed. Private evidence:
`.local/diagnostics/20260929T050036.944052Z/`, including `summary.json`,
`usb-detection.jsonl` and `device-trace.jsonl`. Initial read-only PMIC control
values were `30h=60h` and `8fh=01h`, with their documented regmap-cache limits.
No charger, current-limit, governor or regulator settings were changed.

The post-batch check found no firmware crash/removal, kernel warning/BUG/Oops
messages in its preceding ten-minute window, no failed units and no kernel
taint. USB remained `not attached`. A full post-batch archive is retained at
`.local/diagnostics/20260929T050555.401588Z/`.

## Experimental cold start without USB

The owner briefly pressed power to shut down, waited ten seconds after the
screen went dark and powered on with USB remaining unplugged. The normal
login screen returned. Wi-Fi SSH verified a new boot
`8a3c7582-92c2-4d41-8c25-a1dd5532ac6a`; the journal identifies the preceding
boot and records an orderly poweroff, filesystem syncing and journal stop.

The driver again accepted experimental polling. USB remained `not attached`,
the valid battery monitor reported discharging, and all six monitored services
were active with zero restarts, no failed units and no taint. The integration
checks passed over Wi-Fi. No firmware crash/reprobe appeared in the initial
new-boot kernel check, and the radio remained `phy0`. Local readiness was
14.6576 seconds; `systemd-analyze` reported 14.855 seconds, with the same
physical power-on/bootloader timing limits noted above.

Repeat with USB unplugged and the configured network available: orderly
power-button shutdown, wait ten seconds after darkness, power on, then run
`device:status`, `device:usb-policy`, `device:check` and `device:logs` with
`ROUTE=wifi`. Preserve the new boot ID and preceding shutdown journal; a
software reboot alone is not evidence of this physical cold-start procedure.

Private evidence under `.local/diagnostics/`:

- `20260929T050734.299894Z`: disconnected new-boot status.
- `20260929T050734.146998Z`: accepted experimental policy.
- `20260929T050808.337097Z`: passing integration checks.
- `20260929T050809.437124Z`: full new-boot diagnostic archive.

For the comparison, `task device:usb-policy ROUTE=wifi MODE=stock` verified
and selected the stock script for the next boot. It reported the current
experimental policy unchanged and `reboot_performed: false`. Selection
evidence: `.local/diagnostics/20260929T050855.071980Z/`. The owner was then
asked to repeat the battery-only shutdown/cold-start procedure.

## Stock cold start without USB

The owner repeated the same unplugged cold-start procedure and confirmed the
login screen. Wi-Fi verified new boot
`aa18fd5a-aea4-4656-8388-c9329088523c`, an orderly preceding shutdown and
`not attached` USB state. The actual driver message was
`GameShellNeo USB polling: stock: opt-in disabled`, with requested parameter
`N` and stock also selected for the next boot.

All six monitored services were active without restarts; the battery monitor
was valid/discharging, and no failed units, taint or initial radio crash/removal
messages appeared. Local readiness was 14.3864 seconds; `systemd-analyze`
reported 14.802 seconds. These individual boot observations do not establish
a performance difference between the policies.

Private captures: `.local/diagnostics/20260929T051035.251821Z/` (status) and
`20260929T051035.254316Z/` (verified stock policy).

## Stock detailed detection and comparison

The same `task device:usb-detect CYCLES=4` task passed all four stock-policy
cycles on boot `aa18fd5a-aea4-4656-8388-c9329088523c`. Fresh USB SSH was verified
for every attachment; Wi-Fi observation stayed available. Both supplies
reported present/online on attachment and absent/offline after removal, with
exactly one increment of each of the four named insertion/removal IRQs per
cycle, matching the experimental run's functional results.

| Observation | Experimental | Stock |
| --- | --- | --- |
| Detailed cycles passed | 4/4 | 4/4 |
| ACIN/VBUS insert/remove IRQs | One of each per cycle | One of each per cycle |
| Final supply state | Both absent/offline | Both absent/offline |
| Recorder samples | 11,680 | 8,156 |
| Recorder duration | 234.649 s | 163.872 s |
| Largest observed sampler gap | 46.15 ms | 42.36 ms |
| Observer CPU time | 109.384 s | 75.888 s |

Stock configured-to-settled-removal windows were approximately 23.42, 24.27,
27.08 and 24.54 seconds. Host USB SSH checks took 4.66–11.46 seconds through
the tailnet/Mac path. The differing manual durations, variable remote-access
time and high recorder overhead prevent treating these data as an energy or
physical detection-speed comparison.

Final trace validation and cleanup passed. Private stock evidence:
`.local/diagnostics/20260929T051104.764393Z/`, with the same summary/trace/log
files as the experimental run. USB was left unplugged after the final cycle.

## Remaining acceptance

Independent Wi-Fi SSH and the initial experimental attached/detached starts
plus stock detached startup and both detailed cable batches are now verified.
Complete stock attached startup,
rapid reconnection and separate matched
battery-only comparisons. Detailed event recording must not run during power
measurements. Direct poll-call instrumentation and error/IRQ coverage remain
requirements before broad enablement or measured-work claims. Keep the
diagnostic.4 recovery image and current charger/governor settings.
