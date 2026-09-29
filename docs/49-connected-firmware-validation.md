# Connected A0 firmware validation

Date: **29 September 2026 NZDT**. Task: **NEO-30**. Target: owner's CPI v3.1,
diagnostic.5 / Linux `6.18.54-gameshellneo5`, with the 2.4 GHz hotspot connected
as recorded in [report 46](46-wifi-transition-and-scan-recovery.md).

## Scope

The [offline comparisons](48-a0-firmware-trials.md) established that the pinned
upstream May 2017 A0 candidate avoided the observed crash loop during short
scan windows. This separate test checks association and software reconnection
to an available AP, followed by original-firmware restoration. It does not
establish cold-start, sleep, AP-disappearance or energy behavior.

```sh
task device:wifi-firmware-connected SECONDS=120
```

Keep USB connected, the hotspot enabled and the Mac awake. Credentials remain
in `.env` and the unchanged device supplicant configuration. This task uses the
same binary/NVRAM/board/USB/normal-scan-policy preflight and pinned candidate
manifest as the observation-only firmware task. It leaves the original
firmware installed and does not change image provenance.

## Protocol and acceptance

1. Verify original-firmware association/address and a fresh independent Wi-Fi
   SSH connection through the Mac, with the pinned host key and same boot.
2. Load the exact candidate and require a new matching runtime identity.
   Verify candidate association/address and independent Wi-Fi SSH.
3. Four times: request a software disconnect; require an observed
   `DISCONNECTED` state; wait two seconds; request reconnection; require
   association/address and independently verified Wi-Fi SSH again.
4. Observe `SECONDS` of connected operation at nominal ten-second intervals.
   Require normal scan policy, unchanged credentials/NVRAM, same boot and
   continued association. Count firmware crashes and SDIO removals across
   candidate reconnection/observation, reporting reload events separately.
   Any such candidate event fails connected-mode acceptance.
5. Restore original bytes, file mode and a freshly loaded original identity.
   Verify original-firmware association/address and Wi-Fi SSH once more.

The host confirms all **seven** checkpoints. USB remains the control route;
it does not count as proof of Wi-Fi recovery. Device requests carry fresh
tokens, and the host rejects wrong boots, USB endpoints, stale tokens and
out-of-order phases. Acknowledgement occurs only after a fresh Wi-Fi SSH
session reaches the expected endpoint. Checkpoint times include polling,
DHCP and host verification; they are not precise radio reassociation latency.

The device restores in `finally` and through the bounded service's independent
`ExecStopPost`. Host verification failure stops the service and explicitly
invokes the restore helper, retaining failed evidence/helpers. If transport
is lost, the device-side timeout still bounds the trial. This needs a working
kernel/systemd and does not promise recovery from sudden power loss.

## Validation evidence

The connected-mode regression suite covers split JSON events, acknowledgement
ordering, failed SSH, wrong boot/endpoint/phase, stale tokens, and the need to
observe a real disconnected state before reconnection. Existing firmware
identity and rollback tests remain. An additional failure regression exercises
the actual trial's restoration when candidate association fails, including
original bytes and removal of the completed recovery record.
`task check` passed **13 runtime and 133
tool tests**, with one optional user-systemd test skipped; current-limit and
Mac mount-guard C checks, Bash syntax and ShellCheck passed.

Hardware capture: `.local/diagnostics/20260929T065409.211309Z/`.
`firmware-trial.jsonl` records device transitions; `wifi-ssh.jsonl` records the
independent host sessions. Runtime identity and unchanged hashes are the same
candidate documented in reports 47–48. The test runs on boot
`73a1cbd0-0b12-4137-bdb1-7965671bab5d`.

The complete trial passed. All four cycles observed disconnection before
reconnection. The candidate remained `COMPLETED` for all thirteen samples over
120.209 seconds; candidate reload, reconnection and observation recorded **zero
firmware crashes and zero SDIO removals**. These counts cover reconnection as
well as the timed observation; 120.209 seconds is the observation duration,
not the whole trial's duration.

| Independently verified Wi-Fi checkpoint | Device checkpoint duration |
| --- | --- |
| Original before trial | 3.446 s |
| Candidate initial association | 4.610 s |
| Candidate reconnect 1 | 4.471 s |
| Candidate reconnect 2 | 7.438 s |
| Candidate reconnect 3 | 4.455 s |
| Candidate reconnect 4 | 5.463 s |
| Original restored | 6.533 s |

Original firmware bytes and fresh runtime identity were restored, the final
Wi-Fi SSH checkpoint passed, and the helper was removed. Postcheck
`20260929T065751.494280Z/` found active services, no failed units, valid battery
monitoring at 100% while charging, and a configured USB link. The board still
uses the original firmware and normal scan-offload policy. USB experimental
policy verification `20260929T065751.422096Z/` also passed.

The candidate has now passed bounded scan, connected-operation, reconnection
and rollback tests on this board. Cold-start/image integration, sleep behavior,
long-term stability and battery effects remain unqualified; the candidate
manifest deliberately retains `qualified=false` for production adoption.
