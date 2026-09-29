/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Private diagnostic state. All mutable fields except enabled use lock. */
#ifndef AXP20X_USB_DIAG_H
#define AXP20X_USB_DIAG_H

#define NEO_USB_MAX_ERRORS 4
#define NEO_USB_EVENTS 8

struct neo_usb_event {
	int result;
	unsigned int status, retry_ms;
	bool injected;
};

struct neo_usb_counts {
	u64 generation, entries, completed, success, real_errors, injected_errors;
	u64 synthetic_requests;
	unsigned int inflight, budget, status, event_count;
	bool status_valid;
	unsigned long expires;
	struct neo_usb_event events[NEO_USB_EVENTS];
};

struct neo_usb_diag {
	spinlock_t lock;
	struct mutex control_lock;
	struct neo_usb_counts counts;
	bool enabled;
	bool recording;
};

#endif
