# Clock capture deployment and admission

12 October 2026 NZDT. NEO-192. The host/device wrapper for
[report 270's exact-call workload](270-clock-userspace-boundary.md) is implemented
and checked offline. **No GameShell access occurred.** The instrumented image
is still unbuilt, and the original clock fault remains unresolved.

## Matching the executing code

The host first verifies the reader's retained build inputs/outputs, current
sources, ARM fixture replay, ELF properties and imports against the previously
captured, hash-verified target libc. It requires an explicitly selected
`clock_provenance` image experiment and a kernel configuration enabling the
recorder. It also checks the image's source inventory, completed kernel
receipt, matching configuration and verified raw-image hash/identity.

The completed-kernel inventory now includes **`vmlinux`**. Its GNU build ID is
used alongside the kernel release and exact configuration hash. The device
parses `/sys/kernel/notes` and compares the running build ID before opening
the recorder. Matching a release string alone cannot admit this operation.
Historical image receipts remain unchanged; they are not regenerated to make
an old image appear instrumented.

The reader also inventories the vDSO **in the capturing process**, outside the
armed interval. It binds `AT_SYSINFO_EHDR` to the loader's mapping and verifies
the opened handle's base before testing unversioned and `LINUX_2.6` clock
exports. Both time32/time64 clock exports must be absent. Missing mapping
evidence or any clock export refuses capture. The locked clocksource-ID header
is checked at reader-build time; the architectural source's numeric ID is 1.

The device independently checks staged file hashes, interpreter/libc identity,
boot, running image/configuration, clocksource, namespace, affinity, initial
PID namespace and single-task ownership. Python runs with `-I -S -B`, without
site/environment customization or bytecode files in the private stage.
Loader overrides, configured preload, Python tracing, taint, active PM tests,
missing services or absent USB power refuse admission. Before/after evidence
must agree. Existing battery restart counts are preserved rather than reset;
this awake diagnostic does not claim they are healthy.

## Bounded execution and original results

The host starts one uniquely named transient systemd unit, with a 45-second
runtime limit and five-second stop timeout. An independent **60-second host
deadline** supervises it. Both the normal completed-unit path and errors stop
that same owned unit. A lost start acknowledgement never triggers a second
launch. The wrapper checks process/control PIDs and unit state after stop; a
timeout or successful stop command by itself is not proof of termination.

`RemainAfterExit` retains the original exit status until the host has read it.
The host then retires the unit. Full completion requires its successful normal
exit, confirmed termination, unchanged device state and an independent host
replay of the downloaded originals. Failed, partial or unconfirmed work leaves
the private stage available for investigation.

On the device, the opened descriptor is released even if workload preallocation
fails. Close is idempotent and never retries an ambiguous close on a potentially
reused descriptor. Termination signals request graceful partial export; process
loss, SIGKILL or an indefinitely blocked original kernel call can still prevent
export and must remain incomplete.

The original kernel bytes and userspace JSON are saved **before** postflight or
replay. A changed postflight or malformed stream does not discard those
originals. Files are exclusive-create and made readable by the owner of the
private staging directory. Fully validated downloads are retained locally and
their specific remote files removed. No secret values or raw captures enter Git.

An operation can complete while reporting a backwards clock or a boundary
mismatch. Such findings are retained; neither host nor device output grants
PM admission or clock-reliability qualification. The wrapper changes no
clocksource, affinity, charger setting, battery service, display or PM policy.

## Repeatable commands

```sh
task test:clock-deployment
task check:clock-boundary
# Future use only after a matching instrumented image is built and installed:
task device:clock-boundary BUILD=<reader-build> RUNTIME_CAPTURE=<runtime-inventory>
task report:clock-boundary KERNEL=<kernel.ndjson> USERS=<users.json>
```

The reader build runs the 14 boundary and 17 deployment test cases, native
sanitized fixtures, ARM fixtures and production library checks in the pinned
offline container. Device credentials remain in `.env`. The device task holds
the existing host PM-operation lock and checks for device PM tests; the kernel
itself enforces exclusive recorder ownership.

Final accepted build:
`.local/diagnostics/20261011T124945.184873Z/build-receipt.json`.
ARM library SHA-256:
`41f2dbb4b4b88e1014a1693277a64a95df39b81823ee515e70b2ce5845e680c1`.
All 27 ARM raw-buffer fixtures replay independently on the host.
Full host checks pass: **24 runtime and 1,001 tooling tests**, one optional
skip, both existing C checks and Bash/ShellCheck. The full log is
`.local/build/clock-deployment-check.log`.

The new offline admission routine was also run against the retained real
diagnostic.25 image/configuration and runtime inventory. Reader verification
passed, then admission refused it with
`Required instrumented configuration is absent: CONFIG_NEO_CLOCK_DIAG`.
That check never connected to the device. The result is saved alongside the
build as `old-image-admission.json`.

Fixtures establish the wrapper's refusal, persistence, deadline and ownership
logic. They do not establish live systemd behavior, full kernel-to-Python
correlation or a hardware cause. The next step is to compose the diagnostic
kernel into a separately identified image, validate the final composition,
build/verify it and then arrange the card swap. NEO-192 stays open; NEO-191 and
NEO-182 PM admission remain pending.
