# GameShellNeo

A modern, maintainable Linux foundation for the ClockworkPi GameShell **CPI v3.1**.

The first milestone is a diagnostic image: Linux 6.18.54, minimal Debian 13,
standard device interfaces, and the bootloader already proven on the owner's
board. Sleep, a launcher, OTA and other board revisions are later work.

Start with the [first-build specification](docs/23-first-build-spec.md),
[build workflow](docs/24-building-and-testing.md),
[first-build results](docs/25-first-build-validation.md), [research index](docs/README.md)
and [follow-up activities](FOLLOW-UP.md).
Implementation is tracked in Kaneo's OpenSource / GameShellNeo (NEO) project.
The first private image has passed offline validation; hardware qualification
remains open under NEO-5.

Credentials, captured firmware, personalized images, downloads and build
outputs belong under ignored `.local/`. The existing `.env` is private.
The original working card must be preserved; experimental images target a
separate microSD card. A successful build is not hardware qualification.
