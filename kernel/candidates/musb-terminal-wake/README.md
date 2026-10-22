# Explicit terminal IRQ/wake composition

NEO-219 combines the unchanged `musb-retirement` queue, unchanged startup
candidate 0029 and bridge 0062. The original wake/startup and retirement
profiles remain independently selectable with their original inputs.
Production's 33 patches and source lock are unchanged.

The bridge carries 0026's checked wake helpers and system-PM policy bodies
onto the retirement queue. Qualification compares those bodies byte for byte
with the unchanged wake/startup profile. Terminal cleanup instead belongs to
`musb_free_irq()`, before action release and `nIrq` invalidation, in process
context without `musb->lock`. The later allocation finalizer sees no action
and cannot repeat disarm against an invalid number. Source/capability cleanup
remains conditional on core ownership. Failed final disarm is diagnosed once
and its debt remains outstanding; freeing an action does not resolve it.

```sh
task test:musb-terminal-wake-reference
task test:musb-terminal-wake
task check:musb-terminal-wake-drivers
task test:musb-terminal-wake-kunit
```

The compiling naive-composition controls reproduce a prospective composition
mistake, not a shipping or installed defect. The native fixture uses actual
probe/remove, wake/IRQ/PM accounting and terminal function bodies with modeled
resource boundaries. The Linux fixture uses real IRQ action/reference
ownership and wakeup-source teardown, including held SRCU/handler waits, with
a simulated chip wake hook. Its explicit fixture debt recovery follows debt
assertions and is not production retry behavior. Complete MMIO, backend/DMA,
SMP, failed-power recovery, system suspend and board qualification remain
separate. [Report 303](../../../docs/303-musb-terminal-wake-composition.md)
records evidence and retained failures.
