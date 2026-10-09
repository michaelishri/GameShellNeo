# Awake validation of bounded kernel evidence

10 October 2026 (New Zealand; captures dated 9 October UTC). NEO-184.
The new recorder passes its first **awake hardware checks** on diagnostic.25,
kernel `6.18.54-gameshellneo24`. Fresh attended PM qualification remains open.
The owner is asleep: no tone, blanking, reboot, sleep, alarm or cable action
was performed. No image or card swap is required for these diagnostic helpers.

## What passed

The existing boot, `2170b296-d964-4d16-bdb1-c135b0e7b812`, still contains a
complete printk sequence beginning at zero. The initial USB inspection saves
1,660 records, sequences 0–1659, including the expected kernel-origin Wi-Fi
firmware identification. A Wi-Fi inspection validates the same checkpoint.
This uses the running kernel's records, without importing saved journals or
rebooting to replace the failed test's evidence.

An independent general-journal inspection still contains only 1,139 kernel
lines / 83,120 characters and lacks that firmware identification. The journal
storage policy validates. This demonstrates recovery of the required evidence
from the separate printk source; it does not establish why journal history
disappeared. No log retention setting, rotation or repair was performed.

The new repeatable awake smoke task submits one userspace/debug marker to
`/dev/kmsg`. It verifies the marker appears exactly once, at sequence 1660 and
priority 15, while remaining excluded from the kernel-only rendered text.
All original records and the initial anchor remain unchanged. The checkpoint
grows from 136,439 to 136,533 bytes. A final USB inspection validates the same
1,661-record checkpoint without another append.

The directory is root-owned mode 0700. `checkpoint.json` and `lock` are
root-owned mode 0600 regular files with one link each; the lock is empty and
there is no interrupted staging file. The smoke task verifies these properties
before and after the append, then independently verifies Wi-Fi SSH after its
USB collection. Both routes work.

PM statistics remain **53 successes / zero failures**, with all failure
counters zero. Software display state stays at brightness 1 / `bl_power=0`;
keypad identity, PM controls, charger configuration, USB state, CPU policy,
network configuration and service state remain unchanged across the smoke.
This is software-state evidence, not a new owner observation of the screen.

## Repeatable procedure

```sh
task device:pm-inspect
task device:pm-inspect ROUTE=wifi
task device:journal-inspect
task device:kernel-evidence-smoke
```

The [smoke runner](../tools/check-kernel-evidence.py) saves original before/after
snapshots, storage metadata, source hashes and the marker token in a private
diagnostic directory. It rejects an active diagnostic before marker submission,
holds the existing PM host lock and never retries an uncertain write. A failure
preserves the original evidence and cannot publish a successful summary. Its
one marker is a deliberate diagnostic write; the task does not clear logs or
configure hardware. Re-running it is unnecessary after a passing check unless
the collector or a relevant assumption changes.

## Evidence and validation

Captures are private under `.local/diagnostics/`:

| Capture | Evidence |
| --- | --- |
| `20261009T112039.960159Z` | Initial USB inspection and complete boot anchor |
| `20261009T112124.357675Z` | Wi-Fi inspection of the same checkpoint |
| `20261009T112221.494467Z` | Independent general-journal inspection |
| `20261009T112613.740266Z` | Awake append, protected storage and both-route proof |
| `20261009T112737.260085Z` | Final unchanged checkpoint and health validation |

The smoke's `after.json` SHA-256 is
`442637b6b97d4fd844ea5bbab34a56122d24556ad9e721ec03e2da5e634d620c`.
The final `inspection.json` SHA-256 is
`b2142cd7f3a48c91c0e45eb9ef76a4dfee0e013f92601ebdbab58fd40404a7c3`.
The initial anchor contains 1,660 records with digest
`150774f032096ebf16652e5f751db9d5162679f7fbb8c8e675387ca5fff252cb`.

Collector source remains
`4ab460c5d691b053adfc42254b0fb1025381fe41a4b8d2eb299e6900d41968d0`;
PM snapshot producer remains
`3b26d041132a32ef5542288b6afc6c33541a911dad1dd97735ab28929f9a61c7`.
The private `.local/neo184-awake-review.json` records the complete capture
hashes, source context and unchanged historical-result hashes. NEO-182's
original recovered battery result and failed preparation result are intact.

`task test:kernel-evidence` passes **39 tests**, including eight smoke-runner
tests covering marker provenance, state changes, unsafe/interrupted storage,
invalid input, uncertain submission, active diagnostics and failed route proof.
`task check` passes **16 runtime and 882 tooling tests**, with one existing
optional skip, compiled C checks and Bash/ShellCheck validation. The first
sandboxed full run failed five existing local-socket fixtures; the complete
rerun with local socket permission passed. Output is saved in
`.local/neo184-awake-full-check-unrestricted.log`.

## Remaining gates

This qualifies initial capture, ordinary append/readback, real record parsing,
protected storage and current-source awake health. Live ring-overrun,
interrupted-publication and crash-recovery behavior were not induced; their
coverage remains offline. End-to-end SSH task elapsed time is not a measurement
of collector overhead or energy.

NEO-184 remains in review pending fresh attended freezer, driver and five
late/noirq checks using the current sources. NEO-182 then needs a matching
60-second awake battery rehearsal and a separately observed actual battery
sleep, including original-result collection and independent Wi-Fi proof.
Historical journal-only records cannot authorize the new path. Keep the
60-second cap. Preserve any new failure before deciding how to recover.
