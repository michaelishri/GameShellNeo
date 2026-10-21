# Socket state after the original SSH setup outcome

8 October 2026. NEO-151 integrates the Mac socket method from
[report 213](213-forwarded-socket-identity.md) into the actual forwarded SSH
connection path, behind an explicit option. Awake silent and greeting-only
controls pass, as do healthy USB/Wi-Fi controls and the existing two-ended packet
workflow. The original exception, first SSH state and first byte counters survive
observation and cleanup. The intermittent post-resume failure from
[report 210](210-rtc-wake-segmented-observer-validation.md) remains unresolved.

No sleep, reboot, display blanking, cable action or image change occurs in this
slice. Diagnostic.23 stays on the same boot at **PM11/0**. These are diagnostic
changes on the Intel host, not a driver fix or a performance improvement.

## Connection ordering

`remote.forwarded_device()` is shared by normal forwarded device connections and
the saved failure controls. With `SOCKET_STATE=1` and an active timing capture:

1. Run one baseline command through the already authenticated Mac SSH transport.
   Verify its worker/outer socket identity and absence of a pre-existing outgoing
   socket to the requested target.
2. Open the normal forwarding channel and start device SSH immediately. Nothing
   is inserted between forwarding-channel creation and the SSH exchange. The
   existing pinned keys, ten-second SSH deadlines and one attempt remain.
3. Record the original SSH state and forwarding counters, then close the setup
   timing span with its actual success or error. The exception is re-raised
   unchanged; error text and traffic payloads are not copied into metadata.
4. Collect a second worker snapshot before the caller explicitly closes the SSH
   client/channel. Save the original observations, rather than rereading counters
   after collection. The SSH library may already have retired a failed socket.
5. Close the caller-owned connection normally. Observer unavailability, output
   limits or write failures never introduce a connection retry or replace its
   original result.

The baseline and collection have separate `socket.prepare` and `socket.collect`
spans. In the live controls they take approximately 63–79 ms and 109–117 ms,
respectively. They add wall time and can perturb subsequent activity; these
instrumented totals are not evidence of improved SSH or resume latency. The two
synthetic failed setups each retain an approximately 10.02-second setup span.

Without the option, no snapshot commands run. Without timing capture, the
forwarding channel is also left unwrapped, preserving the existing normal path.
Direct Wi-Fi connections do not have a Mac forwarding worker to observe.

## Evidence and bounds

The Mac helper runs unprivileged from supplied Python source on stdin; it creates
no remote helper files. Its returned source digest is computed from those actual
bytes. The existing ten-second helper deadline, bounded child-process execution,
64 KiB output and 128-descriptor limits remain. A separate 15-second host watchdog
closes the command channel if request or response handling stalls. Only the
observer's own command/channel is affected.

Each capture admits at most 32 observed setups. Individual saved files are
limited to 256 KiB and created exclusively with mode 0600. The private
`socket-observations/` directory retains four implementation sources, numbered
observations and a manifest of hashes. The main timing capture retains its
original state and error-category events. Offline checking binds the saved first
states to those events, verifies ordering/source identities and recomputes the
socket candidate classification. Truncation, record-limit exhaustion and failed
writes cannot qualify a complete observation capture.

Snapshots retain PID/parent/start identity, the worker's outer transport,
descriptors, numeric endpoints, TCP state and available queue counts. Multiple
new endpoint pairs remain ambiguous; worker or outer-transport changes remain
unavailable. A single new pair is named `unique-worker-candidate`, with
`independently_confirmed: false`. It is not promoted just because an earlier
healthy experiment established that the method can work. No process command
lines, credentials, actual SSH greetings or traffic payloads are retained.

## Repeatable awake controls

```sh
task device:ssh-failure-smoke
task report:ssh-socket-state CAPTURE=.local/diagnostics/20261008T080822.256587Z
task device:ssh-trace-awake SOCKET_STATE=1
task report:ssh-socket-state CAPTURE=.local/diagnostics/20261008T081027.383413Z
```

The failure task creates one unprivileged Mac loopback listener at a time, on an
ephemeral port. One sends nothing; the other sends a fixed synthetic SSH greeting
and does not complete key exchange. Each accepts one connection, counts/discards
received data and exits when that connection closes. An independent 60-second
alarm bounds its lifetime even if the controller is lost. Both finish normally
in this run. No device or Mac network policy is changed.

The same production forwarding/authentication code connects to these peers with
its unchanged timeouts. The task then checks real USB and Wi-Fi connections and
compares boot/PM state before and after. Independent peer endpoint records are
retained for the loopback controls; healthy controls retain the authenticated
GameShell's `SSH_CONNECTION` endpoint separately.

| Control | First API bytes sent / received | First SSH state | Post-setup socket |
| --- | --- | --- | --- |
| Silent loopback peer | 24 / 0 | No greeting, key exchange or authentication | Missing |
| Greeting-only loopback peer | 1,280 / 36 | Greeting received; key exchange and authentication incomplete | One established candidate; separate peer endpoint agrees |
| Healthy USB | 1,648 / 1,657 | Greeting, key exchange and authentication complete | One established candidate; GameShell endpoint agrees |
| Healthy Wi-Fi | 1,648 / 1,657 | Greeting, key exchange and authentication complete | One established candidate; GameShell endpoint agrees |

For all three surviving candidates, the snapshot reports zero send/receive
queue bytes. These are point-in-time queues, not the history of delivery. API
byte counts likewise are not TCP acknowledgments. The silent control is useful:
its retained peer record proves a connection was accepted, yet no outgoing
socket survives until collection. Thus **a missing snapshot cannot establish
that TCP never connected**. No endpoint is invented to fill that gap.

The existing awake packet workflow also passes with the option enabled. All
seven setups (USB discovery plus three USB/Wi-Fi pairs) have successful original
SSH outcomes and unique worker candidates. Packet validation passes and matches
four USB greeting flows at both ends. It does not silently promote packet-flow
identity using the new candidate records. Both the failure-control capture and
the awake packet capture pass offline socket rechecking.

Twelve new focused regressions cover ordering outside the handshake, exact
exception preservation, immutable first counters despite later activity,
unavailable snapshots, full-disk behavior, default-off operation, the timing
prerequisite, failed tunnel opening, healthy setup, record/output bounds,
artifact changes and closing a blocked command request without retry. Existing
worker/ambiguity/parser and remote-route tests remain in the suite.

Full `task check` passes **764 tool tests** (one optional skip), **13 runtime
tests**, compiled current-selector/mount-guard checks, Bash syntax and ShellCheck.

## Final state and next boundary

Final inspection `20261008T081249.328214Z/inspection.json` passes full PM health
and validates the unused continuation on boot
`cc26703f-d9ef-4d71-8da1-9d766f3efdbe`, PM11/0. The continuation is still
`20261008T070741.360669Z/qualification-next.json`, retaining rehearsal
`e1afea155b864a79b04bb133496e4e26`. No sleep claim was consumed.

NEO-152 covers one separately attended RTC-wake qualification of this integrated
observer, after fresh health/admission and watching/listening readiness. It uses
the existing image and requires no card swap. If an SSH failure occurs, preserve
the original outcome, worker candidate and packet-segment limits before any
recovery action. A successful next sleep would qualify the new observation path,
not resolve the earlier intermittent cause. Do not repeat sleeps merely to
provoke failure. Snapshot timing is not atomic, PID/start is not a persistent
kernel socket cookie, and packet gaps remain gaps. CPU retention and sleep
energy remain separate qualification work.

## Evidence identities

All capture paths below are inside ignored `.local/diagnostics/`.

| Artifact | SHA-256 |
| --- | --- |
| `tools/socket_observation.py` | `c1a0e0f352daeef670efb2464da56751419a912d9ba77f93ba981d589348c6a2` |
| `tools/forward_socket.py` | `817b833ac881f6dac3654f333c6941f7abf23c7723a6fc57ec63b3463bd49cd9` |
| `080822.256587Z/ssh-failure-smoke.json` | `a2190883c934394adc68d3684f1af21880cd47189c14f599ea81babbfa5c214a` |
| `080822.256587Z/socket-observations/index.json` | `5f7fafb8b8efee58a1863dd99d2a9811ca3365617309875c78da8bcb57e458b6` |
| `081027.383413Z/socket-observations/index.json` | `1b62e8ce281cb05c664615891005bc50d668bf6717ef1c9bacef260bb9d3dd2a` |
| `081027.383413Z/tcp-report.json` | `877c31adf87a7c40af786a75bd9c4fe36289201cb7231e606e97bab9fee9725b` |
| `081249.328214Z/inspection.json` | `0bd23ca55b2939849e15960b12fdba6b04c2a9161a36d66586fc8c2446236c8f` |
| `.local/neo151-final-admission.json` | `f1f788a2dcb43d95496a8bc0204d1d40f5e7e8c58e50b68f4e29440ff0356fb0` |

The two socket manifests hash their exact sources and numbered records. The
failure-control summary additionally hashes its runner, fixture and timing log.
