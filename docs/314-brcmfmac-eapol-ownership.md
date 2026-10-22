# Pending EAPOL ownership at the key-programming boundary

NEO-230 is a bounded offline child of NEO-55, related to NEO-58. Opt-in
candidate `0057-brcmfmac-eapol-ownership.patch` preserves outstanding EAPOL
completions at timeout, returns `-ETIMEDOUT`, and refuses the subsequent
`wsec_key` command. It keeps the **950 ms** wait and genuine completion path.
The production/image queue is unchanged.

## Original event and source finding

NEO-55's diagnostic.11 cycle 2, run
`19cad390d8e34367b3fc67afd3dbb39d`, remains failed at its unchanged 30-second
postflight gate. Association succeeded, authentication timed out, status-16
events backed off, and security eventually completed about 135 seconds after
PM exit. Saved captures contain no pending-802.1x timeout message. Zero
`xmitstate` also occurs in a passing cycle. This source defect and later
successful traces do not establish the original cause. See the
[original result](74-diagnostic11-pm-validation.md) and
[authentication audit](76-wifi-resume-authentication-source-audit.md).

The selected `brcmf_netdev_wait_pend8021x()` forcibly clears the pending count
at timeout and returns positive 1; `send_key_to_dongle()` ignores it. A genuine
late `brcmf_txfinalize()` still decrements its completion. Actual-source baseline
observations are retained:

| Sequence | Baseline | Candidate contract |
| --- | --- | --- |
| One outstanding frame times out | return 1; count 0 | return -110; count 1 |
| Genuine late completion | count -1; packet freed once | count 0; packet freed once |
| New frame submitted before old completion | count 0 with a new outstanding frame | count 1 until its completion |
| Key command after timeout | return 0; one firmware write | return -110; no firmware write |

The [original authored 2022 patch](https://lists.openwall.net/netdev/2022/07/22/140)
cleared the count to prevent repeated waits after lost msgbuf flowring
completions. This child makes a deliberate different tradeoff: a permanently
lost completion stays a visible failed-key condition pending separately owned
transport recovery. It adds no retry/reset, wider deadline or interface-epoch
policy. The [existing completion-ordering fix](https://kernel.googlesource.com/pub/scm/linux/kernel/git/wireless/wireless/+/621d90169cef6c8da5b6134db5c0c4e23cdd09ce)
is already present; its barrier and wake logic are unchanged.

## Exact source and callers

The Linux input is v6.18.54, commit
`1b357ecb321392158d507b04672ffee57bfa071d`, archive SHA256
`9df30b02dd8102bbd0be52556288ef6889ddbe7f1ddb96fbf847d0becf3eacac`.
Primary code is in
[core.c](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/core.c?h=v6.18.54)
and [cfg80211.c](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/cfg80211.c?h=v6.18.54).
Executable evidence uses the verified local archive and saved hashes.

The checker hashes all 33 production patches and extracts five driver files.
It applies complete intersecting patches 0020/0021/0022 with the existing strict
applicator; any intersecting patch with another target rejects. A separate
small copy receives 0057. Actual pending-count getter/wait, TX finalizer, key
conversion and key-send bodies, plus both actual key structs, are extracted.
The 32-byte key-size seam was checked against the locked
`include/linux/ieee80211.h`; only synthetic key bytes are used.

The key helper is the wait helper's only caller. Its four direct callers retain
these boundaries:

| Actual caller | Existing error behavior |
| --- | --- |
| `brcmf_set_sharedkey` | Returns before shared-auth configuration |
| `brcmf_cfg80211_del_key` | Returns the key-command error |
| `brcmf_cfg80211_add_key` | Exits before further `wsec` commands |
| `brcmf_cfg80211_reconfigure_wep` | Logs/stops before further `wsec` commands; void API retained |

Add/delete can update their software key cache before a firmware command.
Cache rollback is not added. New submissions after successful drain and
interface destruction/recreation are separate lifetime/admission questions.

## Finite qualification

The 14 case families and baseline map were fixed before execution:

| Case | Checked boundary | Baseline |
| --- | --- | --- |
| `empty_wait` | Empty success without error | Pass |
| `drained_wait` | Two genuine completions, frees/barriers/enrolled wakes | Pass |
| `timeout_single` | Count retained; -ETIMEDOUT | Fail |
| `timeout_multiple` | Multiple completion owners retained | Fail |
| `late_successful_completion` | Late success balances count/free | Fail |
| `late_failed_completion` | Late failure balances count/free and TX error | Fail |
| `old_plus_new_outstanding` | Old completion cannot consume a new frame's count | Fail |
| `wait_after_genuine_drain` | Genuine late drain permits next wait | Fail |
| `key_install_timeout_refused` | No firmware write after failed install drain | Fail |
| `key_delete_timeout_refused` | No firmware write after failed delete drain | Fail |
| `successful_key_bytes` | Actual converter's initialized fields/data/address | Pass |
| `firmware_errno_after_drain` | Original -EIO, one attempt | Pass |
| `unrelated_frame_completion` | Other EtherType/null-interface free behavior | Pass |
| `interface_isolation` | One interface's error/completion does not consume another's count | Fail |

Seven compiling controls must fail the exact named assertion and numeric
observation. Setup/compile failure is inconclusive. Unexpected return, stderr,
missing/duplicate result or different assertion/value rejects:

| Control | Case: assertion | Expected / observed |
| --- | --- | --- |
| Reset count | `timeout_single: pending_preserved` | 1 / 0 |
| Positive timeout | `timeout_single: timeout_errno` | -110 / 1 |
| Ignore drain | `key_install_timeout_refused: no_key_write` | 0 / 1 |
| Omit decrement | `drained_wait: genuine_completion` | 0 / 2 |
| Invert type gate | `unrelated_frame_completion: unrelated_count` | 1 / 0 |
| Drop firmware errno | `firmware_errno_after_drain: firmware_errno` | -5 / 0 |
| Corrupt key index | `successful_key_bytes: wire_index` | 305419896 / 305419897 |

Wait enrollment/progress, submission and transport are scripted seams; atomic
storage/barrier observations are scalar. This does not execute Linux waitqueue
scheduling or prove SMP ordering, actual TX admission/teardown, firmware, radio,
PM, latency or energy. Only converter-initialized fields are compared; unused
padding is outside this change. The real barrier is retained, not qualified by
a scalar ordering test.

## Workflow and retained evidence

```sh
task test:brcmfmac-eapol-reference -- --archive /path/to/linux-6.18.54.tar.xz
task test:brcmfmac-eapol -- --archive /path/to/linux-6.18.54.tar.xz
task test:brcmfmac-eapol -- --compile-drivers --native-evidence /path/to/original-attempt --archive /path/to/linux-6.18.54.tar.xz
```

The archive is supplied as an existing verified file; it is not downloaded or
copied. Unique attempts, input hashes and suite locking retain failed evidence
and exclude duplicate writers. Each native compile/case saves the actual
command, raw exit and stdout/stderr hashes. Controls require original exit 1;
candidate/sanitizer cases require 0.

The managed-only phase checks the original native source/type/function/fixture,
compiler flags, binaries and every outcome/hash against current executable
closure and the stricter numeric oracle, without rewriting or relabeling that
historical receipt. It writes a new equivalence proof. A fresh immutable full
production33+0057 source must match all five projected files. One owned pinned
builder stage, offline/no-pull, one CPU/3 GiB and serial builds, runs ARM32/QEMU
14 cases then complete normal/debug `brcmfmac.o` with checked project Kconfig
and ARM ELF identity. Only successful original managed completion after
released ownership is accepted; no fallback admits nonzero/old output.

Original evidence under this worktree's `.local/tests/brcmfmac-eapol/`:

- `20261022T205845Z-9295023c703b41e98038a78e893145bb`: session 47502,
  terminal admission exit 0 for nine failing (raw 1) and five passing cases.
- `20261022T205917Z-f6cd222a640b4209bd9a3c879a40fa9b`: session 62346,
  terminal exit 0, native 14/14, ASan/UBSan 14/14 and seven compiling controls.
  This predates managed-phase/helper additions; its exact historical inputs
  remain recorded rather than claimed current.
- Initial YAML parse and two whitespace-sensitive deadline-extractor setup
  failures remain in `.local/audit/task-yaml-initial-failure.json`, original
  failed attempts and rotated workflow logs. They executed no fixture and are
  not source or sanitizer qualification.

The managed-only operation is terminal:

- `20261022T210837Z-56dd96486ed143ef8f3d5d50dad1e874`, original session
  34129, source/test checkpoint `72f95fbfef6cdfa7f169fa9e39cd7e0c3d6ac216`:
  ARM32/QEMU 14/14 matches original native output byte for byte; complete board
  and debug objects pass. Original managed run
  `4c90590ae9224c5fb91300d5d5659eb3` exited 0 without OOM/stop/error and released
  ownership. Result SHA256
  `aa1d8593714d9909002ae830de945cdfe23106e2d7f0d1405b2affc23129254c`.
- Read-only current native provenance proof SHA256
  `5fac54c5f287598bd05e1fa7f6356dfd068a911cd608e38652e26dd51477fc2a`
  verifies the original binaries, compiler flags, exact generated types/bodies,
  five selected source files and all 35 native/sanitizer/control outcomes.
  The three changed host files are this checker, its support and host tests;
  seven newly pinned managed/configuration helpers are listed in the proof.
  The original native receipt remains at its historical hashes.
- Full production33+0057 source tree SHA256
  `0cceb01121f80d4280114743c735e2fb3f8e6b37a88cb2f49f70a6032a617fa4`;
  no other candidate is composed and no image patch is selected.

| Complete object | BRCMDBG | Object SHA256 | Resolved config SHA256 |
| --- | --- | --- | --- |
| `brcmfmac.o` board | n | `b30c77bb271e95b4667b7cb8b1792bf7cf14daafc390b50a118ae2f966fd7a24` | `7e12dbb20507c838ea3c674e3db21ff25f012742d36cd3286fe0844355b7df02` |
| `brcmfmac.o` debug | y | `8e08273fa505e7c56135fa16f1ee1fb6607553135b24a19d70844762a998a88f` | `bbe048986ab9a98b8ececb20b4627ccf21768947085a0c3aba55753c211a63c2` |

At the original `269e511` source checkpoint, nine additional host regressions
exercise read-only
provenance admission with disposable metadata fixtures: altered source,
fixture/applicator dependency, binary, output hash, compile flags, raw exit and
numeric-prefix outcomes reject; identical valid evidence passes without
execution or original-file writes. Together with the 16 initial admission
checks, all 25 focused checks pass. This adds tests only to the qualified
checkpoint; candidate, driver fixture, checker, shared helpers and all kernel
inputs remain unchanged. The single full host check at
`0a8d02a007864440644ed1eebd00ac653f891f88`, original session 65296, is terminal
exit 0: 24 runtime tests, 1463 tooling tests (nine expected skips), both compiled
C checks, Bash syntax and ShellCheck pass. The retained log is
`.local/build/neo230-host-check.log`. The final original-base `269e511` commit
changed documentation only. This is historical qualification with its own
tested inputs, distinct from the subsequent host correction below.

## Complete per-case result grammar

A read-only self-audit at frozen `269e511` found a host admission gap: raw exit 1
with the exact declared control failure plus an additional unrelated `FAIL`
line was accepted. The original counterexample is retained separately as
`.local/audit/neo230-extra-result-counterexample.json`, SHA256
`c3e30e9b21d7996a93fd8ab028f8ab139d19bbc877230d5cf18d6fba354b17bd`.
The entire original checkout/ref, 950-file manifest and 329-artifact index
remain unchanged; all genuine saved executions have the expected output.

The correction lives in a new `wifi-eapol-final-admission` checkout. The shared
per-case validator now requires exactly two complete newline-terminated lines:
one `OBSERVE` with the original case name and complete numeric field schema,
then exactly one expected `PASS` or numeric `FAIL`. An extra wrong-case failure,
assertion, diagnostic, duplicate/malformed observation or missing final newline
rejects. Raw exit must be an integer with the original expected value; stderr
still rejects. The full helper's same-suite source/ownership guards are retained.

All 30 focused host checks pass, including the actual maintained observer and
native-admission routes with additional wrong-case/assertion/diagnostic lines.
Metadata fixtures exercise the admission boundary; they are not kernel runs.
The new read-only proof
`.local/audit/neo230-grammar-proof/proof.json`, SHA256
`a6c99935daec76031e48596dc71b0aaccf5a89a5499549c998d10f408ddb857d`,
checks all 329 original artifact pins and re-admits all 63 genuine original case
outputs: baseline 14, native 14, sanitizer 14, controls 7 and ARM 14. AST comparison
proves the validator is the only changed helper body. Candidate 0057, driver
fixtures/types, compiler flags, source projections, shared helpers, ARM binaries
and objects are unchanged. No binary/container is executed and no historical
receipt is relabeled or rewritten. Cross-checkout output validation uses the
current shared validator with original hashes/provenance; it does not bypass or
extend the complete helper's existing same-suite reuse contract.

The combined current host check and explicit upstream publication boundary are
recorded after local context reconciliation. No new native/sanitizer/ARM/object
run is needed for this host-only validator change.

NEO-55/58 remain open for original
cause/recovery ownership, deliberate candidate composition/image integration
and matching hardware qualification. Clock/provenance blocks live PM admission;
no image or device change is part of this child. Source qualification is
complete on original base `d5d67790668f4cb2b3d308a5b60da03c26b04911`;
fresh independent final reviews and publication of the identical upstream
dependency remain required before publication or child closure.
