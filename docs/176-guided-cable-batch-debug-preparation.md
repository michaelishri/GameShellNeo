# Guided cable batch: fresh debug preparation

6 October 2026; capture timestamps are UTC. NEO-118, supporting NEO-110/117.

Following the [home Wi-Fi admission](175-home-wifi-and-batch-admission.md),
the owner readied the seven-stage preparation. All seven automated checks pass
on diagnostic.20, with unchanged kernel `6.18.54-gameshellneo19` and boot
`34483a13-9373-4ee3-8984-fd81a99bc5de`. PM successes advance from 0 to 7 with
every failure counter zero; SDIO usage remains 2. USB is connected. No actual
sleep or cable transition has run in this new session.

After the batch, the owner confirmed **“Yes—warnings clear and all returns
normal.”** The next actual sleep requires its separately described cable-action
readiness. This preparation does not qualify the new four-cycle batch.

## Original debug results

The saved tasks ran one attempt at a time, with each original result reviewed
before the next submission:

```sh
task device:pm-power-key STAGE=freezer CYCLES=1
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
task device:pm-platform
# Four more separate platform invocations, each after reviewing its predecessor.
```

Host checkpoint: `a512e54`, branch `work/power-insertion-wake`. No diagnostic
source changed during the sequence. Each capture below is beneath the active
worktree’s private `.local/diagnostics/` and contains `cycle-1/result.json`.

| Stage | Capture | Run ID | Stage seconds | Final PM successes |
| --- | --- | --- | ---: | ---: |
| Freezer | `20261006T090010.461075Z` | `48445e83b27f4241b906fadc55c7425c` | 5.666 | 1 |
| Driver | `20261006T090248.610841Z` | `94464f77f2424eb68cae2a0029bf2323` | 7.720 | 2 |
| Late/noirq 1 | `20261006T090409.978248Z` | `3aa718e401824862bb4bef7888879ddb` | 7.776 | 3 |
| Late/noirq 2 | `20261006T090545.443456Z` | `5267e89544a34b888a11c4f71d06efb9` | 7.850 | 4 |
| Late/noirq 3 | `20261006T090813.873455Z` | `13789a816e2341658f61df06a65ef842` | 7.967 | 5 |
| Late/noirq 4 | `20261006T090928.552431Z` | `a3fbaeb49263475fb90be2d14127d4fd` | 8.771 | 6 |
| Late/noirq 5 | `20261006T091056.992354Z` | `2382914498024e92b9b61d44b3119743` | 7.849 | 7 |

All originals are complete/passed with both SSH routes independently verified
to the same boot. Process memory, untouched POWER ownership handback, restored
brightness 1/backlight power 0 and health checks pass. MUSB and both power-supply
wake controls remain disabled. SDIO stays active/forbidden, control `on`, usage 2.

All six driver/platform results retain the original keypad handle without
disconnect, poll/ioctl errors or held keys. Keypad and Wi-Fi traces are complete
and restored. Every platform trace contains the ordered late/noirq phases and
successful RSB callbacks. Each dark interval has recorded successful level-5,
1,000 ms warning playback, mixer restoration and idle amplifiers before entry.
The owner confirmed audibility and normal visible screen return after the batch.
The timings include the five-second debug delay and are not wake-latency or
energy measurements.

The host conversation was interrupted while collecting late/noirq 2. On
continuation its process handle was no longer present, but the task log and
original complete result independently showed success and both route proofs.
That attempt was reviewed and not resubmitted.

Each driver/platform collector retains one transient collection error:
`ChannelException: Connect failed` for the driver and platform 3/4;
`SSHException: No existing session` for platform 1/2/5. Some stderr logs also
contain a protocol-banner failure or `No route to host`. Collection recovered
the same original runs; no PM submission was repeated. The connection path
includes the Mac, so these errors alone do not identify a GameShell driver
fault or establish recovery latency. Preserve them for the existing transport
timing investigation.

Original result SHA-256 values, in table order:

```text
10aa77677578c64d1587298fdb6746b8684aba60b52dce4b44ba1624b31ae190
d1a03be5604b05270d2c7ecb40754de996a9f6ceea2521bb9875d0d989708f17
ae676421640bc1bafbbf92e8f6b19dff465def8da5e0ab4c0c025549623afe26
b7da963eae062559cf823f741bdb31b25316a1fd1679ea88c5d6e4b234a92a6a
77ef5ab638afc562812d6c714a748641e0498f00a8e05648f003e56fae4759a9
99c019cbf02f66a8b48a0e8407b80945dfa4156b42145cabd613a33258a78bb5
7ecbc6930def4efb7f04b1230dbd7806f51eab01e0da20c196129ba7aad49e38
```

## Preserved baseline and next step

`task check:sdio-ref-history -- --require-stable` accepted the seven explicit
original paths into `.local/neo118-home-debug-history.json`, SHA-256
`0f0b9b377e18e889cb8d4b5a7f8b9ddd87d055fd1b17e8301bf82e84983877f0`.
Final read-only `device:pm-inspect` capture
`20261006T091236.467660Z/inspection.json` passes the existing health/source
validator at PM7/0, SHA-256
`967c87fea7a92bfab9f22d8dd733fba89a0b33c3409049821446368fe2782df1`.
The saved receipt validator accepts the seven originals against that fresh
snapshot for `usb-remove`, with no previous sleep in this chain. This offline
validation did not arm an alarm, consume the baseline or submit PM.

After physical confirmation and readiness, use the [guided runner](174-guided-cable-sleep-batch.md):

```sh
task device:sleep-cable-batch-start \
  QUALIFICATION=.local/neo118-home-debug-history.json ATTENDED=1 CABLE_ACTION=1
```

The first invocation performs its own awake rehearsal, then exactly one
removal-during-sleep attempt. Its endpoint remains unplugged for the separate
owner report. Subsequent explicitly readied steps alternate attachment,
removal and attachment, preserving each original result and observation.
Do not insert an extra awake reconnect between steps or reuse consumed older
baselines. No card swap is needed. Charging during sleep, standby energy,
CPU retention and production power-key behavior remain separate work;
ordinary automatic/button sleep remains disabled.
