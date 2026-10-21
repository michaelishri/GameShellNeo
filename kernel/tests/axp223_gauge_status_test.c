/* Actual locked MFD/regmap functions with deterministic bus/cache storage. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include "axp_registers.h"

#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define REGCACHE_NONE 0
#define REGCACHE_MAPLE 1
#define BUG_ON(x) assert(!(x))
#define dev_info(...) ((void)0)
#define trace_regmap_reg_read(...) ((void)0)
#define trace_regmap_reg_read_cache(...) ((void)0)
#define regmap_reg_range(a, b) { (a), (b) }
enum { AXP221_ID, AXP223_ID, AXP809_ID };
struct device { int unused; };
struct regmap_range { unsigned int range_min, range_max; };
struct regmap_access_table {
	const struct regmap_range *yes_ranges, *no_ranges;
	unsigned int n_yes_ranges, n_no_ranges;
};
struct regmap_config {
	unsigned int reg_bits, val_bits, max_register, cache_type;
	const struct regmap_access_table *wr_table, *volatile_table;
	bool (*volatile_reg)(struct device *, unsigned int);
};
struct axp20x_dev {
	unsigned int nr_cells;
	const int *cells, *regmap_irq_chip;
	const struct regmap_config *regmap_cfg;
};
static const int axp221_cells[] = { 0 }, axp223_cells[] = { 0 }, axp809_cells[] = { 0 };
static const int axp22x_regmap_irq_chip, axp809_regmap_irq_chip;
struct regmap;
struct cache_ops {
	int (*read)(struct regmap *, unsigned int, unsigned int *);
	int (*write)(struct regmap *, unsigned int, unsigned int);
};
struct regmap {
	struct device *dev;
	struct { bool format_write; } format;
	const struct regmap_access_table *volatile_table;
	bool (*volatile_reg)(struct device *, unsigned int);
	const struct cache_ops *cache_ops;
	unsigned int cache_type, max_register;
	bool cache_only, cache_bypass;
	int (*reg_read)(void *, unsigned int, unsigned int *);
	unsigned int hardware[256], cached[256], bus_reads, cache_writes;
	bool valid[256];
	int bus_error;
};
static bool regmap_readable(struct regmap *map, unsigned int reg)
{
	return reg <= map->max_register;
}
static bool regmap_reg_in_range(unsigned int reg, const struct regmap_range *range)
{
	return reg >= range->range_min && reg <= range->range_max;
}
bool regmap_reg_in_ranges(unsigned int, const struct regmap_range *, unsigned int);
static void *_regmap_map_get_context(struct regmap *map) { return map; }
static bool regmap_should_log(struct regmap *map) { return false; }

#include "axp_status_functions.h"

static int cache_read(struct regmap *map, unsigned int reg, unsigned int *val)
{
	if (!map->valid[reg])
		return -ENOENT;
	*val = map->cached[reg];
	return 0;
}
static int cache_write(struct regmap *map, unsigned int reg, unsigned int val)
{
	map->cache_writes++;
	map->cached[reg] = val;
	map->valid[reg] = true;
	return 0;
}
static int bus_read(void *context, unsigned int reg, unsigned int *val)
{
	struct regmap *map = context;
	map->bus_reads++;
	if (map->bus_error)
		return map->bus_error;
	*val = map->hardware[reg];
	return 0;
}
static const struct cache_ops storage = { cache_read, cache_write };
static struct regmap make_map(const struct regmap_config *config)
{
	struct regmap map = { 0 };
	map.max_register = config->max_register;
	map.cache_type = config->cache_type;
	map.cache_ops = &storage;
	map.volatile_reg = config->volatile_reg;
	map.volatile_table = config->volatile_table;
	map.reg_read = bus_read;
	return map;
}
static bool legacy_volatile(unsigned int reg)
{
	/* Independently frozen from the locked 22x map; mutation tests must not
	 * derive expected behavior from the same potentially changed table. */
	return reg <= 0x01 || (reg >= 0x40 && reg <= 0x4c) || reg == 0x94 ||
	       (reg >= 0x56 && reg <= 0x7f) || reg == 0xb9;
}
static bool legacy_writeable(unsigned int reg)
{
	return (reg >= 0x04 && reg <= 0x4c) ||
	       (reg >= 0x33 && reg <= 0x35) || (reg >= 0x80 && reg <= 0xe6);
}
static void check_profiles(void)
{
	for (int variant = AXP221_ID; variant <= AXP809_ID; variant++) {
		const struct regmap_config *config = select_config(variant);
		struct regmap map = make_map(config);
		assert(config->reg_bits == 8 && config->val_bits == 8);
		assert(config->max_register == 0xe6 && config->cache_type == REGCACHE_MAPLE);
		assert(config->wr_table);
		for (unsigned int reg = 0; reg <= 0xff; reg++) {
			bool expected = reg <= 0xe6 &&
				(legacy_volatile(reg) || (variant == AXP223_ID && reg == 0xb8));
			assert(regmap_volatile(&map, reg) == expected);
			assert(regmap_check_range_table(&map, reg, config->wr_table) == legacy_writeable(reg));
		}
	}
}
static void check_status_reads(void)
{
	struct regmap map = make_map(select_config(AXP223_ID));
	unsigned int value;
	/* Exercise every possible byte, preserving all controls and reserved bits. */
	for (unsigned int status = 0; status <= 0xff; status++) {
		map.hardware[0xb8] = status;
		value = 0xfeed;
		assert(_regmap_read(&map, 0xb8, &value) == 0 && value == status);
	}
	assert(map.bus_reads == 256 && map.cache_writes == 0 && !map.valid[0xb8]);
	/* An old cached value must not hide current hardware or a read error. */
	map.valid[0xb8] = true;
	map.cached[0xb8] = 0xc0;
	map.hardware[0xb8] = 0xd0;
	assert(_regmap_read(&map, 0xb8, &value) == 0 && value == 0xd0);
	map.hardware[0xb8] = 0xc0;
	assert(_regmap_read(&map, 0xb8, &value) == 0 && value == 0xc0);
	map.bus_error = -EIO;
	value = 0xfeed;
	assert(_regmap_read(&map, 0xb8, &value) == -EIO && value == 0xfeed);
	map.bus_error = 0;
	unsigned int reads = map.bus_reads;
	map.cache_only = true;
	assert(_regmap_read(&map, 0xb8, &value) == -EBUSY && value == 0xfeed);
	assert(map.bus_reads == reads);
	map.cache_only = false;
	assert(_regmap_read(&map, 0xb8, &value) == 0 && value == 0xc0);
}
static void check_unchanged_cache(void)
{
	for (int variant = AXP221_ID; variant <= AXP809_ID; variant++) {
		struct regmap map = make_map(select_config(variant));
		unsigned int value;
		map.hardware[0x33] = 0xc6;
		assert(_regmap_read(&map, 0x33, &value) == 0 && value == 0xc6);
		map.hardware[0x33] = 0x46;
		assert(_regmap_read(&map, 0x33, &value) == 0 && value == 0xc6);
		assert(map.bus_reads == 1 && map.cache_writes == 1);
		if (variant == AXP223_ID)
			continue;
		map.hardware[0xb8] = 0xc0;
		assert(_regmap_read(&map, 0xb8, &value) == 0 && value == 0xc0);
		map.hardware[0xb8] = 0xd0;
		assert(_regmap_read(&map, 0xb8, &value) == 0 && value == 0xc0);
		assert(map.bus_reads == 2 && map.cache_writes == 2);
	}
}
int main(void)
{
	check_profiles();
	check_status_reads();
	check_unchanged_cache();
	puts("AXP223 status: profiles, live transitions, read failures and cache-only checks passed");
	return 0;
}
