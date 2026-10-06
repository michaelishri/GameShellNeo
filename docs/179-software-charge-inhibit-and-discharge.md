# Software charge inhibition and battery discharge

Research date: 6 October 2026. Scope: whether the battery can be discharged while the USB cable remains connected. Source inspection and read-only device inspection only; no charging control or power-path setting was changed.

## Conclusion

**The existing driver can disable battery charging in software, but that does not force the GameShell to run from its battery.** USB can continue supplying the system. For the next charging-through-sleep experiment, physical USB removal remains the established way to obtain a lower battery state of charge. A software-only equivalent is not qualified on this board.

## Existing charging control

The locked Linux 6.18.54 `axp20x_battery.c` exposes writable `POWER_SUPPLY_PROP_STATUS`. Its setter maps `Charging` to setting `AXP20X_CHRG_CTRL1_ENABLE` and both `Discharging` and `Not charging` to clearing that bit. This is register `0x33`, bit 7; the read-modify-write preserves the other charge-control bits. The setter does not change input routing or create an electrical load. In particular, requesting the status named `Discharging` does **not** guarantee discharge. The separate getter derives reported status from hardware charging/current/gauge readings. [Linux battery driver][battery]

The vendor's register description independently identifies `REG33H[7]` as charger enable, distinct from the input power paths. [AXP223 v1.1, PDF p. 40][vendor40]; [AXP223 English v1.0, PDF p. 42][english42]

The read-only check saved in `.local/charge-control-readonly-20261006.log` confirms `/sys/class/power_supply/axp20x-battery/status` exists and is root-writable (`-rw-r--r--`) on the current image. It reports the AXP221-compatible battery child used for AXP223, capacity 100%, `Charging`, current 2,000 µA and voltage 4,158,000 µV. These are reported telemetry, not an independent calibration or proof that a disable request works. The status attribute was not written.

## Why charging inhibition is insufficient

AXP223's power-selection policy prefers external power when available; ACIN has priority over VBUS. The published ClockworkPi schematic joins the named `ACIN5V` and `USBVBUS` nets at the PMIC inputs. Thus disabling a charger, or reasoning about VBUS alone, does not establish battery-only operation. This is a board-routing inference from the published CPI3 drawing, not a fresh electrical measurement of the owner's CPI v3.1. [Power-path description, PDF p. 23][english23]; [ClockworkPi power schematic, sheet 6][schematic]

`REG30H[7]` selects VBUS forced-on versus control by `N_VBUSEN`; it is not a software force-off bit. Linux explicitly withholds writable USB `online` for AXP20x/AXP22x for this reason. The AXP22x AC supply descriptor also has no setter. Changing `N_VBUSEN` would still require resolving the ACIN path and actual board behavior. No documented, qualified control that disconnects both external input paths was established in this investigation. [Vendor register table, PDF p. 39][vendor39]; [Linux USB driver][usb]; [Linux AC driver][ac]

The independent read-only capture `.local/charge-path-readonly-20261006.log` confirms both `axp20x-usb/online` and `axp22x-ac/online` are read-only (`-r--r--r--`) on kernel `6.18.54-gameshellneo19`, boot `34483a13-9373-4ee3-8984-fd81a99bc5de`.

## Test implications

- Use USB removal for the planned controlled discharge, with reliable Wi-Fi for collection. A lower percentage, elapsed battery-only operation and battery telemetry provide a clearer starting condition than merely inhibiting charging.
- If charge inhibition becomes a product requirement, use the driver's supported property through a saved, bounded helper with explicit restoration and before/after telemetry. Qualify its behavior separately; do not relabel it as a forced-discharge feature.
- Do not reduce input-current limits or modify charger voltage/current merely to manufacture a discharge condition. That would introduce separate, presently unqualified power-path behavior into the charging-through-sleep experiment.

The battery driver's source SHA-256 in the inspected source tree is `20fae6ab58e4ce5688d8fb1a7bf24dc7817f879332758fed2866862aa6429cdb`. Source inspection establishes the available interface; no inhibit/re-enable hardware test has been performed.

[battery]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/power/supply/axp20x_battery.c?h=v6.18.54
[usb]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/power/supply/axp20x_usb_power.c?h=v6.18.54
[ac]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/power/supply/axp20x_ac_power.c?h=v6.18.54
[vendor39]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=39>
[vendor40]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=40>
[english23]: https://linux-sunxi.org/images/e/e5/AXP223_Datasheet_V1.0_en.pdf#page=23
[english42]: https://linux-sunxi.org/images/e/e5/AXP223_Datasheet_V1.0_en.pdf#page=42
[schematic]: ../../GameShell/clockwork_Mainboard_Schematic.pdf#page=6
