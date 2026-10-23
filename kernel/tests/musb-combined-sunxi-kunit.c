// SPDX-License-Identifier: GPL-2.0-only
/* Appended to the complete actual Sunxi driver in the disposable test view. */
#include <linux/usb/phy_companion.h>
#include <linux/unaligned.h>
#include "musb-combined-lifecycle-kunit.h"

/* The generator undefines its hardware access aliases before this fragment. */
static bool neo_sunxi_register(void __iomem *address, size_t bytes)
{
	struct neo_joined_lifetime *life = neo_joined_current;
	unsigned long offset;

	if (!life)
		return false;
	offset = (unsigned long)address - (unsigned long)life->registers;
	if (offset > life->register_bytes || bytes > life->register_bytes - offset)
		return false;
	if (!atomic_read(&life->backend_clock))
		atomic_inc(&life->bad_access);
	return true;
}

static u8 neo_sunxi_readb(void __iomem *address)
{
	if (neo_sunxi_register(address, 1))
		return READ_ONCE(*(u8 __force *)address);
	return readb(address);
}

static u16 neo_sunxi_readw(void __iomem *address)
{
	if (neo_sunxi_register(address, 2))
		return get_unaligned_le16((void __force *)address);
	return readw(address);
}

static void neo_sunxi_writeb(u8 value, void __iomem *address)
{
	if (neo_sunxi_register(address, 1)) {
		WRITE_ONCE(*(u8 __force *)address, value);
		return;
	}
	writeb(value, address);
}

static void neo_sunxi_writew(u16 value, void __iomem *address)
{
	if (neo_sunxi_register(address, 2)) {
		put_unaligned_le16(value, (void __force *)address);
		return;
	}
	writew(value, address);
}

static int neo_sunxi_clock_on(struct clk *clock)
{
	struct neo_joined_lifetime *life = neo_joined_current;
	struct sunxi_glue *glue = life ? life->sunxi_private : NULL;

	if (glue && clock == glue->clk) {
		atomic_inc(&life->backend_clock);
		return 0;
	}
	return clk_prepare_enable(clock);
}

static void neo_sunxi_clock_off(struct clk *clock)
{
	struct neo_joined_lifetime *life = neo_joined_current;
	struct sunxi_glue *glue = life ? life->sunxi_private : NULL;

	if (glue && clock == glue->clk) {
		if (atomic_read(&life->backend_clock) != 1)
			atomic_inc(&life->bad_access);
		atomic_dec(&life->backend_clock);
		return;
	}
	clk_disable_unprepare(clock);
}

static int neo_sunxi_reset_off(struct reset_control *reset)
{
	struct neo_joined_lifetime *life = neo_joined_current;
	struct sunxi_glue *glue = life ? life->sunxi_private : NULL;

	if (glue && reset == glue->rst)
		return 0;
	return reset_control_deassert(reset);
}

static int neo_sunxi_reset_on(struct reset_control *reset)
{
	struct neo_joined_lifetime *life = neo_joined_current;
	struct sunxi_glue *glue = life ? life->sunxi_private : NULL;

	if (glue && reset == glue->rst)
		return 0;
	return reset_control_assert(reset);
}

static void neo_sunxi_notifier_enter(struct notifier_block *notifier)
{
	struct neo_joined_lifetime *life = neo_joined_current;
	struct sunxi_glue *glue = life ? life->sunxi_private : NULL;

	if (glue && notifier == &glue->host_nb) {
		atomic_inc(&life->notification_calls);
		neo_joined_gate_wait(&life->notifier_gate);
	}
}

static int neo_sunxi_notifier_register(struct extcon_dev *edev, unsigned int cable,
				     struct notifier_block *notifier)
{
	struct neo_joined_lifetime *life = neo_joined_current;
	int ret = extcon_register_notifier(edev, cable, notifier);

	if (!ret && life && edev == life->extcon)
		WRITE_ONCE(life->notifier_linked, true);
	return ret;
}

static int neo_sunxi_notifier_unregister(struct extcon_dev *edev, unsigned int cable,
				       struct notifier_block *notifier)
{
	struct neo_joined_lifetime *life = neo_joined_current;
	int ret;

	if (life && edev == life->extcon)
		complete(&life->notifier_retiring);
	ret = extcon_unregister_notifier_sync(edev, cable, notifier);

	if (!ret && life && edev == life->extcon)
		WRITE_ONCE(life->notifier_linked, false);
	return ret;
}

static bool neo_sunxi_work_disable(struct work_struct *work)
{
	struct neo_joined_lifetime *life = neo_joined_current;
	struct sunxi_glue *glue = life ? life->sunxi_private : NULL;

	if (glue && work == &glue->work)
		complete(&life->work_retiring);
	return disable_work_sync(work);
}

/* This is the control's only source change; it has no admitted/running worker. */
NEO_JOINED_SUNXI_CONTROL_BODY

static int neo_sunxi_exit_dispatch(struct musb *musb)
{
	struct neo_joined_lifetime *life = neo_joined_current;

	if (life && life->controller == musb->controller && life->work_disable_control)
		return control_sunxi_musb_exit(musb);
	return sunxi_musb_exit(musb);
}

static struct musb_platform_ops neo_sunxi_test_ops;

int neo_joined_sunxi_prepare(struct neo_joined_lifetime *life)
{
	struct sunxi_glue *glue;
	int ret;

	glue = kunit_kzalloc(life->test, sizeof(*glue), GFP_KERNEL);
	if (!glue)
		return -ENOMEM;
	life->sunxi_private = glue;
	glue->dev = life->parent;
	glue->phy = life->phy;
	glue->extcon = life->extcon;
	/* These tokens are consumed only by the declared clock/reset effect seams. */
	glue->clk = (struct clk *)&life->backend_clock;
	glue->rst = (struct reset_control *)&life->work_calls;
	glue->initial_phy_mode = PHY_MODE_USB_DEVICE;
	glue->phy_mode = glue->initial_phy_mode;
	set_bit(SUNXI_MUSB_FL_HAS_RESET, &glue->flags);
	set_bit(SUNXI_MUSB_FL_NO_CONFIGDATA, &glue->flags);
	INIT_WORK(&glue->work, sunxi_musb_work);
	disable_work(&glue->work);
	glue->host_nb.notifier_call = sunxi_musb_host_notifier;
	glue->usb_phy = usb_phy_generic_register();
	if (IS_ERR(glue->usb_phy))
		return PTR_ERR(glue->usb_phy);
	glue->xceiv = usb_get_phy(USB_PHY_TYPE_USB2);
	if (IS_ERR(glue->xceiv)) {
		ret = PTR_ERR(glue->xceiv);
		usb_phy_generic_unregister(glue->usb_phy);
		glue->usb_phy = NULL;
		return ret;
	}
	dev_set_drvdata(life->parent, glue);
	neo_sunxi_test_ops = sunxi_musb_ops;
	neo_sunxi_test_ops.exit = neo_sunxi_exit_dispatch;
	return 0;
}

void neo_joined_sunxi_destroy(struct neo_joined_lifetime *life)
{
	struct sunxi_glue *glue = life->sunxi_private;

	if (!glue)
		return;
	disable_work_sync(&glue->work);
	if (!IS_ERR_OR_NULL(glue->xceiv))
		usb_put_phy(glue->xceiv);
	if (!IS_ERR_OR_NULL(glue->usb_phy))
		usb_phy_generic_unregister(glue->usb_phy);
	sunxi_musb = NULL;
}

const struct musb_platform_ops *neo_joined_sunxi_ops(struct neo_joined_lifetime *life)
{
	return &neo_sunxi_test_ops;
}

const struct musb_hdrc_config *neo_joined_sunxi_config(void)
{
	return sun8i_a33_musb_cfg.hdrc_config;
}

void neo_joined_sunxi_flush(struct neo_joined_lifetime *life)
{
	struct sunxi_glue *glue = life->sunxi_private;

	flush_work(&glue->work);
}

void neo_joined_sunxi_recover(struct neo_joined_lifetime *life)
{
	sunxi_musb_recover(life->musb);
}

bool neo_joined_sunxi_late_queue(struct neo_joined_lifetime *life)
{
	struct sunxi_glue *glue = life->sunxi_private;

	return schedule_work(&glue->work);
}

bool neo_joined_sunxi_notifier_linked(struct neo_joined_lifetime *life)
{
	/* Record ownership only after the real synchronous API has returned. */
	return READ_ONCE(life->notifier_linked);
}

void neo_joined_sunxi_control_cleanup(struct neo_joined_lifetime *life)
{
	struct sunxi_glue *glue = life->sunxi_private;

	/* Only after the control's accepted-queue observation, with no live worker. */
	flush_work(&glue->work);
	disable_work_sync(&glue->work);
}
