# Diagnostic.8 hardware validation

Date: **30 September 2026 NZDT**. Board: owner's **CPI v3.1**; Samsung
64 GB DEV card. Tracked as **NEO-42**, following
[diagnostic.8 preparation](59-diagnostic8-preparation.md).

Status: **flash, full readback, safe ejection, first boot, integration, both
SSH routes, one freezer and seven devices debug tests passed**, including two
bounded keypad traces. The owner confirmed normal display recovery after the
first driver test, four-cycle batch and first trace. No actual sleep has been
performed. NEO-42 is complete; the selected next comparison is NEO-43.

## Card installation

The owner confirmed that the shut-down GameShell's DEV card was in the Mac
reader. Fresh inspection found one external physical USB card: 64,013,467,648
bytes, 512-byte sectors, the expected reader and an existing `armbi_boot`
volume. The current disk identifier was `disk16`; it was freshly checked for
this write and must be rechecked for any later operation.

The saved workflow was:

```sh
task mac:status
task mac:inspect DISK=disk16
task mac:preflight
task mac:flash DISK=disk16
```

Preflight verified the compressed archive, complete decompressed image and
recorded card identity. The flash repeated those checks, unmounted the card
and verified the mount guard's actual rejection of a mount attempt. It wrote
all 4,294,967,296 image bytes, flushed them, read the entire written region
back with the expected SHA-256, and safely ejected the card.

| Item | Result |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.8-cpi31-3df063ed9bee.img` |
| Expected kernel | `6.18.54-gameshellneo8` |
| Source and readback SHA-256 | `3df063ed9bee29ca8ec90af655b683aae3c9c7269234ba587955178eafa66b03` |
| Written and verified bytes | 4,294,967,296 |
| Mount veto | Passed |
| Safe ejection | Passed |

Private evidence is
`.local/diagnostics/20260930T053154.983156Z/{flash-result.json,flash.log}`.
The host command logs are `.local/neo42-mac-{status,inspect,preflight,flash}.log`.
Diagnostic.7's image and matching recovery checkpoint remain available, along
with the earlier recovery artifacts and original-card backup. The physical
original card was not used.

## First boot and integration

The owner reinstalled the card, connected USB and confirmed the normal login
screen. Read-only PM and keypad inspection succeeded over USB. The board runs
`0.1.0-diagnostic.8` / `6.18.54-gameshellneo8`, boot
`b749db5f-89ef-4208-9fc6-fe44bd38c873`. All seven inspected services were active
with zero restarts; there were no failed units, kernel taint or recorded PM
failures. The expected radio firmware loaded once. Battery monitoring was
valid and reported 100% while charging; this does not establish gauge accuracy.

`task device:check ROUTE=usb` passed all six groups: image identity, services,
database/policy, journal ACLs, isolated BPF enforcement and country. Configured
and global country were NZ; the radio reported its existing `99` domain.

Both USB polling experiments read `N`. PM controls remain `pm_test=none`,
`pm_async=1`, only `s2idle` available, and a five-second debug delay. The keypad
is still low-speed `4242:e131` at `/dev/input/event1`, with persistence enabled,
runtime PM forbidden, no advertised remote wake and an enabled `keypad-vbus`
supply. Dynamic debug and regulator tracing are now available. This is initial
enumeration, not evidence of continuity across a PM cycle.

Private initial evidence:

- PM: `.local/diagnostics/20260930T053529.168833Z/inspection.json`.
- Keypad: `.local/diagnostics/20260930T053529.151283Z/keypad.json`.
- Integration: `.local/diagnostics/20260930T053556.245250Z/integration.json`.

Wi-Fi remained in `SCANNING`; the configured SSID was absent from seven cached
entries. The Mac was connected on 5 GHz and redacted its network name. These
observations do not establish whether the regular access point also offers
2.4 GHz. Since the large transfer is complete, the owner was asked to enable
the previously configured 2.4 GHz hotspot and connect the Mac to it. No Wi-Fi
configuration or firmware was changed. Visibility evidence is under
`.local/diagnostics/20260930T053605.217738Z/` and
`.local/diagnostics/20260930T053605.218702Z/`.

## Hotspot recovery and first PM tests

After the owner enabled the hotspot and connected the Mac, the GameShell
associated automatically with its existing configuration. No credential,
firmware or network policy change was needed. The follow-up inspection at
`.local/diagnostics/20260930T053738.843638Z/inspection.json` showed
`wpa_state=COMPLETED` and the same boot with one firmware load. Independent
Wi-Fi and USB SSH checks then passed before and after each PM test.

The saved tasks ran `STAGE=freezer CYCLES=1`, then `STAGE=devices CYCLES=1`
after the owner confirmed readiness to watch. Both passed their five-second
debug-wait, memory, PM counters, configuration restoration and network checks.

| Stage | Run ID | Stage duration | Keypad original handle | Unsupported ULPI warnings |
| --- | --- | --- | --- | --- |
| Freezer | `d09acf019d21409ca94cbe3dcb0fb37d` | 5.270153 s | Healthy | 0 |
| Devices | `d3a68ce3ddd04bebad57988e4a7633f6` | 9.442448 s | ENODEV / POLLERR / POLLHUP | 0 |

Durations include the intentional five-second pause; they are not actual sleep
or final resume measurements. The devices cycle re-enumerated the keypad once,
and a fresh handle worked. The MUSB correction removed the two unsupported
access warnings seen in diagnostic.7's comparable cycles. This first pass
does not establish robustness under repeated or deeper PM stages.

Evidence is under `.local/diagnostics/20260930T053805.797509Z/cycle-1/` and
`.local/diagnostics/20260930T053915.202875Z/cycle-1/` (each includes
`run.json`, `before.json` and `result.json`).

The owner confirmed normal dim console and brightness after the first devices
test. `task device:pm-test STAGE=devices CYCLES=4` then passed all four repeats,
with fresh USB/Wi-Fi SSH every time. Each cycle recorded zero unsupported-ULPI
warnings, one keypad disconnect, a dead original input handle and a healthy
new handle. All PM failure counters remained zero and the success count
advanced from two to six. Configuration and PM controls were restored after
every cycle. The detailed results are under
`.local/diagnostics/20260930T054121.479912Z/cycle-{1,2,3,4}/`.

## Keypad supply and recovery trace

The owner confirmed normal display/brightness after the four-cycle batch.
`task device:pm-test STAGE=devices CYCLES=1 KEYPAD_TRACE=1` then passed, including
both fresh SSH routes, unchanged PM failure counters, restored settings and a
healthy newly opened keypad handle. The PM success count reached seven.
Run ID: `2b18f3dc8cfa4c1c90df24f07770f244`; stage duration 9.565311 seconds,
including the deliberate five-second pause.

The trace captured **3,742 events**, with zero overruns, commit overruns or
dropped events on every CPU. Selected debug flags were restored and the private
trace instance and ownership file were removed. Evidence:
`.local/diagnostics/20260930T054704.011007Z/cycle-1/result.json`.

The common monotonic trace clock recorded:

| Event | Seconds since boot |
| --- | --- |
| Keypad regulator disable begins | 759.690524 |
| Keypad regulator disable completes | 759.690539 |
| Keypad regulator enable begins | 764.820257 |
| Keypad regulator enable completes | 764.820272 |
| Keypad USB resume callback begins | 765.160289 |
| Keypad USB resume callback ends | 768.181335 |

The regulator disabled/enabled interval was approximately **5.130 seconds**.
This confirms the software supply transition across the debug pause; there is
no external voltage measurement. Linux's regulator core emits the completion
event after the disable/enable operation returns successfully. The USB log
then records `status 0000.0100 after resume, -19`: power is reported on, but
the connection bit is absent. Linux rejects the resume and disconnects the
keypad. It re-enumerates as USB device 8 and input7. As before, the original
input handle is dead while a freshly opened handle works.

The USB keypad callback occupied **3.021046 seconds**, much longer than the
traced display-engine resume (35.012 ms), OHCI platform resume (26.836 ms), or
backlight class resume (4.340 ms). These are callback intervals in this
serialized, instrumented debug run, not final wake latency or energy figures.
They make keypad recovery a concrete latency target.

Source review identifies a preceding wait that report 58 initially omitted:
`usb_port_resume()` calls `wait_for_connected()` when persistence is enabled.
That helper loops in nominal 20 ms sleeps up to a nominal 2,000 ms budget,
before the three short retries in `check_port_resume_type()`. Its bookkeeping
counts requested sleeps rather than elapsed wall time; the observed three-second
callback cannot be equated to a precise two-second wall-time limit. The full
callback interval does not by itself prove exactly where each millisecond went.

The trace selector now includes `wait_for_connected`'s existing debug message
to confirm the exhausted nominal wait explicitly.
This host-helper change needs no image rebuild. `task check` again passed 209
tests (one optional skip), current-limit and mount-guard regressions, Bash syntax
and ShellCheck. The source correction is also recorded in report 58.

The additional capture passed as run `3fc27984a10d43a4a7bcc4beefc0ee86`,
recorded under `.local/diagnostics/20260930T055133.332401Z/cycle-1/`. It logged
`Waited 2000ms for CONNECT`, then the same powered-but-disconnected port status
and ENODEV rejection. The keypad USB callback lasted **3.021147 seconds**;
the full debug stage took 9.621690 seconds. The software supply-off interval
was 5.129607 seconds. It again captured 3,742 events with no overruns, commit
overruns or dropped events. Tracing and PM controls were restored and both
fresh SSH routes passed.

Final read-only inspection at
`.local/diagnostics/20260930T055322.172877Z/inspection.json` confirmed the same
boot, eight successful PM debug cycles, all failure counters zero, all seven
services active with zero restarts, zero taint and one firmware load. Controls
were back to `pm_test=none` and `pm_async=1`. An independent readback of the
dynamic-debug control file confirmed that all 30 selected callsites had their
printing flags disabled. Its private evidence is
`.local/neo42-final-dynamic-debug.txt`.

## Next decision and limits

Two bounded comparisons now have a concrete basis: preserving the keypad
supply to test continuity, or disabling persistence only for this exact internal
keypad to test faster disconnect/reopen recovery while keeping the present
power-off policy. **NEO-43 selects the persistence comparison first**, using
baseline/candidate/baseline runs with transactional restoration and the same
stable-identity/input-handle checks. It can be tested without reflashing and
isolates the measured wait before introducing a new supply policy. Neither
option is a selected production policy. Retention needs separate energy measurement;
the installed keypad MCU and firmware remain unconfirmed.

All seven driver debug tests produced zero unsupported-ULPI warnings. The AXP
polling lifetime change recovered through these ordinary driver stages, but
the asynchronous notification/supplier ordering gates still block late/noirq
and actual sleep. Normal sleep remains disabled. Physical wake, held-button
behavior, sleep energy and subsecond resume remain unqualified.
