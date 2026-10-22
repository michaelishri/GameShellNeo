# Require a failed command for the wake negative control (NEO-225)

23 October 2026, Pacific/Auckland. This bounded offline follow-up starts from
published main `7120990023cb17ecc152eadefa57f37c19309ed9` in the isolated
`work/musb-wake-control-exit` checkout. Its `cdf84dc` preparation remains frozen;
the separate `work/musb-wake-control-exit-final` checkout adopts accepted clock
main `7e6a081a724c709f928a357928896dd0eaca2cd0` for final context checks. Both
maintained Python files remain byte-identical to that preparation. The sole
documentation conflict preserves the new 309 row and the accepted 305/302 rows.
NEO-220's fresh source/pre-integration
Spec review found a control admission gap that also exists in the published
NEO-218 wake runner. No kernel, fixture, configuration, profile, registry,
production patch, managed helper or image input changes here.

## Concrete failure and change

The `--suite wake --wake-control policy-ignored` route requires an original
command exit of 1 and exactly five named KUnit failures. Its typed-failure
handler verifies the original identity/result, clean terminal exit, released
ownership and expected failed-case output. However, a normal `execute()` return
previously skipped that handler: fresh log/JSON describing those failures could
be accepted even though the command reported exit 0.

The runner now refuses any normal return on that expected-nonzero wake-control
route before checking test output or publishing evidence. Only
`ManagedCommandFailure` can enter the existing original-result admission. Other
suites, normal wake success and retirement behavior keep their existing routes.
The managed API, stale-result retention/removal, current-output requirement and
all existing refusal checks are unchanged.

## Preserved reproduction and focused qualification

The original false acceptance was reproduced through actual maintained
`main()` in a disposable host executor fixture. Source preparation and executor
boundaries were modeled; fresh valid failed-case KTAP/JSON were written during
that invocation, and the executor returned clean exit 0. Published source
`7120990:tools/check-musb-restart-kunit.py` (SHA-256
`9f802e5caac5cdb569369d589f9dc0fb0b59afcac03c79b993e8a1a703d2d42c`)
accepted the control. The retained source audit is
`.local/worktrees/musb-wake-device-pm-control-exit/.local/audit/control-zero-exit-source-audit.json`
(SHA-256 `65aa7d2e3581b085ec7d6f73ff4f1f4a491cb49064315e214b521d8a80a5a90c`).
It preserves the original mock result and separately identifies the loaded
fixed source; a fixture-local `__file__` only supplies disposable input paths.

The new actual-main regression supplies the same valid fresh negative output
and normal clean exit 0. It requires the explicit original-exit-1 error, no
fallback result observation and no accepted evidence. Existing actual-main
fixtures still accept the typed original raw-1 result with newly produced
identical output, and reject stale/partial files, unresolved cleanup, active
ownership, stopped/OOM/running/wrong-original results. Complete named control
assertions, source-profile admission and positive evidence guards also remain
covered.

The focused logged host command passed nineteen tests: fourteen wake tests and
five accepted managed-result test groups. Its log is
`.local/build/musb-wake-control-exit-host.log` (SHA-256
`34327ac1ca03ac2a119366df901c352cfefb08e2bd0be8b0f975d4be28737adf`).
The single final `task check` on accepted clock base `7e6a081` completed with
exit 0 (original host session 71886): 24 runtime tests and 1,355 tooling tests
passed with nine expected skips, followed by the C checks, Bash syntax and
ShellCheck. The retained log is `.local/build/neo225-final-check.log`. The Python
source and tests were unchanged during and after that operation; final edits
record only context/evidence documentation. Fresh independent Standards/Spec
reviews and separate publication authorization remain required.

## Evidence limits

This is a host return-path rule and uses actual maintained runner execution
with disposable executor fixtures. It does not require another kernel replay
solely to observe that host branch. NEO-218's real original raw-1 compiling
control remains a valid historical observation; no old receipt is relabeled
current after this maintained runner/test change. Its original evidence and all
frozen worktrees remain retained.

NEO-220's analogous dedicated-runner correction is separate. NEO-98 retains its
actual remaining device-PM, allocation/sysfs concurrency, terminal composition,
image and physical gates. No Mac, GameShell or main operation belongs to this
qualification. Separate publication authorization is required before closure.
