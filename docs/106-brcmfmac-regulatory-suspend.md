# Wi-Fi country requests across suspend (NEO-82)

3 October 2026, Pacific/Auckland. Patch 0020 prevents the brcmfmac regulatory
notifier from issuing country commands between its wiphy suspend and resume
callbacks. The latest valid request is applied after the parent transport has
resumed. Native/ARM32 callback regressions and complete ARM driver compilation
pass. This is a source fix awaiting hardware qualification under NEO-84;
diagnostic.14 remains installed and unchanged.

## Evidence and cause

[Reports 104](104-diagnostic14-hardware-qualification.md) and
[105](105-diagnostic14-late-noirq-repeats.md) preserve the observed errors.
Both management routes eventually recovered, but several PM cycles logged
country GET/SET failures and control-response timeouts. Similar messages occur
in diagnostic.13, before the wake-IRQ changes in diagnostic.14.

Raw printk timestamps make the ordering clearer than journal receipt times:

| Observation | Debug hold starts | Control failure | Following evidence |
| --- | --- | --- | --- |
| First devices test | 358.766614 s | Timeout at 361.227544 s, then country SET rejection | Failure is inside the five-second suspended hold |
| First platform test | 612.446219 s | Timeout at 617.447277 s, country GET `-110` at 617.447333 s | RSB restoration begins at 617.450009 s |
| Platform repeat 1 | 1152.196723 s | Country SET rejection at 1157.197404 s | RSB restoration begins at 1157.199319 s |
| Platform repeat 2 | 1245.967136 s | Country SET rejection at 1250.968215 s | RSB restoration begins at 1250.970482 s |

Private captures are `.local/neo82-kernel-raw.log` and
`.local/neo82-kernel-raw-after-repeats.log`. These are original kernel times;
do not subtract them from ftrace times without aligning the clock offsets.
The generic SET rejection text does not distinguish a transport timeout from
a firmware refusal. The GET error explicitly reports `-ETIMEDOUT`.

The locked Linux 6.18.54 source permits this sequence:

1. `wiphy_suspend()` holds RTNL and the wiphy lock while invoking brcmfmac's
   suspend callback, then releases both locks.
2. Regulatory work runs on the ordinary system workqueue. It is not frozen
   with userspace/freezable workers. Its notifier calls are serialized by
   RTNL, but previously had no brcmfmac suspend gate.
3. The SDIO parent collects and parks the radio's service workers. A regulatory
   notification can therefore issue a country command after wiphy suspend,
   with no available worker to complete its reply during the hold.
4. The existing transport rejects commands once down, but that does not protect
   a command already admitted before the workers park.

This identifies an unprotected command path consistent with the recorded
country failures. It does not prove that every channel-query timeout, rejected
packet or delayed control frame shares this cause. The older intermittent
authentication failure remains NEO-55.

## Driver change and ownership

[Patch 0020](../kernel/patches/0020-brcmfmac-regulatory-suspend.patch) changes
`cfg80211.c` and its private state in `cfg80211.h`. It adds no worker, timer,
polling interval or new mutex. The existing RTNL ownership serializes notifier
execution with the suspend and resume callbacks; assertions document that
requirement. Registration's notifier path also runs under RTNL.

At every successful exit from the suspend callback, including the not-ready
interface case, the driver closes country-command admission. Subsequent valid
notifications replace a two-byte pending country code without firmware I/O.
The existing ignore rules for `00` and invalid alphabetic codes remain intact;
they do not replace an already pending valid request.

After the parent transport's resume and existing WoWL restoration, wiphy resume
reopens admission and consumes the pending request once. The factored helper
retains the existing country GET, mapping, SET and band-refresh sequence.
An already matching country remains a successful no-op after the GET.
Subsequent awake notifications follow the same immediate path as before.
Coalescing applies only to brcmfmac's deferred firmware writes, not to Linux's
regulatory request processing or channel restrictions.

There is one intentional failure-policy change: errors applying a deferred
request propagate from the wiphy resume callback. The cfg80211 core then closes
that wiphy's interfaces and reports the resume error. This avoids declaring
success with an unapplied request. It can leave Wi-Fi unavailable after a real
country/mapping/transport error, so qualification must retain independent USB
access. Pending state is consumed even on failure; there is no silent replay
loop. The ordinary awake notifier retains its void API, and the SET failure
message now includes its actual errno.

Country mapping, regulatory database, firmware binary, configured country,
association policy and charging settings are unchanged. The change applies
to brcmfmac's common cfg80211 callbacks; only CPI v3.1 SDIO is targeted for
hardware qualification. Other transports and WoWL remain unqualified.

## Reproducible validation

```sh
task test:brcmfmac-regulatory
task check:brcmfmac-regulatory-driver
task check
```

The saved checker verifies the locked archive, applies patch 0020 without fuzz,
and extracts the actual country mapping/helper/notifier and full suspend/resume
callback bodies. The C harness models RTNL ownership, parent ordering and
firmware calls. Firmware access outside the modeled awake interval fails an
assertion. It is a deterministic callback test, not kernel concurrency or
lockdep testing.

Sixteen scenarios pass natively and under ARM32 emulation. They cover ordinary
and WoWL callback branches, ready/not-ready interfaces, latest-valid-request
coalescing, ignored requests, no-pending and same-country cases, mapping tables,
GET/SET/band/missing-interface failures, no duplicate replay and repeated cycles.
Nine deliberately broken variants fail by assertion, including removing the
deferral, losing a pending request and swallowing a replay failure.

The complete `brcmfmac/cfg80211.o` also compiles as ARM ELF32 with the full
project patch queue and locked builder/configuration. The first full compile
caught a missing `linux/rtnetlink.h` include for `ASSERT_RTNL`; that was corrected
before the successful final compile. The source tree, installed modules and
diagnostic.14 artifacts were not overwritten.

| Final evidence | Value |
| --- | --- |
| Patch SHA-256 | `01afc0758ba3df6acf16cb36dc9bd1d77f1b0d1e87ece73dca8dc9bd238ddb4f` |
| C harness SHA-256 | `5c591b570148f9ecf6d04d5f9cf27efa5a76a83ab0d3c524989013a32135401f` |
| ARM object SHA-256 | `fd4edc398eff260b00d9e21b8310dd60c1d2e452bb664dcb52abea503f057824` |
| Compile scratch | `.local/build/brcmfmac-regulatory-tests/kernel-481d43eddfab19d0/` |
| Results and source hashes | `.local/build/brcmfmac-regulatory-tests/compile-evidence.json` |
| Full driver transcript | `.local/build/brcmfmac-regulatory-driver.log` |
| Host checks | 13 runtime tests; 346 tool tests with one optional skip; compiled current-selector/mount-guard checks; Bash syntax and ShellCheck passed |

`task build` includes the new callback regression. All tests here use the build
host; no new device test, image build, flash or live driver replacement ran in
this implementation slice. No latency or energy saving is claimed.

## Next qualification

NEO-84 owns a clean diagnostic image and hardware comparison. Preserve
diagnostic.14 recovery, use the existing verified flash workflow, and establish
startup, country state, independent routes and integration first. With fresh
owner readiness, repeat the guarded freezer/devices and late/noirq sequence.
Compare original kernel error times, final radio state, callback results,
keypad continuity, screen return and all restoration checks. Preserve any
deferred-update error instead of changing country or adding retries to pass.
Actual sleep remains disabled.

An adjacent source issue is deferred in `FOLLOW-UP.md`: `brcmf_setup_wiphybands()`
can use uninitialized `nmode` after a failed firmware GET. Patch 0020 propagates
the helper's existing return value; it does not claim all its internal queries
are checked. That separate error path needs its own regression and correction.

## Source references

The primary evidence is the SHA-verified Linux v6.18.54 archive recorded in
[the source lock](../build/sources.lock.json), commit
`1b357ecb321392158d507b04672ffee57bfa071d`:

- [`net/wireless/sysfs.c`](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/net/wireless/sysfs.c?h=v6.18.54): wiphy PM locking, ordering and failed-resume interface shutdown.
- [`net/wireless/reg.c`](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/net/wireless/reg.c?h=v6.18.54): regulatory work, notifier dispatch and RTNL serialization.
- [`net/wireless/core.c`](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/net/wireless/core.c?h=v6.18.54): registration under RTNL.
- [`brcmfmac/cfg80211.c`](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/cfg80211.c?h=v6.18.54): original notifier, country mapping, PM callbacks and band setup.
- [`brcmfmac/core.c`](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/core.c?h=v6.18.54): wiphy parent assignment. Project patches 0014–0018 provide the inspected SDIO worker lifecycle changes.
