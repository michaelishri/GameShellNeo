# Wi-Fi band capability query errors (NEO-86)

3 October 2026, Pacific/Auckland. Patch 0022 makes band setup return failed
required reads and transport errors instead of using indeterminate or guessed
capabilities. Legacy firmware-rejection defaults for optional queries remain.
Native/ARM32 tests and full ARM compilation pass; diagnostic.15 is unchanged.

## Findings

The locked `brcmf_setup_wiphybands()` declares `nmode` without initialization,
logs a failed GET and continues. `brcmf_fil_iovar_data_get()` copies a response
only on success, so the later `if (nmode)` can read an indeterminate value.
No observed GameShell outage has been attributed to this path.

Other scalar queries mix optional compatibility with transport failures:

- VHT mode, stream count and beamforming reads discard all errors.
- RX-chain failure always falls back to one chain, including timeouts.
- The void bandwidth helper hides transport failures behind a legacy query or
  default. A failure of its second band query triggers a kernel warning and
  still reports no failure to the caller.
- Channel state is changed before optional VHT scalar queries finish.
- An excessive RX-chain bit count reaches an HT `memset()` with that count
  and a VHT map that can represent only eight spatial streams.

The ordinary fwil API maps **all negative firmware replies** to `-EBADE`, not
just unsupported-command replies. Transport errors remain separate. Therefore
this patch cannot claim that an `-EBADE` fallback proves a command is unsupported.
It preserves the existing firmware-rejection compatibility policy while
stopping transport failures from being treated as valid capability data. It
does not toggle the interface-wide `fwil_fwerr` mode to recover raw statuses.

## Behavior

| Query/result | New behavior |
| --- | --- |
| Required `nmode`, any error | Return the original error before any use or band mutation |
| Optional VHT mode/stream/beamforming, `-EBADE` | Keep initialized zero default |
| Optional VHT query, transport error | Return the original error |
| RX-chain `-EBADE` | Keep the legacy one-chain fallback |
| RX-chain transport error | Return the original error |
| Initial bandwidth query `-EBADE` | Try the existing legacy `mimo_bw_cap` query |
| Initial bandwidth transport error | Return it without a speculative fallback query |
| Second band query `-EBADE` | Keep that band's 20 MHz default; no kernel warning |
| Second band transport error | Return it |
| Legacy bandwidth query `-EBADE` | Preserve both 20 MHz defaults |
| Legacy bandwidth transport error / unknown successful value | Return original error / `-EINVAL` |
| RX-chain count greater than eight | Return `-EINVAL` before capability mutation |

Successful capability values and existing legacy mappings are preserved. The
zero-chain successful response retains existing behavior; this patch does not
claim a complete semantic validator for every firmware-provided bitfield.

All scalar capability reads and the chain bound now complete before calling
`brcmf_construct_chaninfo()`. A scalar failure therefore leaves advertised
channel and HT/VHT state untouched. The bandwidth arrays changed during queries
are private stack data. The existing channel-construction error propagates as
before; its internal partial mutation is **not** made transactional here.

These errors are visible both during initial wiphy setup and to patch 0020's
country helper. A deferred country-refresh failure can therefore fail resume;
patch 0021 holds network transmission until the configuration result is known.
The ordinary regulatory notifier still has a void API. Independent USB recovery
remains required for later hardware tests.

## Reproducible checks

```sh
task test:brcmfmac-band-queries
task check:brcmfmac-band-query-driver
task check
```

`task build` includes the new test. The checker verifies the locked archive,
applies patch 0022 without fuzz, and extracts the actual bandwidth and full
band-setup functions. The firmware model does not write failed response values,
matching fwil; channel and HT/VHT consumers record invocation and inputs.

**85 scenarios** pass natively and on ARM32: normal HT/VHT values; four distinct
transport errors at each of nine query positions; required-query firmware
rejection; optional defaults; all three legacy bandwidth modes; first/second
band and legacy fallbacks; invalid legacy response; chain counts 0–32; no HT/VHT;
channel-construction failure and a successful later call after an early error.
Every injected scalar error checks the returned errno, last query and absence
of channel/capability mutation. Ten deliberately broken variants fail by
assertion, including moving channel mutation before the VHT queries.

The full ARM `cfg80211.o` compiles with the complete project patch queue,
including 0020 and 0021. The resolved configuration is unchanged. Host checks
pass 13 runtime and 346 tooling tests (one existing optional skip), the compiled
current-selector/mount-guard checks, Bash syntax and ShellCheck.

| Evidence | Value |
| --- | --- |
| Patch 0022 SHA-256 | `f324dac4ce497da7c85238289e4c59fe35e30c4b2314270c4d355c92a952fefc` |
| Harness SHA-256 | `608e0ba9d201f29b0bda2eb7cfd0e121d1e7c58f192dc7f7c12fe4c327ce7b9f` |
| ARM cfg80211 object | `d62c922727e97c9ac1d00d7f3165ee836ea28d6b4bb3a73bc6bb0d4e5a31ccf3` |
| Resolved Kconfig | `d370205bf2e4eed5e35483f15372a6785e7d96252d40c343dfee0b2dde37a017` |
| Isolated compile | `.local/build/brcmfmac-band-query-tests/kernel-d38295f17f46666b/` |

Full metadata is `.local/build/brcmfmac-band-query-tests/compile-evidence.json`;
the saved build log and `.local/neo86-*.log` retain command results. This is
actual-function testing with modeled consumers, not a firmware simulator or
hardware failure-injection result.

## Remaining channel work and hardware gates

The audit also found that `brcmf_construct_chaninfo()` mutates channel flags
while processing replies, and a later successful `per_chan_info` query can
overwrite an earlier error. It clears band flags before validating the complete
chanspec count. These need separate first-error and transaction coverage;
patch 0022 does not claim to repair them. Other successful scalar bitfields and
stale capability flags on a changed mode also need a bounded validation audit.
They are recorded in `FOLLOW-UP.md`.

The next candidate can include 0021/0022 together after preserving diagnostic.15
recovery. Offline verification precedes transfer and the later owner-assisted
flash. Recheck initialization, association, country handling and attended PM
restoration. No new hardware command or PM test ran for this source slice.
No energy saving or actual sleep qualification is claimed.

Primary source anchors are the SHA-verified Linux 6.18.54 archive: brcmfmac
`cfg80211.c` (bandwidth/setup/channel/update helpers), `fwil.c`/`fwil.h`
(error mapping and successful-only response copy), and
`include/linux/ieee80211-{ht,vht}.h` (ten-byte HT mask and eight-stream VHT map).
