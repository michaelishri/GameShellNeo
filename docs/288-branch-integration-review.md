# Branch integration review and cleanup (NEO-204)

22 October 2026, Pacific/Auckland. The owner requested review of all open
branches, merging every ready branch and cleaning up merged references.
The review covers 36 local feature branches and their 35 remote counterparts;
there were no open GitHub pull requests at inspection.

## Result and fixed points

The ready cumulative branch `work/build-stage-ownership` at
`0f53a712bfe2c1206c0a89b5424c0dc5485168af` is integrated into main, originally
`9eb2710d0e4ec49473687195ca2bf1091eb46d3a`. It contributes 166 commits absent
from the original main, including hardware foundation work, current Razer Kiyo
tools, isolated Wi-Fi candidates and completed NEO-194 build ownership.
Seventeen original branch tips are already ancestors of this cumulative head.
Six earlier histories are acknowledged separately after implementation review,
so all 23 ready branch tips are ancestors of the result. Thirteen branches
remain open for the concrete integration issues below.

Merge `8175f3f` keeps main's expanded AGENTS.md handoff and the cumulative
README, Taskfile and complete current camera implementation/tests. These were
the only conflict resolutions. Before the documentation refresh, the entire
result differed from the cumulative source only in AGENTS.md. Merge `3e45cd3`
records the six superseded histories using the existing tree unchanged; it
introduces no old candidate or parking instructions.

## Already integrated histories

| Earlier branch | Implementation/evidence retained in the cumulative source |
| --- | --- |
| `work/awake-sample-clock` | `1e8e91b`, report 217: exact awake clock helper, 300-line tests and recorder/core fixtures; subsequent transport/identity changes retained |
| `work/battery-boottime` | `1e8e91b`, reports 133/217: exact guard/runtime tests/sample contract; later `e05981f` closes NEO-100 |
| `work/cpi-wfi-s2idle` | `1e8e91b`, reports 134/217: both patches, driver/source fixtures and configuration tests retained; disabled-build test adapted for enabled integration |
| `work/pm-inspection-route` | Patch-equivalent `c62c18e`, report 223; confirmed with `git cherry` |
| `work/musb-sleep-disconnect` | Patch-equivalent `01d89ff`, report 154; qualification in reports 155–163 |
| `work/cpi-wfi-integration` | Parent `8d8a2e4` already integrated; only unique tip `624c49d` parks NEO-108. Later `ad5becd`, `6b69e6f` and report 239 record authorized resumption and completion, so current instructions take precedence |

## Standards

The independent Standards review found one blocker in retained work:
**[P1] `work/musb-callback-kernel` conflicts with NEO-194's container lifecycle.**
`tools/check-musb-callback-kunit.py` supplies `--name`; `tools/kernel_qemu.py`
supplies `--name` and `-i`, and both expect later named-container operations.
Their saved Tasks run through the build logger, whose ownership shim rejects
these options and collects terminal containers itself. Bypassing the shim
would violate durable writer ownership. NEO-206 tracks adaptation and bounded
SMP regression checks before this branch is merged.

No hard Standards finding remains in the accepted cumulative merge. A possible
repeated retirement-helper smell in deferred source was not treated as a hard
violation. Ordinary foreground `--rm` fixtures on the power/Sunxi branches
fit the wrapper contract; their separate Spec blocker still prevents merging.

## Spec

The independent Spec review found one blocker in retained work:
**[P2] merging retirement candidates unchanged would promote unqualified image
inputs.** `tools/kernel-inputs.py` globs every `kernel/patches/*.patch` into the
production queue; a generated export manifest does not select active patches.
The power branch adds 0037 and the Sunxi branch/ancestors add 0038–0045 there.
Their reports 222/231 require a separately identified future image. NEO-205
tracks adapting candidate placement, native/KUnit/ARM queues and default build
checks while preserving diagnostic.26's exact inputs.

The older removal-lifetime branch also cannot be merged wholesale: callback
0030 is integrated, extcon/Sunxi 0031/0033/0034 are superseded as 0043–0045,
and 0032/0035 become test-only, but wake 0026 and startup 0029 remain unique
under NEO-98/102. Keep those branch references and the untracked removal audit.
No missing/incorrect requirement remains in the accepted merge. Source review
and historical offline receipts do not establish hardware acceptance.

Review totals: Standards 1 blocker in deferred branches, 0 in accepted work;
Spec 1 blocker in deferred branches, 0 in accepted work.

## Validation

In `.local/worktrees/merge-ready-branches`, the accepted source passed:

- `task check`: 24 runtime tests, 1,007 tooling tests (two optional skips),
  current-limit and Mac mount-guard C checks, Bash syntax and ShellCheck.
- `task test:docker-ownership`: all twelve bounded groups, including interrupted
  success/failure, command contract, reservation/recovery, stop/removal retry,
  logging constraints, cancellation, attachment races and delayed start.
  Attempt `dc7cbcc328884457b377c4ef2df0ce02`; all five saved input hashes were
  rechecked against the accepted source after authoritative completion.
  No pending fixture ownership remains; only the two pre-existing unrelated
  Docker containers remain.
- Generated production queue comparison: all 33 patch names/hashes and
  `build/sources.lock.json` exactly match `0f53a71`. Current camera helper and
  tests also match that reviewed cumulative source byte-for-byte.
- Both independent review axes checked originating ticket/report scope,
  conflict resolution, superseded histories and retained blockers. Existing
  power/Sunxi and SMP receipts were rehashed rather than copied as new claims.

No image was built, flashed or installed. No device, network or PM experiment
was run. Diagnostic.26 remains an offline-verified image awaiting its recorded
installation/awake checks; NEO-192 and all existing hardware gates remain open.

## Cleanup and preservation

Only branch tips proved ancestors of the final main are eligible for deletion.
Remote deletions use each pinned expected SHA; concurrent remote updates must
prevent deletion. The 23 original local merged references and 22 corresponding
remote references are removed after main is published. Eighteen associated
worktrees are detached at their exact existing revisions, retaining every
ignored build artifact, private identity, image and test result. The review
worktree is also retained detached for its repeated validation evidence.

The owner's two tracked documentation edits and two untracked documents in the
canonical checkout are backed up privately and restored after updating main.
The untracked `kernel/tests/musb_request_resume_audit.c` in the retained removal
worktree is untouched. No worktree is removed and no ignored file is cleaned.
Private inventory, backup, queue comparison and cleanup receipts are retained
under `.local/branch-review/2026-10-22/` in the canonical checkout.

## Merged references

| Branch | Reviewed tip |
| --- | --- |
| `work/awake-sample-clock` | `d46c1e116373b6859fa64e83466c97f97759889a` |
| `work/axp223-gauge-status` | `ec6f286a6ec823c09ad582008e055a1cf25ff217` |
| `work/battery-boottime` | `9c2d6d9f731e273aa44bb4f6a5ce8aa55a2feffb` |
| `work/battery-rtc-qualification` | `12e050cdd940457f6274c996d639a65b42bbabbe` |
| `work/brcmfmac-clock-deadline` | `4d9efd42f74550269e133602fbb9f7ab699827e2` |
| `work/brcmfmac-control-rx` | `6da261d3e7b812b25e818b036fab2482d86e6236` |
| `work/brcmfmac-diagnostic-bounds` | `57a6c225e0001dd0e2cb0e7d11713cc5f333f438` |
| `work/brcmfmac-rx-recovery` | `9c4f16e53e714ad144f830dabadccf1011cab18e` |
| `work/brcmfmac-shared-diagnostics` | `14cd2fa7b88ec18854c99bdf47b5affb4a623bff` |
| `work/brcmfmac-tx-poll` | `1898229af8a24e2fb590bbb915342bb77ce1eada` |
| `work/brcmfmac-tx-recovery` | `49534eb4d6aa9654dab9abb4de75166df5a99a79` |
| `work/brcmfmac-watchdog-errors` | `d47ef9834e06552ac2c3ccc4b863a72433a4fe78` |
| `work/build-stage-ownership` | `0f53a712bfe2c1206c0a89b5424c0dc5485168af` |
| `work/cpi-wfi-integration` | `624c49dbf11297bc3ebe9ceae8a65df1267b6e9f` |
| `work/cpi-wfi-s2idle` | `2b876a9b85b039211c3497ded01cf6560da2c0ce` |
| `work/diagnostic-stdin` | `304314f2be818732eb6bb696c4dc6d0bb4900be3` |
| `work/kernel-scratch-reuse` | `2fc70e5d14690697ac79e855c123157ddbef1aef` |
| `work/musb-request-resume` | `2d40f6f23b50798c2acf7fa450eaf90b18550fc9` |
| `work/musb-restart-integration` | `fa2a95dee2a694b8dd6cdda10e896a8843a8b9e7` |
| `work/musb-sleep-disconnect` | `e32156954ac3e4dd58f67e881cf511f8c3206207` |
| `work/pm-inspection-route` | `a45bcbb82ea5b1d32ad6664dfaf0dda151375d99` |
| `work/power-insertion-wake` | `97ba5a910f9c4322f6dd6b497b9c104904fe5f96` |
| `work/sleep-cable-transition` | `0e38490660a7ed40d371821b37fa60618ebd91d8` |

## Retained references

These remain at their reviewed tips pending NEO-205/206 or reconciliation of
unique removal/wake/startup work. Their source and historical qualification
receipts remain in their original worktrees.

| Branch | Reviewed tip |
| --- | --- |
| `work/musb-callback-kernel` | `53923426a8b41d2d2a3fd46d701d6b81e4ddf829` |
| `work/musb-callback-lifetime` | `9f5e68c97621fa585dcc5293907e8f361a602e6c` |
| `work/musb-core-work-retirement` | `4d1a07a2c5fb1729ae425cb4f35d13c122574460` |
| `work/musb-irq-retirement` | `0e73b3a24542eed02cb3c1750402136c4f284063` |
| `work/musb-probe-unwind` | `d8a6899698514f0c89fe1629647e7c2c2a0c02e7` |
| `work/musb-removal-lifetime` | `48af268846453062e205b1023ce39f782f2a7451` |
| `work/musb-resume-retirement` | `66e3b552ebd7930b2029ec493f1159db577ec7ed` |
| `work/musb-runtime-retirement` | `c21f64d85c2424eadaa5c93969ce7838d0c733c1` |
| `work/musb-startup-pm` | `2c1bf7d6333c0a6e31607275f98c09e8fb0d191f` |
| `work/musb-teardown-audit` | `666965f2b18a4dd42c7296c70c5be9d739abff2c` |
| `work/musb-wake-irq-policy` | `2b6e295cb16947fb12e892d525135883f2f73925` |
| `work/power-supply-unregister` | `989c1a15e70d135bd1b0ca2dbccda4761df1b882` |
| `work/sunxi-retirement` | `ec243d21973ebf9e1e8d1108bcbeeafcab0f23b1` |
