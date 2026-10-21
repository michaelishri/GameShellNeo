# SSH greeting stalls: source audit and remaining evidence

8 October 2026. NEO-153 audits the SSH implementations behind the unresolved
post-resume setup failure in [report 210](210-rtc-wake-segmented-observer-validation.md).
The source identifies several distinct places where an established forwarding
channel can stop making progress before the inner SSH session is ready. It does
not identify which happened in that run. No sleep, reboot, display blanking,
cable operation, timeout change or network-policy change was performed. The
audit is complete; the underlying intermittent failure remains open as NEO-154.

The most useful finding is that `No existing session` is a **local session-state
check**, not a TCP diagnosis or an error sent by the GameShell. The existing
failure controls already demonstrate that different peer behaviours can reach
incomplete negotiation. The newly qualified byte/socket observations should be
retained during future already-planned diagnostics; repeated sleeps merely to
provoke a failure are not justified by this review.

## Source and running implementation identities

The read-only provenance capture is
`.local/diagnostics/20261008T085505.323861Z/ssh-provenance.json`.
It records the authenticated server identification, executable version and
binary hashes separately. They answer different questions: a version string
identifies an advertised release; a hash distinguishes a binary; neither proves
that a particular published source tree produced that binary.

| Component | Observed implementation | Source comparison used here |
| --- | --- | --- |
| Intel orchestration | Paramiko 4.0.0 | Installed `transport.py`, `client.py`, `channel.py`, `packet.py`, `buffered_pipe.py` and `common.py` are byte-identical to the upstream `4.0.0` files |
| Mac forwarding server | OpenSSH 10.2p1 / LibreSSL 3.3.6; macOS 26.5.1, build 25F80 | Apple `OpenSSH-354.120.2`, commit `2cc66abd7f8f1eb27d6a3074e476514194efe07e`, is a compatible published reference; binary/source equivalence is not established |
| GameShell server | OpenSSH 10.0p2 Debian-7+deb13u4 / OpenSSL 3.5.7; package `1:10.0p1-7+deb13u4` | Exact Debian source archives, with all 43 listed patches applied for review; the original archive already declares portable version `p2` |

Apple's repository `main` currently points to `OpenSSH-354.0.3`, while its
published tags include `354.120.2`; the latter's `version.h` declares 10.2p1.
Consequently the earlier `main` reference is insufficient as installed-version
provenance. This audit uses the pinned commit above.
[Apple published tags](https://github.com/apple-oss-distributions/OpenSSH/tags),
[pinned version declaration](https://github.com/apple-oss-distributions/OpenSSH/blob/2cc66abd7f8f1eb27d6a3074e476514194efe07e/openssh/version.h).

The source cache, URLs and SHA-256 values are preserved beneath
`.local/research/neo153-agent/`. `manifest.json` covers the upstream sources;
`apple-manifest.json` covers the pinned Apple files;
`installed-paramiko-comparison.json` binds the installed and reference hashes.
The comparison is source review, not a rebuilt-binary qualification. It cannot
expose unpublished vendor changes, compiler effects or the socket state during
the old event.

The Debian source archives are stored in `.local/research/neo153-debian/`, with
URL/hash manifests and the patch-application log. Archive sizes and SHA-256
values match the downloaded `.dsc`; its signature was not independently
verified. No source was built or installed. The `10.0p1` archive's own
`version.h` declares `SSH_PORTABLE "p2"`, and Debian retains that declaration
while adding its package suffix. Thus the package/binary version labels are
consistent with the inspected source; they do not indicate an unexpected local
replacement. Binary reproducibility remains unverified.
[Debian source package](https://packages.debian.org/source/trixie/openssh),
[Debian version patch](https://sources.debian.org/src/openssh/1:10.0p1-7%2Bdeb13u4/debian/patches/package-versioning.patch/).

Use the saved workflow for future inventories:

```sh
task device:ssh-provenance
```

It uses `.env` access through the Mac and USB, saves source copies, versions,
binary hashes and selected global policy privately, and verifies unchanged
GameShell boot, PM counters and display state. `sshd -G` dumps configuration
before loading host private keys; the ordinary Mac account suffices. This is
an on-disk global configuration view, without per-connection `Match` evaluation
or proof of the failed attempt's historical settings. The earlier `084616`
capture retains the Mac's unsuccessful `-T` check; `084818` records the corrected
`-G` check. Neither earlier artifact is overwritten.
[Pinned Apple configuration-dump path](https://github.com/apple-oss-distributions/OpenSSH/blob/2cc66abd7f8f1eb27d6a3074e476514194efe07e/openssh/sshd.c).

## Why the original error can precede a more specific timeout

`SSHClient.connect()` sets its transport's banner and authentication timeouts,
then calls `start_client(timeout=timeout)` before obtaining the server host key.
With the project's configuration the caller negotiation wait and banner wait
are both ten seconds. Supplying an existing forwarding channel avoids a new
client-side TCP connect; it does not skip SSH negotiation.
[Paramiko client setup](https://github.com/paramiko/paramiko/blob/4.0.0/paramiko/client.py#L409).

`start_client()` starts a separate transport thread and waits for completion or
its caller deadline. When that deadline wins while the transport remains active,
the method can return without initial key exchange being complete. The following
`get_remote_server_key()` raises `No existing session` when either the transport
is inactive or initial key exchange is incomplete. Thus the saved `active=true`,
`initial_kex_complete=false` combination is consistent with the caller reaching
its deadline before the background thread reports a banner error. It does not
prove that the forwarding socket closed.
[Paramiko negotiation and key lookup](https://github.com/paramiko/paramiko/blob/4.0.0/paramiko/transport.py#L717).

The transport writes its own identification before reading the peer's. Its
separate 15-second handshake timer starts only after identification parsing;
`banner_timeout` does not replace that timer. A failure before this point must
not be described as an authentication or cryptographic-algorithm failure.
[Paramiko transport sequence](https://github.com/paramiko/paramiko/blob/4.0.0/paramiko/transport.py#L2155).

The packetizer repeatedly handles short socket timeouts while collecting an
identification line, and preserves bytes after its newline for subsequent SSH
packets. Its read timeout begins per underlying read-wait invocation; partial
lines and pre-identification lines therefore differ from receiving no bytes.
The project-level caller deadline remains a separate bound. An unset parsed
identification alone cannot establish that no data arrived.
[Paramiko packetizer](https://github.com/paramiko/paramiko/blob/4.0.0/paramiko/packet.py#L388).

These details explain the **shape of the error**, not the earlier lack of
progress. Extending a deadline could change which error wins or hide an existing
stall; this audit supplies no evidence that it fixes the underlying problem.

## Forwarding confirmation and later data are different milestones

The pinned Apple `channel_post_connecting()` waits for socket writability and
checks `SO_ERROR`. A zero result changes the channel to open and queues its
confirmation. Later callbacks move data between the destination socket, channel
buffers and SSH packets. In particular, reading the destination depends on
channel state, available receive capacity and the remote window; writing it
depends on pending output and socket readiness. Confirmation therefore does not
mean that the GameShell's identification has been read and delivered to the
Intel host.
[Pinned Apple channel implementation](https://github.com/apple-oss-distributions/OpenSSH/blob/2cc66abd7f8f1eb27d6a3074e476514194efe07e/openssh/channels.c#L2101).

The inspected confirmation, socket-read/write and channel-data functions are
byte-identical between that Apple publication and the downloaded upstream
`V_10_0_P1` reference. `function-comparison.json` records the selected-function
comparison; it is not a claim that the complete trees or binaries are equal.

The Mac's server loop also suppresses channel packet generation during outer
SSH rekeying or when enough transport output is already pending. This is an
additional forwarding-layer branch after connection confirmation. There is no
evidence that rekeying or backpressure occurred in the failed attempt; the
fresh, small connections make ordinary accumulated bulk traffic a weak starting
hypothesis.
[Pinned Apple server loop](https://github.com/apple-oss-distributions/OpenSSH/blob/2cc66abd7f8f1eb27d6a3074e476514194efe07e/openssh/serverloop.c#L331).

On the Intel side, `Channel.send()` waits for its outgoing window before sending
channel data. `recv()` drains the channel's receive buffer and later credits the
window. Those operations are separate from the Mac's destination TCP socket.
Positive API byte counts are consequently not destination TCP acknowledgements;
an empty channel buffer does not identify which upstream stage is waiting.
[Paramiko channel implementation](https://github.com/paramiko/paramiko/blob/4.0.0/paramiko/channel.py#L683).

The buffer itself waits on a condition variable and can time out while remaining
open. Receiving such timeouts is compatible with normal library polling; it is
not evidence of TCP retransmission or failed application-level retry attempts.
[Paramiko buffered pipe](https://github.com/paramiko/paramiko/blob/4.0.0/paramiko/buffered_pipe.py#L138).

## What happens before the GameShell sends identification

SSH requires both sides to send their identification after establishing the
connection. OpenSSH's inspected `kex_exchange_identification()` writes its own
identification before reading the peer's; the server does not normally wait for
the client's first line before emitting its own. Its write result is still an
application/socket observation, not proof of delivery to Paramiko.
[RFC 4253 section 4.2](https://www.rfc-editor.org/rfc/rfc4253.html#section-4.2),
[OpenSSH identification exchange](https://github.com/openssh/openssh-portable/blob/V_10_0_P1/kex.c#L1235).

The server worker performs re-execution/configuration setup and a privilege-user
database lookup before reaching that exchange. It arms its login-grace timer
before identification; the inspected path passes an unlimited local read bound
to the exchange and relies on that process timer. Cryptographic negotiation and
user authentication follow identification. A stalled accepted worker is a
plausible distinct branch; user authentication latency is not a sufficient
explanation for an identification that has not yet arrived.
[OpenSSH worker initialization](https://github.com/openssh/openssh-portable/blob/V_10_0_P1/sshd-session.c#L1041).

The exact Debian worker additionally runs TCP-wrapper access checks **before**
identification and before arming the login-grace timer. Debian enables this
feature, and the installed worker links `libwrap`. The saved inspection finds
zero active lines in both `/etc/hosts.allow` and `/etc/hosts.deny`, retaining
their hashes without publishing their contents. No active wrapper-rule cause is
established. `UseDNS no` is an OpenSSH setting, not a blanket exclusion of
lookups by other pre-identification code. Any future attribution to this path
needs evidence from the failing worker.
[Debian wrapper patch](https://sources.debian.org/src/openssh/1:10.0p1-7%2Bdeb13u4/debian/patches/restore-tcp-wrappers.patch/),
[Debian build flags](https://sources.debian.org/src/openssh/1:10.0p1-7%2Bdeb13u4/debian/rules/).

There is also a pre-worker rejection branch. The listener checks connection
limits and source penalties after accepting a socket and before starting its
worker. A refusal logs its reason subject to rate limiting, attempts a short
plaintext refusal and closes the socket. The inspected implementation does not
deliberately hold a rejected connection silently for ten seconds. A refusal whose
data/close failed to reach the client remains possible, but there is no evidence
for it in the saved failure.
[OpenSSH listener admission](https://github.com/openssh/openssh-portable/blob/V_10_0_P1/sshd.c#L590).

Source penalties apply by address grouping and require an active penalty before
they refuse a new connection. Connections that close before authenticating can
contribute to later penalties; this is a reason to preserve admission evidence,
not a reason to disable the mechanism. Existing successful connections and
individual preauthentication closures do not, by themselves, establish whether
a later attempt was penalized.
[OpenSSH source-penalty checks](https://github.com/openssh/openssh-portable/blob/V_10_0_P1/srclimit.c#L259).

The installed Debian patch set already repairs mistracking of MaxStartups
process exits that could otherwise fill the admission slots. Recommending that
same patch would not change this version. Debian's later channel/IPQoS changes
also make a blanket upstream-tree equivalence claim inappropriate; this audit
does not attribute the old stall to them.
[Installed tracking correction](https://sources.debian.org/src/openssh/1:10.0p1-7%2Bdeb13u4/debian/patches/fix-max-startups-tracking.patch/),
[Debian patch series](https://sources.debian.org/src/openssh/1:10.0p1-7%2Bdeb13u4/debian/patches/series/).

Both current global configuration dumps report `LoginGraceTime 120`,
`MaxStartups 10:30:100`, `UseDNS no`, and source penalties with a 15-second
minimum activation threshold. These are present-day settings, not a saved
counter snapshot from the failure. The later same-peer/port closure in
[report 211](211-forwarded-ssh-observation.md) cannot be equated to login-grace
expiry just because it occurred about a minute after PM return. Its exact
request ownership and start time are still unverified.

The preserved 06:25:00–06:28:30 UTC journal interval was searched again: 914
whole-boot-window records and 40 SSH-service records. Neither contains matching
admission-limit/penalty/refusal, worker crash/fork/exec error or login-grace
expiry messages; both retain the same later preauthentication closure. These
are bounded negative searches, not proof those paths did not occur. Private
`.local/neo153-journal-categories.json` records the patterns' categories, source
hashes and matching metadata; original journals remain unchanged. It provides
no new ownership or greeting timestamp for the failed connection.

## Evidence ranking and the next useful discriminator

The older failure predates forwarding byte counters and bound worker snapshots.
Source analysis cannot supply those missing observations retrospectively. The
following branches remain hypotheses, in descending order of what the existing
diagnostics can usefully separate, rather than a claimed ranking of probability.

| Branch | Useful discriminator | What would still remain unknown |
| --- | --- | --- |
| The inner client has not completed its first identification write | First send-call and returned-byte counters, original SSH outcome | Whether scheduling, outer transport or channel state blocked progress |
| Client identification returned through the API but no peer data reached its receive calls | First byte counters plus worker socket candidate/queues and qualified packet segments | Which forwarding, TCP, device-worker or recording stage accounts for missing progress |
| Peer bytes arrived but complete identification or key exchange did not | Nonzero receive bytes and the preserved parsed-identification/key-exchange flags | Partial line, refusal, scheduling and later protocol stages require separately bounded evidence |
| Server admission rejected the connection | Correctly bound listener/worker evidence and original close/refusal observations | Absence of a log alone is insufficient, especially with rate limiting |
| The old SYN-only flow belongs to another attempt | Independent request/socket identity rather than temporal overlap | Historical port reuse and recorder gaps cannot be repaired by a successful later run |

[Report 214](214-ssh-failure-socket-observations.md) already validates silent,
identification-only and healthy awake controls. A silent accepted connection
can have no surviving socket at observation time. A surviving established
candidate with zero queues remains only a point observation. Those controls
must not be treated as a reproduction of the post-resume cause.

[Report 215](215-rtc-wake-socket-observation-validation.md) validates twelve
successful inner SSH setups and three earlier forwarding failures with the new
observer. It preserves the distinction between passing functional recovery and
the unqualified continuous packet recording. It does not demonstrate that the
older ten-second inner-session failure is fixed.

Keep the original failed setup as the primary result if the issue recurs during
already-planned diagnostics. First use the existing counters, socket candidates
and source-bound packet segments to select a branch. Only then add the smallest
missing observation for that branch. Avoid broad debug logging, more snapshots
between channel confirmation and identification, or changes to retries,
deadlines, windows or server admission policy without evidence of a defect.
This review establishes no driver fault, measured performance improvement or
sleep-energy result.

## Validation and handoff

The saved inventory passes against both running servers, including configuration
dump, executable hashes, linked libraries and rule counts. The GameShell stays
on boot `cc26703f-d9ef-4d71-8da1-9d766f3efdbe`, PM12/0, with brightness 1 and
`bl_power=0`. `task check` passes 13 runtime and 764 tooling tests (one optional
skip), both compiled C checks, Bash syntax and ShellCheck. Python compilation
and the documentation/whitespace checks pass.

Final `task device:pm-inspect` and offline admission recomputation validate all
seven debug checks and five original sleep records. The unused continuation
remains `.local/diagnostics/20261008T083013.709559Z/qualification-next.json`, with
rehearsal `e1afea155b864a79b04bb133496e4e26`. No new sleep qualification is claimed;
future tests still require current health, valid admission and fresh readiness.

| Private evidence | SHA-256 |
| --- | --- |
| `085505.323861Z/ssh-provenance.json` | `bddf8f720285e369e9ccdaf8da5263f08fc44eeb0e2c205ff3cbacbfe22f88ff` |
| `.local/neo153-journal-categories.json` | `5e0856bd347713a7b345347f41772154b16286682cd6eb51f3e2530920b907a8` |
| `.local/research/neo153-debian/manifest.json` | `5590595a7f11586b3c5ae9c0bf2f0b3182716a8145a18c99091f389c36b61b84` |
| `.local/research/neo153-debian/applied-patches.json` | `0eddfa3291a1a186b553e28e3bd07237473debcb6af91fe0a180b353a5ddd52b` |
| `085625.144296Z/inspection.json` | `e27b32c53b1bc442746a8ed6d9889bfafdf4546075272db0fb8c090745a6e9bc` |
| `.local/neo153-final-admission.json` | `5216e35e11f20db08166c70d320a27aa5244a50c04ede98147587ab5f60506bb` |
| `083013.709559Z/qualification-next.json` | `7c5798f3a2a56c63e943347861cdb213f5cd73bb3d1876289862c71f1fb48da6` |
| `.local/neo153-check.log` | `14aea5387e7f028e70e860df1a63dfb6539cda9c108fd5cec72ecd54f49d12c6` |

Abbreviated capture paths above are beneath `.local/diagnostics/20261008T`.
The source/evidence audit closes NEO-153; NEO-154 tracks the unresolved cause.
