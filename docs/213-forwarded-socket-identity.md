# Independently checking forwarded socket identity while awake

8 October 2026. NEO-150 establishes a working attribution method on the owner's
Mac and GameShell. The new saved tasks identify the SSH worker process, inspect
its TCP descriptors and confirm the outgoing connection against the GameShell's
authenticated endpoint record. USB and Wi-Fi controls pass. Two forwards in one
session are rejected as ambiguous; traffic from another session is excluded.

This prepares stronger evidence for the unresolved setup failure in
[report 210](210-rtc-wake-segmented-observer-validation.md). It does not reproduce
or fix that failure, and is not yet integrated into the sleep/failed-setup path.
All work is awake: no sleep, reboot, display or cable action occurs. The same
diagnostic.23 boot remains at PM11/0.

## Identity method

The first inspection establishes that the Mac's session has an accessible
`sshd-session` ancestor and TCP descriptors. The final helper works without Mac
root privileges. It runs as a command within the same authenticated outer SSH
transport that opens the forward. It walks at most eight ancestors to the SSH
worker, retaining PID, parent PID and process start time, but no command lines
or account names. It verifies the worker's identity again after inspection.

The helper compares `SSH_CONNECTION` with an established socket owned by that
worker. OpenSSH defines this variable as the client/server address and port
tuple. It is read separately on the Mac and on the authenticated GameShell;
neither value is substituted for the other.
[OpenSSH environment documentation](https://man.openbsd.org/ssh.1#SSH_CONNECTION).

The helper requests numeric, NUL-delimited TCP fields from `lsof`, selecting the
worker PID and TCP files together with `-a`. It retains file descriptors,
endpoint pairs, state and available queue counts. Missing queues remain unknown.
Two descriptors can refer to the same endpoint pair, so they do not automatically
mean two connections. These fields and selection semantics are documented by
[lsof](https://raw.githubusercontent.com/lsof-org/lsof/master/docs/manpage.md).

For one fresh outer transport, the smoke task:

1. Saves a baseline with no outgoing socket to the selected target.
2. Opens one ordinary `direct-tcpip` channel and saves the worker's socket state.
3. Authenticates the GameShell using the existing pinned host key and SSH policy.
4. Confirms that the GameShell's observed client/server tuple equals the one new
   established socket in that same worker.
5. Exercises ambiguity and unrelated-transport controls before cleanup.

The matching endpoint is now corroborated by the authenticated connection itself,
rather than just request timing. The worker's outer connection is also checked
directly. A changed worker/start identity or outer endpoint fails validation.

## Bounds and saved evidence

`tools/forward_socket.py` runs one read-only snapshot. Its commands share
a ten-second deadline; each command's combined output is capped at 64 KiB and
the parsed TCP listing at 128 descriptors. On failure, only the helper's own
child is killed and reaped. Unsupported fields/states, missing identities,
duplicate fields, command warnings and malformed listings fail qualification.
No traffic payload, password, SSH greeting or unrelated process table is captured.

`tools/check-forward-socket.py` uploads the helper into its own private temporary
directory and removes its files afterward. It does not run a persistent recorder.
Cleanup failure is recorded without replacing an earlier failure. Raw endpoint
records and source copies remain in ignored, private diagnostic directories;
the offline summary does not print addresses or ports. Credentials remain in
`.env` through the existing access helpers.

The device authentication block is extracted into `remote.authenticate_device()`
so the new harness and existing tasks use the same pinned key and timeout policy.
Forwarding type, destination, originator fields and connection timeouts retain
their existing values. The normal PM workflows gain no socket-observer hooks.

The evidence contains baseline/open/two-forward/other-transport snapshots, both
independent board endpoint records, source copies, file hashes and before/after
boot/PM readings. The offline checker repeats the endpoint comparisons and
ambiguity rejection. It rejects missing or changed artifacts, mismatched helper
sources, changed health identity and inconsistent board endpoints.

## Repeatable tasks and results

Keep the GameShell awake with USB connected and Wi-Fi associated. The Wi-Fi
address is discovered through USB; both cases use the Mac as the bridge. These
controls add temporary connections and read-only inspection commands, so their
timing is not representative of the uninstrumented connection path.

```sh
task device:ssh-socket-smoke ROUTE=usb
task device:ssh-socket-smoke ROUTE=wifi
task report:ssh-sockets CAPTURE=.local/diagnostics/<capture>
```

| Final capture | Route | Board endpoint | Two forwards, same worker | Separate transport |
| --- | --- | --- | --- | --- |
| `20261008T073655.877136Z` | USB | Confirmed | Ambiguity rejected | Excluded |
| `20261008T073749.024955Z` | Wi-Fi | Confirmed | Ambiguity rejected | Excluded |

Both final captures and their offline reassessments pass, with zero cleanup
errors. In the USB case the worker has two descriptors for the outer connection,
then three descriptors with one forward, four with two forwards, and three while
the unrelated transport is connected. The independent board records confirm
which endpoint belongs to the tested channel. Queue/state fields are snapshots,
not a continuous TCP history or proof of the earlier greeting's fate.

Earlier awake development captures `073133.762750Z` and `073245.281767Z` also
passed live controls, but predate retention of the separate board records and
the offline checker. They are not substituted for the final complete captures.

Seventeen new tests cover bounded subprocess execution, parser truncation and
malformation, IPv6 endpoint parsing, duplicate descriptors, ambiguous flows,
worker/outer identity changes, wrong board endpoints, source/artifact changes,
incomplete captures and preservation of an original error during failed cleanup.
Existing remote-route tests still check pinned keys, bridge cleanup, no fallback
and unchanged timeout behavior. Full `task check` passes **752 tool tests**
(one optional skip), **13 runtime tests** and compiled/shell checks.

## Limits and next work

This is an awake identity control, not a causal diagnosis or an optimization.
The snapshots are sequential live observations, not atomic kernel snapshots.
PID/start checks reduce reuse ambiguity but are not a persistent kernel socket
cookie. Unique new-flow selection is rejected if multiple forwards are present.
The successful control is independently corroborated only after authentication;
an unauthenticated failure cannot borrow that stronger claim automatically.

NEO-151 will prepare opt-in state capture around the actual failed setup path,
preserving the original SSH error and byte counters before cleanup. It must avoid
delaying the greeting or retrying the failed connection, retain unavailable or
ambiguous results, and pass awake failure/lifecycle controls before any separately
attended PM experiment. No repeated sleeps are needed merely to provoke failure.

Final read-only inspection `20261008T073837.588483Z/inspection.json` passes full
PM health and the existing unused continuation at boot
`cc26703f-d9ef-4d71-8da1-9d766f3efdbe`, PM11/0. No qualification claim is consumed.
The continuation remains `20261008T070741.360669Z/qualification-next.json`, with
rehearsal `e1afea155b864a79b04bb133496e4e26`. CPU retention, energy and the
intermittent post-resume setup failure remain unqualified/unresolved separately.

## Evidence identities

| Artifact | SHA-256 |
| --- | --- |
| Observer source | `cec1d45f4cb5790cb2f7ecff0b22eba27c16082022afae003378599ebc864972` |
| USB `socket-smoke.json` | `37b87ba4e4f73e13dd3de4589f49ba9a9e27fd5f4b4dc8365e0d4ae3c9e6b7fe` |
| USB `socket-report.json` | `887276968028cb1b713b355564251e5c1d6d8e30ce35298023737a6eec051a6b` |
| Wi-Fi `socket-smoke.json` | `b6697c72ab8fc2bfdcd0e5d0029c9d3f708248ea6c6f0b5870509246ba954917` |
| Wi-Fi `socket-report.json` | `f9ae166d50e87f27c2374221e2c32585b530c9750f8d7d376c3e8e1d4563f0ca` |
| Final inspection | `017cdd26f8778f1ed74619fa123463bfae642386fc7f2a6b625a6e9fb175b8a8` |
| `.local/neo150-final-admission.json` | `f1f788a2dcb43d95496a8bc0204d1d40f5e7e8c58e50b68f4e29440ff0356fb0` |

Each final `socket-smoke.json` also hashes its eight source/observation artifacts.
