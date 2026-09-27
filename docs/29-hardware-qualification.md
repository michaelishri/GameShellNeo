# Diagnostic image hardware qualification

Status: **in progress**, 27 September 2026. Kaneo NEO-5 remains open.

This report records physical checks on the owner's CPI v3.1 running
`0.1.0-diagnostic.2`, kernel `6.18.54-gameshellneo2`. The image and its first
boot are identified in [report 27](27-diagnostic-integration-refresh.md).
Acceptance criteria remain those in [report 23](23-first-build-spec.md).

## Input results

The owner operated the controls while input events were collected over USB
SSH through the Mac. The internal keypad is USB HID `4242:e131`, named
`rancidbacon.com UsbKeyboard`, currently `/dev/input/event1`. The separate
`axp20x-pek` power key is currently `/dev/input/event0` and was not grabbed
during keypad capture. Its later shutdown test is recorded below. Event numbers
must be rediscovered after boot.

`evtest --grab` isolated the keypad from the login console during capture.
Each successful ordinary-key test included `EV_KEY` value 1 (press) followed
by value 0 (release). Holding some directions also produced value 2 repeats.
The following are observed mappings, consistent with the
[reference keypad sketch](../../GameShell/Code/Keypad/clockworkpi_keypad.ino).
This does not identify the firmware actually flashed on the controller.

| Physical control | Observed Linux event | Result |
| --- | --- | --- |
| Up | `KEY_UP` | Press/release passed |
| Down | `KEY_DOWN` | Isolated press/release passed on retry |
| Left | `KEY_LEFT` | Isolated press/release passed on retry |
| Right | `KEY_RIGHT` | Press/release passed |
| A | `KEY_J` | Press/release passed |
| B | `KEY_K` | Press/release passed |
| X | `KEY_U` | Press/release passed |
| Y | `KEY_I` | Press/release passed |
| Menu | `KEY_ESC` | Press/release passed |
| Select | `KEY_SPACE` | Press/release passed |
| Start | `KEY_ENTER` | Press/release passed |
| Front Shift + A | `KEY_H` | Alternate mapping and release passed |
| Front Shift + Select | `KEY_KPMINUS` | Alternate mapping and release passed |
| Front Shift + Start | `KEY_KPPLUS` | Alternate mapping and release passed |

The first Down test also included a brief Left press; the first Left test
included a brief Up press. Centred retries produced the requested direction
alone. This is compatible with incidental diagonal actuation, but does not
establish its mechanical cause or measure directional sensitivity.

The main keypad's basic checks passed. This is not an exhaustive test of
simultaneous-key combinations, every Shift mapping, input latency or endurance.
Front Shift changes key mappings in the reference firmware; a standalone
PC-style Shift event is not required for its operation.

## Lightkey issue

The owner confirmed that the five-button rear Lightkey bar is fitted. With
the back facing the owner, the requested sequence was leftmost, second from
left, second from right, rightmost. Only one `KEY_H` press/release appeared.
Repeating the latter three controls, followed by front A as a positive control,
produced only A's expected `KEY_J` press/release. Capture remained active.
The first batch alone does not independently label which physical button
produced its single event.

The centre-button check then requested centre+A, A alone, centre+Start,
Start alone, releasing centre between combinations. The resulting sequence
was `KEY_J`, `KEY_J`, `KEY_ENTER`, `KEY_ENTER`, each with a release. The owner
subsequently clarified that the need to hold both buttons at the same time
had been misunderstood. **This attempt is inconclusive for rear Shift**, and
must not be counted as a failed simultaneous combination. The reference
mapping changes A to `KEY_H` and Start to `KEY_KPPLUS`, as the front Shift
tests already demonstrated.

At the owner's request, a fresh capture then tested four rear-centre presses
alone, each held for about one second and fully released. No events were
recorded while the capture service remained active. **This standalone check is
inconclusive:** the reference firmware uses the centre button to select an
alternate mapping and does not report it as an ordinary key. A functioning
centre button could therefore also be silent when pressed alone.

The simultaneous test was then repeated with explicit instructions to hold
rear centre down while tapping A and Start, release centre, and tap A and
Start again. The owner confirmed completing that sequence. The fresh capture
recorded `KEY_J`, `KEY_ENTER`, `KEY_J`, `KEY_ENTER`, all with clean releases.
**The rear centre did not select alternate mappings in this clarified test.**
This is a functional observation, not a diagnosis of the switch, connection
or firmware. Front Shift's successful alternate mappings provide a comparison.

**Lightkey qualification is incomplete.** No connector, switch, firmware or
Linux-driver cause has been established. The owner is unsure whether all five
rear controls worked with the original software. Compare or inspect the
affected path before choosing a fix. No keypad firmware was flashed and no wiring was
changed during these tests. This issue is tracked in [FOLLOW-UP.md](../FOLLOW-UP.md).

## Capture reliability and private evidence

The first captures streamed through SSH. One expired before a requested
four-control batch; its log contained no events for that batch, so that
attempt was discarded and repeated. This was a test-harness failure, not
evidence of missing device input.

Subsequent capture ran as the temporary device service
`gameshellneo-keypad-capture`, using `stdbuf -oL evtest --grab`, a one-hour
runtime limit and a root-only log at
`/run/gameshellneo-keypad-capture/events.txt`. This kept recording across SSH
disconnections. It was explicitly stopped after the centre-button test to
release the keypad. Operations used the shared `task device:exec ROUTE=usb`
entry point and private connection configuration from `.env`.

The retained host evidence is under ignored `.local/diagnostics/`:

| Capture | Contents |
| --- | --- |
| `neo5-keypad.dpbPc6DU/events.txt` | Initial Up/Down tests and initial Left with additional Up |
| `neo5-keypad.iNMkyRtP/events.txt` | Discarded streaming attempt; device description only |
| `neo5-keypad.046dL2fy/events.txt` | Cumulative device-side recording: successful main-keypad batches, both outer-Lightkey attempts and centre-button comparison |
| `neo5-keypad.dTZRAbdC/centre-only.txt` | Fresh capture for four standalone rear-centre presses; active service and device description, no input events |
| `neo5-keypad.XKllT44R/centre-held.txt` | Clarified simultaneous test: centre held for A/Start, released for A/Start; normal mappings in both cases |

Intermediate snapshots are also retained. Key-event data remains private.
The device-side copy is volatile and is not the recovery copy of this evidence.
The separate centre-only and clarified-combination captures were also stopped
after collection, releasing the keypad each time.

## Backlight results

The owner watched `task device:backlight ROUTE=usb` on 27 September 2026,
03:46:49–03:47:14 UTC. Initial brightness and software readback were 1,
maximum 31, with `bl_power=0` (unblanked). The test requested brightness
1, 16 and 31 for four seconds each, then three cycles of 0 for two seconds
and 31 for two seconds. It restored the starting brightness of 1.

Every sysfs write succeeded and each software readback matched the requested
value. The owner confirmed three distinct visible brightness levels, three
complete dark/bright cycles and normal console recovery. **These basic visual
backlight checks passed.** The driver does not implement a hardware brightness
readback; software values alone would not prove visible output or electrical
power-off. This test does not qualify panel rail cycling or sleep/resume.

The task is documented in the [README](../README.md). It uses a temporary
systemd service with a 60-second bound and a restoration trap. Host validation
passed all 25 existing Python tests, the C current-selector regressions, shell
syntax and ShellCheck. The host tooling needs no image rebuild.

Private evidence is `.local/diagnostics/20260927T034641.417076Z/backlight.txt`
and `postcheck.txt`. The postcheck confirmed brightness/readback 1, unblanked
panel, active USB/battery/SSH services and zero kernel taint. Failed-unit and
kernel-warning checks are recorded alongside those reads.

## USB reconnection results

The first batch of four physical removals/reconnections passed using
`task device:usb-reconnects CYCLES=4`. The Wi-Fi observer saw each USB removal
and subsequent configured state. After each return, a fresh SSH connection
through the Mac reached the USB address on the same boot. Initial attachment
was verified separately and was not counted. A second batch of four also
passed with the same boot throughout. A final recorded batch of two completed
the target: **ten USB reconnections verified**, excluding the two actions
whose observer failed as described below.

Private evidence is
`.local/diagnostics/20260927T035215.285355Z/{usb-reconnects.jsonl,summary.json}`.
First observed configured state to completed SSH verification took 15.073,
5.871, 13.071 and 4.314 seconds. These intervals include observer polling,
SSH setup, retries and the final state check; they are not pure USB
enumeration or network-ready latency measurements. Some initial SSH attempts
failed while connectivity recovered; all four cycles completed without a
board reboot. Subsequent instructions allow 20 seconds connected between
removals. Wi-Fi polling during this test does not qualify idle power.

The second batch is recorded in
`.local/diagnostics/20260927T035525.615187Z/{usb-reconnects.jsonl,summary.json}`.
Configured-state-to-verification intervals were 12.463, 3.637, 4.864 and
3.707 seconds, with the same measurement limits above.

The next requested two-cycle batch was **not verified**. Its Wi-Fi observer
saw one removal and then failed with `Timeout opening channel`; the owner
reported completing the actions, but no additional cycles were credited.
Evidence is `.local/diagnostics/20260927T035838.730022Z/`. A subsequent direct
Wi-Fi SSH attempt also failed. USB SSH remained usable on the same boot,
with all six services active, zero restarts/failed units and no kernel taint.
The radio was associated at -85 dBm; five subsequent ICMP probes succeeded
and no new kernel warnings were recorded. These observations do not establish
the cause of the SSH failures. Postcheck evidence is in
`.local/diagnostics/20260927T040024.759411Z/`.

The reusable task now runs a bounded state recorder on the GameShell and
retrieves its events through USB SSH after reconnection. This removes the
continuous Wi-Fi SSH dependency. It still requires a fresh USB SSH check for
each counted cycle and rejects multiple removals between checks. The failed
Wi-Fi-observed batch remains excluded.

The final two-cycle repeat passed with on-device recording. Its complete trace
contains configured → not attached → configured → not attached → configured;
each return was followed by successful USB SSH on the original boot. Initial
SSH attempts returned routing, banner/session or channel errors before later
attempts succeeded. The temporary recorder was stopped and its remote files
removed. Evidence is
`.local/diagnostics/20260927T040647.062293Z/{usb-reconnects.jsonl,device-states.jsonl,summary.json}`.
Future instructions allow 30 seconds after reconnection to leave time for
the host's complete verification path. This confirms eventual recovery in
the tested setup, not a latency target or ten uninterrupted first-attempt
SSH successes.

Final USB postcheck in `.local/diagnostics/20260927T041021.837995Z/status.txt`
showed the original boot still running, all six services active with zero
restarts, no failed units and no kernel taint. The reusable monitor and
recorder passed Python compilation checks; `task check` passed the existing
25 Python tests, C regressions and shell lint. The initial observer failure
and intermittent SSH setup errors remain follow-up work.

## CPU, memory, storage and frequency results

`task device:stability ROUTE=usb` passed on 27 September 2026,
04:15:43–04:21:20 UTC. It created a temporary file on the diagnostic root
filesystem, wrote 128 MiB of random data, flushed the file with `fsync`, and
read it using `dd iflag=direct`. The full read size and SHA-256 matched:
`ce3d62e190574f9cd9f9ed262380cbacaeac17ffcb646e97fb5a93300be2f7ff`.
Direct reads bypassed the file data cache; the temporary directory was removed.
This is a bounded file-integrity check, not whole-card or endurance qualification.

The following five-minute load used `stress-ng` 0.19.02 with four CPU workers,
one 256 MiB memory worker, `--verify` and `--abort`. It reported all five
workers passed, zero skipped/failed stressors, zero untrustworthy metrics and
exit status zero. A live process snapshot confirmed the four active CPU
workers and the memory worker; memory use was approximately 353 MiB, with
646 MiB available during that snapshot.

The governor remained `schedutil`, with reported limits of 120–1,008 MHz.
All load samples reported 1,008 MHz. After load stopped, recovery samples
reported 240 MHz, 240 MHz and 120 MHz. This demonstrates the sampled governor
transitions; it is not an exhaustive voltage/OPP or idle-residency test.

Reported CPU temperature rose from 46.494 °C to a sampled maximum of
66.258 °C. The test's 80 °C stop limit was not reached. Fifteen seconds after
the load ended, the sensor reported 56.700 °C. Kernel taint remained zero;
no kernel journal entries appeared during the test interval. The final
status capture showed six active services with no restarts, zero failed
units, the same boot, working USB SSH and approximately 74 MiB memory used.
No temperature, clock, governor, voltage or charging policy was changed.

Private evidence:

- `.local/diagnostics/20260927T041537.374392Z/stability.jsonl`: parameters,
  checksum, samples, stress-ng output and successful completion.
- `under-load.txt` and `postcheck.txt` in the same directory: process/memory
  snapshot, logind configuration, kernel log check and temporary-file cleanup.
- `.local/diagnostics/20260927T042245.487229Z/status.txt`: final device status.

The reusable task is documented in the [README](../README.md). It uses a
seven-minute transient-service limit, five-second temperature/taint samples,
available-memory/free-space preflight checks and temporary files. The script
passed Python compilation and the existing `task check` suite passed. This
short run supports basic diagnostic-image stability; it does not establish
long-duration reliability, battery endurance or suspend behavior.

## Power-button shutdown and second cold start

The owner briefly pressed power with USB connected and confirmed that the
screen went dark and stayed dark. USB SSH became unavailable. The live SSH
journal stream ended without capturing the shutdown messages, so that stream
alone was not counted as proof of orderly shutdown.

After the owner powered on again and confirmed the login console, the saved
journal of boot `d363e3cf-8abb-4e69-a99d-1f0affc166da` showed:

- `Power key pressed short.` followed by logind's power-off request.
- Services stopping, `/boot` unmounting and `poweroff.target` being reached.
- `systemd-shutdown` syncing filesystems/block devices before journald stopped.

This supports **a successful supervised button-triggered orderly shutdown**,
combined with the owner's physical observation and the subsequent successful
start. The journal ends before the final PMIC action; no electrical power-off
measurement or exact button-to-darkness timing is available.

One shutdown diagnostic remains open: a UDC event requested
`usb-gadget.target/start` while the power-off transaction was queued. Systemd
rejected that start request and shutdown continued. Record this ordering
warning for investigation; it did not prevent this observed power-off. An SSH
preauthentication child was also terminated by SIGTERM during shutdown.

The new boot ID is `f98ef69c-47cd-4fac-9427-81a5552a4ef7`. On 27 September
2026 at 04:32 UTC, USB SSH returned, all six expected services were active with
zero restarts, no units were failed and kernel taint was zero. Four CPUs and
1,000 MiB RAM were present; reported memory use was about 68 MiB. Both input
devices enumerated again and backlight brightness returned to 1, unblanked.
The current kernel journal contains no ext4 recovery/error report; this is
not an offline filesystem check (the root fsck unit was skipped because root
was already mounted read/write).

Local readiness was recorded at 14.658 seconds; systemd reported 2.542 seconds
kernel plus 12.429 seconds userspace, total 14.972 seconds. These software
timestamps exclude bootloader time and do not establish button-to-usable-display
latency or the five-second aspiration. At this stage, **two cold starts were
observed** for this candidate; eight remained.

Private evidence:

- `.local/diagnostics/neo5-powerkey.wEHCpmx3/journal.txt`: incomplete live stream.
- `previous-boot.txt` and `new-boot.txt` in the same directory: saved shutdown
  sequence, new boot identity/kernel journal and input/backlight reads.
- `.local/diagnostics/20260927T043247.288841Z/status.txt`: post-start services,
  memory, readiness and power status.

`task device:boot-cycles CYCLES=4` now provides the repeatable batch recorder;
its operator steps and evidence limits are in the [README](../README.md).
`CYCLES=0` captures a baseline without adding cycle credit. Each counted new
boot must follow the previously recorded boot, pass the software checks and
return both USB and direct Wi-Fi SSH. Physical off/console observations remain
necessary; software capture alone does not confirm a cold start.

The current-boot capture passed over both USB and direct Wi-Fi SSH in
`.local/diagnostics/20260927T043802.488053Z/`, including the local getty service.
Two earlier recorder development attempts failed before completing collection
because `journalctl` does not accept `--no-legend`; that option was removed.
Those attempts involved no power operation and add no cycle credit. Python
compilation, `git diff --check`, all 25 existing Python tests, the C selector
regressions and shell lint passed. The physical batch result follows.

## First batch of four power cycles

The owner completed four shutdown/startup cycles with USB connected, waiting
ten seconds after darkness and sixty seconds after each login console. The
recorder verified all four, with no missed boot IDs. At this stage, **the
candidate had six observed consecutive cold starts; four remained.**

| Candidate boot | Boot ID | Local readiness (seconds) | Systemd startup total (seconds) |
| --- | --- | --- | --- |
| 3 | `062f38b7-67ee-47ee-bb36-d9751747ee18` | 14.171 | 14.324 |
| 4 | `8e1333f1-8a3f-418b-aee1-ed1074e48501` | 14.169 | 14.343 |
| 5 | `9bda7973-fed3-47a1-8467-0235fb3ed263` | 14.599 | 14.844 |
| 6 | `596ac163-4f5b-4a1b-a729-8ca8e549fd93` | 14.994 | 15.220 |

Every boot passed image/kernel identity, four CPUs, 1,024,520 KiB memory,
untainted kernel, active services without restarts, no failed units, local
getty, input enumeration, backlight restoration and valid battery monitoring.
Fresh USB SSH and direct Wi-Fi SSH both reached the same boot. The saved
journals link each boot to the preceding captured boot and show each short
power press reaching `poweroff.target` and filesystem syncing.

The shutdown USB-target ordering warning recurred in all four preceding
shutdowns; it remains tracked and did not prevent these observed cycles.
The kernel warning/error search found the same inherited `/init` lookup and
optional board-specific radio firmware/CLM lookup messages as the baseline,
without an oops, panic, timeout or ext4 recovery/error report in these captures.
SSH probes reported connection refusals, missing routes or timeouts between
boots; all four cycles subsequently passed both access checks. This does not
measure network readiness latency or remove the earlier connectivity follow-up.

Private evidence is `.local/diagnostics/20260927T043918.378623Z/`:
`boot-cycles.jsonl`, a successful four-of-four `summary.json`, and the baseline
plus four per-boot JSON files containing checks and kernel/shutdown journals.
The recorder exited successfully. Readiness times retain the exclusions
described above; software polling during this batch is not an idle-power test.

## Final batch and completed cold-start check

The owner completed another four physical shutdown/startup cycles using the
same procedure. The recorder verified all four and exited successfully, with
an unbroken previous-boot chain. **Ten consecutive cold starts are now
observed for this candidate: the initial start, the supervised power-button
restart, and two recorded batches of four. The cold-start count gate passed.**

| Candidate boot | Boot ID | Local readiness (seconds) | Systemd startup total (seconds) |
| --- | --- | --- | --- |
| 7 | `429ef585-cdb3-48b4-9d1c-936a1eb829f5` | 14.748 | 14.958 |
| 8 | `4fc3d255-cc3a-437c-9323-cf8738b3d0b4` | 14.671 | 15.123 |
| 9 | `72d37e63-fec3-43b8-84b2-449e5aad8fec` | 14.851 | 15.356 |
| 10 | `b82a951a-31a3-4e7f-b4db-69a4fc5aa894` | 14.755 | 14.998 |

Every new boot passed the same identity, CPU/memory, service, getty, input,
backlight, battery-monitor and USB/direct Wi-Fi SSH checks as the first batch.
There were no failed units or kernel taint. Every preceding saved shutdown
contained the short power-button event, power-off target and filesystem sync.
The same UDC/USB-target shutdown warning recurred; its investigation remains
open. Kernel warning/error matches remained the inherited `/init` and optional
radio firmware/CLM lookups, with no oops, timeout or ext4 recovery/error report
in these captures.

During startup the observer again encountered missing routes, refusals,
timeouts and SSH banner/session errors before successful connections. Each
cycle ultimately passed both routes; these results qualify recovery in this
setup, not uninterrupted first-attempt SSH success or network-ready latency.
The eight batch readiness markers range from 14.169 to 14.994 seconds and
exclude bootloader time; they do not meet or measure the complete five-second
boot aspiration.

Private evidence is `.local/diagnostics/20260927T044812.372580Z/`, containing
the successful four-of-four `summary.json`, `boot-cycles.jsonl` and baseline
plus four per-boot captures. All boot monitors have finished. This completes
the repeated-start subcheck, not the remaining NEO-5 hardware qualification.

## Battery transition: unplugged operation

After the tenth start, direct Wi-Fi SSH remained usable with all six services
active, no restarts/failed units and zero kernel taint. At 04:59:06 UTC the
connected-power snapshot reported battery present, `Charging`, 100% and
4,199,800 µV; the awake battery guard reported valid monitoring. Both USB and
AC supply inputs reported present/online. No charging or input-limit setting
was changed. These are software readings, not calibrated charge/endurance or
electrical current measurements.

Private evidence is `.local/diagnostics/20260927T045838.887394Z/status.txt`
and `.local/diagnostics/neo5-battery.JREzc0bg/connected-before.txt`.

The owner unplugged USB, left the device running for two minutes and confirmed
that the screen stayed on, dim, throughout. At 05:02:45 UTC, direct Wi-Fi SSH
still reached boot `b82a951a-31a3-4e7f-b4db-69a4fc5aa894`. All six services
remained active without restarts, no units were failed and kernel taint was
zero. USB reported `not attached`; both the USB and AC power-supply inputs
reported present/online zero. The battery remained present and reported
`Discharging`. **The supervised transition to battery-only operation passed.**

The battery guard journal changed from valid/Charging to valid/Discharging
at 05:00:26 UTC, with no degraded-monitoring entry or critical condition. Its
later status still reported valid monitoring and zero consecutive low samples.
Backlight brightness was 1 with `bl_power=0`, matching the connected baseline;
the owner's dim-screen observation does not establish an automatic dimming
transition. No new kernel journal entries appeared after the connected baseline.

The direct battery snapshot reported 100%, 4,024,900 µV and -347,000 µA. The
guard's earlier ten-second sample reported 4,051,300 µV. These sequential
software samples were collected during active SSH/status work; they are not
simultaneous readings, an idle-current measurement, a gauge calibration or a
battery-capacity/endurance result. The unchanged 100% reading after this short
interval does not validate or invalidate the gauge by itself.

Additional private evidence is
`.local/diagnostics/neo5-battery.JREzc0bg/disconnected.txt` and
`.local/diagnostics/20260927T050240.984866Z/status.txt`.
After the owner reconnected USB and waited one minute, the 05:05:51 UTC
capture reached the same boot over USB and direct Wi-Fi SSH. USB was configured
at high speed, both USB/AC inputs reported present/online, and the battery
reported `Charging`. All six services remained active without restarts, no
units failed, kernel taint remained zero and there were no new kernel journal
entries since the baseline. Brightness remained 1, unblanked. The guard logged
valid/Charging at 05:04:26 UTC, completing its observed
Charging → Discharging → Charging sequence.

**The functional unplug/reconnect and status-transition checks passed.** The
electrical charging qualification remains open because of the voltage
discrepancy below; successful status transitions are not proof of appropriate
limits or accurate telemetry. Reconnection evidence is
`.local/diagnostics/neo5-battery.JREzc0bg/reconnected.txt` and
`.local/diagnostics/20260927T050546.954145Z/status.txt`.

## Charging-voltage discrepancy (NEO-10)

The reconnected snapshot reported `voltage_now=4254800` µV and positive
battery current of 220,000 µA. The guard's nearby sample reported 4,255,900 µV.
A separate read at 05:06:39 UTC reported `voltage_max=4200000` µV and
`voltage_now=4255900` µV. Configured `constant_charge_current` and its maximum
both read 1,200,000 µA; this is a programmed limit, not that instant's measured
current. The original installation had already reported the same maximum
current in [report 21](21-installed-hardware-baseline.md). No charger, ADC or
gauge setting was changed during these tests.

The largest observed voltage was 55.9 mV above the reported target. **This is
an unresolved software-measurement/configuration discrepancy, not confirmed
physical overcharge or an established driver bug.** `health=Good` is the
driver's limited PMIC status interpretation, not independent validation of
the cell or charge voltage. The owner has since identified an aftermarket
BL-5C advertised as 3.7 V / 1020 mAh; its specified charge limits and physical
voltage remain unverified. See [report 30](30-bl5c-battery-identification.md).

The read-only trace used the locked Linux 6.18.54 source and supplied AXP223
datasheet:

- `drivers/iio/adc/axp20x_adc.c` reads a 12-bit AXP22x battery-voltage value
  with a 1.1 mV/LSB scale. This matches the supplied
  [ADC table, PDF p. 28](<../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=28>).
  The live IIO battery channel subsequently read raw 3674 and scale 1.100000:
  their product is 4,041.4 mV, matching `voltage_now=4041400` µV in that
  unplugged capture. Agreement between two interfaces to the same ADC does
  not independently establish ADC accuracy.
- `drivers/power/supply/axp20x_battery.c` decodes charge-target bits 6:5 of
  `AXP20X_CHRG_CTRL1`; code `10` maps to 4.2 V. The mapping agrees with
  [REG33H, PDF p. 40](<../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=40>).
  `voltage_now` converts the IIO millivolt result to microvolts. No conversion
  or target-decoding defect was identified in this bounded inspection.
- The MFD driver uses a regmap cache and does not classify this charge-control
  register as volatile. The target property is therefore a driver/regmap view,
  not an independent fresh bus read or electrical measurement. This does not
  establish that the cache is stale; no bypass or direct bus operation was
  attempted.

The owner unplugged USB again and confirmed the device remained running.
Wi-Fi SSH verified the original boot, external USB power offline and
`Discharging`. At 05:08:45 UTC, the direct battery reading was 4,023,800 µV
and -357,000 µA; the guard remained valid and had logged the second discharge
transition at 05:07:37 UTC. These are active diagnostic readings, not settled
open-circuit or idle measurements.

NEO-10 tracks the investigation and the replacement battery's model/label,
specified charge voltage/current and independent validation options. The owner
has no external measurement equipment. Extended charging/termination tests
are deferred while this discrepancy is unresolved; battery-only investigation
can continue. Do not apply a guessed ADC offset or change charger limits to
hide the observation. The owner subsequently supplied the BL-5C purchase
listing and its advertised specifications without opening the running device.
This answers the model/listing question, but does not establish the exact
manufacturer's permitted charging current or prove the advertised capacity.
The owner also confirmed that the pack has no printed manufacturer/brand;
it is an unbranded generic BL-5C. Repeat label requests are not a next step.

Additional private evidence in `.local/diagnostics/neo5-battery.JREzc0bg/`:
`charger-readback.txt`, `adc-readback.txt` and `disconnected-again.txt`.
The IIO probe found no optional `name` file for the PMIC ADC; its raw/scale
attributes were present and readable. The channel identity above comes from
the driver mapping, not that missing name attribute.

At 05:13:57 UTC, a further Wi-Fi read after pack identification reached the
same boot with USB power offline and valid Discharging monitoring. The gauge
reported 99%; the direct sample reported 3,993,000 µV and -347,000 µA. The
guard's separate sample was 4,022,700 µV. This confirms the gauge value can
change, not percentage accuracy or a discharge curve. Evidence is
`identified-pack-status.txt` in the same private directory; the check made no
charger or gauge writes.

The owner subsequently reported another brief USB reconnection and removal.
The guard journal recorded Charging at 05:20:29 UTC and Discharging at
05:20:39 UTC. At 05:25:25 UTC, Wi-Fi reached the same boot, USB power was
offline and monitoring was valid at 94% and 3,980,900 µV. The guard retained
PID 266 with zero restarts, there were no failed units, and the kernel had
zero taint with no new entries since the preceding check. This establishes
software continuity, not the electrical effect of the brief charge interval.
Evidence: `policy-postcheck.txt` in the same private directory.

## Installed battery-policy simulation

`task device:battery-check ROUTE=wifi` passed all nine battery test methods
on the running ARM system. The six main-loop methods cover fifteen scenarios,
in addition to three existing parser/policy methods. The installed guard's
SHA-256 matched the tracked production source:
`834c5b6c1b834b22752ec21ed7088fc8e1eea10f35cd164edaaac45fea42a6f0`.

The scenarios cover three consecutive low readings at the provisional 10%
boundary; suppression while charging or above the threshold; invalid and
missing readings; recovery that resets the observation count; delayed or
too-fast samples; atomic status publication; and retry after a rejected
shutdown request. Each run uses fake power-supply files, simulated time and
a temporary status directory. The shutdown command is intercepted inside
the isolated process. The real guard continues running and no actual
power-off, charger write or gauge change occurs.

The on-device run completed in 0.483 seconds. Evidence:
`.local/diagnostics/20260927T052409.864112Z/battery-policy.txt`.
The postcheck above confirmed the live service remained healthy. This
qualifies the installed software's simulated behavior; physical low-battery
shutdown reserve, percentage accuracy and charging limits remain open.

## Awake-idle baseline

`task device:idle-sample ROUTE=wifi SECONDS=600` now provides a bounded,
read-only measurement: one minute settling, then ten minutes of software
readings at ten-second intervals. It preserves the existing brightness and
CPU governor and checks that battery-only operation, Wi-Fi association and
valid battery monitoring continue. It stops sampling on changed conditions,
20% or lower reported capacity, excessive temperature or kernel taint. The
ordinary battery guard remains responsible for its existing shutdown policy.

The task records raw current/voltage, gauge percentage, temperature,
frequency, signal context and actual sample times. Its summary integrates
current and power over elapsed time. Estimates remain uncalibrated and
include an open Wi-Fi SSH connection, transmitted samples and the existing
battery guard. Host regression tests verify charge/energy units and
nonuniform sampling integration. A complete run is required before interpreting
its results; this does not establish true capacity or extrapolated endurance.

### First dim-screen run

The first run completed successfully on 27 September 2026. The temporary
service ran from 05:33:07 to 05:44:08 UTC, including its settling minute.
All 61 measurement samples covered 599.996 seconds on boot
`b82a951a-31a3-4e7f-b4db-69a4fc5aa894`. The owner confirmed leaving the
device alone for the requested interval.

Conditions remained constant: USB/AC offline, battery present and Discharging,
brightness 1/31 with `bl_power=0`, Wi-Fi associated and `schedutil` active.
The guard remained valid with samples 5.34–6.95 seconds old; kernel taint
stayed zero. The largest sampling interval was 10.007 seconds and maximum
lateness was below 10 ms. Wi-Fi signal was -76 dBm initially and -77 dBm
at completion.

| Software-derived quantity | First run |
| --- | ---: |
| Time-weighted discharge current | 263.52 mA |
| Time-weighted battery power | 1.042 W |
| Sampled power range | 0.995–1.079 W |
| Integrated charge estimate | 43.92 mAh |
| Integrated energy estimate | 173.68 mWh |
| Reported capacity, measurement start → end | 92% → 90% |
| Sampled battery voltage range | 3.9413–3.9655 V |
| Sampled temperature range | 38.394–39.852 °C |

The readings provide an initial comparison point for this particular awake
scenario, not a calibrated electrical measurement. The two-percentage-point
gauge movement must not be used to infer pack capacity or reconcile the
integrated estimate. Frequency samples ranged from 240 to 1008 MHz; reading
them wakes software, so they do not establish idle residency or a persistent
minimum frequency. Weak Wi-Fi signal and the SSH/sampling observer remain
part of the recorded conditions.

The service exited successfully and was collected. Its reported CPU time
was 3.016 seconds with a 5.7 MiB memory peak; that accounts for this service,
not all SSH, driver or battery-monitor overhead. The postcheck at 05:45 UTC
reached the same boot with all six expected services active, zero restarts,
no failed units, zero taint and no new kernel entries since the run began.
USB remained disconnected and the guard remained valid at 90% Discharging.

Private evidence:
`.local/diagnostics/20260927T053302.905042Z/idle-sample.jsonl`,
`postcheck.txt` in the same directory, and
`.local/diagnostics/20260927T054541.151942Z/status.txt`.

A second run with unchanged settings is the next check, to assess repeatability
before changing display or power settings. This first run passes capture and
continuity checks; repeatability, endurance and electrical accuracy remain open.

## Remaining hardware gates

- Lightkey diagnosis and a successful repeat of affected controls.
- Local operation without an access point.
- Charging-voltage discrepancy and replacement-pack limits (NEO-10).
- Physical low-battery reserve, awake-idle repeatability/comparisons and separate
  readiness timings with their uncertainty.

Sleep remains disabled. A short power-button press still requests shutdown;
this session has not tested sleep, wake, the five-second boot aspiration or
week-long standby.
