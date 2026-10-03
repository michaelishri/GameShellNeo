# Extcon provider lifetime during lookup and removal

4 October 2026, Pacific/Auckland. NEO-106.

Patch 0034 adds `extcon_get_edev_by_fwnode()` and uses it in the Sunxi parent
probe. Lookup now establishes a managed dependency on the registered extcon's
parent driver before returning its resources. The provider must be fully
bound, and the device link must protect the probing consumer. Existing raw
lookup functions retain their previous behavior.

This continues [report 146](146-sunxi-child-notifier-work.md) on
[work/musb-removal-lifetime](https://github.com/michaelishri/GameShellNeo/tree/work/musb-removal-lifetime).
It addresses the extcon provider prerequisite for child-owned notifier draining.
It does not complete the core MUSB removal implementation or qualify removal
of the physical Allwinner PHY and all its other consumers. Diagnostic.18 and
the running GameShell are unchanged.

## Admission and lifetime contract

The old extcon lookup returns a pointer after dropping `extcon_dev_list_lock`.
A caller cannot establish safe driver ownership merely by adding a link later:
the provider could already be unbinding. Keeping a device object referenced is
also different from keeping its driver-owned registration and state available.

The new API holds the extcon device-list mutex from matching the provider
firmware node through `device_link_add()`. Registration cannot be removed
through `extcon_dev_unregister()` during that interval. A new link requests
`DL_FLAG_AUTOREMOVE_CONSUMER`, without adding runtime-PM flags or a permanent
power hold. Existing links can retain their longer lifetime/PM policy. In the
pinned core, upgrading an existing stateless link adds managed ownership but
does not copy the new auto-remove flag, so its managed dependency can remain
after consumer unbind. Releasing the original stateless reference does not
release that managed owner.

Before publishing the pointer, the getter checks both the link's
`DL_STATE_CONSUMER_PROBE` status and the supplier's `DL_DEV_DRIVER_BOUND`
status. Driver-core link creation serializes with supplier unbind. An admitted
probing consumer causes supplier removal to wait for probing to finish; an
active consumer must then be unbound before the supplier driver is removed.
If removal wins admission, the getter returns `-EPROBE_DEFER`. It also defers
for a missing or still-probing supplier. An invalid caller/node or failed link
creation returns `-EINVAL`.

Rejecting a still-probing supplier is deliberate. It can publish extcon before
its probe finishes, then fail. The pinned driver core can roll back that probe
without first unbinding newly probing consumers. Waiting for completed binding
avoids publishing that provider's resources through this API. A concurrent
transition from bound to unbinding can conservatively cause a deferral even
when the new link would have protected access.

Consumers must call the getter from their probe and drain their uses and
notifiers during remove **and before returning a failed probe**. In Linux
6.18.54, `really_probe()` calls `device_links_no_driver()` before
`device_unbind_cleanup()` on failure. Generic devres cleanup after the probe
returns is therefore too late to rely on this newly created link. Normal
unbind orders consumer remove/devres cleanup before link cleanup.

The Sunxi parent acquires the link before creating its child. Its successful
remove unregisters the child first, including patch 0033's synchronous notifier
unlink and worker shutdown. Child init failure has its own synchronous unwind.
There is no fallible parent-probe step after successful child registration.
The parent reference lookup is balanced with `fwnode_handle_put()`.

The provider contract is equally explicit: its parent driver owns the extcon
registration for its bound lifetime and must stop complete event producers
before unregistering/freeing it. This API does not protect a provider which
independently unregisters extcon while remaining bound. Consumer SRCU draining
covers notifier dispatch; the provider must also retire the rest of
`extcon_sync()`, including its subsequent uevent work.

## Real-kernel tests

Patch 0035 adds an optional KUnit suite using synthetic platform drivers,
software firmware nodes and real device links. It runs against Linux's actual
probe/unbind implementation, extcon registration, notifier SRCU, completions
and kernel threads. No physical USB controller is needed.

```sh
task test:extcon-provider-kunit
task test:extcon-provider-kunit VARIANT=tree
task test:extcon-provider-kunit VARIANT=tiny
task check:sunxi-owner-drivers
task check
```

The default KUnit command runs TREE and TINY SRCU sequentially. The saved runner
boots with `fw_devlink=off`, so inferred firmware dependencies cannot account
for the successful provider ordering. Lockdep, RCU and atomic-sleep diagnostics
are enabled. Both kernels have one virtual CPU; these results do not establish
SMP, ARM interrupt or physical PHY behavior.

The ten test cases cover:

| Case | Required behavior |
| --- | --- |
| Bound provider | Successful lookup, callbacks, three consumer rebinds and consumer-before-provider teardown |
| Existing links | Upgrade a stateless link without taking its caller's reference, and preserve an existing persistent managed policy |
| Missing provider | Defer without publishing resources or leaving a notifier |
| Invalid use | Reject a missing consumer, a caller outside probe and a self-link |
| Consumer probe failure | Explicitly drain before returning an error; newly created links disappear |
| Supplier still probing | Defer while it holds probe open; succeed on consumer retry after binding |
| Supplier probe failure | Never publish resources which the failing supplier subsequently frees |
| Supplier already unbinding | Defer while its remove callback deliberately retains the registration |
| Supplier removal during consumer probe | Wait while the consumer holds probe open, then remove the bound consumer first |
| Supplier removal during callback | Enter consumer remove, wait for the held callback, then allow provider remove |

The waiting cases use held completions and bounded observations. The probe
case observes the real driver-core unbinding state before checking that removal
remains pending. The provider explicitly joins its event producer before
freeing extcon, so a callback-only barrier is not mistaken for retirement of
the entire dispatch/uevent operation. Test threads remain alive until fixture
cleanup joins them.

For controlled negative admission cases, the synthetic consumer records the
getter's original error and returns `-EINVAL` to the platform core. This avoids
automatic deferred-probe retries obscuring that observation. The real Sunxi
caller preserves the getter's error, including `-EPROBE_DEFER`.

The result validator requires this exact suite, every expected case once,
matching counts and no skipped/failing cases or kernel warnings. It also checks
the kernel-reported command line for exactly one `fw_devlink=off` setting. It cannot
accept the separate notifier suite as provider evidence. Accepted runs retain
independent copies of the kernel, config, full log and result JSON with hashed
receipts. The latest summary can change without overwriting those copies.

## Recorded kernel result

The final ten cases pass under both TREE/PREEMPT and TINY/PREEMPT_NONE SRCU,
with the explicit `fw_devlink=off` boot argument. The saved strict validator
accepts both complete raw logs and result files. No relevant kernel warning,
lockdep, RCU or atomic-sleep failure appears in these runs.

An earlier nine-case prototype also passed, but is not the final qualification.
The first ten-case run failed an expectation that upgrading an existing
stateless link would remove it on consumer unbind. Inspection of the pinned
core established that this upgrade retains managed ownership and the longer
link policy. The fixture now checks that the link remains available and still
orders subsequent consumer/provider removal. The production patch was not
changed to satisfy that expectation. The failed raw log and result remain in
`kernel-tree-1543afc245f35a74/`; no accepted receipt was issued for that run.

The current test inputs, exported patch manifest, complete source inventory,
independent artifact copies and per-run receipts were checked after both runs.
Strict checkpatch accepts patches 0034/0035 and the fixture with zero errors,
warnings or checks.

| Artifact | SHA-256 |
| --- | --- |
| Patch 0034 | `5d3de524fd4850b7c4d6319b6ada7e58cf30921ad85932d92abf5ea20affa40b` |
| Patch 0035 | `c533b2250ba8ad87f9e502607cba2c4899d894700bc69c1adbdcc174a35977ab` |
| Provider fixture | `ebad19dfe46ddbde74e4e5a818118d53e64f27d9fa5f35e84d79cb075573db2d` |
| KUnit summary | `f6d82754ebb8c4455e8a22f927146c7928fbf68e15b1eb832a0680aa875abd4c` |
| Complete source inventory | `c87446dcce3f31114ff925d0645d743d778a9d3f76e7949bfc5c73a2bc704ff4` |

Accepted artifacts live under `.local/build/extcon-provider-kunit/`:

- **TREE:** `kernel-tree-edf8458cdc5f1f8a/accepted-runs/f0879d374b2e44a5a03ea7957c41aee1`.
  Kernel SHA-256 `cfc2675d446c33ba652438b66dd095b926b34777c0c59aba84dd61ea87b0e41c`;
  receipt SHA-256 `ef7b04be5fb19e16afb8f51cbf8eec0d21560313ef84fec7b6e9e01a46730b51`.
- **TINY:** `kernel-tiny-0b6f7d79dec0d8a7/accepted-runs/37a59f609e36425f91b33eab7aaa168a`.
  Kernel SHA-256 `acaa11c65a3b8c27a94f94f85460c396313f2b992f45bf813e3b0e15a913d001`;
  receipt SHA-256 `d1894135c5d5593e330f8c88926d898ef5372a79b1ac4c9fcd03506ad3417a6d`.

The logs are `.local/extcon-provider-qualified.log` and
`.local/build/extcon-provider-kunit.log`. The nine-case prototype and failed
ten-case attempt retain separate scratch directories; neither replaces these
final accepted artifacts.

The current queue also passes all 240 Sunxi child-source scenarios natively
and on ARM32, with seven deliberate negative controls failing as required.
Sunxi and extcon objects compile in peripheral, host and dual-role ARM
configurations. Every Sunxi object references the linked getter rather than
the old raw getter; extcon defines its exported symbol and references
`device_link_add()`. Object/config hashes, the full source inventory and the
patch queue match the final KUnit source. These are ARM object builds, not a
complete linked image or physical role qualification.

ARM evidence is `.local/build/sunxi-owner-tests/compile-evidence.json`, SHA-256
`7c70d99e386c3ea241eb8201594ab6cbaab94cd676150fb166561d70948236ee`.
Outputs under that directory are `kernel-ec2f0fe684840d01` (peripheral),
`kernel-cffeccb58bb0c9ee` (host), and `kernel-3017bbff9245d401` (dual role).
Report 146's original receipt was retained separately before the latest summary
was replaced. The ARM task log is `.local/build/sunxi-owner-drivers.log`.

The final `task check` passes 13 runtime and 495 tooling tests, with two
existing optional skips, plus C regressions, Bash syntax and ShellCheck.
Its full log is `.local/extcon-provider-final-host-check.log`.

## Integration limits and next work

The physical Sunxi driver itself is not executed by these KUnit cases. Its
getter call and parent-probe paths compile on ARM; complete kernel linking
and later image/board qualification remain required. The ARM fixture from
report 146 executes child and worker hooks with modeled boundaries; it is not
a substitute for this real provider test or for physical remove/rebind testing.

On CPI, the USB PHY supplies the extcon registration, but this must not become
an assumption for every Sunxi configuration. Other generic PHY consumers and
configurations with different extcon/PHY providers retain separate lifetime
obligations. The pinned generic `phy_get()` uses a stateless device link, which
alone does not order driver unbind. Audit those consumers before attempting
physical provider unbind, particularly when inferred firmware links are absent.

The remaining NEO-106 implementation must retire the core shared IRQ, delayed
work/timers and runtime-PM callbacks before releasing resources they access,
while preserving endpoint cleanup and completion requirements. The other
backend contracts in [report 141](141-musb-removal-backend-contracts.md) still
apply. Full kernel/image validation and attended hardware tests remain required
before deployment. No boot-time or energy-saving result is claimed here.
