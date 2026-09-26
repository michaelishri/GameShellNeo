// SPDX-License-Identifier: GPL-2.0-only
/*
 * Orient Chip OCP8178 backlight.
 * Based on Wim de With's v4 submission, Copyright (C) 2026 Wim de With.
 * Off/on lifecycle and serialization: Copyright 2026 GameShellNeo contributors.
 * See kernel/README.md for provenance and hardware qualification limits.
 */
#include <linux/backlight.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/ktime.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/platform_device.h>
#include <linux/property.h>

struct ocp8178 {
	struct gpio_desc *ctrl;
	struct mutex lock;
	bool enabled;
};

static void ocp8178_off(struct ocp8178 *ctx)
{
	gpiod_set_value(ctx->ctrl, 0);
	fsleep(3000); /* Datasheet shutdown requires more than 2.5 ms. */
	ctx->enabled = false;
}

static int ocp8178_enable(struct ocp8178 *ctx)
{
	int retry;
	u64 start;

	for (retry = 0; retry < 5; retry++) {
		ocp8178_off(ctx);
		start = ktime_get_ns();
		gpiod_set_value(ctx->ctrl, 1);
		udelay(110);
		gpiod_set_value(ctx->ctrl, 0);
		udelay(270);
		gpiod_set_value(ctx->ctrl, 1);
		if (ktime_get_ns() - start < 1000000) {
			ctx->enabled = true;
			return 0;
		}
	}
	ocp8178_off(ctx);
	return -ETIMEDOUT;
}

static void ocp8178_write_byte(struct ocp8178 *ctx, u8 value)
{
	unsigned long flags;
	int bit;

	/* Keep the bounded wire transaction intact; never mask the off delay. */
	local_irq_save(flags);
	gpiod_set_value(ctx->ctrl, 1);
	udelay(2);
	for (bit = 7; bit >= 0; bit--) {
		gpiod_set_value(ctx->ctrl, 0);
		udelay(value & BIT(bit) ? 2 : 5);
		gpiod_set_value(ctx->ctrl, 1);
		udelay(value & BIT(bit) ? 5 : 2);
	}
	gpiod_set_value(ctx->ctrl, 0);
	udelay(2);
	gpiod_set_value(ctx->ctrl, 1);
	local_irq_restore(flags);
}

static int ocp8178_update(struct backlight_device *bl)
{
	struct ocp8178 *ctx = bl_get_data(bl);
	int brightness = backlight_get_brightness(bl);
	int ret = 0;

	mutex_lock(&ctx->lock);
	if (!brightness) {
		ocp8178_off(ctx);
		goto out;
	}
	if (!ctx->enabled) {
		ret = ocp8178_enable(ctx);
		if (ret)
			goto out;
	}
	ocp8178_write_byte(ctx, 0x72);
	/* Bits 7:5 stay zero: never request an ACK on the push-pull GPIO. */
	ocp8178_write_byte(ctx, brightness & 0x1f);
out:
	mutex_unlock(&ctx->lock);
	return ret;
}

static const struct backlight_ops ocp8178_ops = {
	.options = BL_CORE_SUSPENDRESUME,
	.update_status = ocp8178_update,
};

static void ocp8178_release(void *data)
{
	struct ocp8178 *ctx = data;

	mutex_lock(&ctx->lock);
	ocp8178_off(ctx);
	mutex_unlock(&ctx->lock);
}

static int ocp8178_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct backlight_properties props = {
		.type = BACKLIGHT_RAW,
		.max_brightness = 31,
		.brightness = 1,
		.power = BACKLIGHT_POWER_OFF,
		.scale = BACKLIGHT_SCALE_NON_LINEAR,
	};
	struct backlight_device *bl;
	struct ocp8178 *ctx;
	u32 brightness;
	int ret;

	ctx = devm_kzalloc(dev, sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;
	mutex_init(&ctx->lock);
	ctx->ctrl = devm_gpiod_get(dev, "ctrl", GPIOD_OUT_LOW);
	if (IS_ERR(ctx->ctrl))
		return dev_err_probe(dev, PTR_ERR(ctx->ctrl), "backlight CTRL\n");
	if (gpiod_cansleep(ctx->ctrl))
		return dev_err_probe(dev, -EINVAL, "sleeping GPIO not supported\n");
	if (!device_property_read_u32(dev, "default-brightness", &brightness)) {
		if (brightness > 31)
			return -EINVAL;
		props.brightness = brightness;
	}
	ret = devm_add_action_or_reset(dev, ocp8178_release, ctx);
	if (ret)
		return ret;
	bl = devm_backlight_device_register(dev, "ocp8178", dev, ctx,
					    &ocp8178_ops, &props);
	if (IS_ERR(bl))
		return PTR_ERR(bl);
	platform_set_drvdata(pdev, ctx);
	/* DRM enables the backlight only after panel preparation succeeds. */
	return backlight_update_status(bl);
}

static void ocp8178_shutdown(struct platform_device *pdev)
{
	ocp8178_release(platform_get_drvdata(pdev));
}

static const struct of_device_id ocp8178_match[] = {
	{ .compatible = "ocs,ocp8178" },
	{ }
};
MODULE_DEVICE_TABLE(of, ocp8178_match);

static struct platform_driver ocp8178_driver = {
	.driver = { .name = "ocp8178-bl", .of_match_table = ocp8178_match },
	.probe = ocp8178_probe,
	.shutdown = ocp8178_shutdown,
};
module_platform_driver(ocp8178_driver);

MODULE_DESCRIPTION("Orient Chip OCP8178 backlight with shutdown support");
MODULE_LICENSE("GPL");
