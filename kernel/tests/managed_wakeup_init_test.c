// SPDX-License-Identifier: GPL-2.0
/* Actual inline bodies; framework effects are the disclosed synchronous model. */
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct source {
	unsigned int id;
};

struct device {
	struct {
		bool can_wakeup;
		struct source *wakeup;
	} power;
	bool registered;
};

enum fault {
	NO_FAULT,
	SOURCE_ALLOCATION,
	ACTION_ALLOCATION,
};

struct failure {
	const char *assertion;
	long long actual;
	long long expected;
};

struct fixture {
	struct device dev;
	const char *name;
	enum fault fault;
	void (*action)(void *);
	void *action_data;
	bool ids[16];
	unsigned int fault_hits;
	unsigned int allocations;
	unsigned int frees;
	unsigned int action_resets;
	unsigned int releases;
	unsigned int failure_count;
	struct failure failures[32];
	int result;
	bool action_present;
	bool capable_after_release;
};

static struct fixture *active;

static void fatal(const char *message)
{
	fprintf(stderr, "Unexpected model boundary: %s\n", message);
	exit(2);
}

static void require_device(struct device *dev)
{
	if (!active || dev != &active->dev || !dev->registered)
		fatal("unowned or unregistered device");
}

static void device_set_wakeup_capable(struct device *dev, bool capable)
{
	require_device(dev);
	if (active->fault == ACTION_ALLOCATION && !capable && dev->power.can_wakeup)
		active->action_resets++;
	dev->power.can_wakeup = capable;
}

static struct source *source_allocate(void)
{
	struct source *source;
	unsigned int id;

	if (active->fault == SOURCE_ALLOCATION && !active->fault_hits) {
		active->fault_hits++;
		return NULL;
	}
	for (id = 0; id < 16 && active->ids[id]; id++)
		;
	if (id == 16)
		fatal("source ID exhaustion");
	source = calloc(1, sizeof(*source));
	if (!source)
		fatal("host allocation");
	source->id = id;
	active->ids[id] = true;
	active->allocations++;
	return source;
}

static void source_free(struct source *source)
{
	if (!source || source->id >= 16 || !active->ids[source->id])
		fatal("invalid source release");
	active->ids[source->id] = false;
	active->frees++;
	free(source);
}

static int device_wakeup_enable(struct device *dev)
{
	struct source *source;

	require_device(dev);
	if (!dev->power.can_wakeup)
		fatal("capability not initialized");
	source = source_allocate();
	if (!source)
		return -ENOMEM;
	if (dev->power.wakeup) {
		source_free(source);
		return -EEXIST;
	}
	dev->power.wakeup = source;
	return 0;
}

static void device_wakeup_disable(struct device *dev)
{
	require_device(dev);
	if (!dev->power.can_wakeup)
		return;
	if (dev->power.wakeup) {
		source_free(dev->power.wakeup);
		dev->power.wakeup = NULL;
	}
}

static int __devm_add_action(struct device *dev, void (*action)(void *),
			     void *data, const char *name)
{
	require_device(dev);
	if (!action || data != dev || strcmp(name, "device_disable_wakeup") || active->action)
		fatal("different managed action");
	if (active->fault == ACTION_ALLOCATION && !active->fault_hits) {
		active->fault_hits++;
		return -ENOMEM;
	}
	active->action = action;
	active->action_data = data;
	return 0;
}

#include "managed-wakeup-inline.h"

static unsigned int devres_release_all(struct device *dev)
{
	void (*action)(void *);
	void *data;

	require_device(dev);
	if (!active->action)
		return 0;
	action = active->action;
	data = active->action_data;
	active->action = NULL;
	active->action_data = NULL;
	action(data);
	return 1;
}

static void expect(struct fixture *f, const char *name, long long actual,
		   long long expected)
{
	struct failure *failure;

	if (actual == expected)
		return;
	if (f->failure_count == 32)
		fatal("assertion overflow");
	failure = &f->failures[f->failure_count++];
	*failure = (struct failure) { name, actual, expected };
}

static void begin(struct fixture *f, const char *name, enum fault fault)
{
	memset(f, 0, sizeof(*f));
	f->dev.registered = true;
	f->name = name;
	f->fault = fault;
	active = f;
}

static void observe_release(struct fixture *f)
{
	f->action_present = active->action != NULL;
	devres_release_all(&f->dev);
	f->capable_after_release = f->dev.power.can_wakeup;
}

static void finish(struct fixture *f)
{
	unsigned int i;

	expect(f, "second_devres_release", devres_release_all(&f->dev), 0);
	device_wakeup_disable(&f->dev);
	for (i = 0; i < 16; i++)
		expect(f, "final_source_id", f->ids[i], 0);
	expect(f, "final_source", f->dev.power.wakeup != NULL, 0);
	expect(f, "balanced_sources", f->allocations, f->frees);
	f->dev.registered = false;
	f->releases++;
	active = NULL;
}

static void successful_case(struct fixture *f, bool capable)
{
	if (capable)
		device_set_wakeup_capable(&f->dev, true);
	f->result = devm_device_init_wakeup(&f->dev);
	expect(f, "result", f->result, 0);
	expect(f, "enabled_capability", f->dev.power.can_wakeup, 1);
	expect(f, "enabled_source", f->dev.power.wakeup != NULL, 1);
	expect(f, "action_present", f->action != NULL, 1);
	observe_release(f);
	expect(f, "released_source", f->dev.power.wakeup != NULL, 0);
	expect(f, "capable_after_release", f->capable_after_release, 0);
	finish(f);
}

static void source_error_case(struct fixture *f)
{
	f->result = devm_device_init_wakeup(&f->dev);
	expect(f, "result", f->result, -ENOMEM);
	expect(f, "action_present", f->action != NULL, 0);
	expect(f, "source_absent", f->dev.power.wakeup != NULL, 0);
	expect(f, "failed_init_capability", f->dev.power.can_wakeup, 1);
	expect(f, "source_fault_once", f->fault_hits, 1);
	observe_release(f);
	expect(f, "capable_after_release", f->capable_after_release, 1);
	finish(f);
}

static void existing_source_case(struct fixture *f)
{
	uintptr_t identity;
	unsigned int id;

	if (device_init_wakeup(&f->dev, true))
		fatal("existing-source setup");
	identity = (uintptr_t)f->dev.power.wakeup;
	id = f->dev.power.wakeup->id;
	f->result = devm_device_init_wakeup(&f->dev);
	expect(f, "result", f->result, -EEXIST);
	expect(f, "action_present", f->action != NULL, 0);
	observe_release(f);
	/* Identity and the ID table remain safe to inspect after a bad control frees it. */
	expect(f, "source_preserved", (uintptr_t)f->dev.power.wakeup == identity, 1);
	expect(f, "id_preserved", f->ids[id], 1);
	expect(f, "capable_after_release", f->capable_after_release, 1);
	finish(f);
}

static void action_error_case(struct fixture *f)
{
	f->result = devm_device_init_wakeup(&f->dev);
	expect(f, "result", f->result, -ENOMEM);
	expect(f, "action_present", f->action != NULL, 0);
	expect(f, "action_fault_once", f->fault_hits, 1);
	expect(f, "reset_source_absent", f->dev.power.wakeup != NULL, 0);
	expect(f, "reset_capability", f->dev.power.can_wakeup, 0);
	observe_release(f);
	finish(f);
}

static void print_case(const struct fixture *f)
{
	unsigned int i;

	printf("{\"name\":\"%s\",\"failures\":[", f->name);
	for (i = 0; i < f->failure_count; i++) {
		const struct failure *failure = &f->failures[i];

		printf("%s{\"assertion\":\"%s\",\"actual\":%lld,\"expected\":%lld}",
		       i ? "," : "", failure->assertion, failure->actual, failure->expected);
	}
	printf("],\"observations\":{\"result\":%d,\"fault_hits\":%u,"
	       "\"source_allocations\":%u,\"source_frees_final\":%u,"
	       "\"action_present\":%u,\"action_resets\":%u,"
	       "\"capable_after_release\":%u,\"device_releases\":%u,\"final_sources\":0}}",
	       f->result, f->fault_hits, f->allocations, f->frees,
	       f->action_present, f->action_resets, f->capable_after_release, f->releases);
}

int main(void)
{
	struct fixture cases[5];
	unsigned int i, failed = 0;

	begin(&cases[0], "managed_wakeup_success_test", NO_FAULT);
	successful_case(&cases[0], false);
	begin(&cases[1], "managed_wakeup_source_error_test", SOURCE_ALLOCATION);
	source_error_case(&cases[1]);
	begin(&cases[2], "managed_wakeup_existing_source_test", NO_FAULT);
	existing_source_case(&cases[2]);
	begin(&cases[3], "managed_wakeup_action_error_test", ACTION_ALLOCATION);
	action_error_case(&cases[3]);
	begin(&cases[4], "managed_wakeup_capable_disabled_test", NO_FAULT);
	successful_case(&cases[4], true);
	printf("{\"cases\":[");
	for (i = 0; i < 5; i++) {
		if (i)
			printf(",");
		print_case(&cases[i]);
		failed += cases[i].failure_count != 0;
	}
	puts("]}");
	return failed ? 1 : 0;
}
