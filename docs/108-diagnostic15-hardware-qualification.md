# Diagnostic.15 hardware qualification (NEO-84)

3 October 2026, Pacific/Auckland. Diagnostic.15's flash, full readback,
owner-confirmed boot, integration and awake prerequisites passed.
One freezer, one devices and five late/noirq stages passed, with owner-confirmed
normal display return. Country/control timeouts did not recur. One separate
suspended-transmit warning remains tracked under NEO-85.
Preparation and recovery provenance are in
[report 107](107-diagnostic15-preparation.md); the driver change is in
[report 106](106-brcmfmac-regulatory-suspend.md).

## Card installation

The owner confirmed shutdown and placement of the Samsung DEV card in the Mac.
Fresh inspection found one external physical USB card at `disk16`, capacity
`64013467648` bytes, matching the intended 64 GB spare. The saved workflow ran:

```sh
task mac:status
task mac:inspect DISK=disk16
task mac:preflight
task mac:flash DISK=disk16
```

Preflight verified compressed/decompressed hashes and fresh target identity.
The mount guard was active, the volume was unmounted, and its attempted
automatic mounting was blocked during the write/readback. All `4294967296`
image bytes were written and read back with SHA-256
`3067fcbc9253ccc414669188832889e3a8c6f7bd4a90222e89ed367dc9513e50`.
The card was then safely ejected.

Image: `GameShellNeo-0.1.0-diagnostic.15-cpi31-3067fcbc9253.img`.
Flash evidence: `.local/diagnostics/20261002T130737.626743Z/flash-result.json`
and `flash.log`; host transcript `.local/neo84-flash.log`. Fresh status,
inspection and preflight transcripts are `.local/neo84-card-*.log`.

## Running baseline and awake prerequisites

The owner confirmed the normal login screen after reinsertion, with USB
connected. USB and independent Wi-Fi SSH reached the same boot,
`7d89da56-9678-41ec-ae6b-168b2e00c3e8`, running
`6.18.54-gameshellneo15` / `0.1.0-diagnostic.15`. The installed manifest records
patch 0020 with the expected SHA-256
`01afc0758ba3df6acf16cb36dc9bd1d77f1b0d1e87ece73dca8dc9bd238ddb4f`.

All seven inspected services were active with zero restarts, no failed units
and kernel taint zero. All six integration groups passed: image identity,
services, database/policy, journal ACL, BPF enforcement and country policy.
Provisioning remains NZ; the owner's accepted access-point announcement still
sets the Linux global domain to AU. The phy label is 99. These Linux labels do
not establish firmware country acceptance; that qualification remains open.

The radio firmware and NVRAM hashes match the locked inputs. The raw startup
log contains one expected firmware identity (`BCM43430/0`, version `7.13.53.9`)
and no country GET/SET or control-timeout error. The existing missing
board-specific filename/CLM/txcap messages remain visible; the generic pinned
firmware loaded successfully. No country setting or firmware was changed.

Initial PM success/failure counters were all zero, `pm_test=none`, async 1,
debug delay five seconds and only s2idle available. All five normal sleep
targets remain masked. The keypad and PEK input devices are present, and the
speaker card/mixer baseline was captured without playback. Brightness is 1
with the backlight on. Battery monitoring was valid at the early snapshot,
reporting 100%, Charging and 4.1888 V; this is neither capacity nor voltage
calibration. No charging policy changed.

The saved journal check ran ordinary `logrotate.service` and verified that
journald did not restart, the kernel history remained available and the
displaced-journal inventory did not change. Awake power-key ownership verified
the inhibitor and exclusive PEK device ownership, observed no key events,
verified logical release and returned ownership normally. No gesture was
tested. The same-boot RTC smoke check delivered one `RTC_IRQF | RTC_AF`
notification after **10.748 seconds** for its ten-second deadline, then restored
the original disabled logical alarm. Run ID:
`e4f65c3755f24de2844d1ff0fe645732`. This establishes awake alarm delivery only.

```sh
task device:pm-inspect
task device:journal-inspect
task device:exec ROUTE=wifi -- cat /proc/sys/kernel/random/boot_id /proc/sys/kernel/osrelease
task device:audio-inspect
task device:check ROUTE=usb ACTIVE_COUNTRY=AU
task device:journal-rotation
task device:power-key-smoke
task device:rtc-smoke
task device:exec ROUTE=usb -- sudo -n dmesg --time-format=raw
```

Private evidence under `.local/diagnostics/`:

| Check | Capture directory |
| --- | --- |
| PM/startup baseline | `20261002T131101.752003Z` |
| Initial journal | `20261002T131101.738980Z` |
| Audio baseline | `20261002T131236.744008Z` |
| Integration | `20261002T131238.516951Z` |
| Journal continuity/ordinary rotation | `20261002T131715.462021Z` |
| Awake power-key ownership | `20261002T131739.115922Z` |
| Awake RTC delivery/restoration | `20261002T131802.511019Z` |

The independent Wi-Fi identity proof is `.local/neo84-wifi-proof.log`; the
unaltered kernel baseline is `.local/neo84-kernel-before-pm.log`. Other host
transcripts are `.local/neo84-*.log`.

## First attended freezer and devices gates

After explicit owner readiness, the saved freezer task passed, followed by one
devices cycle with exclusive PEK ownership and keypad/Wi-Fi tracing:

```sh
task device:pm-test STAGE=freezer
task device:pm-power-key STAGE=devices KEYPAD_TRACE=1 WIFI_TRACE=1
task device:exec ROUTE=usb -- sudo -n dmesg --time-format=raw
```

| Stage | Run ID | Private capture |
| --- | --- | --- |
| Freezer | `006aba7bc40e4b20aba5478db24c63a1` | `20261002T132045.372673Z/cycle-1/` |
| Devices | `66a316f71b2d4e7593d5d6b929f6ec6d` | `20261002T132209.462832Z/cycle-1/` |

Both independent SSH routes verified the original boot after each run. The
success counter advanced from zero to two; every failure counter remained zero,
with no failed services or kernel taint. PM controls, input/backlight state,
Wi-Fi profile/power-save setting, CPU policy and charging policy restored.
The devices collection recorded one transient SSH channel timeout; the collector
retrieved the original run, without resubmitting the test.

The original keypad handle remained healthy, USB device number stayed 2 and
the input sysfs path was unchanged. There were no supply-disable events or
keypad disconnects. Both traces were complete and restored, with no nonzero
device PM callback result. PEK ownership returned normally with no key events.
Wi-Fi metadata captured four EAPOL transmissions and four receptions; both
network proofs passed after recovery.

The devices stage took 7.814 seconds including its deliberate five-second
debug hold. This is not real resume latency. Raw printk evidence in
`.local/neo84-kernel-after-devices.log` places that hold at 732.113142 seconds,
following suspend entry at 731.403373 seconds and before exit at 738.776401
seconds. There were **no country GET/SET errors, control timeouts, channel-query
errors or delayed control-frame warnings** in the new raw kernel-log interval.
This is an encouraging first comparison with diagnostic.14's devices result,
not proof that all radio faults or firmware country handling are resolved.

The owner confirmed the normal dim console and readiness for one late/noirq
cycle before it was submitted.

## First attended late/noirq cycle

`task device:pm-platform` passed for run
`2342ca12522a4630a7bdaa9d6ca02a44`, capture
`.local/diagnostics/20261002T132501.643883Z/cycle-1/`, transcript
`.local/neo84-platform-first.log`. Its stage duration was 8.026 seconds including
the deliberate five-second debug hold. The success count advanced to three,
all failure counters remained zero and both SSH routes verified the same boot.
One temporary no-route collection error was retained; only this run was
submitted and collected.

The complete trace qualified the ordered late/noirq/early boundaries with no
callback errors, no loss and restored instrumentation. RSB noirq resume
returned at ftrace time 909.619728 seconds, before PEK noirq resume began at
909.619791 seconds. These trace times must not be directly subtracted from
raw printk times. The original keypad handle, USB number 2 and input path
survived, with no disconnect or supply-disable event. PEK ownership returned
without key events. Wi-Fi metadata again recorded four EAPOL transmissions and
four receptions. Health and policy restoration checks passed.

Raw evidence `.local/neo84-kernel-after-platform-first.log` contains no country
GET/SET, control-timeout, channel-query or delayed-control-frame error in this
cycle. It does contain one **`xmit rejected state=0`** at 906.317645 seconds,
inside the debug hold starting at 904.704035 seconds and before RSB restoration
at 909.707188 seconds. Journal receipt placed this later; the raw times retain
its actual ordering. A network transmit still reached the suspended radio's
rejection path. The capture does not identify its packet or origin, and this
is not evidence of a country-request failure or proof that it is harmless.
It remains a separate driver-lifecycle investigation.

The owner confirmed normal console return and gave fresh readiness for four
further individually reviewed late/noirq cycles.

## Four-repeat comparison and final state

Each repeat used one invocation of `task device:pm-platform`. Its completed
result, traces, restoration and both-route proofs were reviewed before the
next invocation. The owner subsequently confirmed all four display returns
and the final brightness were normal.

| Repeat | Run ID | Private capture | Stage including 5 s debug hold |
| --- | --- | --- | --- |
| 1 | `f038964e30a94166b8bc047f20a3efdd` | `20261002T132946.438555Z` | 8.117 s |
| 2 | `5f273ee80081431eb80b386ec9571195` | `20261002T133129.537921Z` | 8.147 s |
| 3 | `53e8c8d438644fa9a4c280dbc43c1bef` | `20261002T133312.668492Z` | 7.861 s |
| 4 | `3546b0b33bf149faba900bff34b1dece` | `20261002T133456.248040Z` | 8.031 s |

Each capture is beneath `.local/diagnostics/<capture>/cycle-1/`, with host
transcripts `.local/neo84-platform-repeat-{1,2,3,4}.log`. Every trace qualified
late/noirq/early ordering, zero callback errors, no loss and full restoration.
RSB noirq completion preceded PEK noirq entry in each. All four original keypad
handles, USB numbers and input paths survived without supply-disable events;
PEK ownership returned normally. Each Wi-Fi trace recorded four EAPOL
transmissions and four receptions. No tracked radio error appeared in any
repeat's delta, including the earlier suspended-transmit warning.

There were transient collection failures while the USB route recovered:
channel timeouts in repeats 1 and 4, no route in repeat 2, and both in repeat 3.
They are retained in the captures. Every original run was recovered; none was
resubmitted. Both independent SSH routes then verified the same boot.

Final read-only PM/audio inspections and all six integration groups passed:

```sh
task device:pm-inspect
task device:audio-inspect
task device:exec ROUTE=usb -- sudo -n dmesg --time-format=raw
task device:check ROUTE=usb ACTIVE_COUNTRY=AU
```

PM successes reached **7**, all failure counters remained zero, and the full
initial policy/health baseline matched: boot/kernel, masks and PM controls,
USB experiments, retained supplies, services, taint, Wi-Fi profile/power save,
charging and CPU settings, input/backlight and radio hashes. Idle audio matched
its initial capture exactly. Final evidence: PM `20261002T133649.650248Z`,
audio `20261002T133649.639774Z`, integration `20261002T133743.621929Z`.
The raw log is `.local/neo84-kernel-after-repeats.log`.

## Conclusion and remaining limits

Against diagnostic.14's repeatedly failing country/control path, the new image
completed the same devices and five late/noirq comparisons without country
GET/SET, control-timeout, channel-query or delayed-control-frame errors. This
supports the fix on this board and boot. It is not direct observation of every
deferred request, firmware country readback, all brcmfmac transports, long-term
radio reliability, NEO-55 resolution or measured latency/energy improvement.

NEO-85 separately owns the suspended-transmit rejection. Initial inspection of
the locked `core.c` finds `brcmf_bus_change_state()` publishes DOWN without
stopping network queues, while `brcmf_netdev_start_xmit()` stops the queue and
frees the packet after observing a down bus. This is a concrete path to audit,
not yet a validated fix or packet-origin attribution. No live driver change,
warning suppression or retry was used in this qualification.

No actual sleep, wake gesture, physical keypad-input or cable-disconnection
test ran in this slice. Normal sleep remains masked and the diagnostic power
button still requests shutdown. NEO-84's build/install/debug comparison is
complete; the broader sleep and radio work remains open.
