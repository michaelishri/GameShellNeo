/* Actual locked helper and IIO callbacks, with a scripted read-only bus. */
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdbool.h>
#include <stdio.h>

#define BIT(n) (1UL << (n))
#define IIO_VAL_INT 1
enum { IIO_VOLTAGE, IIO_CURRENT, IIO_TEMP };
struct regmap {
	unsigned int base, high, low, reads;
	unsigned int fail_at;
	int error;
};
struct axp20x_adc_iio { struct regmap *regmap; };
struct iio_dev { struct axp20x_adc_iio info; };
struct iio_chan_spec { unsigned int type, channel, address; };
static void *iio_priv(struct iio_dev *dev) { return &dev->info; }

static int regmap_read(struct regmap *map, unsigned int reg, unsigned int *val)
{
	assert(map->reads < 2);
	assert(reg == map->base + map->reads);
	map->reads++;
	if (map->fail_at == map->reads) {
		assert(map->error < 0);
		return map->error;
	}
	*val = map->reads == 1 ? map->high : map->low;
	return 0;
}

#include "axp_adc_functions.h"

static unsigned int expected(unsigned int high, unsigned int low, unsigned int width)
{
	/* Independent arithmetic oracle: a base-2 digit contribution, not an OR. */
	unsigned int radix = 1;
	for (unsigned int bit = 8; bit < width; bit++)
		radix *= 2;
	return high * radix + low % radix;
}

static void check_all_bytes(void)
{
	unsigned int cases = 0, canonical = 0;
	for (unsigned int width = 9; width <= 16; width++) {
		for (unsigned int high = 0; high <= 255; high++) {
			for (unsigned int low = 0; low <= 255; low++) {
				struct regmap map = { .base = 0x78, .high = high, .low = low };
				int result = axp20x_read_variable_width(&map, map.base, width);
				assert(result == (int)expected(high, low, width));
				assert(map.reads == 2);
				assert(result >= 0 && (unsigned int)result < (1U << width));
				cases++;
				/* Valid low bytes, including every 16-bit pair, are unchanged. */
				if (low < (1U << (width - 8))) {
					map.reads = 0;
					assert(original_read_variable_width(&map, map.base, width) == result);
					assert(map.reads == 2);
					canonical++;
				}
			}
		}
	}
	assert(cases == 524288 && canonical == 130560);
	printf("Exhaustive byte pairs: %u; unchanged canonical pairs: %u\n", cases, canonical);
}

static void check_errors(void)
{
	const int errors[] = { -EIO, -ETIMEDOUT, -EBUSY, -ENXIO };
	unsigned int cases = 0;
	for (unsigned int width = 9; width <= 16; width++) {
		for (unsigned int index = 0; index < sizeof(errors) / sizeof(errors[0]); index++) {
			for (unsigned int fail_at = 1; fail_at <= 2; fail_at++) {
				struct regmap map = { .base = 0x56, .high = 0xa5, .low = 0xff,
					.fail_at = fail_at, .error = errors[index] };
				assert(axp20x_read_variable_width(&map, map.base, width) == errors[index]);
				assert(map.reads == fail_at);
				cases++;
			}
		}
	}
	assert(cases == 64);
	printf("Read-error cases: %u\n", cases);
}

typedef int (*raw_fn)(struct iio_dev *, const struct iio_chan_spec *, int *);
struct caller_case { raw_fn read; unsigned int type, channel, width; };

static void check_callers(void)
{
	const struct caller_case cases[] = {
		{ axp192_adc_raw, IIO_VOLTAGE, AXP192_BATT_V, 12 },
		{ axp192_adc_raw, IIO_CURRENT, AXP192_BATT_CHRG_I, 13 },
		{ axp192_adc_raw, IIO_CURRENT, AXP192_BATT_DISCHRG_I, 13 },
		{ axp192_adc_raw, IIO_CURRENT, AXP192_VBUS_I, 12 },
		{ axp192_adc_raw, IIO_TEMP, 0, 12 },
		{ axp20x_adc_raw, IIO_VOLTAGE, AXP20X_BATT_V, 12 },
		{ axp20x_adc_raw, IIO_CURRENT, AXP20X_BATT_CHRG_I, 12 },
		{ axp20x_adc_raw, IIO_CURRENT, AXP20X_BATT_DISCHRG_I, 13 },
		{ axp20x_adc_raw, IIO_CURRENT, AXP20X_VBUS_I, 12 },
		{ axp20x_adc_raw, IIO_TEMP, 0, 12 },
		{ axp22x_adc_raw, IIO_VOLTAGE, AXP22X_BATT_V, 12 },
		{ axp22x_adc_raw, IIO_CURRENT, AXP22X_BATT_CHRG_I, 12 },
		{ axp22x_adc_raw, IIO_CURRENT, AXP22X_BATT_DISCHRG_I, 12 },
		{ axp22x_adc_raw, IIO_TEMP, 0, 12 },
		{ axp813_adc_raw, IIO_VOLTAGE, AXP813_GPIO0_V, 12 },
		{ axp813_adc_raw, IIO_VOLTAGE, AXP813_BATT_V, 12 },
		{ axp813_adc_raw, IIO_CURRENT, AXP22X_BATT_CHRG_I, 12 },
		{ axp813_adc_raw, IIO_CURRENT, AXP22X_BATT_DISCHRG_I, 12 },
		{ axp813_adc_raw, IIO_TEMP, 0, 12 },
	};
	unsigned int checks = 0;
	for (unsigned int i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
		const struct caller_case *test = &cases[i];
		struct regmap map = { .base = 0x78, .high = 0x02, .low = 0xf3 };
		struct iio_dev dev = { .info = { .regmap = &map } };
		struct iio_chan_spec chan = { test->type, test->channel, map.base };
		int value = INT_MIN;
		assert(test->read(&dev, &chan, &value) == IIO_VAL_INT);
		assert(value == (int)expected(map.high, map.low, test->width));
		assert(map.reads == 2);
		checks++;
		for (unsigned int fail_at = 1; fail_at <= 2; fail_at++) {
			map.reads = 0;
			map.fail_at = fail_at;
			map.error = -ETIMEDOUT;
			value = INT_MIN;
			assert(test->read(&dev, &chan, &value) == -ETIMEDOUT);
			assert(value == INT_MIN && map.reads == fail_at);
			checks++;
		}
	}
	assert(checks == 57);
	printf("Actual IIO callback cases: %u\n", checks);
}

int main(void)
{
	check_all_bytes();
	check_errors();
	check_callers();
	puts("AXP ADC width and read-error checks passed");
	return 0;
}
