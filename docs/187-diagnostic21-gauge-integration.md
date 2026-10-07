# Diagnostic.21 gauge-status integration

7 October 2026. NEO-125. Integration in progress; diagnostic.20 remains
installed. This report will record the completed image verification before
installation is arranged. No charging/gauge settings, ADC scale or battery
calibration policy changes are included.

## Scope and identity

The source-tested AXP223 B8 volatility correction from
[report 186](186-axp223-gauge-status-candidate.md) is integrated into
`work/power-insertion-wake`. The new image identity is
`0.1.0-diagnostic.21`, with kernel `6.18.54-gameshellneo20`.
The remaining configuration, firmware, userspace policies and supply/USB wake
settings are unchanged. Normal product sleep remains disabled.

The previous diagnostic.20 raw/compressed artifacts and matching metadata were
verified using `task image:checkpoint NAME=diagnostic20-before-gauge-status`
before advancing the identity. They remain available for recovery.

## Inspection contract

Schema 3 of `task device:charge-inspect` accepts only two explicit contracts:

| Image | Kernel | Expected B8 metadata |
| --- | --- | --- |
| diagnostic.20 | `6.18.54-gameshellneo19` | nonvolatile, possibly cached |
| diagnostic.21 | `6.18.54-gameshellneo20` | volatile, hardware register read |

The helper checks the expected pair, installed version/kernel record, running
kernel, CPI/PMIC identity and observed register layout/cache policy. An unknown
pair, cross-paired image/kernel, or wrong B8 volatility rejects before register
access. It retains the same eleven-address read-only allowlist and bounded
seven-byte reads; no cache bypass or charger/gauge write is introduced.

B8 controls/status move from `assessment.cached_configuration` into
`assessment.gauge_control`, carrying the raw byte and the recorded source label.
E0/E1 capacity and other nonvolatile configuration retain their cache limitation.
Fresh B8 does not make them fresh or establish capacity calibration. REG34's
disputed polarity and ADC-byte coherence/accuracy limitations remain explicit.

The awake charging sampler embeds the same helper and therefore emits schema 3
for its nested inventory while retaining its existing outer schema. Historical
captures and their helper hashes remain unchanged.

## Validation progress

The focused inventory/baseline suite passes 26 tests, including both complete
profile captures, cache-policy mismatch rejection, unknown/cross-paired image
admission, installed-kernel mismatch and separate B8/cached-register provenance.
The first new full-capture fixture incorrectly supplied a backwards mock clock;
it was corrected to advance between checkpoints, retaining the production
continuity guard. No device failure was involved.

Full host, source-regression and image-build results will be added here after
completion. Hardware startup, fresh gauge inspection, unchanged charger limits,
normal display and PM checks remain pending. No real calibration transition
will be provoked by programming B8 merely to test its status bit.
