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

At this checkpoint ARM/objects and combined host checks are pending. Final
results will be recorded before review. NEO-55/58 remain open for original
cause/recovery ownership, deliberate candidate composition/image integration
and matching hardware qualification. Clock/provenance blocks live PM admission;
no image or device change is part of this child.
