# Completed-kernel verification prerequisites (NEO-233)

23 October 2026 NZDT. Reusing a completed kernel now checks the certificate,
provenance-file and source/builder prerequisites before image-stage entry.
The existing artifact guard was already early; its inventory lacked these
dependencies. Final image and regulatory signature checks remain unchanged.
Fresh independent review and publication are pending.

## Source boundary and original reproduction

The historical diagnostic.20 assembly/empty-certificate verification failure
is recorded in `FOLLOW-UP.md`. This work reproduces the missing boundary using
current published base `d707759ec08a55e2628d98b0e65128a5d276e645`; it does not
rebuild or relabel that historical image.

[build-image.sh](../tools/build-image.sh) already runs completed-kernel checking
before entering Docker/rootfs assembly. [Finalization](../tools/image.py) checks
again. The old [inventory](../tools/kernel-artifacts.py) covered release,
compiled/module files, generated patch hashes and the configuration fragment.
The existing five missing/stale ledger/artifact controls correctly refuse early.

The [regulatory verifier](../tools/verify-rootfs.py) additionally needs the
selected Linux source tree's `net/wireless/certs/*.hex`. It constructs a PEM set
and verifies the package's detached signature with `-nointern -noverify`.
The former disables signer discovery inside the signature; the latter disables
certificate-chain validation, not content-signature verification.
[Official OpenSSL CMS documentation](https://docs.openssl.org/3.0/man1/openssl-cms/).
The [kernel fragment](../kernel/gameshellneo.config) requires signed regulatory
data and shipped kernel keys. Inspected Linux Kconfig/Makefile/regulatory source
supports that input relationship; its hashes are in private primary-source
facts. The inspection is not a new archive-to-source attestation.

Fourteen original routes execute byte-identical maintained shell/checker code,
real filesystem/hash operations and real OpenSSL fixture signatures:

| Original route | Before image stage | Regulatory component |
| --- | --- | --- |
| Valid representative stage | Reaches sentinel | Pass |
| Missing, empty, malformed or stale-signer certificates (four routes) | Reaches sentinel | Each fails |
| Missing ledger; changed kernel/module/patch/fragment (five routes) | Each refuses | Not run |
| Changed Linux/builder declarations (two routes) | Reaches sentinel | Pass, without resolving context mismatch |
| Missing compiler/package records (two routes) | Reaches sentinel | Pass; finalization not executed |

Reaching the explicit nonexecuting Docker sentinel means late admission, never
successful image assembly. Only host disk-headroom is replaced by an explicit
20 GiB snapshot. No maintained checker/decoder/final result is substituted.
Representative binary/private inputs and signing keys belong solely to the
temporary fixtures. No real private configuration is loaded.

Finalization later copies `compiler.txt` and `builder-packages.txt` from the
kernel build directory. The producer writes them inside its locked builder.
Their late copy requirement is source evidence; the baseline does not claim
an executed finalizer or observed late copy exception.

Original session 12538, worker 1381530/wrapper 1381520, exits 0. All 967 tracked
inputs match before/after. Original log SHA
`13032431a7ec4d706ee5ba37bfa79470598f8101cddac88ba0e47f8cdd897a9a`;
result `25eb8310fc6659c9aa6530186c6664a2e02bf996a21a727e29e0660f518da259`.
Every raw route output, refusal, sentinel and original terminal is retained.

## Versioned completion contract

The saved producer still records completion after the actual kernel/module
build. Schema 2 retains existing release/patch/fragment/artifact fields and adds:

- Exact full current Linux and builder declarations.
- Exact compiler and builder-package file hashes.
- The nonempty complete regulatory certificate file set and its hashes.

Each certificate must parse as X.509 using the host Python SSL library. This
checks prerequisite syntax; it neither authenticates an arbitrary kernel nor
verifies a future package's signature. The actual locked archive, patch replay,
toolchain and managed-stage checks remain the producer's responsibility.
Matching declarations/file hashes are not independent build attestation.

`check` requires schema 2 and exact current inventory, without writing data or
migrating old receipts. Missing/stale files, changed declarations, added/removed
keys and legacy metadata refuse before image-stage entry. A failed `record`
with malformed certificates also preserves the previous receipt. Do not
promote retained old stages by re-recording metadata instead of qualifying the
producer. Every original stage/cache/receipt stays untouched by this work.

The existing raw clock inventory comparison also remains conservative for
legacy metadata under this new helper. Its consumers, historical images,
frozen hardware tooling, captures and evidence are unchanged. No clock or PM
acceptance follows.

```sh
task test:kernel-artifacts
task check:kernel
task build:image
```

An isolated workspace needs the matching completed-stage metadata, compiled
outputs/modules, compiler/package records and selected certificate inputs.
Staging only compiled binaries is insufficient. Rootfs-only assembly remains
independent of completed-kernel/certificate admission. No cache-key redesign,
certificate export/fallback, final-verifier change or trust expansion is added.

## Current qualification

Clean executed source `20f5def188b18544c08772f498b28101836decb5` passes the
saved focused Task: **five methods /20 actual shell routes /19 direct kernel
checks**. The only stage entries are valid-image and rootfs-only controls.
All 18 invalid image routes refuse first. The unchanged real OpenSSL regulatory
control passes. Exact certificate additions/removal, compiler/package content
changes and legacy read-only refusal supplement the original 14 routes.
All fixture content/mtime and receipt bytes remain exact across checking.
Ten staged entrypoint hashes match maintained source in every case.

Focused original session 2784, Task 1383740/wrapper 1383727, exits 0. Receipt SHA
`c3b7eb4b750ab98bac7fddaa0537e92c569c309238b445664d50e4a2c12e8aff`;
outer log `64afeacaa34f9fdda54a0bedc289e98c8f39f933da74f771d58570f465aa5fbb`.
One combined normal-host check, original session 66995,
Task 1383956/wrapper 1383943, exits 0: **24 runtime /1496 tooling tests**, nine
expected skips, both C guards and Bash/ShellCheck. Receipt SHA
`a768c56c02d57b0d6776bbbc685f8b1700f81202a665c9690fab68f85edf70f5`;
outer log `bbddf2d1caadd3a2f8bdebf8748a20997e0af0c6bf4149d65e85bef72dd593bf`.
All 968 tracked inputs match before/after both Tasks. Actual source/commands,
fixture data, stdout/stderr and terminal results are retained under ignored
`.local/kernel-reuse-preflight/`. No original qualification failed or was retried.

Both current jobs are terminal; largest child RSS 143488 KiB on one host CPU.
Evidence was approximately 15.8 MB before final collation, below 128 MiB. Only
four own documentation/status/navigation paths change after qualification.
There is no full kernel/image/container build, archive extraction/download/copy,
source-cache or original-stage mutation, device/Mac/PM/reboot operation, driver
or production-queue change. Full image/signature and hardware acceptance remain
separate; this ticket establishes the bounded offline preflight behavior only.
