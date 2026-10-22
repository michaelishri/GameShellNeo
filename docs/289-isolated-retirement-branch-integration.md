# Isolated retirement branch integration (NEO-205)

22 October 2026, Pacific/Auckland. The isolated native, ARM and real-kernel
qualification has completed. Production image inputs remain unchanged.

The branch review in report 288 found that merging prepared power-supply and
MUSB/Sunxi retirement work would silently add candidates to image builds.
The production input generator reads every `kernel/patches/*.patch`; there is
no checked-in active-patch manifest. The retained source branches are now
integrated with explicit offline candidate queues.

## Source and build boundaries

Patch 0037 for power-supply producer retirement is stored under
`kernel/candidates/power-supply-lifetime/`. Retirement patches 0038–0045 are
stored under `kernel/candidates/musb-retirement/`. Every patch retains the
exact bytes from its originating branch. Reports 222 and 226–231 remain the
historical implementation and qualification records; paths in those reports
refer to the checkout in which the original evidence was recorded.

`tools/kernel_candidates.py` names the two complete candidate profiles.
NEO-207 separately adds the wake/startup profile described in
[report 291](291-legacy-musb-source-integration.md); the complete production,
power and retirement manifest names/bytes remain identical after that addition.
Native source extraction uses the same basename ordering as the full queue.
KUnit and full ARM object builders replay explicitly selected bytes, recording
their hashes in the immutable source identity. Missing, duplicate, unknown or
already promoted candidate inputs reject rather than selecting an older tree.

The ordinary request-resume task still runs the 48-case production regression.
The explicit `test:musb-retirement-resume` task selects the retirement profile
and 52 cases, using its own work directory. Both paths share their verifier
and C fixture, with terminal-retirement cases enabled only for the candidate.
Default image-build gates remain production checks. Additional candidate Tasks
are explicitly invoked; passing them does not promote source into an image.

The complete power candidate has an explicit
`check:power-supply-lifetime-driver` ARM build; the existing ordinary
`check:power-supply-driver` continues to compile production source. Shared KUnit
artifact retention now keeps independently hashed binary/configuration/raw
results through one helper instead of duplicate implementations.

## Validation

The source under test is `057b50ee0d49c00bef859b322e713de0edb115f2`.
The production queue remains exactly 33 patch
names/hashes; source lock, image configuration, overlay and input generator
match main `5fe9ca2015493ff40072edd110174d4499a11891` byte-for-byte.

The following saved Tasks have completed; native counts also pass as ARM32
fixture binaries. Negative controls are deliberate broken-source variants that
must reject, not failed qualification attempts.

| Check | Result | Receipt SHA-256 |
| --- | --- | --- |
| Probe roles | 25 scenarios, including 17 successful retries | `c296d08062a8c299c98cbb0f8cc5579e2f3e2ec148532b88ff80765663ed99f9` |
| Core retirement and full ARM objects | 43 scenarios; project, host, dual-role, module and no-PM builds | `5c20bbd0edf402bfe4f39bee8bd3157bfdf608668ae18f7c0d00d9cb518a4bc5` |
| Production request-resume | 48 scenarios | `e748d8632a4b90148ed71db36cf6a47733ff71e6be812f290c8cb6c59615a174` |
| Candidate request-resume | 52 scenarios | `d77c4bc65b8c942834aa9994c0ad95f1eb115029b91b296d80cecd23db947ac9` |
| Extcon notifier and full ARM objects | 29 scenarios; board, module and TINY SRCU builds | `4cdbf20a818b19d8c804cbd4e45d77a19de135e1677a1e904918ce77a98f9451` |
| Power-supply candidate and full ARM core | 21 scenarios per ordering; two rejected controls | `f6d29836c1aa180add6ac8459541ab6ebbadf957c59ea4786454b6d91a159c29` |
| Sunxi owner | 240 scenarios; eight rejected controls | `52674518d6018bdf4049f5b40fdae238581b37af98858849feb0339ced483a26` |

The first five receipts are retained in `remaining-branch-integration` under
`.local/build/{musb-probe-roles,musb-irq-tests,musb-request-resume-tests,
musb-retirement-resume-tests,extcon-notifier-tests}/`. The last two are in
`remaining-extra-validation` under `.local/build/{power-supply-lifetime-tests,
sunxi-owner-tests}/`. The complete extra-validation receipt is
`.local/build/extra-validation-result.json`, SHA-256
`1e155217ec8bb507b954901a36a00140250d47d1bd15a1b1155bb8db1aacbdf9`.
Its 776 frozen tracked inputs, full source-tree digest, ARM object and config
hashes all verify. The power queue contains exactly 33 production inputs plus
the isolated power candidate. The complete ARM power object hashes to
`18a8123af5de64c7c7f937b4c0d30b22bc45c36f546b833f4b1ade45a20c356f`.

Independent native/ARM audit verifies 53 recorded native binaries, three ARM
fixtures, 53 reconstructed variants, twenty extracted-source hashes and final
generated headers. Both complete 97,300-entry immutable retirement source
trees rehash to
`670150a749f0974bb30c4aca40ed5de689c4c48e4b1991e378d322122c033c0d`;
their manifests contain 33 production patches plus eight explicit retirement
candidates. The audit aggregate in `remaining-branch-integration` is
`.local/build/native-validation-result.json`, SHA-256
`34c8b138dfa1d95523ea2123da9a3c944855816c0d262b47291e810f329e05ae`.
The older request-resume receipt format does not record original binary hashes;
the audit distinguishes its current binary snapshots from the original
source/input/result evidence, rather than inventing an execution identity.

Real-kernel qualification uses worktrees at the same frozen `057b50e` source. Each
accepted run retains a separate kernel, configuration, raw TAP log and JSON
result, rather than relying on a mutable Kbuild output directory.

| UML kernel fixture | Result | Receipt SHA-256 |
| --- | --- | --- |
| Power-supply lifetime, original and reordered | Four cases per ordering pass | `8c0e1d93e05e46e69a7fb712918a7cda715559cb3c04228f78c8d001fa3b205a` |
| MUSB restart | Seventeen cases pass | `6b72e18c055a62ff2e3058a55e2c11c52bd23f2a47c952cb915a16472758e09a` |
| MUSB IRQ retirement | Four cases pass | `2bc2ee84195b66e5ef0aaa1cf9066e3efe4119904e6ca0e0cf88a81b7c4a59e4` |
| MUSB work retirement | Eight cases pass | `dd924f381d13b778942e24376d446b1552ec41c1f9ef2e31a7cdcd519a5b5563` |
| MUSB runtime-PM retirement | Eight cases pass | `5a7972c4b73e1edccf8e63d5460acb3f69f25ff7f87db8d1994fb9423eecdb53` |
| Extcon provider, TREE/TINY SRCU | Ten cases per SRCU configuration pass | `84f7e2c3c604c3151822cd6ee7158fc84526bbe534695cbf09efa2867a8f397b` |

These UML fixtures use a single virtual CPU with KASAN/lockdep and controlled
interleavings through actual kernel locking, workqueue, timer, PM and notifier
helpers. Their receipts state which hardware callbacks and controller state
are modeled. They do not qualify complete controller removal, DMA, electrical
USB, board suspend or all backend producers. The separate four-CPU ARM callback
fixture is recorded in [report 290](290-managed-smp-runner-integration.md).

The original-order power fixture deliberately retains a device reference while
reproducing the old ordering; its pass is a baseline reproduction, rather than
safe-unregister evidence. The reordered run qualifies the selected core
producer correction under the fixture's real workqueue/kthread/completion and
device-teardown boundaries. Arbitrary external producers, SMP, live AXP unbind,
supplier graphs and energy remain outside that check.

The independent power-kernel audit revalidates all twelve input hashes, eight
retained artifacts and their scratch copies, both configuration identities and
all eight raw TAP/JSON results. Each complete source inventory has 97,302
entries. Original and reordered digests are respectively
`302a2c2d50398a340bec24c641553c34687c7769a53134e9cab4fb5152d8523b`
and `7bf2f96e847c7e898606e5294b54d675a49dac5ed54e2d5380814cf0c595eda1`.
The original queue contains production plus test gates; the reordered queue
adds only the isolated power candidate, and both gate patches reconstruct
exactly. Both managed runs exited zero with no OOM or stop request. The private
aggregate `.local/build/power-kunit-validation-result.json` hashes to
`2cce47fbfc3b54f513337750afb45703d6cf674eeea42dddc500615736fc69b0`.

PM and extcon first completed concurrently in `remaining-extra-validation` and
`remaining-smp-validation`. Their original receipts remain respectively
`81f8da656c3e78afc97767f957f9ebb3232830d8deb8ab135d55fe8c952a02e3`
and `042953624865f19d013d83d3824f22f41f974cab671cc42aea9237213824bf93`.
Exact source, queue, configuration and kernel identities were checked before
copying immutable source caches and Kbuild outputs into the original sequence
under the runners' locks. Accepted runs, result JSON, raw guest logs and
top-level receipts were excluded from the copy. The original sequence then ran
fresh PM, TREE and TINY guests and retained the new receipts in the table above. Both
`cache-seed.json` records remain in their respective build directories. The
parallel and repeated runs do not increase the 65 UML case/configuration
outcomes reported here.

Independent final audits re-admit all 65 outcomes from raw TAP and JSON,
verify every declared input and retained kernel/configuration/log/result,
rehash the complete immutable source inventories and reconstruct the exact
test-only patches. Each managed run records exit zero, no OOM and no stop
request. The six integration/validation worktrees have no active managed build
ledger. The private index at
`.local/remaining-branches/2026-10-22/final-kernel-validation.json` pins all six
final receipts, their independent audits and both cache-provenance records;
its SHA-256 is
`316b0d7ddd8e84f0dee4492b46b03cf41c875807a657faac50cb263f5d50c63b`.

Initial integration failures remain in `.local/build/remaining-check.log` and
`.local/build/remaining-test-musb-retirement-resume.log`: an existing unit
expectation still assumed the candidate's 52-case contract for the production
parser, and the first copied candidate runner used the production ARM output
directory. The shared verifier/fixture now explicitly selects its 48/52-case
contract and work directory. The authoritative successor checks above pass;
the original errors remain recorded. Candidate driver-patch bytes were not
changed to obtain these passes.

## Branch disposition and human-dependent work

Eight original branch tips are ancestors of the integrated result. Once final
qualification is accepted and main published, remove their local/remote refs
with expected-SHA guards, retaining their worktrees and ignored evidence.

| Integrated source branch | Original reviewed tip |
| --- | --- |
| `work/musb-callback-kernel` | `53923426a8b41d2d2a3fd46d701d6b81e4ddf829` |
| `work/musb-core-work-retirement` | `4d1a07a2c5fb1729ae425cb4f35d13c122574460` |
| `work/musb-irq-retirement` | `0e73b3a24542eed02cb3c1750402136c4f284063` |
| `work/musb-probe-unwind` | `d8a6899698514f0c89fe1629647e7c2c2a0c02e7` |
| `work/musb-resume-retirement` | `66e3b552ebd7930b2029ec493f1159db577ec7ed` |
| `work/musb-runtime-retirement` | `c21f64d85c2424eadaa5c93969ce7838d0c733c1` |
| `work/power-supply-unregister` | `989c1a15e70d135bd1b0ca2dbccda4761df1b882` |
| `work/sunxi-retirement` | `ec243d21973ebf9e1e8d1108bcbeeafcab0f23b1` |

The five older histories below are reconciled separately by NEO-207. Callback
0030 is already production source, and the Sunxi/extcon portions are mapped to
the isolated retirement profile. Unique wake 0026/startup 0029, tests, wake-error
classification and the historical audit are retained explicitly in report 291.
The history acknowledgement changes no tree content after that per-file mapping.
Their refs can be retired after final validation and publication as well.

| Separately reconciled source branch | Original reviewed tip |
| --- | --- |
| `work/musb-callback-lifetime` | `9f5e68c97621fa585dcc5293907e8f361a602e6c` |
| `work/musb-removal-lifetime` | `48af268846453062e205b1023ce39f782f2a7451` |
| `work/musb-startup-pm` | `2c1bf7d6333c0a6e31607275f98c09e8fb0d191f` |
| `work/musb-teardown-audit` | `666965f2b18a4dd42c7296c70c5be9d739abff2c` |
| `work/musb-wake-irq-policy` | `2b6e295cb16947fb12e892d525135883f2f73925` |

NEO-98/102 need a separately identified future candidate image, ordinary
startup checks and attended USB/wake/RTC qualification. Whole-kernel IRQ/PM
traversal, terminal wake-disarm failure and failed-power stop/removal design
remain software work. NEO-103 still requires matching-board function-driver
unbind/bind checks. NEO-106 retains caller/global accessor, PHY detector and
other-backend/DMA ownership, source masking and inaccessible-hardware software
work as well as full controller/producer/backend hardware qualification. These
are open parent scopes, rather than claims that every remaining task needs a
person. Wake/startup and retirement still need deliberate software composition
before any future combined image. A passing isolated candidate does not close
those parent tickets.

The current physical prerequisite is installation of the prepared diagnostic.26
clock-provenance card and matching awake evidence in report 272; NEO-192 still
blocks fresh PM tests. Card movement and the later cable/button/power/rebind
checks require the owner. No new image, live PM or device operation is part of
this integration. Preserve the untracked removal audit and all original
qualification/recovery artifacts. The source branch refs can be removed once
their reconciled histories are published; the parent tickets stay open.
