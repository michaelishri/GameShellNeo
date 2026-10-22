/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual MPFS probe/remove plus actual generic/platform unregister helpers. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define GFP_KERNEL 0
#define PLATFORM_DEVID_AUTO -2
#define EPROBE_DEFER 517
#define DMA_BIT_MASK(n) ((UINT64_C(1) << (n)) - 1)
#define ERR_PTR(error) ((void *)(intptr_t)(error))
#define PTR_ERR(pointer) ((intptr_t)(pointer))
#define IS_ERR(pointer) ((uintptr_t)(pointer) >= (uintptr_t)-4095)
#define IS_ERR_OR_NULL(pointer) (!(pointer) || IS_ERR(pointer))
#define dev_err(...) ((void)0)
#define dev_info(...) ((void)0)
typedef uint32_t u32;
enum { USB_DR_MODE_UNKNOWN, USB_DR_MODE_HOST, USB_DR_MODE_PERIPHERAL, USB_DR_MODE_OTG };
enum failure {
	SUCCESS, GLUE_ALLOC, CHILD_ALLOC, CLOCK_GET, CLOCK_ENABLE, PDATA_ALLOC,
	PHY_REGISTER, ADD_RESOURCES, ADD_DATA, ADD_CHILD, FAILURE_COUNT
};
struct device {
	struct device *parent;
	uint64_t coherent_dma_mask, *dma_mask;
	void *driver_data;
	bool registered;
};
struct resource { struct resource *parent; };
struct platform_device {
	struct device dev;
	struct resource *resource;
	unsigned num_resources, references;
	bool id_auto;
	int id;
};
struct clk { int unused; };
struct musb_hdrc_platform_data {
	const void *config, *platform_ops;
	bool extvbus;
	int mode;
};
#include "mpfs_ownership_definitions.h"

static struct platform_device parent, child, phy;
static struct mpfs_glue glue;
static struct musb_hdrc_platform_data pdata;
static struct clk clock;
static const int mpfs_musb_hdrc_config, mpfs_ops;
static int platform_devid_ida, failure, mode, allocations;
static bool parent_clock_enabled, external_vbus;
static char retirement[8];
static unsigned retired, scenarios;

static void record(char event)
{
	assert(retired + 1 < sizeof(retirement));
	retirement[retired++] = event;
}

static void *dev_get_platdata(struct device *dev)
{
	assert(dev == &parent.dev);
	return NULL;
}

static void *devm_kzalloc(struct device *dev, size_t bytes, int flags)
{
	assert(dev == &parent.dev && flags == GFP_KERNEL);
	allocations++;
	if (allocations == 1) {
		assert(bytes == sizeof(glue));
		return failure == GLUE_ALLOC ? NULL : &glue;
	}
	assert(allocations == 2 && bytes == sizeof(pdata));
	return failure == PDATA_ALLOC ? NULL : &pdata;
}

static struct platform_device *platform_device_alloc(const char *name, int id)
{
	assert(!strcmp(name, "musb-hdrc") && id == PLATFORM_DEVID_AUTO);
	if (failure == CHILD_ALLOC)
		return NULL;
	child.references = 1;
	return &child;
}

static struct clk *devm_clk_get(struct device *dev, const char *name)
{
	assert(dev == &parent.dev && !name);
	return failure == CLOCK_GET ? ERR_PTR(-ENODEV) : &clock;
}

static int clk_prepare_enable(struct clk *clk)
{
	assert(clk == &clock && !parent_clock_enabled);
	if (failure == CLOCK_ENABLE)
		return -EAGAIN;
	parent_clock_enabled = true;
	return 0;
}

static void clk_disable_unprepare(struct clk *clk)
{
	assert(clk == &clock && parent_clock_enabled);
	parent_clock_enabled = false;
	record('K');
}

static void device_set_of_node_from_dev(struct device *dev, struct device *source)
{
	assert(dev == &child.dev && source == &parent.dev);
}

static bool device_property_read_bool(struct device *dev, const char *name)
{
	assert(dev == &parent.dev && !strcmp(name, "microchip,ext-vbus-drv"));
	return external_vbus;
}

static int usb_get_dr_mode(struct device *dev)
{
	assert(dev == &parent.dev);
	return mode;
}

static struct platform_device *platform_device_register_simple(const char *name, int id,
						      struct resource *res, unsigned count)
{
	assert(!strcmp(name, "usb_phy_generic") && id == PLATFORM_DEVID_AUTO);
	assert(!res && !count && parent_clock_enabled);
	if (failure == PHY_REGISTER)
		return ERR_PTR(-EPROBE_DEFER);
	phy.references = 1;
	phy.dev.registered = true;
	return &phy;
}

static void platform_set_drvdata(struct platform_device *dev, void *data)
{
	assert(dev == &parent && data == &glue);
	dev->dev.driver_data = data;
}

static void *platform_get_drvdata(struct platform_device *dev)
{
	assert(dev == &parent);
	return dev->dev.driver_data;
}

static int platform_device_add_resources(struct platform_device *dev,
					 struct resource *res, unsigned count)
{
	assert(dev == &child && res == parent.resource && count == parent.num_resources);
	return failure == ADD_RESOURCES ? -EINVAL : 0;
}

static int platform_device_add_data(struct platform_device *dev, const void *data, size_t bytes)
{
	assert(dev == &child && data == &pdata && bytes == sizeof(pdata));
	assert(pdata.config == &mpfs_musb_hdrc_config && pdata.platform_ops == &mpfs_ops);
	assert(pdata.extvbus == external_vbus);
	assert(pdata.mode == (mode == USB_DR_MODE_UNKNOWN ? USB_DR_MODE_OTG : mode));
	return failure == ADD_DATA ? -EOVERFLOW : 0;
}

static int platform_device_add(struct platform_device *dev)
{
	assert(dev == &child && dev->references == 1 && parent_clock_enabled);
	assert(dev->dev.parent == &parent.dev);
	assert(dev->dev.coherent_dma_mask == DMA_BIT_MASK(39));
	assert(dev->dev.dma_mask == &dev->dev.coherent_dma_mask);
	if (failure == ADD_CHILD)
		return -EBUSY;
	dev->dev.registered = true;
	return 0;
}

static void device_del(struct device *dev)
{
	assert(dev != &parent.dev); /* A child's PHY release must never unregister its parent. */
	assert(dev->registered);
	if (dev == &child.dev) {
		/* Child client/IRQ/DMA cleanup still requires the parent's clock. */
		assert(parent_clock_enabled);
		record('C');
	} else {
		assert(dev == &phy.dev);
		record('P');
	}
	dev->registered = false;
}

static void put_device(struct device *dev)
{
	struct platform_device *owned = dev == &child.dev ? &child : &phy;

	assert(dev == &child.dev || dev == &phy.dev);
	assert(!dev->registered && owned->references == 1);
	owned->references--;
}

static void ida_free(int *ida, int id) { (void)id; assert(ida == &platform_devid_ida); }
static void release_resource(struct resource *res) { (void)res; assert(false); }

#include "mpfs_ownership_functions.h"

static void reset(void)
{
	memset(&parent, 0, sizeof(parent));
	memset(&child, 0, sizeof(child));
	memset(&phy, 0, sizeof(phy));
	memset(&glue, 0, sizeof(glue));
	memset(&pdata, 0, sizeof(pdata));
	memset(retirement, 0, sizeof(retirement));
	parent.references = 1;
	parent.dev.registered = true;
	parent_clock_enabled = false;
	retired = allocations = 0;
}

int main(void)
{
	static const int expected[] = {
		0, -ENOMEM, -ENOMEM, -ENODEV, -EAGAIN, -ENOMEM,
		-EPROBE_DEFER, -EINVAL, -EOVERFLOW, -EBUSY,
	};

	for (failure = SUCCESS; failure < FAILURE_COUNT; failure++)
	for (unsigned known_mode = 0; known_mode < 2; known_mode++)
	for (unsigned vbus = 0; vbus < 2; vbus++) {
		reset();
		mode = known_mode ? USB_DR_MODE_PERIPHERAL : USB_DR_MODE_UNKNOWN;
		external_vbus = vbus;
		assert(mpfs_probe(&parent) == expected[failure]);
		if (failure == SUCCESS) {
			assert(glue.musb == &child && glue.phy == &phy && glue.clk == &clock);
			assert(child.dev.registered && phy.dev.registered && parent_clock_enabled);
			mpfs_remove(&parent);
			assert(!strcmp(retirement, "CPK"));
		}
		assert(!child.dev.registered && !child.references);
		assert(!phy.dev.registered && !phy.references && !parent_clock_enabled);
		assert(parent.dev.registered && parent.references == 1);
		scenarios++;
	}
	reset();
	usb_phy_generic_unregister(NULL);
	assert(parent.dev.registered && parent.references == 1 && !retired);
	scenarios++;
	usb_phy_generic_unregister(ERR_PTR(-ENOMEM));
	assert(parent.dev.registered && parent.references == 1 && !retired);
	scenarios++;
	printf("MPFS backend ownership: %u actual-source scenarios passed\n", scenarios);
	return 0;
}
