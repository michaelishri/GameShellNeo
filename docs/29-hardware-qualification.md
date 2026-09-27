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
latency or the five-second aspiration. **Two cold starts are now observed**
for this candidate; eight remain.

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
regressions and shell lint passed. The four-cycle workflow still needs its
physical batch test.

## Remaining hardware gates

- Lightkey diagnosis and a successful repeat of affected controls.
- Eight more cold starts to reach ten for this candidate.
- Local operation without an access point.
- Charging/unplugging and battery-policy hardware checks, timed awake-idle
  measurements and separate readiness timings with their uncertainty.

Sleep remains disabled. A short power-button press still requests shutdown;
this session has not tested sleep, wake, the five-second boot aspiration or
week-long standby.
