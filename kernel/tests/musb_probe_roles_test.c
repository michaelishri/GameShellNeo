/* Exercise the production role initializer with controlled registration APIs. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

enum { MUSB_HOST = 1, MUSB_PERIPHERAL, MUSB_OTG };
struct device { int unused; };
struct musb { int port_mode; struct device *controller; };
struct musb_hdrc_platform_data { int power; };
static int host_error, gadget_error, mode_result;
static bool host_live, gadget_live, resources_live;
static char events[16];
static unsigned int event_count;

#define dev_err(...) ((void)0)

static void event(char value)
{
	assert(resources_live && event_count + 1 < sizeof(events));
	events[event_count++] = value;
}

static int musb_host_setup(struct musb *musb, int power)
{
	assert(musb->port_mode != MUSB_PERIPHERAL && !host_live);
	assert(power == 127);
	event('H');
	if (!host_error)
		host_live = true;
	return host_error;
}

static int musb_gadget_setup(struct musb *musb)
{
	assert(musb->port_mode != MUSB_HOST && !gadget_live);
	assert(musb->port_mode != MUSB_OTG || host_live);
	event('G');
	if (!gadget_error)
		gadget_live = true;
	return gadget_error;
}

static int musb_platform_set_mode(struct musb *musb, int mode)
{
	assert(mode == musb->port_mode);
	assert(host_live == (mode != MUSB_PERIPHERAL));
	assert(gadget_live == (mode != MUSB_HOST));
	event('M');
	return mode_result;
}

static void musb_gadget_cleanup(struct musb *musb)
{
	assert(musb->port_mode != MUSB_HOST && gadget_live);
	assert(musb->port_mode != MUSB_OTG || host_live);
	event('g');
	gadget_live = false;
}

static void musb_host_cleanup(struct musb *musb)
{
	assert(musb->port_mode != MUSB_PERIPHERAL && host_live);
	assert(!gadget_live);
	event('h');
	host_live = false;
}

#include "musb_probe_roles_function.h"

static void clean_success(struct musb *musb)
{
	if (gadget_live)
		musb_gadget_cleanup(musb);
	if (host_live)
		musb_host_cleanup(musb);
}

static void reset_events(void)
{
	memset(events, 0, sizeof(events));
	event_count = 0;
}

static unsigned int cases, retries;

static void check(int role, int host, int gadget, int mode, int expected,
		  const char *sequence)
{
	struct musb musb = { .port_mode = role };

	assert(!host_live && !gadget_live);
	resources_live = true;
	host_error = host;
	gadget_error = gadget;
	mode_result = mode;
	reset_events();
	assert(musb_init_roles(&musb, 127) == expected);
	assert(!strcmp(events, sequence));
	cases++;
	if (expected < 0) {
		assert(!host_live && !gadget_live);
		/* A failed registration must leave no owner for a subsequent try. */
		if (role >= MUSB_HOST && role <= MUSB_OTG) {
			host_error = gadget_error = mode_result = 0;
			reset_events();
			assert(!musb_init_roles(&musb, 127));
			assert(host_live == (role != MUSB_PERIPHERAL));
			assert(gadget_live == (role != MUSB_HOST));
			retries++;
			clean_success(&musb);
		}
	} else {
		assert(host_live == (role != MUSB_PERIPHERAL));
		assert(gadget_live == (role != MUSB_HOST));
		clean_success(&musb);
	}
	resources_live = false;
}

int main(void)
{
	static const int setup_errors[] = { -ENOMEM, -EBUSY };
	static const int mode_errors[] = { -EIO, -EINVAL, -ETIMEDOUT };
	unsigned int i;
	int role;

	for (role = MUSB_HOST; role <= MUSB_OTG; role++) {
		const char *success = role == MUSB_HOST ? "HM" :
			role == MUSB_PERIPHERAL ? "GM" : "HGM";
		const char *failed = role == MUSB_HOST ? "HMh" :
			role == MUSB_PERIPHERAL ? "GMg" : "HGMgh";

		check(role, 0, 0, 0, 0, success);
		check(role, 0, 0, 1, 1, success);
		for (i = 0; i < sizeof(setup_errors) / sizeof(*setup_errors); i++) {
			if (role != MUSB_PERIPHERAL)
				check(role, setup_errors[i], 0, 0,
				      setup_errors[i], "H");
			if (role != MUSB_HOST)
				check(role, 0, setup_errors[i], 0,
				      setup_errors[i], role == MUSB_OTG ? "HGh" : "G");
		}
		for (i = 0; i < sizeof(mode_errors) / sizeof(*mode_errors); i++)
			check(role, 0, 0, mode_errors[i], mode_errors[i], failed);
	}
	check(0, 0, 0, 0, -EINVAL, "");
	check(99, 0, 0, 0, -EINVAL, "");
	assert(cases == 25 && retries == 17);
	printf("MUSB probe roles: %u cases passed (%u successful retries)\n",
	       cases, retries);
	return 0;
}
