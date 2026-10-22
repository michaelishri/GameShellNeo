# OMAP2430 mailbox ownership candidate

NEO-222, related to NEO-102 and NEO-106, adds explicit ownership for the core
mailbox publisher and OMAP2430 child users. This is an opt-in offline profile.
It does not select a production image or qualify the GameShell hardware.

`musb-omap-mailbox` composes the unchanged `musb-retirement` queue, unchanged
0029 startup/runtime-PM candidate and new 0063. It has no 0026 or NEO-219/0062
dependency. Existing profiles, production patches and source locks are retained.

0063 unpublishes the exact controller owner and drains admitted dispatch before
backend work is disabled. Work drains before the parent-PM child gate closes,
because running work may need to resume the parent. Child readers then drain
before clients or PHY resources retire. Both OMAP parent runtime callbacks use
the same child admission; their admitted hardware sequence and reference/error
behavior are retained. A missing or closed child keeps the original successful
no-op behavior. The cached parent-owned status level survives child rebind;
it is retained information rather than a guaranteed fresh physical reading.

Saved qualification commands, with the pinned archive/builder and managed
container ownership, are:

```sh
task test:omap-musb-mailbox-reference
task test:omap-musb-mailbox
task check:omap-musb-mailbox-drivers
task test:omap-musb-mailbox-kunit
```

The first Task reproduces four original schedules. The native candidate checks
32 bounded cases, ASan/UBSan, ARM32 execution and nine compiling assertion
controls. Complete-driver qualification selects OMAP in six configurations.
All 12 Linux cases pass with real SRCU/work/device/runtime-PM operations against
a synthetic controller and PHY provider. This includes the held parent
callbacks and parent PM/glue/PHY consistency after closed callbacks and rebind.

[Report 306](../../../docs/306-omap-mailbox-ownership.md) records source seams,
receipts, retained failed originals and the remaining qualification gates.
Other backend/DMA lifetime, failed-power MMIO, full system PM, SMP, image and
physical qualification remain separate. NEO-102 and NEO-106 stay open.
