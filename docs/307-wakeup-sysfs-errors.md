# Wakeup sysfs errors and idempotency (NEO-223)

23 October 2026, Pacific/Auckland. This bounded offline child of NEO-98 starts
from published main `02c633a` in `work/wakeup-sysfs-errors`. Candidate 0071 changes
only the frontend's observable errno/idempotency contract. It is not registered
in `kernel_candidates.py` or selected for an image.

## Source contract

Linux 6.18.54 `drivers/base/power/sysfs.c:wakeup_store()` discards the return
from `device_set_wakeup_enable()` and reports the full request length. In
`wakeup.c`, a failed `wakeup_source_register()` becomes `-ENOMEM`; object, name,
IDA and source-sysfs registration failures are already collapsed into this
public error. This frontend cannot recover a hidden lower errno.

An already-enabled request is idempotent even if another allocation would fail.
Candidate 0071 observes the existing source under `dev->power.lock`, releases
that lock before allocation, and treats a concurrent attachment's `-EEXIST` as
success. It preserves the internal API's return values and source/IDA ownership.
It does not promise that the last completing concurrent writer determines the
final state. Capability is stable for the concurrency tests; manual capability
changes and driver unbind are outside this slice.

## Finite kernel plan fixed before execution

| Named case | Required observation |
| --- | --- |
| `sysfs_enable_test` | Actual kernfs write enables policy and owns one source/IDA entry |
| `sysfs_disable_test` | Actual write disables, detaches and frees its exact source/IDA entry |
| `sysfs_enabled_idempotent_test` | Repeated enable succeeds with the next target allocation failure armed and the same source retained |
| `sysfs_disabled_idempotent_test` | Repeated disable succeeds with zero fixture source ownership |
| `sysfs_invalid_request_test` | Malformed and incapable requests return `-EINVAL`, without policy/source changes |
| `sysfs_object_alloc_error_test` | Target object failure gate hits once; write returns `-ENOMEM`, readback is disabled and no source/IDA remains |
| `sysfs_name_alloc_error_test` | Dynamic name allocation failure gate hits once with the same observable error and complete unwind |
| `sysfs_id_alloc_error_test` | Actual fixture IDA boundary failure gate hits once; earlier object/name ownership is returned |
| `sysfs_registration_error_test` | Source-sysfs boundary returns lower `-EIO` once; existing public API reports `-ENOMEM` and unwinds |
| `sysfs_two_enables_test` | Two distinct open-file writers observe disabled, perform actual allocations/attachment, both succeed and leave one source; duplicate ownership frees once |
| `sysfs_disable_enable_srcu_test` | Disable detaches the old source and waits for a retained SRCU observer; a new source attaches and survives old-source destruction |
| `sysfs_unregister_active_write_test` | Actual device removal drains a gated in-flight kernfs write; release permits completion, PM source cleanup and exactly one final device release; old open writes reject |

Dynamic fixture device names exercise the real `kstrdup_const()` allocation
path. Targeted test-only boundary hooks affect only the uniquely named fixture
and otherwise call the real allocator, IDA, source registration and SRCU APIs.
No production function body is replaced. No gate waits while holding a spinlock.
Every started worker joins and every controlled gate releases before assertions
can return from a case. Tests use real private sysfs VFS operations in disposable
UML with KASAN and lockdep; they do not need a userspace root image.

The compiling `errors-ignored` control suppresses only final frontend error
propagation. Exactly the four allocation/registration error cases must fail,
with exactly one `result == -ENOMEM` assertion per case and actual result 8 for
`enabled\n`. Each must still observe disabled readback, fault-hit count 1 and
zero fixture source/IDA ownership. The other eight cases pass. Missing or extra
assertions/cases, compilation/setup failure, diagnostics, skips and any different
outcome reject the control. All original failed output stays separate from
positive evidence.

## Qualification status

The ten-case native reference uses exact extracted frontend code and API/lock
shims. Before its first execution, the source controls were fixed:
upstream and errors-ignored must each fail only the four error cases;
no-idempotent-snapshot fails only enabled-idempotent; no-concurrent-idempotency
fails only concurrent-enable; the candidate passes all ten.

The first sandbox Task (session 92497, run
`dc92357d685040d791fe4b14d7233afd`) reproduced the four original native failures,
then stopped at LeakSanitizer's explicit ptrace-environment failure. That
sanitizer observation is inconclusive and retained in its original directory;
the candidate had not executed. After terminal completion, a new authorized
normal-host Task (session 34272, run `0fae130a9c3a4d7d97ad72116d97c96b`) completed
with exit 0. The candidate passed all ten cases both natively and with
ASan/UBSan; every source control compiled and failed only its exact named cases.
Sanitizers, including LeakSanitizer, remained enabled without diagnostics. Four
host source/oracle regression tests also passed. The first host receipt is
`.local/audit/neo223-first-host-evidence.json` (SHA-256
`fef6db5073700914ee3c22d1b9ccb1499723a75c77f3ba0aa7a4a3655f461fb0`).

The saved `test:wakeup-sysfs` Task runs native/sanitizer, managed ARM reference
and selected full PM/sysfs objects; `-- --host-only` deliberately runs just the
host references. ARM and kernel qualification are still pending. Actual
allocation, IDA, kernfs and SRCU semantics require the separate twelve-case
kernel suite. The later final receipt must include the finalized checker/test
input set; the first host observations remain historical when those inputs
change during preparation.

Any managed nonzero control will use the accepted published NEO-218 result API;
the shared helper will not be copied or forked. Current inputs, source profile,
binary/config and original managed results must be retained. No existing NEO-218
or NEO-220 evidence is modified. Fresh independent Standards and Spec reviews
and a separate publication grant are required before closure.

MUSB IRQ timing/device-DPM traversal, terminal destruction/composition, image
selection and physical hardware behavior remain separate. NEO-98 stays open.
