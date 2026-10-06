# Cable batch stopped before sleep: Wi-Fi transport timeout

6 October 2026; capture timestamps are UTC. NEO-118, supporting NEO-110/117.

The first guided batch passed its awake alarm rehearsal, then stopped during
the read-only preflight for its first actual sleep. No sleep command was
submitted, no cable action was requested after the stop, and PM remains 7/0.
The failed batch is preserved. Subsequent USB checks pass without intervention;
Wi-Fi access is intermittent and the radio reports −90 dBm, later −88 dBm.
Weak reception is a plausible contributor, not an established root cause.

## Original attempt

After the owner’s explicit readiness for one removal after ten seconds of
darkness, the saved command ran on unchanged diagnostic.20 / kernel
`6.18.54-gameshellneo19`, boot `34483a13-9373-4ee3-8984-fd81a99bc5de`:

```sh
task device:sleep-cable-batch-start \
  QUALIFICATION=.local/neo118-home-debug-history.json ATTENDED=1 CABLE_ACTION=1
```

Host checkpoint: `f1fbb7b`. Private batch directory:
`.local/diagnostics/20261006T091939.429678Z`; batch ID
`731324478f7d450880a1ff124859c55d`. The unchanged `batch.json` records
`event=failed`, current cycle 1, no completed cycles and no pending observation.
Its SHA-256 is
`ab0f597dace1a493d52a05bdbd22d28eda3d06cb3f87140763264dee86005ee5`.

Awake run `c70fc8a166e343dca9054598c3b4eef5` completed with both SSH routes
verified. Its original `cycle-1/awake/result.json` has SHA-256
`a929099a022758441c179802d000429d7fdb9bc64f3a2f62d86c1f996f192641`.
The RTC delivered one event, flags `0xa0`, after 30.056 seconds; IRQ31 count
advanced 1 to 2. Alarm, traces, controls and power-key policy were restored.
PM remained 7/0. Revalidation with the existing complete-result validator passes.

The next invocation entered `check-sleep-rtc.py:experiment` but timed out in
`helper.inline(client, '--inspect')`, before writing its `before.json`, uploading
a sleep worker or submitting a systemd unit. The SSH channel raised
`TimeoutError` while awaiting output under the existing 40-second read timeout.
The batch’s `cycle-1/sleep/` directory is empty. The original traceback remains
in `.local/neo118-home-cable-cycle1.log`. No timeout was increased and no PM
command was retried.

## Read-only investigation

Saved tasks used after the stop:

```sh
task device:status ROUTE=usb
task device:status ROUTE=wifi
task device:pm-inspect
task device:power-policy-inspect
task device:exec ROUTE=wifi -- /usr/sbin/iw dev wlan0 link
task mac:usb-inspect
task device:sleep-collect RUN=c70fc8a166e343dca9054598c3b4eef5 ROUTE=usb
task device:sleep-collect RUN=c70fc8a166e343dca9054598c3b4eef5 ROUTE=wifi
task device:sleep-connection-inspect ROUTE=wifi
```

Private evidence beneath `.local/diagnostics/`:

| Capture | Result |
| --- | --- |
| `20261006T092407.801316Z` / `20261006T092407.887175Z` | USB and Wi-Fi status pass |
| `20261006T092426.169065Z` | Full PM health validation passes; PM7/0, SDIO2, brightness1, original boot; no kernel entries added since the awake result |
| `20261006T092426.162463Z` | Original diagnostic poweroff policy, no policy owner or drop-in |
| `20261006T092610.134999Z` | All six Mac USB/network/history reads pass; latest recorded wake is 20:03:49 NZDT, before this 22:19 NZDT session |
| `20261006T092610.108225Z` | Wi-Fi collection fails during SSH establishment with `No existing session`; no device operation or original overwrite |
| `20261006T092746.465380Z` | USB recollects the unchanged awake original and restored live controls |
| `20261006T092825.403434Z` | Wi-Fi recollects that same original after the owner moved closer |
| `20261006T092933.559618Z` | Sequential Wi-Fi cable-state inspection passes |

The final PM inspection SHA-256 is
`26d17bd207bc6ed66ffc74d35866f357843326deb8a3056a7ecd4d8df7f71caf`.
Both independently recollected device originals have SHA-256
`ade47d0e2fcc8716fbcdbacc142b7260d0bda1f3c2c3a9eb7160989acb153770`;
the source-aware digest matches the initial awake result after excluding its
host-only route proof fields. Both live recovery snapshots show `pm_test=none`,
`pm_async=1`, and no power-policy, logind drop-in, sleep-control or console owner.
No recovery mutation was needed.

The first link query used `iw` without its absolute path and failed because it
was not in the SSH account’s PATH; the corrected saved task uses `/usr/sbin/iw`.
An attempted connection inspection concurrent with collection was rejected by
the local exclusive diagnostic lock before device access. Its capture
`20261006T092825.412598Z` and log remain preserved; the later sequential read
passes. These are distinct from the original transport failure.

The corrected Wi-Fi link reads report −90 dBm, then −88 dBm after moving closer,
with 1 Mbit/s receive and 2 Mbit/s transmit link rates. These are instantaneous
radio readings, not measured payload throughput. The owner confirmed that
distance or walls still remained. Moving both devices into the router’s room,
or using a nearby 2.4 GHz hotspot, has been requested before further sleep work.
Do not infer a firmware crash, driver defect or measured latency from these
observations: no new kernel fault was recorded, and the SSH path also includes
the Mac and tailnet.

## Continuation boundary

This failed batch cannot be continued with `next`, edited into a passing state
or assigned an invented physical observation. No actual sleep result exists.
The original seven-debug baseline remains unused: a saved directory listing of
its final run, `2382914498024e92b9b61d44b3119743`, contains the original
`started.json` and `result.json` and no `sleep-successor.json` claim.

Once the connection is dependable, recheck current boot/source/PM and cable
state. If the existing admission still passes, a new batch may use that
unconsumed baseline and must perform its own fresh awake rehearsal. Preserve
this failed session and request fresh described readiness before that new
actual cable attempt. Never restart an uncertain or previously submitted sleep.
No image, driver, firmware, charging setting or production sleep policy changed.

## Hotspot follow-up

The owner subsequently moved the Mac onto a nearby hotspot and updated the
shared `.env`. The saved `task device:wifi-config` transaction applied those
credentials over USB without rebooting. Capture
`20261006T093232.465181Z/wifi-change.json` records successful verification,
commit and cleanup; SHA-256
`743c40968a1f1d55ad6906bc951fbd8be05a8941964e976fda53d539639591f6`.
The shared `.env` symlink remains intact; credentials and addresses stay private.

Independent Wi-Fi status `20261006T093316.896734Z` passes. The link reports
−47 dBm and 72.2 Mbit/s receive/transmit rates, a substantially stronger signal
than the earlier −88 dBm reading. These remain link readings, not measured
throughput or proof of the original timeout’s cause.

Fresh PM inspection `20261006T093315.835270Z/inspection.json` passes the existing
health validator on the same boot, at PM7/0 and SDIO usage 2; SHA-256
`195fa4ab847f3ced5e14548ca77c89452e7beef2dea722c7bec620d28999cb6e`.
The existing receipt validator accepts the unchanged seven-debug history for
`usb-remove` against this snapshot, with no prior sleep in its lineage.

Wi-Fi collection `20261006T093348.980015Z` also retrieves the original awake
run and live recovery state. The result SHA-256 is again
`ade47d0e2fcc8716fbcdbacc142b7260d0bda1f3c2c3a9eb7160989acb153770`,
and its device digest matches the initial result. No retained diagnostic owners
are present. All these follow-up commands kept the screen on and submitted no
sleep. Fresh described readiness has been requested for a new guided session;
the original failed batch remains unchanged.
