# Wakeup sysfs errors and idempotency (NEO-223)

23 October 2026, Pacific/Auckland. This bounded offline child of NEO-98 starts
from published main `02c633a` in `work/wakeup-sysfs-errors`. Candidate 0071 changes
only the frontend's observable errno/idempotency contract. It is not registered
in `kernel_candidates.py` or selected for an image.

The original source checkpoint adopts accepted published `0886549` and is
retained at `bcb3cf1`. A separate final-admission checkout preserves that history
and adopts exact NEO-226 context `08aa1993c789678268c0d299860b1285aab6458f`.
NEO-220 `a2688ac` is now accepted and published; the included NEO-222/226 tips
remain provisional and unpublished. The current combined host check passes.
Fresh final review may inspect this fixed context, but whole-ticket acceptance,
publication and closure require the identical dependencies to be accepted and
published. No hardware result is inferred here.

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
qualification of the repaired fixture is recorded below.

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

The one new normally guarded cached chain, outer session 23896, completed with
exit 0. Its genuine executions produced fresh output under new managed
identities and released ownership:

| Qualification | Managed run | Actual outcome |
| --- | --- | --- |
| Positive UML/KASAN/lockdep | `9a1350e1e22c4a44babf40ecce9a252c` | Raw 0, twelve passes, no rejected diagnostics |
| Compiling frontend-error control | `feb69966e4ff4bf49550148a9642de8d` | Raw 1, exactly four named errno failures and eight passes; no other assertion or diagnostic |

Both executions retain exactly the earlier profiles, configuration and binary
hashes; only the three maintained host inputs (own runner, oracle and host tests)
changed. The positive binary is SHA-256
`a1d5fa3832b8adb83557490b94bbfcb981e68a9c5a04073bf266aa9eb9b8c792`;
the control is
`9a5b844d3debb56cb4d2a7a77fae5a2f079de98cec32c1c47f322a3f5a3b2736`.
The immutable accepted-run receipts and complete artifact/source/input hashes
are indexed at `.local/audit/neo223-original-base-qualification.json` (SHA-256
`9ecf2e831536b8b2484e1623d0b583a35033b1db6603826866402ccce8d32717`).
Every admitted native/ARM/production-object input still matches its complete
earlier run. Re-execution of those unaffected stages was unnecessary. The
read-only reference-artifact audit also rehashes every saved native/sanitizer/ARM
binary and all three ARM objects, reparses their exact original outcomes and
checks released original ownership. Its receipt is
`.local/audit/neo223-reference-artifact-verification.json` (SHA-256
`0c556565a049d9bfcb4f48f95cc764702e97558cf9445108fe69b5a691975ed6`).

Complete original-base `task check` at clean `e897f91`, original normal-host
session 24547, passed with exit 0: 24 runtime and 1,367 tooling tests, nine
expected skips, both compiled C checks, Bash syntax and ShellCheck. The full log
is `.local/build/neo223-preintegration-host-check.log` (SHA-256
`15312b2e07ef87e80db37496e8d79a06eff349f9b00acc731caca8a30ec537f4`);
its saved receipt records the same clean head before and after. Subsequent
review preparation changes only this report; qualified code and all admitted
kernel/native/object inputs remain unchanged. This remains the original-base
source/pre-integration execution; it is not relabeled as a later current-context
run.

## Provisional combined context and evidence equivalence

The separate `wakeup-sysfs-final-admission` checkout first preserves both
original `bcb3cf1` and provisional upstream `8f56a29` histories at `178f2ef`.
It then merges exact `08aa1993c789678268c0d299860b1285aab6458f` at clean
`e045f87c5b1a87002a608742cfdc6ce0aff40248`. That second adoption changes only
FOLLOW-UP and reports 306/310; all other 937 tracked files retain exact bytes.
The thirteen exclusive candidate, fixture, configuration, extraction, runner,
oracle and regression files remain identical to `bcb3cf1`. The adoption proof
is `.local/audit/neo223-final-upstream-adoption.json`, SHA-256
`6395150fce63807b6f97fb8cd9b9e68b67fd2e6826474ceb5df29d4486feb72d`.

The independent actual-source closure audit reconstructs the selected production
33 patches plus explicit 0071, all five extracted frontend variants and both
generated kernel test patches/full manifests. They match the actual original
native/ARM/object and positive/control source. The fifteen local Python import
inputs match except the explicitly mapped whole registry-file change: two
additive, unselected profiles coexist with unchanged existing profiles/functions.
This sysfs route reads the production queue directly and does not select those
profiles. Both own Task bodies and the global Task prefix remain exact; the
whole Task file differs because of sibling tasks. Thus the historical thirteen
native and sixteen kernel maintained-input receipts are not called current
whole-file receipts, and their strict admission guards are not relaxed. The
closure proof is `.local/audit/neo223-provisional-closure.json`, SHA-256
`e46116b82ce47c5a9c9ac47072fc81740f1cd8b592b280c3698b07c5b3f275c1`.

All four complete original source inventories are independently rehashed once:
97,302 files each for the rejected original positive, repaired positive and
control, and 97,300 for the native/ARM/object tree. A separate artifact audit
verifies fifteen original native/sanitizer/ARM binaries, all three ARM objects,
original managed outcomes/released ownership and genuine kernel binaries,
configurations and logs. It applies the unchanged current pure validators to
the original observations without manufacturing current execution receipts.
The first private observer failed after the four inventories because it assumed
that a retained receipt's sibling directory contained its original binary. The
next observer corrected the pinned path but incorrectly expected a 32-bit UML
binary. Both failures are retained separately. The final read-only correction
uses the receipt/manifest's actual original ELF64 x86-64 UML paths and verifies
their exact hashes, configurations and job provenance. No replacement artifact,
inventory rescan, build or test execution is used to repair these observers.
Its receipt is `.local/audit/neo223-provisional-original-artifacts-corrected.json`,
SHA-256 `25917dacc384b23db07cf8e45b55b78471d7129039a57b488e7a44dcec32b68d`.
The original ptrace/LeakSanitizer attempt, lockdep rejection and old-oracle
rejection remain inconclusive or rejected at their actual historical sources.

One current `task check` runs at clean `e045f87`, original session **40919**,
Task PID **1283013** and supervisor **1283009**, and exits zero. It passes
**24 runtime and 1,428 tooling tests**, nine existing opt-in skips, both compiled
C guards, Bash syntax and ShellCheck. All 940 tracked input hashes match before
and after. The original log is `.local/build/neo223-final-host-check.log`,
SHA-256 `9b994da8a2e0ec2ad8340e449496819f6a3789badb7468cc75f75dd14bdf7684`;
receipt `.local/audit/neo223-final-host.json`, SHA-256
`896537e7846efadd9b0488e3de3e2ad5d3eb63f48a408789f2ae577c2f222d26`.
Only this report and the own FOLLOW-UP result wording change afterward. No
native, ARM or kernel execution is repeated for proven unchanged executable
closure, and all genuine original execution provenance remains explicit.

An entirely fresh final Standards/Spec pair must inspect this complete fixed
source, contract and evidence. Whole-ticket acceptance, integration, publication
and closure additionally require identical upstream NEO-222/226 acceptance and
publication plus a separate serialized grant. A changed dependency invalidates
the fixed context until remapped and requalified as required. No main, device,
image or physical acceptance is provided by this preparation.

MUSB IRQ timing/device-DPM traversal, terminal destruction/composition, image
selection and physical hardware behavior remain separate. NEO-98 stays open.
