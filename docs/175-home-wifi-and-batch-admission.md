# Home Wi-Fi restored and cable-batch admission

6 October 2026; capture timestamps are UTC. NEO-118 and NEO-119.

The owner returned home with the GameShell at its login screen and USB connected
to the Mac. After session network access was restored, USB SSH succeeded and
the saved Wi-Fi workflow applied the credentials in `.env`. Independent Wi-Fi
SSH reached the same boot, the transaction committed and cleanup passed.
The shared `.env` link remains intact. No reboot, image change, screen blanking
or sleep was performed during these checks.

## Access and credential update

The first USB status attempt failed locally with `Operation not permitted`
under the session's restricted network policy. No GameShell operation was
performed in that failed attempt. The owner restored access and requested a
retry; the saved commands then succeeded:

```sh
task device:status ROUTE=usb
task device:wifi-config
task device:status ROUTE=wifi
```

USB status capture `20261006T085032.610593Z` showed configured high-speed USB,
active services, zero failed units, zero kernel taint and disconnected Wi-Fi.
The Wi-Fi transaction capture is
`.local/diagnostics/20261006T085053.933532Z/wifi-change.json`, SHA-256
`02d56849272de1ee22dfa9ea2d82e7f704da7533b1022aca90a84ca568dbfaeb`.
It records `passed=true`, `committed=true` and `cleanup_verified=true`.
The subsequent independent Wi-Fi status capture
`20261006T085130.209089Z` also succeeds. Network names, passwords and addresses
remain in private configuration/evidence.

NEO-119 corrects the local address update for linked `.env` files. The active
worktree uses the main checkout's file through a symlink. Previously, replacing
the link path atomically would create a private copy in the worktree, leaving
the shared address stale and hiding later credential edits. Commit `3313069`
resolves/pins the existing target and replaces that target while preserving the
link. All ten Wi-Fi transaction regressions pass, including shared target
updates, private permissions and concurrent-edit rejection. The live update
confirms both the link and its intended shared target are preserved. The commit
is now pushed; ticket creation also succeeded after access was restored.

## Current boot and awake checks

| Item | Observation |
| --- | --- |
| Image | `0.1.0-diagnostic.20` |
| Kernel | `6.18.54-gameshellneo19` |
| Boot | `34483a13-9373-4ee3-8984-fd81a99bc5de` |
| PM counters | Success 0, fail 0; all failure counters zero |
| SDIO | Active/forbidden, control `on`, usage 2 |
| System wake policy | MUSB and both supply controls disabled |
| Display | Brightness 1, backlight power 0 |
| POWER policy | Diagnostic poweroff, idle-ignore; no retained owner/drop-in |
| Battery | Valid telemetry, 100%/Charging, 4.158 V |

The following saved checks kept the screen on:

```sh
task device:pm-inspect
task device:power-policy-inspect
task device:power-key-smoke
task device:rtc-smoke
```

| Private evidence beneath `.local/diagnostics/` | SHA-256 |
| --- | --- |
| PM `20261006T085129.139140Z/inspection.json` | `431c7ce6f0c2ed41c9e762169f0990b8d6d349209b87e2fa463338092ac23f1e` |
| Policy `20261006T085148.664581Z/before.json` | `6289495073af7662e4bfd0023a911e7f6eef5ccf2fabf5f56f68152091af605a` |
| POWER `20261006T085201.026907Z/result.jsonl` | `4389632fdcc707a3e94b62fe369c669b7b7b1d973587ef69c229031b6961e09c` |
| RTC `20261006T085223.182180Z/result.jsonl` | `ed3488ccc175be758ed8435b9ef47c64e10379fb1ff126c45d82259f23937428` |

The existing PM health/source validator passes. The POWER smoke result passes
with no input events, logical release verified, descriptor closed and ownership
handed back. Awake RTC run `08c0ddc43f9d405688f7e5c2551cd839` delivered one event
with flags `0xa0` after 10.888 seconds, with alarm restoration and trailing
cleanup confirmed. The RTC clock and charging settings were not changed.

## Next physical session

The [guided batch runner](174-guided-cable-sleep-batch.md) is ready for its first
hardware qualification. Fresh readiness has been requested for the seven-debug
preparation: one freezer, one driver and five late/noirq cycles, keeping USB
connected and all controls untouched, with long warnings before darkness.
No screen test starts before that response. The four alternating removal/
attachment steps follow separately, with each owner observation saved before
the next step. No card swap is needed.

This is a new boot. Old PM24/0 evidence, consumed one-shot baselines and earlier
rehearsals remain historical and cannot admit the new run. Awake access and
alarm delivery do not establish sleep recovery, charging during sleep, energy
savings or production power-button behavior. Normal sleep remains disabled.
