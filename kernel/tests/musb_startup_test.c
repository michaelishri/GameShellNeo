/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual MUSB start, UDC start wrapper and PM get helpers; controlled boundaries. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#define EPROBE_DEFER 517
#define RPM_GET_PUT 1
#define USB_SPEED_FULL 1
#define USB_SPEED_HIGH 2
#define USB_EVENT_ID 1
#define PHY_MODE_USB_DEVICE 1
#define OTG_STATE_B_IDLE 1
#define __must_hold(lock)
#define dev_err(...) ((void)0)
#define spin_lock_irqsave(p, flags) do { (flags) = 0; assert(!*(p)); *(p) = 1; } while (0)
#define spin_unlock_irqrestore(p, flags) do { (void)(flags); assert(*(p)); *(p) = 0; } while (0)

struct device { int refs; };
struct usb_gadget;
struct usb_gadget_driver { int max_speed; };
struct usb_gadget_ops { int (*udc_start)(struct usb_gadget *, struct usb_gadget_driver *); };
struct usb_gadget { const struct usb_gadget_ops *ops; };
struct usb_udc {
	struct usb_gadget *gadget;
	struct usb_gadget_driver *driver;
	bool started;
};
struct transceiver { void *otg; int last_event; };
struct musb {
	struct device *controller;
	struct usb_gadget g;
	struct usb_gadget_driver *gadget_driver;
	struct transceiver *xceiv;
	void *phy;
	int lock, softconnect, is_active, state;
};
static struct musb instance;
static int resume_result, base_refs;
static unsigned get_calls, noidle, put_calls, starts, modes, vbus, busy, scenarios;
static struct musb *gadget_to_musb(struct usb_gadget *g)
{ assert(g == &instance.g); return &instance; }
static int __pm_runtime_resume(struct device *d, int flags)
{ assert(d == instance.controller && !instance.lock && flags == RPM_GET_PUT); get_calls++; d->refs++; return resume_result; }
static void __attribute__((unused)) pm_runtime_put_noidle(struct device *d)
{ assert(d->refs > base_refs); noidle++; d->refs--; }
static void __attribute__((unused)) pm_runtime_put_autosuspend(struct device *d)
{ assert(d->refs > base_refs && resume_result >= 0); put_calls++; d->refs--; }
static void powered(void)
{ assert(resume_result >= 0 && instance.controller->refs > base_refs); }
static void pm_runtime_mark_last_busy(struct device *d)
{ assert(d == instance.controller); powered(); busy++; }
static void otg_set_peripheral(void *otg, struct usb_gadget *g)
{ powered(); assert(instance.lock && otg == instance.xceiv->otg && g == &instance.g); modes++; }
static void phy_set_mode(void *phy, int mode)
{ powered(); assert(instance.lock && phy == instance.phy && mode == PHY_MODE_USB_DEVICE); modes++; }
static void musb_set_state(struct musb *m, int state)
{ powered(); assert(m->lock && m == &instance); m->state = state; }
static void musb_start(struct musb *m)
{ powered(); assert(m == &instance && !m->lock && m->gadget_driver && m->is_active); starts++; }
static void musb_platform_set_vbus(struct musb *m, int on)
{ powered(); assert(m == &instance && !m->lock && on == 1); vbus++; }

#include "musb_startup_functions.h"

int main(void)
{
	const int results[] = {0, 1, -EIO, -EBUSY, -EACCES, -EPROBE_DEFER, -ETIMEDOUT};
	const struct usb_gadget_ops ops = {.udc_start = musb_gadget_start};
	for (int backend = 0; backend < 3; backend++)
	for (int hold = 0; hold < 2; hold++)
	for (unsigned i = 0; i < sizeof(results) / sizeof(results[0]); i++) {
		struct device controller = {.refs = hold};
		struct usb_gadget_driver driver = {.max_speed = USB_SPEED_HIGH};
		struct transceiver transceiver = {.otg = &controller, .last_event = backend == 2 ? USB_EVENT_ID : 0};
		instance = (struct musb){.controller = &controller, .g = {.ops = &ops},
			.xceiv = backend ? &transceiver : NULL, .phy = &controller, .softconnect = 1};
		struct usb_udc udc = {.gadget = &instance.g, .driver = &driver};
		struct musb before = instance;
		get_calls = noidle = put_calls = starts = modes = vbus = busy = 0;
		base_refs = hold; resume_result = results[i];
		int ret = usb_gadget_udc_start_locked(&udc);
		if (results[i] < 0) {
			assert(ret == results[i] && !udc.started && get_calls == 1 && noidle == 1);
			assert(!memcmp(&instance, &before, sizeof(instance)) && controller.refs == hold);
			assert(!put_calls && !starts && !modes && !vbus && !busy);
			resume_result = 0;
			assert(!usb_gadget_udc_start_locked(&udc));
		} else {
			assert(!ret && get_calls == 1 && !noidle);
		}
		assert(udc.started && instance.gadget_driver == &driver && instance.is_active && !instance.softconnect);
		assert(instance.state == OTG_STATE_B_IDLE && !instance.lock && controller.refs == hold);
		assert(put_calls == 1 && starts == 1 && modes == 1 && busy == 1 && vbus == (backend == 2));
		unsigned previous_gets = get_calls;
		assert(usb_gadget_udc_start_locked(&udc) == -EBUSY && get_calls == previous_gets);
		/* Invalid speed is rejected before acquiring power or publishing state. */
		udc.started = false; instance = before; driver.max_speed = USB_SPEED_FULL;
		assert(usb_gadget_udc_start_locked(&udc) == -EINVAL && !udc.started && get_calls == previous_gets);
		assert(!memcmp(&instance, &before, sizeof(instance)) && controller.refs == hold);
		scenarios++;
	}
	printf("MUSB UDC startup: %u actual-source scenarios passed\n", scenarios);
	return 0;
}
