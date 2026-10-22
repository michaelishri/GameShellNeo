# Managed wakeup initialization errors (NEO-229)

Candidate 0072 changes only `include/linux/pm_wakeup.h:devm_device_init_wakeup()`.
It returns a failed `device_init_wakeup()` result before adding managed cleanup.
Successful initialization still uses the existing `devm_add_action_or_reset()`
return/reset path. Capability changes made by the underlying API are preserved;
this wrapper neither adopts an existing source nor makes initialization idempotent.

The dedicated Tasks append 0072 explicitly to the unchanged production queue.
There is no candidate-profile registration or image selection:

```sh
task test:managed-wakeup-init
task check:managed-wakeup-init-drivers
task test:managed-wakeup-init-kunit
```

The first Task compiles exact original/candidate inline bodies for native,
ASan/UBSan and ARM32 execution with explicit framework models. The second builds
selected real ARM PM-sleep and PM-without-sleep objects. The third requires the
original-wrapper control's exact two failed cases/eight assertions and all five
candidate cases in actual Linux PM/devres/IDA/device lifetime. Current-run
output and authoritative released managed ownership are mandatory.

[Report 315](../../../docs/315-managed-wakeup-init-error.md) records primary-source
research, the finite contract, original outcomes and limits. No installed CPI,
MUSB/DPM, image, hardware or parent-ticket completion is implied.
