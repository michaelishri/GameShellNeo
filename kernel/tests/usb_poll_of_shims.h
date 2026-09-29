/* SPDX-License-Identifier: GPL-2.0-only */
/* Reference-counted OF and register shims, not a model of electrical behavior. */
#include <assert.h>

typedef uint64_t u64;
typedef struct { bool held; } spinlock_t;
struct mutex { bool held; };
static unsigned long jiffies;
static unsigned int locks_held;
#define spin_lock_init(lock) ((lock)->held = false)
#define mutex_init(lock) ((lock)->held = false)
#define spin_lock_irqsave(lock, flags) do { \
	(flags) = 0; assert(!(lock)->held); (lock)->held = true; locks_held++; \
} while (0)
#define spin_unlock_irqrestore(lock, flags) do { \
	(void)(flags); assert((lock)->held); (lock)->held = false; locks_held--; \
} while (0)
#define mutex_lock(lock) do { assert(!(lock)->held); (lock)->held = true; } while (0)
#define mutex_unlock(lock) do { assert((lock)->held); (lock)->held = false; } while (0)
#define time_after_eq(a, b) ((long)((a) - (b)) >= 0)
#define time_before(a, b) ((long)((a) - (b)) < 0)

#define AXP223_ID 3
#define AXP20X_VBUS_IPSOUT_MGMT 0x30
#define AXP20X_OVER_TMP 0x8f
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x, v) ((x) = (v))
#define msecs_to_jiffies(x) (x)
#define module_param(...)
#define MODULE_PARM_DESC(...)
#define IS_ENABLED(x) (x)
#define CONFIG_AXP20X_ADC 0
#define CONFIG_USB_MUSB_GADGET config_gadget
#define CONFIG_USB_MUSB_SUNXI config_sunxi
#define CONFIG_USB_MUSB_HOST config_host
#define CONFIG_USB_MUSB_DUAL_ROLE config_dual
#define CONFIG_PM_SLEEP config_sleep
#define CONFIG_OF_DYNAMIC config_dynamic

static bool config_gadget, config_sunxi, config_host, config_dual, config_sleep, config_dynamic;
static unsigned int input_config, gpio_config, input_status, read_count, race_position;
static int error_register;
static bool run_early_work;

struct device_node;
struct of_phandle_args {
	struct device_node *np;
	unsigned int args_count, args[1];
};

static const char * const properties[] = {
	"usb0_vbus-supply", "usb0_vbus_det-gpios", "usb0_vbus_det-gpio",
	"usb0_id_det-gpios", "usb0_id_det-gpio", "usb-role-switch", "extcon",
	"vbus-supply", "x-powers,drive-vbus-en",
};

struct device_node {
	struct device_node *parent, *supply, *extcon;
	const char *compatible, *mode;
	bool enabled, supply_property, phys_property;
	unsigned int property_bits, phy_cells;
	int refs, supply_cells, phys_count, parse_error, extcon_cells, extcon_port;
	struct of_phandle_args phys[4];
};
static struct device_node nodes[512];
static unsigned int node_count;
static bool board_match, soc_match;

static struct device_node *of_node_get(struct device_node *node)
{
	if (node)
		node->refs++;
	return node;
}

static void of_node_put(struct device_node *node)
{
	if (node) {
		assert(node->refs > 0);
		node->refs--;
	}
}

static struct device_node *of_get_next_parent(struct device_node *node)
{
	struct device_node *parent = node->parent;
	of_node_put(node);
	return of_node_get(parent);
}

static struct device_node *next_node(struct device_node *previous)
{
	unsigned int next = previous ? (unsigned int)(previous - nodes) + 1 : 0;
	of_node_put(previous);
	return next < node_count ? of_node_get(&nodes[next]) : NULL;
}
#define for_each_of_allnodes(node) for (node = next_node(NULL); node; node = next_node(node))

static bool of_device_is_available(struct device_node *node) { return node && node->enabled; }
static bool of_device_is_compatible(struct device_node *node, const char *name)
{
	return node && node->compatible && !strcmp(node->compatible, name);
}
static bool of_machine_is_compatible(const char *name)
{
	return !strcmp(name, "clockwork,clockworkpi-cpi3") ? board_match : soc_match;
}
static bool of_property_present(struct device_node *node, const char *name)
{
	if (!node)
		return false;
	if (!strcmp(name, "usb0_vbus_power-supply"))
		return node->supply_property;
	if (!strcmp(name, "phys"))
		return node->phys_property;
	for (unsigned int i = 0; i < sizeof(properties) / sizeof(properties[0]); i++)
		if (!strcmp(name, properties[i]))
			return !!(node->property_bits & (1U << i));
	assert(!"unexpected property lookup");
	return false;
}
static int of_property_count_u32_elems(struct device_node *node, const char *name)
{
	if (!strcmp(name, "extcon"))
		return node->extcon_cells;
	assert(!strcmp(name, "usb0_vbus_power-supply"));
	return node->supply_cells;
}
static struct device_node *of_parse_phandle(struct device_node *node, const char *name, int index)
{
	if (!strcmp(name, "extcon")) {
		assert(index == 0);
		return of_node_get(node->extcon);
	}
	assert(!strcmp(name, "usb0_vbus_power-supply") && index == 0);
	return of_node_get(node->supply);
}
static int of_property_read_u32_index(struct device_node *node, const char *name, int index,
				      unsigned int *value)
{
	assert(!strcmp(name, "extcon") && index == 1);
	*value = node->extcon_port;
	return node->extcon_port < 0 ? -EINVAL : 0;
}
static int of_property_read_u32(struct device_node *node, const char *name, unsigned int *value)
{
	assert(!strcmp(name, "#phy-cells"));
	*value = node->phy_cells;
	return node->phy_cells == 99 ? -EINVAL : 0;
}
static int of_count_phandle_with_args(struct device_node *node, const char *list, const char *cells)
{
	assert(!strcmp(list, "phys") && !strcmp(cells, "#phy-cells"));
	return node->phys_count;
}
static int of_parse_phandle_with_args(struct device_node *node, const char *list,
				      const char *cells, int index, struct of_phandle_args *args)
{
	assert(!strcmp(list, "phys") && !strcmp(cells, "#phy-cells") && index < 4);
	if (node->parse_error == index)
		return -EINVAL;
	*args = node->phys[index];
	of_node_get(args->np);
	return 0;
}
static int of_property_read_string(struct device_node *node, const char *name, const char **value)
{
	assert(!strcmp(name, "dr_mode"));
	*value = node->mode;
	return node->mode ? 0 : -EINVAL;
}

static void reset_graph(void)
{
	memset(nodes, 0, sizeof(nodes));
	node_count = 7;
	for (unsigned int i = 0; i < node_count; i++) {
		nodes[i].enabled = true;
		nodes[i].parent = i ? &nodes[0] : NULL;
		nodes[i].parse_error = -1;
	}
	nodes[1].compatible = "x-powers,axp223";
	nodes[2].compatible = "x-powers,axp223-usb-power-supply";
	nodes[2].parent = &nodes[1];
	nodes[3].compatible = "allwinner,sun8i-a33-usb-phy";
	nodes[3].supply_property = true;
	nodes[3].supply_cells = 1;
	nodes[3].supply = &nodes[2];
	nodes[3].phy_cells = 1;
	nodes[4].compatible = "allwinner,sun8i-a33-musb";
	nodes[4].mode = "peripheral";
	nodes[4].extcon = &nodes[3];
	nodes[4].extcon_cells = 2;
	for (unsigned int i = 4; i <= 6; i++) {
		nodes[i].phys_property = true;
		nodes[i].phys_count = 1;
		nodes[i].phys[0] = (struct of_phandle_args){ &nodes[3], 1, { i == 4 ? 0 : 1 } };
	}
	board_match = soc_match = config_gadget = config_sunxi = true;
	config_host = config_dual = config_sleep = config_dynamic = false;
	input_config = 0x60;
	gpio_config = 1;
	input_status = 32;
	error_register = -1;
	read_count = race_position = 0;
}
