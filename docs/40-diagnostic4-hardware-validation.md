# Diagnostic.4 build and hardware validation

Date: **2026-09-28 UTC** (28–29 September NZDT). Ticket: **NEO-19**.
Target: CPI v3.1. Scoped build and hardware regression: **passed**.

## Scope and current status

The owner returned ready for hardware tests. This candidate combines the
[USB work-lifetime correction](38-usb-work-lifetime.md), patch 0006, and the
[fixed-parent clock constraint optimization](39-clock-rate-constraint-optimization.md),
patch 0007. Both passed their host checks before this hardware session.
The complete image build, offline verification, full flash readback and scoped
hardware regression passed. The owner confirmed the display sequence and all
four orderly shutdown/start cycles; four USB reconnects also passed. Overall
hardware acceptance, charging qualification and sleep remain separate work.

The source lock advances the image to `0.1.0-diagnostic.4` and kernel release
to `6.18.54-gameshellneo4`. Linux, builder, Debian snapshots, DT, operating
points, runtime policy and existing patches retain their previous inputs.
The slower USB polling experiment remains a design, not part of this image.
Charger settings and sleep support are outside this validation scope.

## Preserved baseline

Before shutdown, diagnostic.3 was reachable over direct Wi-Fi and USB through
the Mac. All six monitored services were active with zero restarts, no failed
units or kernel taint. The battery monitor was valid, reporting 84%, Charging,
and 4.1954 V at the status sample; this is software telemetry, not electrical
charging qualification. USB was configured at high speed. Four CPUs and about
1 GiB RAM were present. Local readiness was 14.61 seconds, and systemd reported
15.02 seconds for kernel plus userspace; neither includes the full cold-start
bootloader interval.

The existing integration task passed image identity, services, journal ACL,
BPF policy, regulatory database and the owner's accepted AU access-point
announcement. The configured country remains NZ; this session does not claim
NZ radio qualification.

Private baseline evidence:

- `.local/diagnostics/20260928T100959.931133Z/`: status over Wi-Fi.
- `.local/diagnostics/20260928T101040.611333Z/`: integration over USB.
- `.local/diagnostics/20260928T101115.943974Z/`: downloaded diagnostic archive.

`task kernel:reset` retained diagnostic.3's source, output, installed modules
and completion manifest under
`.local/previous-kernels/20260928T101105Z-707835/`.
That task now also saves current artifact metadata/logs as
`artifact-metadata.tar`, automating the preservation previously done separately.
Large recovery images remain in `.local/artifacts/`.

The diagnostic.3 recovery image was hashed again and still matches
`64f092d5770ef344cb2e9d22b16780aebe94a5501732130f6b22c21910554523`.
The new resolved kernel configuration is byte-for-byte identical to that
preserved baseline, and all 132 configuration assertions passed.
The actual-source NKMP, USB lifetime and clock-range regressions passed before
full compilation. Project checks also passed 13 runtime tests, 58 tool tests
(one optional user-systemd skip), current-limit regressions and shell lint.

The complete kernel/module build then passed, recording and verifying 15
artifacts for `6.18.54-gameshellneo4`. The configuration SHA-256 is
`088d97999930260b6d8dd163df46a50487d48648a3a16841245d62434787de2e`;
the DTB SHA-256 is
`8280b127316f641aab60a1d341832adfc4fbc7cec3ae65a559bbd33224b40cd4`.
Both are byte-for-byte identical to diagnostic.3.

`task build` completed all stages, including schema/DTB validation with no
diagnostics and offline image verification. The latter checked partition
boundaries, bootloader bytes, FAT16/ext4 filesystems, U-Boot CRCs/addresses,
kernel/DTB/modules/radio hashes, private identity permissions and service policy.
The final artifact checksum inventory also confirms the preserved diagnostic.3
image still matches its original hash after assembly.

| New artifact | Value |
| --- | --- |
| Filename | `GameShellNeo-0.1.0-diagnostic.4-cpi31-99e1abf3102c.img` |
| Bytes | 4,294,967,296 |
| SHA-256 | `99e1abf3102c76afbad2dff99c98ad9dedceccef23734225d482f03a35d8dec3` |
| Kernel | `6.18.54-gameshellneo4` |
| Offline verification | Passed |
| Hardware checks | Scoped regression passed; limits below |

The image, manifests and checksums are private under `.local/artifacts/`.
Stage logs are `.local/build/{kernel,devicetree,image,image-verify}.log`.

## Card preparation

The owner confirmed orderly shutdown and moving the Samsung DEV card into
the Mac's reader. Fresh inspection identified `disk20` as the sole external
physical disk, with 64,013,467,648 bytes, 512-byte sectors, media `Micro SD/M2`,
and existing FAT16 `armbi_boot` UUID
`5F7466E3-BEDB-3CF9-BF29-41E26C47102C`. This is a new disk identifier for this
session; the previous `disk16` value was not reused. The guarded task recorded
the identity before staging.

`task mac:stage` transferred the candidate and verified both compressed and
complete decompressed checksums on the Mac. The gzip transfer is 264,307,578
bytes, SHA-256
`3346ad363f7dab7922a25e02483d08393bc1e37036c8aecd9bce02b5c959ddd8`.
`task mac:preflight` passed, followed by `task mac:flash DISK=disk20`.
All 4,294,967,296 bytes were written and read back with the expected raw-image
SHA-256 above, then the Mac safely ejected the card. Private flash log and
result are in `.local/diagnostics/20260928T105151.034667Z/`.
The owner reinserted the card, connected USB and confirmed the normal login
screen appeared.

## Validation sequence

| Stage | Evidence required | Current result |
| --- | --- | --- |
| Host build | Actual-source regressions, complete kernel/modules, configuration and DT validation, offline image verification | Passed |
| Spare-card installation | Fresh Samsung DEV identity, verified Mac transfer, full written-range readback, safe ejection | Passed |
| First boot | Owner-visible console, exact kernel/image, USB and Wi-Fi SSH, service/policy checks | Passed |
| Display | Visible levels and repeated off/on with original brightness restored | Labeled repeat passed, including owner confirmation |
| Load and storage | Direct-read file verification, bounded CPU/memory workload, frequency/temperature recovery and clean postchecks | Passed |
| USB | Four owner-operated reconnects, with same-boot USB SSH verified after each | Passed |
| Cold starts | Four consecutive owner-operated shutdown/start cycles, console observations and captured shutdown/boot evidence | Passed, including owner confirmation |

The shared tasks provide the build and each test. Physical batches begin only
after their recorder is ready, and observations are recorded separately from
software readbacks. No deliberate driver unbind or probe-failure injection is
performed on the board. Normal boot/cable checks are an integration regression,
not reproduction of the lifetime race under every possible schedule.

### Repeat this hardware sequence

Run these from the repository root, one at a time, with the expected image in
the source lock and private connection details in `.env`. Start with USB
connected to the Mac and the login console visible. The test implementations
are versioned under `tools/`; `Taskfile.yml` invokes them and stores the evidence
under `.local/diagnostics/`.

```sh
task device:check ROUTE=usb ACTIVE_COUNTRY=AU
task device:status ROUTE=wifi
task device:boot-cycles CYCLES=0
task device:battery-check ROUTE=usb
task device:stability ROUTE=usb
task device:status ROUTE=usb
task device:logs ROUTE=usb
task device:backlight ROUTE=usb
task device:usb-reconnects CYCLES=4
task device:boot-cycles CYCLES=4
task device:check ROUTE=usb ACTIVE_COUNTRY=AU
task device:status ROUTE=wifi
task device:logs ROUTE=usb
```

- Keep USB connected and controls untouched during the roughly six-minute
  storage/load/recovery task. Battery-guard tests use simulated telemetry.
- Be ready to watch before invoking the backlight task. Confirm its three
  levels, three dark/bright cycles and final dim restoration. An incomplete
  observation must be repeated; successful software readbacks do not replace it.
- For USB reconnects, wait for the task's `ready` event. Unplug from the
  GameShell for three seconds, reconnect, and leave it connected for at least
  30 seconds. Repeat four times and finish connected. Wait for task completion.
- For cold starts, wait for `ready`. Briefly press power to shut down; wait
  ten seconds after the screen goes dark; power on normally. Wait for the
  login console, then another 60 seconds before the next shutdown. Repeat
  four times, keeping USB connected and leaving the final boot running.
  Stop and report a missing shutdown or login screen. The task never presses
  the power button or performs a reboot itself.

These commands reproduce the test procedure, not identical physical timing,
temperature or battery state. Record owner observations and retain each run's
private evidence. The broader prerequisites and helper behavior are in the
[README](../README.md#routine-device-work).

Artifact identity and measured results are recorded here. Reduced host
clock-search work does not establish
measured board latency or battery savings. Overall hardware acceptance (NEO-5),
charging telemetry (NEO-10), endurance and deep sleep remain separate work.

## First boot and installed policy

The board booted `0.1.0-diagnostic.4` / `6.18.54-gameshellneo4`, with boot ID
`174a8ac8-8fcb-40e5-b998-ac1a8961b100`. Direct Wi-Fi SSH and USB SSH through
the Mac both worked. The integration task passed service identity/state,
journal access, BPF control/deny/allow checks and regulatory database checks.
Configured NZ and observed global AU match the existing provisioning and
owner-accepted access-point announcement; firmware country qualification
remains separate.

Four CPUs and about 1 GiB RAM were present, with no failed services, restarts
or kernel taint. The keypad and power-key input devices were present. The
battery monitor reported valid telemetry, 87%, Charging and 4.1998 V at the
first status sample. The installed battery guard also passed nine simulated
telemetry tests; these do not discharge the battery or request real shutdown.

Local readiness was 16.85 seconds on this fresh-image boot. The status task
reported 22.13 seconds for kernel plus userspace. This fresh-image boot is
recorded separately from repeated starts; one uncontrolled sample cannot
attribute a timing change to either patch. Neither metric includes the
bootloader interval. Repeated starts are recorded separately below.

Private evidence:

- `.local/diagnostics/20260928T105625.497518Z/`: integration through USB.
- `.local/diagnostics/20260928T105625.524892Z/`: status through Wi-Fi.
- `.local/diagnostics/20260928T110032.493361Z/`: validated current boot and
  separate Wi-Fi boot-identity check; zero power cycles requested or credited.
- `.local/diagnostics/20260928T110033.212269Z/`: installed battery-guard tests.

## Display

`task device:backlight ROUTE=usb` read back levels 1, 16 and 31, then three
0/31 cycles, and restored brightness 1. Private evidence is
`.local/diagnostics/20260928T105733.972882Z/`.
The owner only caught the final bright-to-dim transition, so the full visual
sequence is not credited. They requested on-screen labels and a visible hold.
NEO-20 adds a ten-second countdown, requested/readback labels on `tty1`, four
seconds at each lit level and two-second off/on intervals with an advance
notice. The existing getty remains running. The labeled repeat passed all
requested readbacks and restored brightness 1. The owner confirmed clear
labels, three distinct levels, three complete dark/bright cycles and the final
return to dim. Evidence: `.local/diagnostics/20260928T110656.000869Z/`.
This covers backlight off/on, not panel rail cycling or sleep restoration.
The helper and README change is committed as `15d3fb9` (NEO-20). The task sends
the versioned helper at invocation, so this improvement did not rebuild or
alter the installed image. Shell syntax, ShellCheck and whitespace checks passed.

## Storage, CPU and memory load

`task device:stability ROUTE=usb` passed on the initial boot. It wrote and
flushed a temporary 128 MiB random file, then verified its SHA-256 with a direct
read. Four CPU workers and one 256 MiB memory worker passed five minutes of
`stress-ng --verify`, with zero failed or skipped workers. The sampled CPU
frequency stayed at 1,008 MHz under load. Peak sampled temperature was
61.884 °C; the three recovery samples fell to 54.918, 53.460 and 52.164 °C,
at 408, 408 and 312 MHz respectively.

The boot ID remained unchanged, USB stayed configured and kernel taint remained
zero throughout. The task removed its temporary files. Governor `schedutil`
and the 120–1,008 MHz limits were not changed. This verifies a bounded workload
and observed frequency recovery, not every OPP/voltage transition or endurance.
Private evidence: `.local/diagnostics/20260928T110048.187176Z/`.

Post-load status and the downloaded log archive show active services with
zero restarts, no failed units or taint and no kernel entries after the
ordinary startup sequence. Existing CPU `clock-frequency`, PMIC DMA-mask,
generic USB PHY supply and Broadcom fallback-firmware diagnostics are also
present in the diagnostic.3 baseline; they are not newly introduced here.
The post-load battery sample again reported 4.2559 V while Charging, at 93%.
This repeats the unresolved NEO-10 software-voltage discrepancy; charging
settings were preserved and electrical charging qualification is not claimed.
Evidence is `.local/diagnostics/20260928T110647.420754Z/` (status) and
`.local/diagnostics/20260928T110647.420344Z/` (archive).

## USB reconnections

`task device:usb-reconnects CYCLES=4` recorded four removals followed by four
returns to configured USB state. USB SSH through the Mac was verified after
each return on the same boot, `174a8ac8-8fcb-40e5-b998-ac1a8961b100`.
No cycle was missed or counted solely from the owner's response. The on-board
recorder stopped and its temporary files were removed after the fourth check.
There were transient SSH channel timeouts during disconnection/recovery, as in
prior testing; the trace and actual successful connections establish recovery,
not a USB enumeration/SSH latency target.

Private evidence: `.local/diagnostics/20260928T110812.146012Z/`, including
`device-states.jsonl`, `usb-reconnects.jsonl` and the passing four-cycle summary.

## Consecutive cold starts

`task device:boot-cycles CYCLES=4` passed the owner-operated batch with USB
connected. Each new boot passed USB and direct Wi-Fi access, exact identity,
service/input/display/battery checks, zero failed units/restarts and zero taint.
The journal boot chain was consecutive; each preceding shutdown recorded the
short power-key event, power-off target and filesystem sync. The owner
separately confirmed that all four cycles went dark and returned normally to
the login screen.

| Cycle | Boot ID | Local readiness (s) | Kernel + userspace (s) |
| --- | --- | ---: | ---: |
| 1 | `da6afe77-91b6-4c75-8ad5-8c9ac030e81d` | 14.719 | 15.010 |
| 2 | `42fb47dc-310b-4981-a783-209bca92440a` | 14.862 | 15.043 |
| 3 | `5a7c3b9a-2cc2-4445-865e-8f97c714aa06` | 14.924 | 15.131 |
| 4 | `b8d834d9-4549-490a-95c7-1204c2c4060a` | 14.438 | 14.633 |

These results are close to diagnostic.3's 14.61/15.02-second baseline; the
fresh image's slower first boot did not repeat. This is neither a controlled
performance comparison nor the full power-button-to-console interval: the
bootloader is excluded. The five-second startup target is not achieved here.

All four shutdowns again logged the already tracked UDC request to start
`usb-gadget.target` during poweroff; systemd rejected it and orderly shutdown
completed. This remains a follow-up, not a demonstrated new failure.

Private evidence: `.local/diagnostics/20260928T111232.833458Z/`.
The saved summary records four requested and four verified cycles with
`passed: true`. Kernel logs retain the known startup diagnostics; no new
driver crash or storage error was identified.

## Final checks and limits

The final integration check passed on boot
`b8d834d9-4549-490a-95c7-1204c2c4060a`, including image/kernel identity,
service state, journal access, BPF policy and the expected regulatory setup.
Evidence: `.local/diagnostics/20260928T112002.117310Z/`.
Final direct Wi-Fi status also passed: six monitored services active with zero
restarts, no failed units or taint, valid battery telemetry, configured
high-speed USB and four CPUs. Brightness remained restored to 1 in the final
boot capture. Status and final archive are
`.local/diagnostics/20260928T112104.118833Z/` and
`.local/diagnostics/20260928T112104.366178Z/` respectively.

This completes NEO-19's scoped installation and regression checks. It does
not close NEO-5's wider hardware acceptance or NEO-10's charging-voltage
investigation. The image still truthfully carries `hardware_qualified: false`.
No sleep, exhaustive clock-transition, fault-injected kernel teardown or
attributed battery/latency result is claimed. The opt-in slower USB polling
policy remains unimplemented, and diagnostic.3 remains available for recovery.
