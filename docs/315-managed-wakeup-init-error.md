# Managed wakeup initialization errors (NEO-229)

23 October 2026, Pacific/Auckland. This offline child of NEO-98, related to
NEO-102/106, starts from published `d5d67790668f4cb2b3d308a5b60da03c26b04911`
in `work/managed-wakeup-init-error`. Candidate 0072 is explicitly appended only
by its dedicated saved Tasks. The production queue, source lock, all existing
profiles and image selection are unchanged. This is shared driver-API source
correctness, not a reproduced fault in the installed CPI system.

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

Real Linux and selected driver qualification are prepared but still pending.
The first idle heavy-resource lease was explicitly returned unused so another
worker could build; no operation was stopped. New source preparation/UML/object
stages require a fresh host-resource lease, serial j1, bounded disk footprint
and current-run evidence. Existing caches and original proof remain immutable.

Fresh independent Standards and Spec review, a fixed complete evidence handoff
and a separate integration/publication grant remain required. This ticket
does not clear NEO-98/102/106, concurrency/unbind/DPM, image integration,
installed-system, clock, electrical or physical qualification gates.
