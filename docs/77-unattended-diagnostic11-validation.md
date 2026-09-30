# Unattended diagnostic.11 validation (NEO-55/56)

1 October 2026, Pacific/Auckland. The owner left the GameShell connected to
the awake Mac and authorized testing that required no physical input.
Diagnostic.11 remained on the installed Samsung DEV card. Observed PM,
button, cable and screen tests were left for the owner to attend.

This follows the [physical qualification](74-diagnostic11-pm-validation.md)
and [Wi-Fi source audit and awake comparison](76-wifi-resume-authentication-source-audit.md).
All device work used the saved tasks. Private logs remain under `.local/`;
network identifiers and credentials are not included here.

## Repeatable sequence

```sh
task device:wifi-recovery SECONDS=120
task device:stability ROUTE=usb
task device:battery-check ROUTE=usb
task device:check ROUTE=usb ACTIVE_COUNTRY=AU
task device:boot-cycles CYCLES=0
task device:pm-inspect
task device:keypad-inspect
task device:audio-inspect
```

Run the radio comparison to completion and restoration before the load test.
Keep USB connected throughout. `ACTIVE_COUNTRY=AU` checks the previously
accepted country announced by the owner's access point; it does not reconfigure
the radio or replace the saved NZ setting. `CYCLES=0` captures the current boot and verifies
both routes; it does not request a power cycle. The PM/keypad/audio inspections
read state without entering a suspend stage or playing a sound. The battery
check uses isolated simulated readings and shutdown calls against the
hash-verified installed module; it does not run down the actual battery or
request a real shutdown.

The stability task writes and flushes a new 128 MiB temporary random file,
verifies its SHA-256 through a direct read, then runs the saved five-minute
four-CPU/256 MiB memory workload with verification enabled. Its device-owned
unit has a time limit; sampled temperature at 80 C, kernel taint or loss of
configured USB stops the workload. It removes its temporary files and checks
that the boot identity has not changed. These safeguards are bounded software
observations, not continuous electrical measurements.

## Results

The radio comparison passed all four software reconnects, two minutes of
synthetic unavailable-network scanning, restoration of the original network,
and two minutes of connected observation. All seven independent Wi-Fi SSH
checkpoints reached the same boot. One expected firmware load and zero tracked
radio faults were recorded. Exact phase durations and limitations are in
[report 76](76-wifi-resume-authentication-source-audit.md).

The subsequent checks also passed:

| Check | Observed result |
| --- | --- |
| Storage | All 134,217,728 bytes read directly and matched the written SHA-256. |
| CPU/memory | Four CPU workers and one 256 MiB memory worker passed; zero failed stressors, process exit 0, approximately 300 seconds each. |
| Temperature | 40.824 C before storage; maximum sampled 60.588 C; 49.734 C at the final recovery sample. |
| CPU recovery | Final recovery sample at 120 MHz with the original `schedutil` policy and 120–1008 MHz limits. |
| Cleanup | Temporary storage/load files removed; same boot retained. |
| Installed battery policy | All nine isolated tests passed against the hash-verified installed module. |
| Integration | All six groups passed: image identity, services, database/policy, journal ACL, disposable BPF enforcement and country state. |
| Final access/services | USB and independent Wi-Fi SSH reached the same boot; all seven checked services active with zero restarts; no failed units. |
| Final radio/kernel | One expected firmware load, zero tracked radio faults and kernel taint 0; kernel journal unchanged from the post-physical-test baseline. |
| Final power/PM | USB and AC present/online; valid battery estimate 100%/Charging at 4.1932 V; PM test `none`, async `1`, normal sleep masked. |
| Final keypad/audio | Original keypad devnum 2 and input identity, port quirks 0, persistence 1; both audio PCMs closed and both amplifiers Off. |

The PM inspection also passed the saved preflight validator. Its success counter
remained 12 and every failure counter remained zero, unchanged from the earlier
physical-test baseline: no additional PM stage ran unattended. As report 74
explains, that counter includes earlier incomplete qualifications and is not a
count of twelve fully accepted tests. Wi-Fi power saving stayed off and USB
polling stayed at its stock setting.

Private evidence under `.local/diagnostics/`:

| Capture | Directory/file |
| --- | --- |
| Awake Wi-Fi comparison | `20260930T123307.184935Z/` |
| Storage/load | `20260930T124022.796223Z/stability.jsonl` |
| Battery-policy simulations | `20260930T124640.308770Z/battery-policy.txt` |
| Integration | `20260930T124648.273219Z/integration.json` |
| Final boot and routes | `20260930T124707.215277Z/` |
| Final PM/input flags | `20260930T124707.157416Z/inspection.json` |
| Final keypad | `20260930T124707.101005Z/keypad.json` |
| Final audio | `20260930T124707.170634Z/audio.json` |

All captures use boot `3bf2069f-24a7-4e0b-b7d3-18d4048e3c7f`, kernel
`6.18.54-gameshellneo11`. Host transcripts are `.local/neo56-*.log`. No new
image, permanent policy change, radio-firmware reload or charging change was
needed for this work.

## Read-only preparation for the next Wi-Fi capture

The following command confirmed that both proposed EAPOL metadata tracepoints
exist on the installed image, including the interface `name`, `u16 protocol`
and packet `len` fields:

```sh
task device:exec ROUTE=usb -- sudo -n cat \
  /sys/kernel/tracing/events/net/net_dev_start_xmit/format \
  /sys/kernel/tracing/events/net/netif_rx_entry/format
```

Private output is `.local/neo55-eapol-formats.log`. This reads format metadata
only; tracing was not enabled and no packet content was captured. It confirms
that the next recorder can begin with existing tracepoints, without rebuilding
the image merely to expose these fields. Correct filtering, correlation,
cleanup and observed reproduction remain implementation/qualification work
under NEO-55.

## Indicator-light evidence

The supplied mainboard schematic contains **two separate LEDs**: D2/R23 is
connected to the AXP223 `CHGLED` output, while D30/R234 is on the separate `LED`
net. The installed device tree defines PB7 as a GPIO status LED, initially off.
This is source evidence from the published CPI3 design; it does not identify
which light the owner saw on their CPI v3.1 board.
[Mainboard schematic, page 6](../../GameShell/clockwork_Mainboard_Schematic.pdf#page=6),
[installed board description](../kernel/overlay/arch/arm/boot/dts/allwinner/sun8i-r16-clockworkpi-cpi3.dts).

The supplied AXP223 manual describes `CHGLED` as a charging/alarm output. Its
automatic charging indication ceases when charge termination is reached;
both documented indication types leave the output high-impedance when not
charging. An extinguished **charging** LED can therefore be consistent with
charge completion while USB power remains connected. It is not a general
USB-power-present indicator.
[AXP223 manual, page 24, sections 9.3.4 and 9.3.6](<../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=24>).

The observed light, configured LED mode and actual charger termination state
are still unconfirmed. A 100% software estimate or a later healthy input
snapshot does not prove what happened during the earlier rejected PM sample.
No charging register was accessed or changed for this investigation. Keep the
physical identification in `FOLLOW-UP.md` rather than interpreting the light
as evidence of either a driver fault or a harmless full-battery event.

## Limits and next work

These are awake functional and short stress checks. They do not measure battery
capacity, endurance, energy savings, actual sleep/wake, late/noirq safety or
long-term reliability. The earlier Wi-Fi recovery failure remains open even
though the awake comparison passed. NEO-55's next useful step is a saved,
bounded metadata recorder, followed by an explicitly owner-ready PM capture.
The known per-key audio-cue delay remains deferred at the owner's request.
