# Diagnostic.25: USB reconnects after repeated sleep

9 October 2026; evidence timestamps are UTC. NEO-174 is complete under NEO-108.
All four owner-assisted physical USB removal/reconnection cycles pass
after [five actual connected-USB RTC sleeps](235-diagnostic25-connected-sleep-repeatability.md).
Each removal returns to configured USB with an independent USB SSH proof.
The owner confirms completing the requested sequence and leaves USB connected.
Final USB, Wi-Fi and Mac checks pass on the same boot; PM remains 12/0.
This qualifies the bounded ordinary awake reattachment test. It does not enter
sleep, reboot, change network or charging settings, or investigate SSH transport
faults. Cable changes during sleep, battery-only sleep, Mac sleep, latency and
energy remain separate.

## Baseline and protocol

The unchanged candidate is diagnostic.25/kernel `6.18.54-gameshellneo24`, boot
`2170b296-d964-4d16-bdb1-c135b0e7b812`, source checkpoint `e28a1f9`.
The initial read-only PM capture at
`.local/diagnostics/20261009T061414.554320Z` passes the existing full health
validator, with PM12/0 and all four CPU s2idle counts at 5. Inspection SHA-256:
`4f087e853f37bed94f76ea499e0c9f0620be019147c58631a40ec2fb338d04a2`.
Independent Wi-Fi SSH succeeds. The initial `mac:usb-inspect` capture at
`20261009T061412.565613Z` collects all six read-only groups and sees GameShellNeo
in the Mac's USB tree. Saved preflight check:
`.local/neo174-preflight-validation.json`.

After these checks, the existing task ran once:

```sh
task device:usb-reconnects CYCLES=4
```

Capture `.local/diagnostics/20261009T061445.389811Z` records its explicit
`ready` event at `06:14:50.038641Z`, verifying the original boot, configured UDC
and USB SSH endpoint. Only then was the owner given the four-cycle sequence:
unplug at the GameShell for three seconds, reconnect for thirty seconds,
repeat four times and leave USB connected. The recorder uses nominal 250 ms
state sampling and saves state changes; each observed removal/configuration
pair must have an independent USB SSH proof before another removal is accepted.
Requested physical timing is not instrumented and is not plug-to-ready latency.

Private task logs are `.local/neo174-before-{pm,wifi,mac}.log` and
`.local/neo174-usb-reconnects.log`. The original recorder capture retains
`summary.json`, `usb-reconnects.jsonl` and `device-states.jsonl` when collected.

## Recorded sequence

The board trace contains nine ordered observations on the original boot:
initial `configured`, then four pairs of `not attached` and `configured`.
Sequence numbers are complete from 0 through 8. The host independently proves
USB SSH after each return, with accepted cycle numbers 1 through 4 and the
expected USB endpoint/boot identity. Each cycle's accepted observations match
the corresponding original board records. `summary.json` reports four requested
and four verified cycles, with `passed=true`.

The summary completes at `06:20:07.122201Z`. The recorder reports
`recorder_stopped` after retrieving its final trace, stopping the transient
service and removing its temporary capture on the board. No failed/cleanup-pending
event remains. The owner subsequently confirms completion of the requested
four-cycle sequence.

Five `ssh_not_ready` observations remain in the original host log: one channel
opening timeout, one forwarded-channel failure and three `No existing session`
errors. The task log also retains SSH banner exception output. Each cycle
eventually passes its independent USB proof before the next removal is accepted.
No gadget restart, network repair, reboot or diagnostic resubmission was used.
This records functional recovery without assigning a transport root cause or
reviving the abandoned SSH-stall investigation.

The recorded intervals include the owner's unplugged wait, USB enumeration,
sampling and SSH verification. They do not measure insertion-to-ready latency.
Intermediate USB states can fall between samples;
`physical_timing_qualified=false` remains unchanged.

## Final health and host checks

The final `device:pm-inspect ROUTE=usb` capture at
`20261009T062033.067880Z` passes the existing full health validator. It retains
the same boot/image/kernel, taint, complete PM counters and controls, display
settings, input identity, charging and CPU policy, Wi-Fi profile/power policy,
service state, firmware/NVRAM identities, system-wakeup settings and ordinary
sleep masks. SDIO runtime usage remains 2 with unchanged active/on/forbidden
policy. All four CPU s2idle usage/time counters remain unchanged at five
entries per core; no additional sleep occurred. The initial kernel journal
prefix survives, with **zero new kernel journal lines**.

Independent Wi-Fi SSH succeeds. The final read-only Mac capture at
`20261009T062034.816582Z` collects all six groups, sees GameShellNeo in the USB
tree and retains the exact same captured sleep/wake history as the baseline.
No Mac network or power settings were changed.

Final task logs are `.local/neo174-after-{pm,wifi,mac}.log`. The combined saved
offline review is `.local/neo174-cable-review.json`.

| Evidence | SHA-256 |
| --- | --- |
| Recorder `summary.json` | `001a5eb2faf1d84aff8beba95adbf6c7f144e0f5e8897afc0a3ff034623f8834` |
| Host `usb-reconnects.jsonl` | `c9ea2212df24ee86099934f80982818b26247449ff07ef77ef6026720378ce42` |
| Board `device-states.jsonl` | `c3ff24e64d5c1a22231ffbdff598fe84bfd0c98b2679d962da495b296fcee2b2` |
| Final PM `inspection.json` | `b8dcdf0c0dbd3cef52b9feef54162c8b0bbbd84fa4ee959fb2ce7148f2aa8701` |
| Combined review | `69dec2d8f63f0636dfa6ca7aa5a1de293887b2002b8ebc7f6bc814472cf9a794` |

The saved tasks ran unchanged; this slice adds evidence and documentation only.
NEO-108 remains open for the remaining battery/cable profiles on diagnostic.25.
Prepare those separately with current-state admission and coordinated physical
instructions. These four passes do not prove that the deferred-restart race
occurred on this board or establish an energy/performance gain from its fix.
No test or recorder remains running; USB is left connected.
