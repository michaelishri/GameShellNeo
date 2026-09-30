# Wi-Fi authentication delay after ordinary resume (NEO-55)

1 October 2026, Pacific/Auckland. Source audit of diagnostic.11 on the owner's
CPI v3.1. The source audit used saved evidence and source files without device
commands. A separate awake hardware comparison is recorded below; it restored
its temporary radio configuration and changed no driver, firmware or timeout.
The observed qualification run is documented in
[report 74](74-diagnostic11-pm-validation.md).

The evidence narrows the first failure to the interval **after association was
reported and before WPA security completion**. Later status-16 messages are
less specific than their wording suggests: this brcmfmac driver synthesizes
that status for several connection failures. They do not establish that the
access point sent an authentication-timeout response. The roughly two-minute
outage includes deliberate supplicant retry backoff; it is not a measurement
of two minutes spent resuming the hardware.

No root cause or corrective patch is established. A metadata trace of EAPOL
delivery and connection state is the next useful discriminator. Normal sleep
remains disabled, and additional observed PM tests wait for the owner.

## Inputs and provenance

- Kernel: the pinned Linux **6.18.54**, commit
  `1b357ecb321392158d507b04672ffee57bfa071d`, examined locally under
  `.local/sources/linux-6.18.54/`. Image local version:
  `6.18.54-gameshellneo11`. Source links below identify this exact upstream tag;
  the browser could not render kernel.org's source page, so the actual analysis
  used the already pinned local source, not a newer branch.
- Supplicant: the image inventory `.local/artifacts/packages.txt` records
  **wpasupplicant 2:2.10-24, armhf**. The matching Debian source files and all
  twenty listed Debian patches were retrieved into the private
  `.local/research/neo55-wpa-source/` directory. Relevant package patches alter
  scan cancellation and signal-change reporting, but do not replace the
  association timer, connection-failure backoff or nl80211 status mapping
  discussed here. [Debian package source](https://sources.debian.org/src/wpa/2%3A2.10-24/),
  [patch series](https://sources.debian.org/src/wpa/2%3A2.10-24/debian/patches/series/).
- Radio: the source lock retains BCM43430a0 firmware `7.13.53.9`, FWID
  `01-130000`. This audit examines the host driver and its firmware interface;
  it has no source for the firmware's internal authentication state machine.
  See [the pinned inputs](../build/sources.lock.json).
- Failed run: `19cad390d8e34367b3fc67afd3dbb39d`,
  `.local/diagnostics/20260930T120012.168539Z/cycle-2/result.json`.
  Radio journals: `.local/neo53-radio-recovery-journal.log` and
  `.local/neo53-radio-reassociation-journal.log`. These remain private because
  they contain network identifiers. This report publishes only timing and
  state information.

## What happened

Times below are journal/kernel monotonic seconds from the same boot. They
locate messages, not individual radio frames; logging and scheduling introduce
small differences between event execution and recorded timestamps.

| Time | Recorded event | Interpretation |
| ---: | --- | --- |
| About 512.7 | Resume boundary; locally generated disconnect reported | Ordinary PM callback processing finished; Wi-Fi still had to reconnect. |
| 512.865 | New association attempt | Reconnection began promptly. |
| 513.152 | Associated | The driver reported an association; WPA completion had not yet been reported. |
| 523.151 | Authentication timeout | Roughly ten seconds after association. |
| 523.167 | Local disconnect | Consistent with the supplicant's timeout handling. |
| 523.985 onward | Repeated `ASSOC-REJECT`, status 16 | Failed subsequent driver connection results; the underlying firmware event is absent from these INFO logs. |
| 525.885 / 535.783 / 556.368 / 586.839 | Temporary disable for 10 / 20 / 30 / 60 seconds | The client deliberately backed off between further attempts. |
| 647.620 | WPA key negotiation completed and connected | First saved successful completion, about 135 seconds after resume. |

Another successful connection was logged at 658.838. A manual reassociate
command was used during diagnosis; the saved logs do not establish that it
caused the first recovery. The failed 30-second postflight remains a failed
qualification cycle. Later passing cycles do not erase it.

The preceding successful PM cycle also logged `xmit rejected state=0`. The
failed cycle preserved the original keypad connection and process-memory
check, with no PM failure counter increase. Saved evidence showed one firmware
load and no firmware-crash, SDIO-removal or PM-underflow message. These negative
observations narrow the investigation but cannot rule out silent firmware or
bus errors. Evidence and limits: [report 74](74-diagnostic11-pm-validation.md).

## Three distinct meanings of “authentication failure”

### The first timeout is a userspace deadline

After the `Associated` event, `wpa_supplicant_event_assoc()` normally arms a
ten-second timer for the first EAPOL packet. On first EAPOL reception,
`wpa_supplicant_rx_eapol()` can replace it with another ten-second timer for
WPA-PSK completion. Fast-transition and handshake-offload paths have different
handling. Therefore the observed ten-second gap is consistent with a stalled
security exchange after reported association, but INFO logs cannot tell us
whether no first EAPOL arrived, a later handshake step stalled, or a required
driver event was missing. It is not proof that the initial 802.11 association
itself took ten seconds. [Association handling](https://sources.debian.org/src/wpa/2%3A2.10-24/wpa_supplicant/events.c/#L3359),
[EAPOL reception](https://sources.debian.org/src/wpa/2%3A2.10-24/wpa_supplicant/wpa_supplicant.c/#L5062).

The common timeout callback logs the timeout, requests deauthentication and
schedules another scan. The later backoff is also client policy:
`wpas_connection_failed()` counts repeated failures and eventually calls
`wpas_auth_failed()`, whose early durations are 10, 20, 30 and 60 seconds.
These match the saved trace. The logged reason is `CONN_FAILED`; there is no
evidence here that changing a previously working password would solve it.
[Timeout callback and retry policy](https://sources.debian.org/src/wpa/2%3A2.10-24/wpa_supplicant/wpa_supplicant.c/#L215).

### Status 16 is synthesized by this driver

The kernel enum names status 16 `WLAN_STATUS_AUTH_TIMEOUT`. In
`brcmf_bss_connect_done()`, **every unsuccessful completion handled while the
interface is CONNECTING receives that same status**. The function does not
copy an access-point status field from the firmware event into this result.
Callers include link-down during connection and `brcmf_is_nonetwork()` cases:
no-network events, unsuccessful SET_SSID, and unsuccessful firmware-supplicant
events. Those different causes collapse into the same public status.
[Status enum](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/linux/ieee80211.h?h=v6.18.54#n1760),
[failure mapping and callers](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/cfg80211.c?h=v6.18.54#n6476).

The nl80211 supplicant backend converts an unsuccessful CONNECT event into
`EVENT_ASSOC_REJECT` and preserves its status. Its event handler then prints
`CTRL-EVENT-ASSOC-REJECT`. The message is an API-level classification; it is
not an over-the-air packet capture. Establishing what the AP actually sent
would require AP-side evidence or an independent suitable radio capture.
[nl80211 mapping](https://sources.debian.org/src/wpa/2%3A2.10-24/src/drivers/driver_nl80211_event.c/#L459),
[event logging](https://sources.debian.org/src/wpa/2%3A2.10-24/wpa_supplicant/events.c/#L4690).

### `xmit rejected state=0` means a local packet was dropped

Zero is `BRCMF_BUS_DOWN`. `brcmf_netdev_start_xmit()` checks the bus before
handing a packet to the firmware; when down it stops the netdev queue, frees
that packet and accounts a transmit drop. The warning does not identify the
packet protocol. It cannot by itself distinguish EAPOL from ordinary data,
prove an SDIO electrical fault, or prove a firmware crash.
[Bus states](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/bus.h?h=v6.18.54#n45),
[transmit check](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/core.c?h=v6.18.54#n294).

The ordinary retained-power SDIO freezer deliberately transitions the data
worker from DATA to DOWN while frozen, then back to DATA on thaw.
`brcmf_bus_change_state(..., BRCMF_BUS_UP)` wakes stopped netdev queues.
Therefore the warning has a plausible normal-PM origin, and its occurrence in
a passing cycle matters. Whether a rejected packet contributed to the failed
handshake needs packet-type and timing evidence. The present trace does not
justify removing this guard, suppressing the warning or resetting the radio.
[SDIO worker](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/sdio.c?h=v6.18.54#n3754),
[bus-state recovery](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/core.c?h=v6.18.54#n1559).

## Ordinary suspend/resume source audit

Without a configured wake-on-wireless policy, cfg80211 leaves existing
connections before calling the driver's suspend callback. brcmfmac stops
scheduled scanning and active scans; its non-WoWLAN path disassociates ready
interfaces, waits for events and configures minimum-power consumption.
Its ordinary resume callback mainly restores WoWLAN-specific configuration
when that mode was active; it does not synchronously complete a new WPA
handshake. A zero PM callback result therefore does not establish that Wi-Fi
is usable. [cfg80211 PM](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/net/wireless/sysfs.c?h=v6.18.54#n110),
[brcmfmac PM](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/cfg80211.c?h=v6.18.54#n4165).

The board description retains Wi-Fi power during these debug stages and does
not advertise `cap-power-off-card`. The driver's retained-power path freezes
its worker, stops its watchdog and requests `MMC_PM_KEEP_POWER`; resume thaws
the worker. This fits the observed absence of removal and firmware reload.
These are ordinary device-stage tests, not validation of late/noirq or a real
power-off/reload path. [Board description](../kernel/overlay/arch/arm/boot/dts/allwinner/sun8i-r16-clockworkpi-cpi3.dts),
[SDIO PM callbacks](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/bcmsdh.c?h=v6.18.54#n1179).

There are source-level robustness gaps worth a separate, tested change:
`brcmf_ops_sdio_suspend()` ignores the return from `brcmf_sdiod_freezer_on()`;
failure to set host PM flags is logged without becoming the returned error;
`brcmf_sdiod_freezer_off()` ignores `brcmf_sdio_sleep(..., false)`'s return.
Those paths weaken the implication of “PM callback returned zero.” They are
**not evidence that these operations failed in this run**. Propagating errors
also requires correct rollback of freezer state, watchdog and wake setup;
adding a return statement alone is insufficient.
[Freezer operations](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/bcmsdh.c?h=v6.18.54#n816).

Patch 0012 changes Allwinner USB PHY detection work, while 0013 changes the
power-supply notification workqueue. Neither changes brcmfmac, SDIO, cfg80211,
supplicant, radio firmware or Wi-Fi DT settings. A source search found no
power-supply notifier consumer in brcmfmac; its SDIO data worker uses its own
ordered workqueue and manual freezer. This audit found no direct call path
from either patch to connection status 16. Shared scheduling and supplier
timing can still change, so source separation and subsequent passing cycles
do not establish causality or exonerate the patches. A controlled A/B would
be needed if future evidence points there.
[PHY change](../kernel/patches/0012-sun4i-usb-phy-suspend-work.patch),
[notification change](../kernel/patches/0013-power-supply-freezable-notifications.patch),
[SDIO workqueue](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/sdio.c?h=v6.18.54#n4476).

## Next discriminating capture

The next owner-observed test should retain the existing postflight deadline
and add bounded evidence, then stop on the first failed cycle. An awake
disconnect/reconnect comparison can check ordinary reassociation independently,
but passing it cannot qualify PM recovery.

1. Save and restore the supplicant log level. Capture one bounded DEBUG window
   locally, without enabling key display, then publish an allowlist of state
   transitions, timer changes, EAPOL direction/count and handshake step names.
   Keep network identifiers and packet/IE dumps private. `LOG_LEVEL` changes
   verbosity and optional timestamp reporting, **not key-display policy**;
   confirm that startup/debug settings do not enable key logging. It requires
   no supplicant restart or profile change.
   [Control interface](https://sources.debian.org/src/wpa/2%3A2.10-24/wpa_supplicant/ctrl_iface.c/#L2630).
2. Use existing `net:net_dev_start_xmit` and `net:netif_rx_entry` metadata
   tracepoints, after verifying their live formats. Their source exposes
   interface name, EtherType and length without payloads. Restrict them to
   `wlan0` and EtherType `0x888e` (EAPOL); align them with existing PM callback
   timestamps and supplicant state. This can distinguish “no EAPOL delivered
   to the host” from “host sent a reply but completion stalled.” A transmit
   entry records submission, **not successful radio delivery**. The source
   also permits tracing `net_dev_xmit` returns, but brcmfmac's local-drop path
   ultimately returns `NETDEV_TX_OK`, so that alone cannot prove delivery.
   [Network trace metadata](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/trace/events/net.h?h=v6.18.54),
   [brcmfmac receive/transmit paths](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/core.c?h=v6.18.54).
3. Record ordinary wiphy suspend/resume and return values if available. Avoid
   enabling every cfg80211 tracepoint: `rdev_connect` contains SSID/BSSID and
   some key-management traces contain sensitive material. The cfg80211
   control-port tracepoints are not a substitute for the network trace here:
   the examined brcmfmac path does not implement their transmit callback and
   passes received data into the normal network stack.
   [Wireless trace definitions](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/net/wireless/trace.h?h=v6.18.54),
   [driver operation table](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/cfg80211.c?h=v6.18.54#n5976).
4. If those observations still leave ambiguity, prepare a diagnostic-only
   kernel patch exposing numeric firmware event code/status/reason/flags,
   connection-state bits, bus transitions and rejected-packet EtherType.
   Exclude SSID, addresses, keys and frame contents. It should distinguish
   arrival from processing of firmware events and retain the original
   behavior. Add sleep/wake return-code observation before attempting error
   propagation. This can be implemented in open host-driver source without
   firmware source, and can explain which failure became public status 16.

The current resolved config has `CONFIG_DYNAMIC_DEBUG=y`, but
`CONFIG_BRCMDBG`, `CONFIG_BRCM_TRACING`, `CONFIG_KPROBES` and
`CONFIG_FUNCTION_TRACER` are disabled. brcmfmac's `brcmf_dbg()` calls compile
away without its debug/tracing options; generic dynamic-debug cannot bring
them back. Existing tracepoint availability must therefore be checked rather
than assuming a broad debug command will expose firmware events.
[Debug macros](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/debug.h?h=v6.18.54),
[Broadcom build flags](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/Makefile?h=v6.18.54).

Any saved recorder should own and restore its tracing/logging settings on
success, timeout and failure, retain trace-loss counters, and measure overhead
against an awake baseline. Do not shorten authentication timers, clear backoff
repeatedly, disable scanning safeguards, swap firmware or widen acceptance
deadlines to make this failure pass. The evidence currently supports improving
observability first; it does not select one of those behavior changes.

## Awake hardware comparison

After the owner left USB connected and authorized unattended testing, the
existing saved task ran once:

```sh
task device:wifi-recovery SECONDS=120
```

This uses the installed firmware without a module/firmware reload. USB is the
control route; seven separate Wi-Fi SSH checkpoints verify the same boot.
It performs four software disconnect/reconnect cycles, selects a temporary
synthetic unavailable network for two minutes, restores the original network,
then observes another two minutes connected. It does not enter PM or require
a cable, button or access-point action.

All phases passed on boot `3bf2069f-24a7-4e0b-b7d3-18d4048e3c7f`:

| Phase | Result |
| --- | --- |
| Initial connection | Independent Wi-Fi SSH passed. |
| Four software reconnections | All passed; recorded phase durations 7.532, 7.382, 4.347 and 3.304 seconds. |
| Unavailable network | 120.165 seconds; 13 scanning observations, no tracked radio fault. |
| Original network restored | Independent Wi-Fi SSH passed; recorded phase duration 3.289 seconds. |
| Connected observation | 120.199 seconds; every sample remained `COMPLETED`; final independent Wi-Fi SSH passed. |
| Cleanup | `passed=true`, `connected=true`, `configuration_restored=true`; original installed firmware unchanged. |

These phase durations include the helper's polling and host verification;
they are not precise over-the-air association or handshake timings. The
recorder retained exactly one expected firmware-load identity and zero
firmware crashes, SDIO removals or PM-usage underflows throughout.

Private evidence: `.local/diagnostics/20260930T123307.184935Z/firmware-trial.jsonl`,
`wifi-ssh.jsonl` in the same directory, and `.local/neo55-awake-recovery.log`.
The task is already documented in the [routine workflow](../README.md).

This supports ordinary awake recovery on the current network and image. It
does not reproduce the earlier resume failure, establish its cause, qualify
physical access-point disappearance, or validate real sleep or energy use.
NEO-55 remains open for the bounded, owner-observed capture described above;
the failed PM qualification and its original deadline remain unchanged.
