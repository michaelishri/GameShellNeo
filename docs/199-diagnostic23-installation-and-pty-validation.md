# Diagnostic.23 installation and terminal validation

7 October 2026; timestamps are UTC. NEO-137 is in progress. The verified
candidate is staged on the Mac and the previous diagnostic.22 installation has
accepted shutdown for the DEV-card swap. No card write or new-boot qualification
has completed at this checkpoint.

## Transfer and shutdown

[Report 198](198-legacy-pty-startup-candidate.md) records the configuration
change, baseline terminal inventory, build checks and artifact hashes.
After the owner confirmed regular Wi-Fi, `task mac:stage` completed with both
compressed and expanded image checksums verified on the Mac. Private transfer
log: `.local/neo137-stage.log`.

The owner then confirmed readiness for the DEV-card swap. The saved USB status
task reached diagnostic.22, kernel `6.18.54-gameshellneo21`, before shutdown.
Private status capture: `.local/diagnostics/20261007T093129.061170Z/`.

`task device:audio-test ROUTE=usb` passed three one-second warning cues and
restored the same boot's mixer/amplifier state. Run
`294dbc17ffd2487abba7ad200ff368ab` is saved in
`.local/diagnostics/20261007T093146.660595Z/`; result SHA-256:
`5cd678c4fec734f8a17c936dc3519613a9e1db1234360c04d32389f0bac1a9c0`.
Both audio snapshots identify boot `7884d229-2309-47df-9af0-b6fe500ad9ac`.
Four collection attempts returned `RuntimeError` before the original completed
result was retrieved; no second warning test was submitted. Audibility has not
been separately confirmed for this shutdown sequence.

`task device:exec ROUTE=usb -- sudo -n systemctl poweroff` returned success.
Private logs are `.local/neo137-before-shutdown.log`,
`.local/neo137-shutdown-warning.log` and `.local/neo137-shutdown.log`.
The owner was asked to wait ten seconds after darkness, disconnect USB and
move the Samsung DEV card to the Mac reader. Card identity, writing, full
readback and ejection remain pending.

## Remaining acceptance

After verified writing and owner-confirmed login, check the exact
diagnostic.23 / `6.18.54-gameshellneo22` identity, both network routes and normal
awake integration, journal, power-key and RTC behavior. Run
`task device:user-startup LEGACY=disabled` to require zero legacy terminal
devices/units while checking modern Unix98 data transfer, resizing and an actual
SSH terminal allocation. Compare fresh-session timing and manager resource
observations with report 198; do not infer an energy saving from unit counts.

Observed suspend/debug and actual sleep qualification require a fresh ready
response on the new boot. Diagnostic.22's existing PM evidence is historical
evidence, not qualification of this candidate.
