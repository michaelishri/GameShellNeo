# Offline MUSB and Sunxi retirement candidate

Patches 0038–0045 and 0060–0061 extend the production source queue only for explicitly named
offline checks. They are excluded from image builds. `tools/kernel_candidates.py`
defines the `musb-retirement` profile; native, KUnit and full ARM object checks
replay that profile and record its actual patch hashes.

Run the saved `test:musb-probe-roles`, `test:musb-irq`,
`test:musb-retirement-resume`, `test:extcon-notifier`, `test:sunxi-owner`,
`test:musb-restart-kunit`, `test:musb-irq-kunit`, `test:musb-work-kunit`,
`test:musb-pm-kunit`, `test:extcon-provider-kunit` and corresponding explicit
driver checks sequentially. The ordinary request-resume check continues to
test the production source independently.

`test:phy-detector` exercises the actual Sun4i detector and exit functions,
including notifications that synchronously exit or exit/reinitialize the PHY.
`check:phy-detector-drivers` also compiles five complete ARM configurations.
`test:phy-detector-kunit` executes ten lifecycle/race/control cases in the
complete actual PHY driver with real Linux work/mutex/extcon APIs under UML.
Candidate 0060 keeps post-notification MMIO and polling within the original
initialized generation. It does not retire every generic-PHY consumer or prove
complete provider removal.

Candidate 0061 retains the MPFS parent clock through child removal and releases
the actual owned PHY. `test:mpfs-ownership` and `check:mpfs-ownership-drivers`
exercise the real probe/remove and generic/platform helper bodies, then compile
explicitly selected MPFS PIO/DMA/module configurations. The separate
`test:mpfs-ownership-kunit` uses real Linux platform-device/PHY/clock cleanup.

Reports 226–231 preserve the original source evidence. NEO-106 retains the
separate image identity, physical USB/removal/rebind and hardware power gates.
