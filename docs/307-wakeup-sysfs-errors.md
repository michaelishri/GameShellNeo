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
positive evidence. The pinned KUnit macro/formatter renders the source assertion
as `Expected result == -12, but` and `result == 8 (0x8)`, without a redundant
right-hand literal value line. The parser requires that exact three-line named
expectation block, not a substring match or a second symbolic representation.

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
host references. Actual allocation, IDA, kernfs and SRCU semantics require the
separate twelve-case kernel suite. The later final receipt must include the
finalized checker/test input set; the first host observations remain historical
when those inputs change during preparation.

Any managed nonzero control will use the accepted published NEO-218 result API;
the shared helper will not be copied or forked. Current inputs, source profile,
binary/config and original managed results must be retained. No existing NEO-218
or NEO-220 evidence is modified. Fresh independent Standards and Spec reviews
and a separate publication grant are required before closure.

The new kernel fixture and strict expected-nonzero runner are now prepared.
Before the first kernel execution, the twelve-case/four-failure plan and actual
generated source comparison were retained at
`.local/audit/neo223-kernel-pre-run/plan.json` (SHA-256
`d5a90c4652310b191417312af4f3d4693f977b266d53630eef50606a07ee8fc6`).
Positive and control use identical actual `wakeup.c` and fixture code; only the
final frontend return differs. A generator/list setup mistake was caught and
retained before any kernel job started; the queue now materializes the actual
`kernel-inputs.py` generator, also modeled by the actual-runner guard fixtures.
Sixteen focused host tests pass (eleven frontend/kernel admission tests and five
accepted managed-result groups). They include raw-0 refusal with fresh valid
failed output, typed original raw-1 acceptance and the previous freshness and
ownership refusals.

The fixture reads actual kernfs deactivation state while its writer holds an
active reference, proving the unregister path began draining that callback.
It does not infer draining merely from a started thread. Each worker's task
storage is retained before wakeup and returned by `kthread_stop_put()` after
gate/SRCU restoration. The incapable subvariant registers a separate stably
incapable device, verifies its real attribute is absent, then invokes the actual
unchanged static frontend through a test-only accessor. It does not simulate an
incapable sysfs file or concurrent capability changes.

Prepared checkpoint `c88e4d3` adopted accepted published main `0886549` through
merge `4918476` before its first managed ARM/object/kernel writer. The private
`.local/audit/neo223-accepted-context.json` receipt (SHA-256
`e562e82f47c52b0b7569c57d02d919185b2a1bdd2f4c9c125b36d38febb70090`)
proves the thirteen own candidate/fixture/source/doc files are byte-identical
across that adoption, both own Task entries are preserved exactly, and the
source lock/configuration, source preparation, managed helper and maintained
production patches are unchanged. The imported context consists of accepted
clock tooling/documentation and the separately reviewed wake-control host fix.
Previous host evidence remains historical when maintained context inputs change.

The first complete native/sanitizer/ARM source Task passed at `70db7ef`, including
managed ARM reference `b0aaa621458d457382ac0c8cefb9a6c3` and the full ARM
`sysfs.o`, `wakeup.o` and `wakeup_stats.o` objects in managed run
`d687478239fd4591979a9df7be44fd33`. All three are verified ELF32 ARM objects.
These source-reference and production-object inputs are unaffected by the later
test-fixture changes.

The original outer session 63443 then stopped with exit 201. Its UML run
`487ea977ccc24650b483cc9d866efdba` executed all twelve passing assertions and
exited normally, but the strict runner rejected the actual lockdep circular
dependency diagnostic. The coordinator had held a production `wakeup_srcu`
reader while issuing a real sysfs write, reversing the sysfs writer-to-SRCU
ordering. The control did not start. Original logs, JSON, configuration, source,
binary and released managed-result pins remain at
`.local/audit/neo223-original-kernel-487ea/receipt.json` (SHA-256
`019d4963cde62364a86f0d48b1fa3ca9a89429107461b2d79a03c75ee92d8314`).
This is rejected evidence and does not qualify the subsequent fixture repair.

The fixture now gives the retained old-source reader its own joined worker,
so the coordinator performs sysfs I/O outside that production SRCU read section.
An independent test-context SRCU domain pins each global-context hook lookup;
unpublication drains every admitted hook before KUnit-managed memory can free.
The unregister case also starts a uniquely named unrelated normal source reader,
holds its context pin at the test boundary, observes that unpublication cannot
finish while that pin remains, then releases and joins both workers before
assertions. Actual allocation, IDA, registration, kernfs and production SRCU
bodies remain unchanged. This adds no case or frontend-control exception: the
twelve names and exact four-error/eight-pass control remain fixed. Fresh kernel
qualification of the repaired fixture is pending.

The repaired positive/control profiles were compared before their execution at
`.local/audit/neo223-fixture-repair-final-plan/plan.json` (SHA-256
`f31ac1ca406c5b8f8cc8dea91999bac21c5c0d368134fee4f53c4e944cce5474`).
Both use identical fixture and actual `wakeup.c` bytes; actual production source
and candidate 0071 match the original run. The frontend differs only at the
predeclared final return. Every maintained input admitted by the complete
native/ARM/production-object receipt still matches. The first preparation
comparison remains separately retained; a pair of fixture-only gate writes was
made explicit with `WRITE_ONCE()` before the final comparison, without executing
the earlier preparation.

The repaired fixture's managed positive `62a4c313f309482bb9ee3fb120087bf9`
completed with twelve passes, no rejected diagnostics and released ownership.
Its retained log observes the old source alive while detached, a successful new
enable, and context unpublication unable to finish until the unrelated hook
reader releases its pin. The same outer session 32730 then stopped with exit
201 because control `8402ea6fa7f14545979b0722475c8052` was rejected by the first
host assertion parser. The kernel actually executed exactly the planned four
failing cases and eight passes, with raw exit 1 and all fault/readback/ownership
observations correct. The parser's synthetic host fixture had assumed symbolic
errno text and a redundant right-value line that pinned KUnit does not emit.
The original rejected wrapper/raw result remains at
`.local/audit/neo223-original-control-8402/receipt.json` (SHA-256
`de221d80294cbc61f2a8a4d120dba06f758ca89371b1449c5d8fd546dab8c843`).

The oracle now follows `KUNIT_EXPECT_EQ` macro expansion and
`lib/kunit/assert.c:is_literal()` from the pinned source. The host regression
embeds the original compiled KTAP verbatim and rejects a wrong errno, decimal or
hex value, missing or extra assertion line, different case/source, fatal
assertion, diagnostic, raw-0 command or unresolved ownership. Seventeen focused
host checks pass. The private
`.local/audit/neo223-compiled-ktap-oracle-proof.json` receipt (SHA-256
`6a4aa79e82db4a8c0b105ccce1367744f7f41653d2874cbaa2dd67fe4a674ad0`)
proves the captured text is exact and the source-generation function, fixture
and semantic control map are unchanged. Changed maintained host inputs require
new owned cached positive/control execution and fresh output files; the earlier
positive and rejected control are preserved as historical observations.

MUSB IRQ timing/device-DPM traversal, terminal destruction/composition, image
selection and physical hardware behavior remain separate. NEO-98 stays open.
