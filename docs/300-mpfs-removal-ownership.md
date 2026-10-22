# MPFS parent resource and PHY ownership

23 October 2026 NZDT. NEO-215 is a bounded software subtask of NEO-106 in
the isolated `work/mpfs-removal-ownership` checkout. NEO-214 and its original
test/evidence worktrees remain frozen. No Mac/GameShell, live unbind, PM,
reset, selector or production-image operation has occurred.

The pinned `mpfs_remove()` first disables the parent clock, then unregisters
its MUSB child. That child can still perform client, IRQ and DMA cleanup that
requires its registers. The same function then passes its own parent `pdev`
to `usb_phy_generic_unregister()` even though probe registered a distinct
`glue->phy`. The actual generic helper directly unregisters its argument;
unregistering the parent from its own remove callback can recurse into device
teardown and leaves the owned PHY behind. These are source defects, not
observed board faults.

[Candidate 0061](../kernel/candidates/musb-retirement/0061-mpfs-parent-resource-lifetime.patch)
unregisters the actual MUSB child, unregisters the owned PHY, then disables
the parent clock. It changes only `mpfs_remove()` and remains in the explicit
offline `musb-retirement` profile. The MPFS backend is not selected for the
CPI v3.1 production image; these tests do not choose a new image queue.

The partial-probe audit found that the common error labels can pass NULL or
an error pointer to the generic helper. Both actual Linux 6.18.54
`platform_device_del()` and `platform_device_put()` guard `IS_ERR_OR_NULL()`.
Those early calls are benign. The earlier audit lead and its correction are
retained in Kaneo; no unwind crash is claimed and no error-label refactor is
included. All original failure returns and acquisition unwind remain intact.

```sh
task test:mpfs-ownership
task check:mpfs-ownership-drivers
task test:mpfs-ownership-kunit
```

The native fixture executes actual MPFS probe/remove, actual generic PHY
register/unregister and actual platform unregister/del/put function bodies.
Forty cases cover success and all nine acquisition failures, with explicit
and default roles and both external-VBUS settings. Two further cases exercise
the real platform helpers' NULL/error-pointer admission. All **42 scenarios**
pass natively, under ASan/UBSan and on ARM32/QEMU. This static fixture allocates
no heap; the known host ptrace constraint is handled by explicitly disabling
LSan while retaining fail-fast ASan/UBSan diagnostics.

The original source and three independent mutations (early clock disable,
wrong PHY owner and omitted PHY unregister) each fail their required native
assertion. Device/clock acquisition effects are modeled in this fixture;
their actual Linux framework cleanup is tested separately below.

Complete `drivers/usb/musb/mpfs.o` builds pass the valid ARM `COMPILE_TEST`
route with verified effective `USB_MUSB_POLARFIRE_SOC`, dual-role MUSB and
NOP PHY selections. Separate configurations cover built-in PIO, built-in
Inventra DMA and modules with DMA. Receipts pin each effective config, object,
compiler/ELF record, complete applied queue and builder. The compile receipt
`.local/build/mpfs-ownership-tests/compile-evidence.json` has SHA-256
`e475f21cd0d58738cf2135494a28d55e3f060bc62c31a549dc39973dd1d3796e`.
The earlier PHY object's qualification is not substituted for this backend.

The complete test-instrumented MPFS object and UML kernel compile, and all
three real-kernel cases pass under KASAN/lockdep without diagnostics. They
execute actual MPFS removal against
real registered platform parent/child drivers, generic PHY unregister and
common-clock APIs. A held child remove callback checks that the parent clock
stays enabled until it returns. Extra owned references keep child/PHY objects
inspectable after unregister. The original source control safely intercepts
its wrong-parent unregister to avoid recursive unbinding while observing both
defects. The exact-case validator rejects missing, skipped or failing cases
and kernel diagnostics. Managed run `1f13c148afec41dbb33b3337a8d99b75`
is terminal with exit zero and no active stage container. Receipt
`.local/build/mpfs-ownership-kunit/evidence.json` has SHA-256
`0a673015c3d28412c418ab94f1256d747e90947175164f9d76915684cbe977d4`.
Independent kernel/config/log/results copies are retained beneath
`.local/build/mpfs-ownership-kunit/kernel-205cff4a3cf38702/accepted-runs/9d31b76855a648ff9d9e0b31a97141f4/`;
all maintained input and accepted-artifact hashes match.

The original isolated checkout's `task check` passes all 1,283 regressions
(nine skipped), current-limit/mount guards, Bash syntax and ShellCheck. Strict
checkpatch (`--no-tree --strict --no-signoff`) reports zero errors, warnings
or checks. Final accepted-base combination and independent
review remain pending.

Controller MMIO and the complete MUSB client IRQ/DMA/timer graph remain outside
this bounded resource test. In particular the MPFS timer/IRQ rearm contracts,
caller/global-accessor retirement, inaccessible-hardware cleanup and combined
image/physical removal gates remain NEO-106 work. Neither compilation nor the
synthetic clock/provider fixture qualifies real MPFS hardware. Fresh independent
Standards/Spec acceptance and serialized publication remain required. Diagnostic.27
stays unconfirmed with fixed recovery the default; no clock/PM fault is cleared.
