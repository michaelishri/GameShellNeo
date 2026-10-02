# Checked wake-interrupt ownership (NEO-78)

2 October 2026. Source and offline tests only; the running board remains on
diagnostic.13. No PM stage, wake policy or charger setting changed.

## Result

Patch 0019 makes parent wake errors visible for the CPI v3.1 interrupt topology
and tracks the wake references actually owned by PEK, RTC and AC. A failed
second power-key arm unwinds the first. Failed cleanup remains recorded, and
must succeed before another suspend can acquire a new reference. Resume also
restores interrupts disabled by that particular suspend, even if wake policy
has since changed.

Previously, these drivers discarded errors; regmap also deferred parent wake
changes to a void bus-unlock callback, hiding the parent's result from its
caller. Checking only the client return therefore could not establish success.
These are source defects, not evidence of a failed physical wake on this board.

## Locking and scope

Regmap selects direct, checked parent propagation only when there is no separate
wake-register bank and the registered parent chip has neither bus-lock hook.
Selection happens after IRQ registration, which can select the parent's chip.
The inspected R_INTC parent qualifies. Its parent API cannot take a sleeping
bus lock, and regmap's child descriptor has a distinct lock class. The public
IRQ API retains shared-parent reference counting.

Nested controllers with sleeping bus locks and controllers with wake-register
banks retain the existing deferred path. Their general error reporting is not
fixed here. The registered parent's bus-lock contract must remain stable;
ordinary register mask/acknowledgement failures are also outside this patch.
[The locking research](99-wake-irq-locking-research.md) records the upstream
nested-regmap counterexample and the selection constraints. This is not a
kernel lockdep or concurrency qualification claim.

The PEK guard also skips an unregistered AXP288 input device. RTC cleanup uses
actual ownership rather than today's wake policy. AC records the disabled IRQ
range and restores it even after a wake-disarm failure. USB already has its
own checked ownership from patch 0010; the new parent path completes that
error-propagation chain for the eligible board topology.

## Reproducible validation

```sh
task test:wake-irqs
task check:wake-drivers
task check
```

The first task extracts actual IRQ-core reference accounting and actual patched
regmap/PEK/RTC/AC functions from the SHA-256-verified Linux 6.18.54 archive. The
candidate passed natively and as ARM32 code under QEMU. Coverage includes
first/second arm failures, partial rollback, failed disarm and retry, policy
changes, shared PEK/AC/USB-equivalent references, and ten repeated cycles.
Five intentionally broken variants were rejected: lost parent error, sleeping
parent selected, lost PEK ownership, lost RTC ownership and lost AC cleanup.
The deferred-path accounting is checked without claiming full slow-bus I/O
qualification. Deterministic shims replace IRQ hardware and scheduling.

The complete four modified drivers compiled successfully for ARM in isolated
scratch with the pinned builder. The resolved configuration hash remained
`d370205bf2e4eed5e35483f15372a6785e7d96252d40c343dfee0b2dde37a017`.
Private evidence, including source/patch hashes and object hashes, is in
`.local/build/wake-irq-tests/compile-evidence.json`; the build log is
`.local/build/wake-drivers.log`. Immutable run copies were retained as
`.local/neo78-wake-irq-compile-evidence.json` and
`.local/neo78-wake-drivers-full.log` before a later run can replace the generic
task outputs. Shared checks passed: 13 runtime tests and
322 tooling tests (one existing optional skip), C checks and shell lint.

## Remaining gates

Build the separately versioned candidate alongside diagnostic power-key
ownership and RTC preparation. Qualify ordinary callbacks first, then the
new guarded `platform + freeze` boundary with the owner watching. Normal
sleep remains masked; no actual wake, latency or energy result is claimed.
Kernel lockdep, physical interrupt delivery, generic nested-controller wake
errors and broader PMIC wake-source policy remain separate qualification work.
