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
or exercised in this session. Event numbers must be rediscovered after boot.

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

## Remaining hardware gates

- Lightkey diagnosis and a successful repeat of affected controls.
- Nine more cold starts to reach ten for this candidate.
- Local operation without an access point, sustained CPU/memory/storage
  checks, frequency transitions and supervised orderly shutdown.
- Charging/unplugging and battery-policy hardware checks, timed awake-idle
  measurements and separate readiness timings with their uncertainty.

Sleep remains disabled. A short power-button press still requests shutdown;
this session has not tested sleep, wake, the five-second boot aspiration or
week-long standby.
