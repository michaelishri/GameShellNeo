# Diagnostic.6 hardware validation

Date: **29 September 2026 NZDT**. Board: owner's **CPI v3.1**; Samsung
64 GB DEV card. Work continues under **NEO-22** (USB polling qualification)
and **NEO-31** (integrated A0 firmware qualification).

Status: **flash/readback, first boot, integration, battery-policy simulation
and connected/unplugged stock/experimental USB diagnostics passed**. Direct
unplugged callback rate fell **76.9%** in the matched one-minute windows.
Wi-Fi recovered after software reboots with USB attached and absent. Physical
cable recovery and repeated cold-start/AP-loss qualification remain pending.
This report follows [diagnostic.6 preparation](51-diagnostic6-preparation.md).
Sleep remains disabled; charging and governor settings are unchanged.

## Image and installation

The installed card image is
`GameShellNeo-0.1.0-diagnostic.6-cpi31-1e1f931ccf1a.img`, with expected kernel
`6.18.54-gameshellneo6`. Raw SHA-256:
`1e1f931ccf1aa907353655dd5d186d6c24ee04c89394553fcd095ded16c475a7`.

The owner confirmed regular Wi-Fi before the 264 MB transfer. The saved
`task mac:stage` workflow verified both the compressed and decompressed
image hashes on the Mac. Before shutdown, diagnostic.5 had working USB SSH,
experimental polling selected, no failed services or kernel taint, and valid
battery monitoring at 92% while charging. Baseline captures:

- Status: `.local/diagnostics/20260929T095423.912586Z/`.
- Diagnostic archive: `.local/diagnostics/20260929T095511.357584Z/`.
- Policy: `.local/diagnostics/20260929T095511.410106Z/`.

The owner then moved the DEV card to the reader. An intervening agent-session
network restriction blocked SSH before any card write; restarting the session
restored access. No Mac SSH, image or card change was needed for that issue.

Fresh inspection identified the owner's 64,013,467,648-byte physical external
card with its recorded boot volume identity. The following saved sequence ran:

```sh
task mac:status
task mac:inspect DISK=disk16
task mac:preflight
task mac:flash DISK=disk16
```

`disk16` is this session's observed identifier, not a reusable target constant.
The temporary mount guard passed its actual mount-veto check. All
4,294,967,296 image bytes were written and read back with the exact SHA-256
above, and the card was safely ejected. Private evidence:
`.local/diagnostics/20260929T100439.561213Z/flash-result.json` and `flash.log`.
The original-card backup and diagnostic.4/5 recovery images remain available.

## First boot and integration

The owner confirmed the normal login screen. USB SSH verified diagnostic.6 /
Linux `6.18.54-gameshellneo6`, four CPUs, approximately 1 GiB RAM, no failed
services or taint, and all six monitored services active without restarts.
The USB link was configured at high speed. Battery monitoring was valid,
reporting 100% and Charging; that does not establish gauge accuracy.

Local readiness was **16.950 seconds**; `systemd-analyze` reported
**21.792 seconds**. These exclude a measured power-on/bootloader interval
and do not meet or qualify the aspirational five-second startup target.
All six integration groups passed, including journal ACL, isolated BPF
enforcement, image identity and configured/global NZ regulatory checks.
All nine simulated battery-policy tests passed against the hash-checked
installed guard, without changing charging settings or powering off.

| Capture under `.local/diagnostics/` | Evidence |
| --- | --- |
| `20260929T100823.005082Z` | First-boot status |
| `20260929T100831.631116Z` | Passing integration checks |
| `20260929T100845.338113Z` | Nine installed battery-guard tests |
| `20260929T100845.334153Z` | Initial diagnostic archive and loaded firmware identity |

The intended **BCM43430/0 7.13.53.9 (r664949), May 29 2017,
FWID 01-130000** loaded on this cold start. Wi-Fi was not associated at
the initial capture; successful firmware loading alone does not establish
cold-start network recovery.

## Boot-policy status correction (NEO-32)

The first `task device:usb-policy ROUTE=usb` capture,
`20260929T100822.954338Z`, accepted the running experimental policy and
verified boot variants but returned `boot_source_matches=false`. The host
helper's final comparison regenerated a source without the diagnostic opt-in.
It now compares the active source against the already hash/source/CRC-verified
selected variant, preserving the detection of stale or altered `boot.cmd`.

The regression invokes the actual CLI status path for stock/experimental
scripts with diagnostics absent, false and true. Both diagnostic-enabled cases
failed before the fix. All **11 boot-policy tests** now pass, including rejection
of an active source that differs from its verified executable. Live status
passed in `20260929T101043.105209Z`. This is a host-helper correction; the
image bytes, on-card boot scripts and kernel were not changed by the fix.

## Connected experimental diagnostics

On boot `1f0bceaa-07bc-4d9d-bcc3-878943d692a7`, the driver accepted the
experimental policy and exposed the diagnostic interface initially disabled.
The following saved tasks passed with USB connected throughout:

```sh
task device:usb-counts ROUTE=usb SECONDS=60
task device:usb-errors ROUTE=usb ERRORS=1
task device:usb-errors ROUTE=usb ERRORS=4
```

| Capture under `.local/diagnostics/` | Result |
| --- | --- |
| `20260929T100909.822073Z` | Zero natural callbacks in 60.005 seconds; zero read errors |
| `20260929T101042.412739Z` | One injected error, then one successful real read |
| `20260929T101117.615421Z` | Four injected errors, then one successful real read |

Each injected failure retained online/present status `0x30` and requested the
50 ms retry; the subsequent real read succeeded and stopped connected polling.
No real read error occurred. Both fault budgets were exhausted, counter
identities remained coherent and all tasks restored counting off with zero
remaining error budget. The natural counter observer used 0.0144 CPU seconds;
that excludes kernel instrumentation and SSH/system overhead.

Zero connected polls is expected, not an unplugged-polling optimization result.
Synthetic failures exercise a narrow driver call site and do not reproduce
electrical faults or qualify physical cable IRQ recovery.

## Wi-Fi configuration and stock comparison

The owner confirmed that `.env` holds an available 2.4 GHz network.
`task device:wifi-config` applied that private configuration over USB and
verified an independent Wi-Fi SSH connection through the Mac before committing
the transaction. Evidence: `20260929T101249.709404Z`. Credentials and the
updated Wi-Fi address remain private; this runtime provisioning change does not
rewrite the preserved image artifact.

`task device:boot-cycles CYCLES=0` then captured the first boot and verified
both access paths (`20260929T101328.667026Z`). This command captures the current
boot only; it does not constitute a repeated cold-start batch.

The saved policy selector chose stock for the next boot, followed by an
explicit remote `systemctl reboot`. On boot
`9068c060-822f-456d-a0fe-d5afea461ed7`, USB and independent Wi-Fi SSH recovered,
the loaded firmware identity remained correct and the stock policy verified.
Status, policy and current-boot captures are `20260929T101435.876145Z`,
`20260929T101435.876022Z` and `20260929T101434.542870Z` respectively. Readiness
was 14.581 seconds; systemd reported 14.994 seconds. A software reboot is not
a physical cold-start test.

The AP announces AU, matching the owner's previously accepted setting.
Configured country remains NZ. The saved integration check passed with
`ACTIVE_COUNTRY=AU` in `20260929T101658.723313Z`; no router or regulatory
configuration was changed for the test.

The same connected count/error commands then passed under stock policy:

| Capture under `.local/diagnostics/` | Result |
| --- | --- |
| `20260929T101455.073729Z` | Zero natural callbacks in 60.005 seconds; observer CPU 0.0146 seconds |
| `20260929T101619.748163Z` | One requested/injected failure; retained `0x30`, no automatic retry |
| `20260929T101649.305609Z` | Four requested, one consumed; unused budget expired, no automatic retry |

Stock preserves its historical connected-state behavior: after an injected
failure it stops polling because it retains the online state. The remaining
three errors in the four-error request expired rather than being deferred to
later cable activity. Experimental retries provide the additional recovery
observed above. All stock tests restored counting off and budget zero, with
no real read errors. Physical removal/reconnection after the fault window
still needs separate verification.

## Direct unplugged counts and recovery

After the owner unplugged USB, Wi-Fi status verified Discharging and an
unattached controller (`20260929T101802.994572Z`). The stock count then ran,
followed by a separate four-error test. The verified selector chose experimental
for the next boot (`20260929T102010.401182Z`), and a remote software reboot
completed on battery with USB still absent. Wi-Fi recovered on boot
`eea8f9b9-a2a3-473d-bd95-5333d6b81dbb`; status and active policy passed in
`20260929T102058.430567Z` and `20260929T102058.429123Z`. The matching experimental
count ran before its separate four-error test.

For each mode, the exact tasks were:

```sh
task device:usb-counts ROUTE=wifi SECONDS=60
task device:usb-errors ROUTE=wifi ERRORS=4
```

| Policy | Count-window capture | Duration | Successful callbacks | Calls/second | Observer CPU seconds |
| --- | --- | --- | --- | --- | --- |
| Stock | `20260929T101816.831934Z` | 60.005094 s | 999 | 16.64859 | 0.01604 |
| Experimental | `20260929T102112.450339Z` | 60.005238 s | 231 | 3.84966 | 0.01415 |

The normalized rate reduction is **76.9%**. Both natural windows recorded
zero real/injected errors and zero synthetic requests, with coherent counters
and retained status `0x00`. No other diagnostic observer ran in either window.
The count uses the two measurement snapshots, excluding any callbacks during
subsequent validation/cleanup. Nominal 50/250 ms delays are requested workqueue
delays; they are not guarantees of exactly 20/4 executions per second.

This directly establishes fewer polling callbacks on this board/image, unlike
the earlier aggregate RSB-interrupt comparison. It does **not** quantify total
CPU wakeups, incremental kernel-counter cost or battery-energy savings. The
reported CPU time covers only the userspace measurement process, excluding
SSH, child processes and kernel instrumentation. These are two initial windows,
not a long-duration energy or scheduling study.

The unplugged four-error checks passed in `20260929T101956.362126Z` (stock)
and `20260929T102230.164983Z` (experimental). Both consumed exactly four
injected failures, retained `0x00`, requested 50 ms retries and recovered with
a successful real read. Stock then requested 50 ms normal polling;
experimental returned to 250 ms. Both restored diagnostics disabled and
budget zero, with no real read errors. Physical cable tests follow separately.

## Remaining qualification

Complete physical cable recovery in both modes after the error windows. Keep
high-rate cable recorders separate from natural count/energy windows. Counting
defaults off and each saved diagnostic task restores its owned controls.

Firmware qualification requires the expected loaded A0 identity, association,
independent Wi-Fi SSH, repeated cold starts and AP-absent/reconnection tests.
Prior reversible firmware trials do not establish these results for this image.
Direct callback reductions do not establish an energy saving; observer cost,
live concurrency, long-term stability and sleep remain separate limits.
