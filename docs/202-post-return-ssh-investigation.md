# Post-return SSH failure: evidence and protocol-state diagnostics

7 October 2026; timestamps and capture names are UTC. NEO-140 completes the
saved-evidence investigation and adds host-only SSH state observations. The
underlying intermittent connection failure remains unresolved. No sleep,
reboot, display blanking, cable action or device-policy change ran in this slice.
Diagnostic.23 remains on boot `7cc788ef-2070-4ab9-887a-1af70c074713`, PM12/0.

## What the original evidence establishes

[Report 201](201-diagnostic23-connected-sleep-repeatability.md) preserves all
four successful actual sleeps and their collection errors. In cycle 4, the
distinct post-return collection attempt starts 1.111–1.732 seconds after the
recorded PM return. Mac SSH succeeds, followed by a successful device tunnel
opening taking 2.203 seconds. Device SSH setup then fails after 10.018 seconds,
before any collection command channel opens. Original result retrieval and both
independent route proofs subsequently pass without a physical reconnect.

A read-only capture retrieves 3,098 journal records spanning device monotonic
2038.677–2481.216 seconds on the same boot. It includes the four sleep intervals.
The relevant cycle-4 sequence is:

| Device monotonic seconds | Evidence |
| ---: | --- |
| 2427.097815 | Original sleep result samples return from PM |
| 2427.199409 | networkd journal receives `usb0: Gained carrier` |
| 2427.389006 | Previous per-user manager has stopped |
| 2440.896868 | An SSH session logs connection closure with `[preauth]` |
| 2446.579515 | Following SSH connection accepts the provisioned public key |
| 2447.136832 | New per-user manager starts |
| 2448.542348 | Manager reports startup complete in 1.147 seconds |

The preauthentication closure is 13.799 seconds after PM return, within the
host failure-end bracket of 13.681–14.303 seconds. It is a strong temporal match;
the host trace did not record the Mac's forwarded source port, so it cannot
independently prove socket identity. There is no successful authentication or
session-opening entry for that candidate connection. The next accepted
connection precedes its user-manager startup, as expected. The evidence places
the failed attempt earlier than the session-opening delay addressed by legacy
PTY removal; it does not rule out CPU scheduling or other system load.

Journal receipt timestamps are not exact network-ready times. In particular,
kernel messages buffered during suspension arrive together after resume;
their journal receipt times must not replace the original kernel trace's PM
timestamps. Host/device alignment remains subject to report 201's clock bounds.

The captured USB trace contains 90 MUSB ISR records between one and fifteen
seconds after return. That proves recorded controller activity, not correct
delivery of a particular SSH packet. Gadget request filters select endpoint 0
or lengths 8/16; they do not capture full Ethernet/TCP traffic. No packet-level
evidence establishes whether a greeting or key-exchange packet was delayed,
lost, or waiting in a host/device queue.

Effective SSH configuration retains `UsePAM yes`, `UseDNS no`, a 120-second login
grace period and `MaxStartups 10:30:100`. Per-source penalties are enabled with
a minimum accumulated duration of 15 seconds. The captured window has no
matching penalty/throttling/drop record. Neither configuration nor absence of
a log entry establishes a penalty as the cause or excludes every possible
server-side failure. No limit, timeout, PAM or retry setting was changed.

## Why the existing error is ambiguous

The actual host runs Paramiko 4.0.0 from `/usr/lib/python3/dist-packages/paramiko`.
Source inspection shows `SSHClient.connect()` calling `start_client(timeout=10)`
before obtaining/checking the server host key and authenticating. The synchronous
`start_client()` loop may finish at that deadline before initial negotiation is
complete. `get_remote_server_key()` then raises `No existing session` when the
transport is inactive or initial key exchange has not completed. Authentication
entry points can also raise that text on an inactive transport.

Consequently that message alone does not distinguish a missing server greeting,
unfinished key exchange or a connection closing later during setup. Cycle 3's
background banner error does not establish cycle 4's protocol stage. Local tests
with real Paramiko transports demonstrate both a silent peer and a peer that
sends its greeting but never completes key exchange; both fail connection setup.
The original failure is not relabeled or treated as fixed.

Inspected installed-source SHA-256 values:

- `client.py`: `77550056055ffde59ff95aa9c2c8e1c8c168e08119717dbeaf366d9289ac7df6`.
- `transport.py`: `06e3b7022d1a684eb5ad0e62fd667b63e658849aacc48665d1b5c3c22e692ca5`.

## Reusable diagnostics

`tools/remote.py` now records an `ssh_state` observation immediately after each
Mac/device `connect()` returns or raises, before caller cleanup. The existing
`tools/host_timing.py` recorder emits only four Boolean-or-unknown fields:

- `banner_received`: a server SSH identification string has been observed.
- `initial_kex_complete`: Paramiko has completed initial key exchange.
- `authenticated`: the transport currently reports authentication complete.
- `active`: the transport currently reports being active.

`observed` says whether all four fields could be read. Missing or unsupported
state stays unknown, not false. Inspection errors cannot replace the original
connection exception. The observer never calls `get_exception()`, which would
consume transport error state. It does not record the greeting text, key
material, credentials, endpoints, commands, packet payloads or exception text.
No transport subclass, background callback, connection retry or timeout change
is introduced. Without a timing capture, observation is a no-op.

The fields are sequential reads of a live transport, not an atomic snapshot or
timestamped protocol milestones. A state recorded after an error may already
reflect connection closure. Interpret it alongside the enclosing failed span;
it is not proof of a driver or network cause. The offline report validates the
field types, SSH-phase ownership and uniqueness, and accepts older captures
without these events.

Existing saved tasks pick up the diagnostic automatically:

```sh
task device:ssh-timing CYCLES=3
task device:ssh-timing-report CAPTURE=.local/diagnostics/<capture>
task device:sleep-collect RUN=d83dfefb4ed643c48044b98a974a39e2 ROUTE=usb
```

The last command reads the original completed result; it cannot submit sleep.
PM/RTC helpers, their source hashes and the installed image remain unchanged.
No rebuild or card swap is needed for this host-only instrumentation.

The journal/configuration captures are also reproducible with existing tasks:

```sh
umask 077
task device:exec ROUTE=usb -- sudo -n journalctl -b \
  --since '2026-10-07 10:10:00 UTC' --until '2026-10-07 10:20:00 UTC' \
  -o json --no-pager -n 5000 > .local/neo140-device-journal.jsonl
task device:exec ROUTE=usb -- sudo -n sshd -T > .local/neo140-sshd-config.txt
```

Keep these raw files private. They contain connection/network details. The
journal and effective-configuration hashes are respectively
`7c407d816dc76264722bfcc5b7dee55f025d5c51671097b945a4c86e3b23ba25` and
`efe2ea34687e3b5d949e11b1479d4d36387a201c44dfec04697fd9059268d410`.

## Validation and next evidence

The focused timing suite passes 18 tests. New cases exercise unknown/failed
inspection, preservation of the original exception and timeout, observation
before cleanup, privacy, old-capture compatibility, silent and greeting-only
real peers, and successful authentication against a pinned host key. The full
`task check` passes 13 runtime and 657 tool tests (one existing opt-in skip),
both compiled host checks, Bash syntax and ShellCheck.

The awake run at `.local/diagnostics/20261007T104853.960901Z/` passes three fresh
USB/Wi-Fi pairs plus the initial USB discovery connection. All 14 Mac/device
SSH observations are complete and authenticated, with no timing error. The
same boot stays at PM12/0 throughout. Device SSH setup takes 0.358–0.374 seconds
over USB and 0.407–0.617 seconds over Wi-Fi. Initial USB command-channel opening
takes 1.923 seconds; subsequent USB openings take 0.223–0.259 seconds. These
awake observations do not reproduce or fix the sleep-related failure.

Awake evidence hashes:

| File | SHA-256 |
| --- | --- |
| `awake-ssh.json` | `4c89df8dacaa710fd037aee0adee071d76f397c63d21bb0d3388379b8f90d208` |
| `host-timing.jsonl` | `a44cc6e43297385a87dce6c4052ece1808283ed474e54c7303d09eced4d7ef94` |
| `host-timing-summary.json` | `e66ece551f743c8e64e1485226976cf42ae495bd2ab423066fc91acb4ad46be6` |

Final read-only inspection is
`.local/diagnostics/20261007T105001.182243Z/inspection.json`, SHA-256
`5ac43eae0ad3793f71c82871faea9028b7d4720951c114258f3ff1c7a7c34f39`.
It confirms the same boot, PM12/0 and brightness/backlight power 1/0.
Original-result collection at `20261007T105101.597008Z` passes with the same
device-content digest as report 201 cycle 4. Its host timing hash is
`bbc64f75ceaa72a6c04cc8841663c93113cdfea90b66a436d996926925435ba3`.
The raw result hash differs because read-only collection does not add the old
host route-proof fields; original device content is unchanged.

The next attended sleep can retain the protocol-state observation if the error
recurs, after fresh readiness and all current qualification/age gates pass.
If that still leaves ambiguity, capture bounded TCP connection metadata at both
ends with matching socket identities, rather than changing retries or declaring
a USB-driver fault. No continuation was consumed here, and no additional sleep
or physical observation is claimed. Root-cause and post-resume latency work
remain open in `FOLLOW-UP.md`.
