# Managed wakeup initialization errors (NEO-229)

23 October 2026, Pacific/Auckland. This offline child of NEO-98, related to
NEO-102/106, starts from published `d5d67790668f4cb2b3d308a5b60da03c26b04911`
in `work/managed-wakeup-init-error`. Candidate 0072 is explicitly appended only
by its dedicated saved Tasks. The production queue, source lock, all existing
profiles and image selection are unchanged. This is shared driver-API source
correctness, not a reproduced fault in the installed CPI system.

Original native and real-Linux qualification ran at `70285ec`, retained with
its checkout and all artifacts unchanged. A separate
`work/managed-wakeup-init-final-admission` checkout descends from that commit
for the selected-object runner correction described below. It reuses the
original verified source read-only; it does not relabel old whole-file input
pins as executions of the corrected runner.

The final-admission checkout now adopts exact local NEO-230 context
`bc3ae1b6a62afbb350589444a08b8c903bbe48b7`, including its NEO-228 base
`631a5451b14de1c3e19abe387aaff66c5631afc5`. Both dependencies remain
provisional and unpublished. The merge preserves their complete entries and
the already qualified managed-wakeup execution payloads; only shared
navigation/Task context changes. Fresh independent review may inspect this
fixed provisional dependency, but whole-ticket acceptance, integration,
publication and closure require the identical dependencies actually published
and a separate grant. A changed dependency must be remapped and receive fresh
required review. The one current combined host check passes as recorded below.

A third isolated checkout, `work/managed-wakeup-init-diagnostic-admission`,
descends from frozen `06c9bd7` for the host diagnostic-admission correction
below. Both earlier checkouts, all original executions, historical indexes
and the unexecuted `06c9bd7` publication preparation remain unchanged. The
provisional dependency and publication conditions above still apply.

## Primary-source findings

The locked Linux 6.18.54 archive is SHA-256
`9df30b02dd8102bbd0be52556288ef6889ddbe7f1ddb96fbf847d0becf3eacac`,
tag `v6.18.54`, commit `1b357ecb321392158d507b04672ffee57bfa071d`.
Exact-version facts below come from the independently hashed local source and
that verified [kernel.org archive](https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.18.54.tar.xz).
The online exact-tag raw-header/source requests were unavailable to the web
cache; the available online pages corroborate the API rather than replace
the pinned archive evidence.

`include/linux/pm_wakeup.h:239-243` discards `device_init_wakeup(dev, true)` and
then returns the result of registering `device_disable_wakeup` as a managed
action. The underlying inline at lines 217-225 sets capability true before
calling `device_wakeup_enable()`. A failed initialization therefore retains
capability true; 0072 preserves that behavior. The
[upstream header](https://github.com/torvalds/linux/blob/master/include/linux/pm_wakeup.h)
corroborates the wrapper/API shape, but its moving master version is not the
version used for qualification.

`drivers/base/power/wakeup.c:326-345` returns `-ENOMEM` when source registration
fails. Its attachment function at lines 306-317 returns `-EEXIST` when a source
already belongs to the device, and the failed newly allocated source is then
unregistered. Registering a managed disable action after either failure both
loses the initial error and can transfer cleanup over a source the call did
not initialize. The distinction between capability and enabled wakeup policy
is part of the documented [device-PM model](https://docs.kernel.org/driver-api/pm/devices.html).

`drivers/base/devres.c:745-758` allocates the action and returns `-ENOMEM` on
allocation failure. `include/linux/device/devres.h:156-168` implements the real
`__devm_add_action_or_reset()` error path by calling the action before returning
that failure. The patch keeps this path intact. The
[Linux 6.18 devres implementation](https://github.com/torvalds/linux/blob/v6.18/drivers/base/devres.c)
and [devres documentation](https://docs.kernel.org/6.18/driver-api/driver-model/devres.html)
describe the allocation, unwind and managed-lifetime contract.

Checked real consumers `drivers/mfd/max77541.c:155-157` and
`drivers/rtc/rtc-stm32.c:1146-1148` rely on this helper's return value. They are
shared API consumers, not evidence that the GameShell selects those devices.
Generic device cleanup supports managed resources on valid devices without a
driver (`drivers/base/core.c:2608-2636`); the fixture uses that supported
registered-device lifetime rather than an invalid or NULL input.

The independently inspected pinned files are:

| File | SHA-256 |
| --- | --- |
| `include/linux/pm_wakeup.h` | `da6e286383312e5ad728c01eb0216e732829080d7df3f113cbd67b73091c8b18` |
| `include/linux/device.h` | `951d5461d34207c54f4007b7fc9d05f30c0bb601a96c37133d7f09e92376ce4c` |
| `drivers/base/power/wakeup.c` | `13c81b0d2640b9c21dd652d29d97101259e17cadb7aa1a4313c5b56d862a3673` |
| `drivers/base/devres.c` | `5c2b58422bebe697e6b528d02bf1f9aea2a2d77c0ba47d8a44e190ee0bfb5a6b` |
| `drivers/mfd/max77541.c` | `a0a87d720b64d137a9cf3219c88c8901e223ee1db60d78b68eb09df31e49729f` |
| `drivers/rtc/rtc-stm32.c` | `4353b15b8bcc6b20d6a3f8d9dc62e08bd1e1f68ec811fb19f610fe40d9aa5a21` |

## Bounded change and fixed qualification map

Return the exact initialization error before devres registration. On success,
retain the existing action result and real reset-on-registration-error path.
Do not roll back capability on source error, adopt foreign ownership, change
source registration or add idempotency. No sysfs/MUSB/IRQ, runtime-PM, role,
image or policy code changes.

| Named case | Required observation |
| --- | --- |
| `managed_wakeup_success_test` | Fresh registered device returns 0; exact action/source/IDA ownership; actual devres cleanup returns ownership once, repeated drain harmless, one final device release |
| `managed_wakeup_source_error_test` | One targeted source-object failure returns `-ENOMEM`; no action/source/IDA, capability stays true through empty devres release |
| `managed_wakeup_existing_source_test` | Ordinary API first owns a source; managed helper returns `-EEXIST`, adds no action and preserves that exact numeric source identity/IDA/capability through devres release |
| `managed_wakeup_action_error_test` | Source setup succeeds, one exact action allocation fails; real add-action-or-reset returns `-ENOMEM`, clears capability and releases source/IDA once |
| `managed_wakeup_capable_disabled_test` | Registered capable device without a source enables successfully and balances the same real cleanup path |

The return-ignored control compiles the exact original wrapper and must yield
**2 FAIL / 3 PASS with exactly eight failed assertions**. The source-error case
must expose result 0 instead of `-ENOMEM`, a new action and false capability
after release. The existing-source case must expose result 0 instead of
`-EEXIST`, a new action, loss of the original source and IDA ownership, and
false capability after release. Setup/fault-hit/allocation/free observations
remain exact. No stale output, raw-0 control, extra assertion, diagnostic,
skip, compile error or unresolved managed operation can qualify.

Before the first Linux execution, the validator fixes the pinned KUnit
rendering: integer results use `Expected result == -12, but` or `-17` plus
`result == 0 (0x0)`; unary assertions use the exact named
`Expected ... to be true/false, but is false/true` line. The required counts,
names, source-file boundaries and ownership records are independently checked.

The native fixture compiles the real four initialization/disable/action-reset
inline bodies. Device, allocator, source/IDA and devres effects there are
explicit synchronous models. ARM32 repeats those references, not a real PM
framework. The separate Linux fixture uses actual source registration,
attachment, IDA range query, action/reset, devres drains and device removal.
Only exact allocation boundaries are faulted. Dynamic valid device names,
current task and exact action/data identity scope the hooks. Short spinlock
observers retain no fixture pointer after unlocking; unpublication completes
before KUnit releases its context. KUnit's actual separate cleanup thread takes
the retained task identity after the case thread joins, so normal final device
removal is also observed without retaining a stale task pointer. No hook sleeps
or waits, and no source SRCU
reader spans a mutating/teardown call. The captured foreign source is compared
as a numeric identity, never dereferenced after the control frees it.

The source is common to both Linux variants: one test-only Kconfig option
selects the complete unchanged original inline or complete 0072 inline. All
other code and hooks are identical. A single output is reused serially, with
immutable executed binary/config/log/JSON retained separately before reuse.
Selected real ARM builds cover PM with sleep enabled and PM without sleep.
Both must select the checked MAX77541 and STM32 RTC consumers; only the
PM_SLEEP build may claim a selected `wakeup.o`.

## Original execution and current status

`task test:managed-wakeup-init` original session **25191** completed with exit 0.
The candidate passes all five cases natively, with ASan/UBSan and as ARM32.
The exact original control produces only two failed cases/eight assertions in
each mode. The twelve maintained inputs remained fixed. LeakSanitizer is
explicitly disabled for the ptrace environment; ASan/UBSan remain fail-fast,
and no leak-sanitizer coverage is claimed.

Native evidence is `.local/build/managed-wakeup-init-tests/evidence.json`,
SHA-256 `f9d9f437a4340a8e1a1c0f1bf44dff4ddf36da84114834248a5e562312fd1bf3`.
Managed ARM run `f2756d65f4f44b458f334d203c09bdce` is authoritatively
exited 0, ownership resolved, without OOM, stop request or runtime diagnostic.
The initial focused-unit failure was an extra extractor newline before any
compiler execution; it is retained, corrected, and the original focused five
tests pass. The Linux validator/actual-runner tests now bring focused coverage
to twelve passing methods, including stale/partial data, raw-0, unrelated
assertion, crash/diagnostic and unresolved-owner refusal.

Original real-Linux Task session **61035** completed with exit 0 at `70285ec`.
The original wrapper's managed run `d8a851e5b8e44b21b6fd12689f5dd2fd` exited
raw 1 with exactly the required two failed cases/eight compiled assertions and
all exact ownership observations. Candidate run
`66d864ffb4304c3d8d7c2112ee92dacd` exited 0 with all five cases passing.
Both have authoritative released ownership, no OOM/error/stop request, verified
KASAN/lockdep configuration and no diagnostic. All 62 original input pins match
the original checkout. Control and candidate evidence SHA-256 values are
`1654b6cf6fb205c9292e2a195384ac713d9ee314a476cb9f15dd39871b3815b3`
and `289bf9150c9fb8c2cf5db7a0ef4b41f1b0fa5823b038a8bf518ee8ecdc94fb71`.

One common source has exactly 35 entries: unchanged production 33, explicit
0072 and the test-only patch. Its identity is
`fa61630b7e019ad9c30c6a5b1a9436815a6e8c44c16eb4b39ae671c8fb154844`.
Both effective inline variants independently match their native/ARM body hashes
exactly. Original source, inventory, binaries, configurations, KTAP, JSON and
managed logs remain under the original checkout's
`.local/build/managed-wakeup-init-kernel/`; its accepted control and positive
artifact directories are separately immutable.

The first selected-object Task, session **53980**, stopped with exit 201.
Managed run `abab14d5b5544bc6bf17590a39a894ca` exited 1 before driver
compilation: `merge_config.sh` tried to create its temporary file in the
correctly read-only source working directory. This is a runner setup failure,
not a candidate behavior or successful configuration result. The original
result/log is retained (container log SHA-256
`1da2d5a8899b7da4dd507f14b494c7a3cc1e68e5b11f543538ea830fa0f07e67`).

After all writers resolved, the separate checkout corrects only that generated
driver command to change into its owned output directory before merging the
configuration. The source bind remains read-only. Driver-only
`--verified-source /absolute/path/to/source` admits only the exact original
35-entry identity and full inventory matching its unchanged cache metadata;
it rejects wrong modes, trees, aliases and metadata rather than repairing them.
New outputs, inventory and evidence belong to the new checkout. The saved route
is `task check:managed-wakeup-init-drivers -- --verified-source PATH`.
Fifteen focused methods pass, including these read-only reuse guards. Only the
two previously unqualified selected-object stages executed after correction;
unchanged native and Linux tests were not repeated. Their original execution
base and changed current whole-file runner/Task provenance remain distinct.

Corrected Task session **8010** completed with exit 0 at clean `702fa7a`.
PM_SLEEP=y run `e4d007772c8e4af68f3204df6bb04876` and PM_SLEEP=n run
`7edd37423e224d569185594319fe99a3` both exited 0 and released ownership,
without OOM/error/stop requests. The requested driver selectors are verified
in each resolved configuration, before compilation. Both select
`MFD_MAX77541=y` and `RTC_DRV_STM32=y` through the documented COMPILE_TEST
dependencies; these are selected consumers, not forced unselected targets.

| Configuration | Complete selected objects | Configuration SHA-256 |
| --- | --- | --- |
| PM=y, PM_SLEEP=y | `devres.o`, `wakeup.o`, `max77541.o`, `rtc-stm32.o` | `587d1fa8ed10ee847cad3058701cae275b05d49b92d12d069ccb3ecc116c3dba` |
| PM=y, PM_SLEEP=n | `devres.o`, `max77541.o`, `rtc-stm32.o`; `wakeup.o` is not selected | `603ba33299e271c3cd79f26801b6534d59fb1ca4368f7badda520787090f6aa5` |

All seven objects independently verify ELF32/EM_ARM. Both builds disable the
test suite and original-return control; allocation hooks compile to their
unchanged non-test paths. They are complete object/configuration checks, not
runtime qualification of those PMIC/RTC devices or a linked CPI image.
Driver evidence at the new checkout's
`.local/build/managed-wakeup-init-tests/driver-evidence.json` has SHA-256
`a273d77c516e708f0a2990782c22adffef85c79820ff3d9c863e9dfe17c29407`.
The detailed terminal/ELF receipt is
`.local/notes/managed-wakeup-init-error/selected-objects-terminal-01.json`,
SHA-256 `78b0682cff04a9ba22c655d82e29d026b2f4859ece236943698ffd17635340a6`.

The first idle heavy-resource lease was explicitly returned unused so another
worker could build; no operation was stopped. Active qualification uses serial
j1, a four-GiB incremental disk ceiling and a three-GiB free-space floor before
a new stage. The reuse path counts retained original plus new qualification
storage. After qualification the combined original/new kernel footprint is
2,014,769,152 bytes and free disk is 5,938,335,744 bytes. The new checkout has
zero copied source caches. All owned heavy operations are terminal and their
ownership is resolved. Existing caches and original proof remain immutable.
The coordinator-allocated single current host check completed at clean combined
`44a7a647255c583bd84792a5f17b1711819d0541`, original session **39950**, exit 0.
It passes 24 runtime tests and 1,488 tooling tests (nine expected skips), both
compiled host guard programs and Bash/ShellCheck. All 967 tracked pre-run inputs
were verified unchanged afterward. Its complete log is
`.local/build/neo229-current-host.log`, SHA-256
`d0e810dee091ce150ed00b7bc21b198a545a75b3a0c645a14a0d01a787d1ba46`;
the terminal receipt is
`.local/notes/managed-wakeup-init-error/current-host-terminal-01.json`, SHA-256
`359d4d3f400b9274c63e5d0973abaf2eed60b9d3b27a0aa3d9c3dec6aff806fa`.
Only factual documentation changes follow that run; no candidate native,
sanitizer, guest or object qualification was repeated for the context merge.
No unpublished upstream candidate is described as accepted or published here.

The read-only original-to-corrected comparison records the exact unchanged
candidate/native/Linux fixture/configuration and shared source helpers,
unchanged production files, equal generated inline variants and equal complete
97,302-entry kernel inventories. It also lists the changed whole-file Task,
runner and host-test pins explicitly. The receipt is
`.local/notes/managed-wakeup-init-error/original-to-corrected-equivalence-01.json`,
SHA-256 `e50042be2becf08d84ee3b8d00ac2d1fa48bdd4c5ea1dd148cb6e1996eb9eef1`.
The first factual index names 110 original/current artifact files without
copying their contents:
`.local/notes/managed-wakeup-init-error/qualification-artifact-index-01.json`,
SHA-256 `2306c7b40b4a0e5e10df0bb92876394d8c26762a3245fb96acf7369fcce508be`.
Those index and comparison records identify `702fa7a` as the corrected code
capture; later documentation-only descendants do not change that execution
provenance. They remain historical when final context is allocated.

The allocated-context comparison is
`.local/notes/managed-wakeup-init-error/current-context-equivalence-01.json`,
SHA-256 `c0bf84def856cb28b9cc0d755de648a739667bd98c24d6e327f29d8cf306d69e`.
It verifies every Task body from both histories, all qualified executable
dependencies and production pins, and the retained original artifact files.
Only README/FOLLOW-UP/report navigation required conflict resolution; both
complete entries were retained. Indexes 01 and 02 remain byte-identical.
Index 02's tracked report pin describes historical `e6d01dd` bytes, retained at
`.local/notes/managed-wakeup-init-error/context-premerge-e6d01dd/315-managed-wakeup-init-error.md`
and bound to that commit's Git blob. It does not describe the current report
path after this factual update; the final handoff distinguishes those versions.

## Complete diagnostic admission

A retained host counterexample inserts either `test case cleanup timed out`
or `Test should be marked slow` after the source-error ownership observation
in a copy of the genuine original-control log. The pinned Linux KUnit parser
retains each diagnostic without adding a JSON parsing error. The prior
maintained runner then accepts both altered results despite the originating
contract requiring any different diagnostic to remain inconclusive. The
actual warning sites are `lib/kunit/test.c:387-389` and `:522`; these strings
need not contain any of the existing kernel-warning blacklist tokens.

The corrected host validator requires the complete ordered permitted KTAP
stream for both candidate and original-control results. It checks the exact
suite headers and plans, all eight expected control assertion blocks, each
case's ownership/result pair, both summaries and the final suite/halt lines.
Only indentation and blank lines are normalized. Unknown lines before or
after ownership, within assertions or at case/suite boundaries reject rather
than disappear when assertion collection stops. This enforces the permitted
stream instead of adding warning names to a blacklist.

Eighteen focused host methods pass, including both KUnit warning examples and
arbitrary unexpected text at the relevant boundaries. Actual maintained-runner
tests reject both positive and control diagnostics, publish no acceptance
evidence and retain the current log/input receipt. The bounded counterexample
and readmission routes use the real parser, validators and maintained runner;
source preparation, the executor and released ownership results are explicit
host models, not new Linux executions.

The corrected validators readmit the unchanged genuine logs/JSON from original
control run `d8a851e5b8e44b21b6fd12689f5dd2fd` and candidate run
`66d864ffb4304c3d8d7c2112ee92dacd`. The exact original counterexample copies
now reject. All 144 earlier artifact pins and original input pins match before
and after this read-only check. Pinned-parser Python sources and bytecode-cache
contents are unchanged; imports explicitly disable bytecode writes. Source
generation, the test-only kernel patch, fixtures, configurations and selected
object runner are unchanged. No native, sanitizer, ARM, guest or object build
is repeated; their execution identities above remain historical.

New host evidence belongs only to the diagnostic-admission checkout under
`.local/notes/managed-wakeup-init-diagnostic-admission/`:
`counterexample/result.json` and `retained-readmission/result.json` identify
their original inputs and modeled boundaries. The corresponding complete logs
are `.local/build/neo229-diagnostic-counterexample.log`,
`neo229-diagnostic-focused.log` and `neo229-retained-readmission.log`.
The first current full-host attempt, session **8571**, ended with exit 201:
sandbox restrictions denied local AF_UNIX bind/send operations, causing six
existing socket/Paramiko fixture errors. The run completed 24 runtime tests
and attempted 1,491 tooling tests with eleven skips. Its original log and
terminal receipt are retained unchanged; it is not a passing host result.

After that operation was conclusively terminal, the separately authorized
normal-host check ran the same Task at unchanged clean
`dfe69455c5f6ec3fec327bc18382d7f774a9107f`, session **11508**, exit 0.
It passes 24 runtime and 1,491 tooling tests (nine expected skips), compiled
host guards and Bash/ShellCheck. All 967 tracked inputs remained unchanged.
No tests or infrastructure were relaxed. The distinct complete log is
`.local/build/neo229-diagnostic-current-host-normal.log`, SHA-256
`fe907573678f5d3c747a2651b7c26949477b3810d4d284a64b2fd769f5068f68`.
The terminal receipt is
`.local/notes/managed-wakeup-init-diagnostic-admission/current-host-normal-terminal.json`,
SHA-256 `bd6d1059ca625c9dbab043d8bb6e90f121edbda9c8106406b2f2c9dcfff0b91e`.
Only factual report/FOLLOW-UP updates follow this run. Neither host attempt
changes the original kernel/ARM execution identities or unpublished-base
conditions.

Fresh independent Standards and Spec review, a fixed complete evidence handoff
and a separate integration/publication grant remain required. This ticket
does not clear NEO-98/102/106, concurrency/unbind/DPM, image integration,
installed-system, clock, electrical or physical qualification gates.
