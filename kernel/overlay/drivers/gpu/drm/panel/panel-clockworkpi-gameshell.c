// SPDX-License-Identifier: GPL-2.0-only
/*
 * GameShell RGB666 panel with a separate serial control interface.
 * Timing/register evidence: Clockwork's 2018 KD027 driver (GPL-2.0-or-later).
 * Lifecycle implementation: Copyright 2026 GameShellNeo contributors.
 * The exact panel controller and reset timing are not yet identified.
 */
#include <linux/gpio/consumer.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/regulator/consumer.h>
#include <linux/spi/spi.h>
#include <drm/drm_connector.h>
#include <drm/drm_modes.h>
#include <drm/drm_panel.h>
#include <linux/media-bus-format.h>

struct gameshell_panel {
	struct drm_panel panel;
	struct spi_device *spi;
	struct regulator *supply;
	struct gpio_desc *reset;
};

static inline struct gameshell_panel *to_gameshell(struct drm_panel *panel)
{
	return container_of(panel, struct gameshell_panel, panel);
}

static int gameshell_write(struct gameshell_panel *ctx, u8 reg, u8 value)
{
	u8 data[] = { reg, value };

	/* Keep CS asserted for the complete command/data pair. */
	return spi_write(ctx->spi, data, sizeof(data));
}

static int gameshell_prepare(struct drm_panel *panel)
{
	struct gameshell_panel *ctx = to_gameshell(panel);
	static const u8 init[][2] = {
		{ 0x2b, 0x01 }, { 0x00, 0x07 },
		{ 0x0c, 0x27 }, { 0x16, 0x04 },
	};
	unsigned int i;
	int ret;

	ret = regulator_enable(ctx->supply);
	if (ret)
		return ret;
	/* Preserve the proven deasserted reset level; do not invent a pulse. */
	gpiod_set_value_cansleep(ctx->reset, 0);
	for (i = 0; i < ARRAY_SIZE(init); i++) {
		ret = gameshell_write(ctx, init[i][0], init[i][1]);
		if (ret) {
			regulator_disable(ctx->supply);
			return ret;
		}
	}
	return 0;
}

static int gameshell_enable(struct drm_panel *panel)
{
	return gameshell_write(to_gameshell(panel), 0x2b, 0x01);
}

static int gameshell_disable(struct drm_panel *panel)
{
	return gameshell_write(to_gameshell(panel), 0x2b, 0x00);
}

static int gameshell_unprepare(struct drm_panel *panel)
{
	struct gameshell_panel *ctx = to_gameshell(panel);
	int ret;

	/* The board's shared supply stays on; this releases our consumer. */
	ret = regulator_disable(ctx->supply);
	return ret;
}

static const struct drm_display_mode gameshell_mode = {
	.clock = 5800,
	.hdisplay = 320, .hsync_start = 326, .hsync_end = 328, .htotal = 388,
	.vdisplay = 240, .vsync_start = 242, .vsync_end = 244, .vtotal = 250,
	.flags = DRM_MODE_FLAG_PHSYNC | DRM_MODE_FLAG_PVSYNC,
	.type = DRM_MODE_TYPE_DRIVER | DRM_MODE_TYPE_PREFERRED,
};

static int gameshell_get_modes(struct drm_panel *panel,
			       struct drm_connector *connector)
{
	u32 format = MEDIA_BUS_FMT_RGB666_1X18;
	struct drm_display_mode *mode;
	int ret;

	ret = drm_display_info_set_bus_formats(&connector->display_info, &format, 1);
	if (ret)
		return ret;
	connector->display_info.bpc = 6;
	mode = drm_mode_duplicate(connector->dev, &gameshell_mode);
	if (!mode)
		return -ENOMEM;
	drm_mode_set_name(mode);
	drm_mode_probed_add(connector, mode);
	return 1;
}

static const struct drm_panel_funcs gameshell_funcs = {
	.prepare = gameshell_prepare,
	.enable = gameshell_enable,
	.disable = gameshell_disable,
	.unprepare = gameshell_unprepare,
	.get_modes = gameshell_get_modes,
};

static int gameshell_probe(struct spi_device *spi)
{
	struct gameshell_panel *ctx;
	int ret;

	ctx = devm_kzalloc(&spi->dev, sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;
	ctx->spi = spi;
	spi_set_drvdata(spi, ctx);
	spi->bits_per_word = 8;
	if ((spi->mode & (SPI_CPOL | SPI_CPHA)) != SPI_MODE_3)
		return dev_err_probe(&spi->dev, -EINVAL, "SPI mode 3 required\n");
	ret = spi_setup(spi);
	if (ret)
		return ret;
	ctx->supply = devm_regulator_get(&spi->dev, "power");
	if (IS_ERR(ctx->supply))
		return dev_err_probe(&spi->dev, PTR_ERR(ctx->supply), "panel supply\n");
	ctx->reset = devm_gpiod_get(&spi->dev, "reset", GPIOD_OUT_LOW);
	if (IS_ERR(ctx->reset))
		return dev_err_probe(&spi->dev, PTR_ERR(ctx->reset), "panel reset\n");
	drm_panel_init(&ctx->panel, &spi->dev, &gameshell_funcs,
		       DRM_MODE_CONNECTOR_DPI);
	ret = drm_panel_of_backlight(&ctx->panel);
	if (ret)
		return ret;
	drm_panel_add(&ctx->panel);
	return 0;
}

static void gameshell_shutdown(struct spi_device *spi)
{
	struct gameshell_panel *ctx = spi_get_drvdata(spi);

	drm_panel_disable(&ctx->panel);
	drm_panel_unprepare(&ctx->panel);
}

static void gameshell_remove(struct spi_device *spi)
{
	struct gameshell_panel *ctx = spi_get_drvdata(spi);

	gameshell_shutdown(spi);
	drm_panel_remove(&ctx->panel);
}

static const struct of_device_id gameshell_of_match[] = {
	{ .compatible = "clockwork,cpi3-lcd" },
	{ }
};
MODULE_DEVICE_TABLE(of, gameshell_of_match);

static const struct spi_device_id gameshell_ids[] = {
	{ "cpi3-lcd" },
	{ }
};
MODULE_DEVICE_TABLE(spi, gameshell_ids);

static struct spi_driver gameshell_driver = {
	.driver = {
		.name = "panel-clockworkpi-gameshell",
		.of_match_table = gameshell_of_match,
	},
	.probe = gameshell_probe,
	.remove = gameshell_remove,
	.shutdown = gameshell_shutdown,
	.id_table = gameshell_ids,
};
module_spi_driver(gameshell_driver);

MODULE_DESCRIPTION("ClockworkPi GameShell RGB panel");
MODULE_LICENSE("GPL");
