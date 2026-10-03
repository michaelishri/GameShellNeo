# Base-rootfs cache identity (NEO-99)

4 October 2026, Pacific/Auckland. Source/tooling validation completed; the
diagnostic.18 build will establish the first cache record with this key.
No build-duration saving has yet been measured.

The previous cache key hashed the whole source lock. A change from
`diagnostic.17` / `-gameshellneo17` to `diagnostic.18` / `-gameshellneo18`
therefore invalidated the Debian base rootfs even if its actual inputs were
identical. The consequence was another bootstrap and package installation
before the final image could be assembled.

## Dependency audit and change

[The Armbian extension](../build/armbian/extensions/gameshellneo.sh) selects
the package list and signed Debian snapshot mirrors during base-rootfs
configuration. Its APT hook calls `tools/image.py:apt_sources()`, which uses
the Debian snapshot fields. Kernel modules, runtime files, device identity,
firmware and image-version metadata are installed by the final-image hook.
[The wrapper](../tools/build-image.sh) uses fixed Armbian `REVISION=0.1.0`,
`KERNELSOURCE=none`, the locked builder and snapshot arguments. The source-lock
image version and kernel local-version suffix do not select its base packages.

[The cache helper](../tools/rootfs-cache.py) now uses a canonical JSON digest
that excludes **only** `image_version` and `linux.localversion`. The digest's
key name is `base_rootfs_lock_v2`. All other lock fields, including unknown
future fields, remain part of the fingerprint. In particular, Linux source
version, builder, Armbian commit, architecture, board, snapshots, features,
experiments and firmware metadata still invalidate the cache conservatively.

The key also retains every tracked base configuration and Armbian patch,
package/APT hook bodies and the APT policy function's AST. It now additionally
hashes `tools/build-image.sh`, covering changes to the wrapper's build
arguments. Final-image hooks remain outside this base-rootfs fingerprint.
If future bootstrap code starts consuming either excluded field, that field
must be restored to the key; the current exclusion is a reviewed dependency
contract, not a claim that arbitrary version changes are always harmless.

Archive SHA-256 verification is unchanged. The pinned
[Armbian cache guard](../build/armbian-patches/0002-verified-local-cache.patch)
also requires the calculated artifact name and verified content hash, and
continues to reject remote cache substitution.

Legacy ledgers have a different input-key set and are rejected. No old record
is reinterpreted or migrated. Diagnostic.18 therefore performs its ordinary
fresh base-rootfs build, then records the new key for later eligible builds.
Changing the USB wake-policy feature still invalidates the key; this change
does not attempt to optimize every final-image-only field.

## Reproducible checks

```sh
python3 -m unittest discover -s tools/tests -p test_rootfs_cache.py -v
task check
```

Five tests run the real record/check implementation with isolated archives and
source fixtures. They demonstrate:

- Both excluded identity fields can change while the same verified archive is
  accepted; the read-only check does not rewrite its ledger.
- Real source-lock dependencies and unknown new fields cause rejection.
- Package/config/patch changes, APT policy and wrapper changes cause rejection.
- Finalization-only hook edits and JSON key ordering do not change this key.
- Legacy ledger shape, corrupt archive content and a missing archive reject.

The repository checks pass with 13 runtime tests and 462 tooling tests, one
existing optional skip, compiled selector/mount-guard checks and shell lint.
Logs: `.local/neo99-check.log`. Actual cache recording/checking after the image
build remains the integration check; a second complete image build solely to
time the cache would not establish a device performance or energy improvement.
