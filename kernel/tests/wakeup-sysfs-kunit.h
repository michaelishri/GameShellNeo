/* SPDX-License-Identifier: GPL-2.0 */
/* Isolated test-only call boundaries; normal operations use the actual APIs. */
#ifndef _NEO_WAKEUP_SYSFS_KUNIT_H
#define _NEO_WAKEUP_SYSFS_KUNIT_H

#ifndef CONFIG_NEO_WAKEUP_SYSFS_KUNIT_TEST
#define wakeup_sysfs_object_alloc(name) kzalloc(sizeof(struct wakeup_source), GFP_KERNEL)
#define wakeup_sysfs_name_alloc(name) kstrdup_const(name, GFP_KERNEL)
#define wakeup_sysfs_id_alloc(name) ida_alloc(&wakeup_ida, GFP_KERNEL)
#define wakeup_sysfs_name_free(name) kfree_const(name)
#define wakeup_sysfs_object_free(ws) kfree(ws)
#define wakeup_sysfs_id_free(ws) ida_free(&wakeup_ida, (ws)->id)
#define wakeup_sysfs_source_add(dev, ws) wakeup_source_sysfs_add(dev, ws)
#define wakeup_sysfs_before_attach(dev, ws) do { } while (0)
#define wakeup_sysfs_after_attach(dev, ws, ret) do { } while (0)
#define wakeup_sysfs_srcu_wait(ws) synchronize_srcu(&wakeup_srcu)
#else
#include <kunit/test.h>
#include <linux/completion.h>
#include <linux/file.h>
#include <linux/fs.h>
#include <linux/kthread.h>
#include <linux/mount.h>

#define WAKEUP_SYSFS_SLOTS 8
#define WAKEUP_SYSFS_TIMEOUT (5 * HZ)

enum wakeup_sysfs_fault {
	WAKEUP_SYSFS_NO_FAULT,
	WAKEUP_SYSFS_OBJECT_FAULT,
	WAKEUP_SYSFS_NAME_FAULT,
	WAKEUP_SYSFS_ID_FAULT,
	WAKEUP_SYSFS_REGISTRATION_FAULT,
};

struct wakeup_sysfs_slot {
	struct wakeup_source *ws;
	struct task_struct *creator;
	const char *name;
	int id;
	bool object_live;
	bool name_live;
	bool id_live;
};

struct wakeup_sysfs_fixture {
	struct device dev;
	struct vfsmount *mount;
	struct file_system_type *fs;
	char *name;
	spinlock_t lock;
	struct wakeup_sysfs_slot slots[WAKEUP_SYSFS_SLOTS];
	unsigned int slots_used;
	unsigned int objects_allocated, objects_freed;
	unsigned int names_allocated, names_freed;
	unsigned int ids_allocated, ids_freed;
	unsigned int ownership_errors;
	atomic_t fault;
	atomic_t fault_hits;
	atomic_t attach_entries;
	atomic_t duplicate_attaches;
	atomic_t release_count;
	bool gate_allocation;
	bool gate_attachment;
	bool observe_srcu;
	bool registered;
	bool initialized;
	struct completion gate_entered[2];
	struct completion gate_release;
	struct completion srcu_entered;
};

static struct wakeup_sysfs_fixture *wakeup_sysfs_active;

/* Defined in sysfs.c solely for the incapable-device frontend subvariant. */
ssize_t wakeup_sysfs_kunit_store(struct device *dev, const char *buf, size_t n);

static bool wakeup_sysfs_target(struct wakeup_sysfs_fixture *f, const char *name)
{
	return f && name && !strcmp(f->name, name);
}

static bool wakeup_sysfs_fault_hit(struct wakeup_sysfs_fixture *f, int fault)
{
	if (atomic_cmpxchg(&f->fault, fault, WAKEUP_SYSFS_NO_FAULT) != fault)
		return false;
	atomic_inc(&f->fault_hits);
	return true;
}

/* Caller owns the fixture lock; slots remain as an audit after actual frees. */
static struct wakeup_sysfs_slot *wakeup_sysfs_creator_slot(struct wakeup_sysfs_fixture *f)
{
	unsigned int i;

	for (i = 0; i < f->slots_used; i++)
		if (f->slots[i].object_live && f->slots[i].creator == current &&
		    !f->slots[i].id_live)
			return &f->slots[i];
	f->ownership_errors++;
	return NULL;
}

static struct wakeup_sysfs_slot *wakeup_sysfs_object_slot(struct wakeup_sysfs_fixture *f,
						       struct wakeup_source *ws)
{
	unsigned int i;

	if (f)
		for (i = 0; i < f->slots_used; i++)
			if (f->slots[i].object_live && f->slots[i].ws == ws)
				return &f->slots[i];
	return NULL;
}

static struct wakeup_source *wakeup_sysfs_object_alloc(const char *name)
{
	struct wakeup_sysfs_fixture *f = READ_ONCE(wakeup_sysfs_active);
	struct wakeup_sysfs_slot *slot;
	struct wakeup_source *ws;
	unsigned long flags;

	if (!wakeup_sysfs_target(f, name))
		return kzalloc(sizeof(*ws), GFP_KERNEL);
	if (READ_ONCE(f->gate_allocation)) {
		complete(&f->gate_entered[0]);
		wait_for_completion(&f->gate_release);
	}
	if (wakeup_sysfs_fault_hit(f, WAKEUP_SYSFS_OBJECT_FAULT))
		return NULL;
	ws = kzalloc(sizeof(*ws), GFP_KERNEL);
	if (!ws)
		return NULL;
	spin_lock_irqsave(&f->lock, flags);
	if (f->slots_used == WAKEUP_SYSFS_SLOTS) {
		f->ownership_errors++;
	} else {
		slot = &f->slots[f->slots_used++];
		slot->ws = ws;
		slot->creator = current;
		slot->object_live = true;
		slot->id = -1;
		f->objects_allocated++;
	}
	spin_unlock_irqrestore(&f->lock, flags);
	return ws;
}

static const char *wakeup_sysfs_name_alloc(const char *name)
{
	struct wakeup_sysfs_fixture *f = READ_ONCE(wakeup_sysfs_active);
	struct wakeup_sysfs_slot *slot;
	const char *copy;
	unsigned long flags;

	if (!wakeup_sysfs_target(f, name))
		return kstrdup_const(name, GFP_KERNEL);
	if (wakeup_sysfs_fault_hit(f, WAKEUP_SYSFS_NAME_FAULT))
		return NULL;
	copy = kstrdup_const(name, GFP_KERNEL);
	if (!copy)
		return NULL;
	spin_lock_irqsave(&f->lock, flags);
	slot = wakeup_sysfs_creator_slot(f);
	if (slot) {
		slot->name = copy;
		slot->name_live = true;
		f->names_allocated++;
		if (copy == name)
			f->ownership_errors++;
	}
	spin_unlock_irqrestore(&f->lock, flags);
	return copy;
}

static int wakeup_sysfs_id_alloc(const char *name)
{
	struct wakeup_sysfs_fixture *f = READ_ONCE(wakeup_sysfs_active);
	struct wakeup_sysfs_slot *slot;
	unsigned long flags;
	int id;

	if (!wakeup_sysfs_target(f, name))
		return ida_alloc(&wakeup_ida, GFP_KERNEL);
	if (wakeup_sysfs_fault_hit(f, WAKEUP_SYSFS_ID_FAULT))
		return -ENOSPC;
	id = ida_alloc(&wakeup_ida, GFP_KERNEL);
	if (id < 0)
		return id;
	spin_lock_irqsave(&f->lock, flags);
	slot = wakeup_sysfs_creator_slot(f);
	if (slot) {
		slot->id = id;
		slot->id_live = true;
		f->ids_allocated++;
	}
	spin_unlock_irqrestore(&f->lock, flags);
	return id;
}

static void wakeup_sysfs_name_free(const char *name)
{
	struct wakeup_sysfs_fixture *f = READ_ONCE(wakeup_sysfs_active);
	unsigned long flags;
	unsigned int i;

	if (f) {
		spin_lock_irqsave(&f->lock, flags);
		for (i = 0; i < f->slots_used; i++)
			if (f->slots[i].name_live && f->slots[i].name == name) {
				f->slots[i].name_live = false;
				f->names_freed++;
				break;
			}
		spin_unlock_irqrestore(&f->lock, flags);
	}
	kfree_const(name);
}

static void wakeup_sysfs_id_free(struct wakeup_source *ws)
{
	struct wakeup_sysfs_fixture *f = READ_ONCE(wakeup_sysfs_active);
	struct wakeup_sysfs_slot *slot;
	unsigned long flags;
	bool owned = false;

	if (f) {
		spin_lock_irqsave(&f->lock, flags);
		slot = wakeup_sysfs_object_slot(f, ws);
		if (slot) {
			if (!slot->id_live || slot->id != ws->id)
				f->ownership_errors++;
			slot->id_live = false;
			f->ids_freed++;
			owned = true;
		}
		spin_unlock_irqrestore(&f->lock, flags);
	}
	ida_free(&wakeup_ida, ws->id);
	if (owned && ida_exists(&wakeup_ida, ws->id)) {
		spin_lock_irqsave(&f->lock, flags);
		f->ownership_errors++;
		spin_unlock_irqrestore(&f->lock, flags);
	}
}

static void wakeup_sysfs_object_free(struct wakeup_source *ws)
{
	struct wakeup_sysfs_fixture *f = READ_ONCE(wakeup_sysfs_active);
	struct wakeup_sysfs_slot *slot;
	unsigned long flags;

	if (f) {
		spin_lock_irqsave(&f->lock, flags);
		slot = wakeup_sysfs_object_slot(f, ws);
		if (slot) {
			if (slot->name_live || slot->id_live)
				f->ownership_errors++;
			slot->object_live = false;
			f->objects_freed++;
		}
		spin_unlock_irqrestore(&f->lock, flags);
	}
	kfree(ws);
}

static int wakeup_sysfs_source_add(struct device *dev, struct wakeup_source *ws)
{
	struct wakeup_sysfs_fixture *f = READ_ONCE(wakeup_sysfs_active);

	if (wakeup_sysfs_target(f, ws->name) &&
	    wakeup_sysfs_fault_hit(f, WAKEUP_SYSFS_REGISTRATION_FAULT))
		return -EIO;
	return wakeup_source_sysfs_add(dev, ws);
}

static void wakeup_sysfs_before_attach(struct device *dev, struct wakeup_source *ws)
{
	struct wakeup_sysfs_fixture *f = READ_ONCE(wakeup_sysfs_active);
	int index;

	if (!wakeup_sysfs_target(f, ws->name))
		return;
	index = atomic_inc_return(&f->attach_entries) - 1;
	if (READ_ONCE(f->gate_attachment) && index < 2) {
		complete(&f->gate_entered[index]);
		wait_for_completion(&f->gate_release);
	}
}

static void wakeup_sysfs_after_attach(struct device *dev, struct wakeup_source *ws, int ret)
{
	struct wakeup_sysfs_fixture *f = READ_ONCE(wakeup_sysfs_active);

	if (wakeup_sysfs_target(f, ws->name) && ret == -EEXIST)
		atomic_inc(&f->duplicate_attaches);
}

static void wakeup_sysfs_srcu_wait(struct wakeup_source *ws)
{
	struct wakeup_sysfs_fixture *f = READ_ONCE(wakeup_sysfs_active);

	if (wakeup_sysfs_target(f, ws->name) && READ_ONCE(f->observe_srcu))
		complete(&f->srcu_entered);
	synchronize_srcu(&wakeup_srcu);
}
#endif
#endif
