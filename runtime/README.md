# Diagnostic runtime

Files under `etc/` and `usr/` are installed by `tools/install-runtime.py` into an
offline Debian armhf root. The installer needs systemd, systemd-resolved,
openssh-server, wpasupplicant, sudo, python3-minimal, usbutils and iproute2.
It validates SSH and sudo configuration in the target and explicitly enables
services. No target device is modified by preparing private inputs.

The diagnostic image uses bounded journald storage. Armbian first-run identity
regeneration, automatic resize/tuning, redundant rsyslog/cron and scheduled APT,
manual-page, trim and scrub jobs are masked to keep measurements repeatable.
Package sources are fixed snapshots; updates are deliberate rebuilds/reflashes
in this milestone. A production update/maintenance policy remains later work.

`gameshellneo-ready` records local **userspace** readiness in
`/run/gameshellneo/ready.json`. Device names are observations, not a claim that
display/input work. Network acquisition is independent. `sudo gameshellneo-collect`
writes a private diagnostic archive under `/var/tmp`; inspect it before sharing
because kernel logs and network addresses can identify the device.

The battery process reads standard power-supply files every ten seconds. Three
valid discharging samples at or below 10% request orderly shutdown. An absent
battery, invalid percentage/status/voltage, read error or interrupted sampling
window resets the count. State lives in `/run`, not repeated SD writes. The
percentage and threshold remain provisional until pack calibration; this is an
awake guard, not hardware protection or a wake-from-sleep mechanism. Python is
used for this diagnostic policy; measure its cost during the efficiency phase.

USB ECM serves DHCP on `usb0` only, without a default route or DNS offer. Device
and host MAC addresses derive from the private per-device machine ID. The Linux
Foundation gadget identity is for this development image; a production USB
identity requires separate qualification. Configuring MaxPower does not program
or measure the PMIC's actual input current.

The ECM configfs `ifname` is the allocation template `usb%d`, as required by
Linux's `gether_set_ifname()`. After binding, the script verifies that the
allocated interface is `usb0`, matching the maintenance network configuration.
Writing a literal `usb0` is rejected by the kernel even though it looks like a
valid network name; this was found and corrected during the first board boot.

`task provision` reads Wi-Fi credentials from the ignored `.env` and writes
wpa_supplicant configuration without printing credentials. The underlying
`tools/provision.py` also supports legacy Wicd import. It creates stable per-device
machine and SSH identities, plus a fingerprint record. Treat the output and
every resulting image as private. Do not reuse one provision directory for
multiple devices. The build never includes `.env` or the original host keys.

Provisioning requires `GAMESHELL_WIFI_COUNTRY` (the owner's confirmed value is
`NZ`) and writes wpa_supplicant's `country=` setting. Changing region retains
the existing machine/SSH identity. Future launcher-based selection is deferred.
The image selects the upstream-signed wireless-regdb alternative to match the
upstream kernel keys; cfg80211 loads as a module after the root filesystem is
available. Offline verification checks the signature against those kernel keys.
Only `wpa_supplicant@wlan0` is enabled; the unused global/D-Bus daemon is masked.
DHCP cannot replace the fixed hostname. Audio remains deferred and `alsa-utils`
is excluded. A sysctl override tolerates the deliberately absent SysRq facility.

Run host regressions with `task check` from the project root.
USB enumeration, actual shutdown and power readings require NEO-5 hardware tests.
