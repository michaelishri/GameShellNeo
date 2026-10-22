# Wakeup sysfs frontend errors (NEO-223)

Candidate 0071 is opt-in and outside the image queue. It changes only
`drivers/base/power/sysfs.c:wakeup_store()`: failed enable requests return the
existing API error, already-enabled requests succeed without another allocation,
and a concurrent successful attachment (`-EEXIST`) remains idempotent success.
Disabled writes retain their existing behavior.

The brief `power.lock` observation finishes before any allocation or SRCU wait.
The patch does not change internal allocator, attach, detach or lifetime APIs.
The current registration API collapses lower failures to `NULL`, so its public
enable error is `-ENOMEM`, including a lower source-registration `-EIO`.

`kernel/tests/wakeup-sysfs-reference.c` compiles the exact extracted frontend
with bounded API/lock shims. It reproduces the dropped errors and rejects
separate compiling controls for error loss and both idempotency decisions.
Its modeled allocation results do not qualify real allocation, sysfs, SRCU or
device lifetime; the dedicated real-kernel suite is required for those claims.

Report 307 records the finite twelve-case kernel plan, exact four-failure
control and remaining qualification. NEO-98 retains MUSB IRQ/DPM, terminal
composition, deliberate image integration and physical acceptance separately.
