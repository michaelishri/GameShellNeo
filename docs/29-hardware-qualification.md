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

## Remaining hardware gates

- Lightkey diagnosis and a successful repeat of affected controls.
- Visual backlight levels and repeated off/on. Initial sysfs brightness was
  1, maximum 31; these reads alone do not qualify visible brightness or off behavior.
- Nine more cold starts to reach ten for this candidate, and ten physical
  USB reconnections. Only the initial attachment has been verified so far.
- Local operation without an access point, sustained CPU/memory/storage
  checks, frequency transitions and supervised orderly shutdown.
- Charging/unplugging and battery-policy hardware checks, timed awake-idle
  measurements and separate readiness timings with their uncertainty.

Sleep remains disabled. A short power-button press still requests shutdown;
this session has not tested sleep, wake, the five-second boot aspiration or
week-long standby.
