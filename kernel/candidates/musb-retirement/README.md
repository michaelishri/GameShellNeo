# Offline MUSB and Sunxi retirement candidate

Patches 0038–0045 extend the production source queue only for explicitly named
offline checks. They are excluded from image builds. `tools/kernel_candidates.py`
defines the `musb-retirement` profile; native, KUnit and full ARM object checks
replay that profile and record its actual patch hashes.

Run the saved `test:musb-probe-roles`, `test:musb-irq`,
`test:musb-retirement-resume`, `test:extcon-notifier`, `test:sunxi-owner`,
`test:musb-restart-kunit`, `test:musb-irq-kunit`, `test:musb-work-kunit`,
`test:musb-pm-kunit`, `test:extcon-provider-kunit` and corresponding explicit
driver checks sequentially. The ordinary request-resume check continues to
test the production source independently.

Reports 226–231 preserve the original source evidence. NEO-106 retains the
separate image identity, physical USB/removal/rebind and hardware power gates.
