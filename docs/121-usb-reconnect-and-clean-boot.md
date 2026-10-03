# USB reconnect investigation and clean-boot recovery (NEO-94/95)

3 October 2026, Pacific/Auckland. One deliberate cable reconnect restored USB
SSH on the original post-sleep boot. A subsequent observed normal reboot restored
the ordinary diagnostic power-button policy. Both SSH routes and startup checks
pass; the owner confirms the dim console is normal. No additional sleep attempt
was submitted, and no driver correction or automatic USB-resume pass is claimed.

[Report 120](120-first-rtc-sleep-findings.md) preserves the original failed
RTC-sleep attempt. This report records recovery and distinguishes later Mac
sleep from that original failure.

## State when the owner returned

The owner confirmed the normal dim console, that the USB cable had been
reconnected since the prior session, and later that the Mac had slept. The
GameShell was still on boot `0dc9db12-dcb4-465d-853c-1a087d9af332`, kernel
`6.18.54-gameshellneo17`, with battery telemetry at 100%.

The saved Wi-Fi collector retrieved the unchanged failed sleep result and a
separate live snapshot. The board now reported UDC `configured`, `usb0` carrier
1, USB supply present/online, and the same bound gadget. This differs from the
original post-sleep `not attached` state. Because a cable reconnect intervened,
it is not evidence of automatic recovery after sleep.

Nevertheless, USB SSH through the Mac failed. The Mac-side read-only capture
showed:

- The GameShell's USB device enumerated at high speed, configuration 1.
- Its ECM interface `en8` and network service existed.
- `en8` reported `status: inactive` and had no IPv4 address.
- The route toward the board's USB address selected the Wi-Fi/default route,
  rather than the USB subnet.

Thus board-side `configured`/carrier alone was insufficient to prove the host
network link worked. No DHCP, service, route or gadget settings were changed.

## One controlled reconnect

After saving both sides' state, the owner unplugged USB from the GameShell,
waited five seconds, reconnected, waited thirty seconds and confirmed the console
remained normal. These are requested human timings, not measured physical-edge
latencies.

The new capture showed Mac `en8` active with its USB DHCP address and a route
through `en8` for the USB subnet. The saved collector then authenticated USB SSH
and retrieved the original result on the **same GameShell boot**. The original
failed result was not relabeled as passed.

This establishes one working cable-reconnect recovery. It does not establish
the cause of either the original sleep failure or the later inactive host link,
nor reliable automatic reconnection. There was no software rebind, driver reload,
DHCP renewal or route repair between the two captures.

## Mac sleep is a separate variable

The Mac's retained power history covers the period around the original test.
All times below are NZDT (`+1300`):

| Event | Time |
| --- | --- |
| Last recorded Mac wake before the original test | 2 October, 17:49:05 |
| Original GameShell RTC-sleep submission/return window | 3 October, approximately 16:14 |
| Next recorded Mac sleep | 3 October, 17:52:49, clamshell sleep |
| Later Mac clamshell sleep | 3 October, 20:16:35 |
| Latest recorded full Mac wake before this recovery | 3 October, 21:12:07 |

Mac sleep is a plausible contributor to the later host-side link problem. The
recorded timeline places it after the original GameShell resume failure, so it
does not explain that earlier failure on this evidence. Do not merge the two
conditions or declare a GameShell driver cause from the later host state.

Further reproduction should record both machines' state and confirm that the
Mac stays awake through the GameShell-only sleep experiment. Host sleep/wake
with the GameShell awake is a separate comparison if needed.

## Normal reboot and final state

Before reboot, inspection still found PM counters **8 successes/0 failures**,
no failed services, restored `pm_test=none`/`pm_async=1`, and retained effective
`HandlePowerKey=ignore`/`HandlePowerKeyLongPress=ignore` ownership from the failed
attempt. The owner gave fresh readiness to observe one normal reboot.

The existing `task device:exec ROUTE=usb -- sudo -n systemctl reboot` command
was submitted once. No ownership marker was manually deleted. Startup was
checked with `task device:boot-cycles CYCLES=0`, followed by the saved power-policy
and PM inspections. The zero-cycle command only checks the current boot; it
does not claim a physical power-cycle qualification.

Final boot: `4ffd75dc-2dae-4164-8bd2-90ad08ed1885`.

- Image/kernel remain diagnostic.17 / `6.18.54-gameshellneo17`.
- Startup checks pass, with both independent USB and Wi-Fi SSH proofs.
- Firmware identity, input devices, battery monitor and required services pass;
  no failed units or kernel taint.
- The owner confirms the normal dim login console after reboot.
- Effective short/long diagnostic power-key policies return to `poweroff`.
  The retained owner and ignore drop-in are absent on the new boot.
- Normal sleep remains masked. No real or debug sleep was requested on this boot.

This returns the device to its ordinary diagnostic behavior; the requested
product short-press sleep/wake and 2/8-second gestures remain future work.

## Saved workflow and evidence

Added a read-only host-side command:

```sh
task mac:usb-inspect
```

It uses `.env` and the existing pinned SSH connection, then saves interfaces,
the route to `GAMESHELL_USB_IP`, hardware ports, service order, USB device tree
and the last 100 logged Sleep/Wake/DarkWake transitions in a private diagnostic
folder. It does not change Mac network or power settings. Individual command
failures retain partial output and are reported in `summary.json`.

The final version ran on the Mac successfully; Python compilation, Taskfile
parsing and diff checks pass. No image rebuild is involved. Existing commands
provided GameShell collection, policy inspection, PM inspection and startup
validation rather than new bespoke remote scripts.

Private captures under `.local/diagnostics/`:

| Capture | Purpose |
| --- | --- |
| `20261003T082751.726492Z` | Original failed result and live board state over Wi-Fi |
| `20261003T083029.568952Z` | Mac interface inactive before prompted reconnect |
| `20261003T083257.131877Z` | Mac interface/address/route restored afterward |
| `20261003T083257.922802Z` | Original result retrieved over working USB on original boot |
| `20261003T083403.942817Z` | Retained effective power-key ignore policy |
| `20261003T083415.802270Z` | Pre-reboot PM state, counters and journal |
| `20261003T083649.435893Z` | Final Mac collector with filtered sleep/wake history |
| `20261003T083742.325912Z` | New-boot startup and both-route checks |
| `20261003T083752.833059Z` | Restored ordinary power-key policy, no retained owner/drop-in |
| `20261003T083855.204249Z` | New-boot PM state |

Reboot submission is saved in `.local/neo95-normal-reboot-submission.log`.
The earlier diagnostic record remains under its original run ID.

## Next investigation

NEO-95 remains in progress. The next useful instrumented comparison is the
GameShell's USB resume/session state plus ECM connection-notification delivery,
with matching host observations. MUSB already exposes state/interrupt/request
tracepoints in `drivers/usb/musb/musb_trace.h`; their availability and coverage
on this build need checking before preparing the next experiment.

The ECM implementation in `drivers/usb/gadget/function/f_ecm.c` separately
queues network-connection and speed notifications (`ecm_do_notify()`), and its
alternate-setting path calls `ecm_notify()`. This supplies a concrete path to
inspect when the gadget is configured but the Mac reports no link. It does not
establish a dropped notification in either recorded failure.

NEO-94 full sleep qualification and NEO-96 CPU-idle support remain open. Any new
sleep test needs current-boot qualification and fresh observation; the previous
boot's accepted debug sequence cannot be reused.
