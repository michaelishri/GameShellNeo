/* SPDX-License-Identifier: GPL-2.0-only */
/* Model the normal debugfs proxy contract, not kernel concurrency. */
#include <sys/types.h>
#include <stdarg.h>
#define __user
#define THIS_MODULE NULL
struct file { void *private_data; };
struct inode { void *i_private; };
struct file_operations {
	void *owner;
	int (*open)(struct inode *, struct file *);
	ssize_t (*read)(struct file *, char *, size_t, loff_t *);
	ssize_t (*write)(struct file *, const char *, size_t, loff_t *);
	loff_t (*llseek)(struct file *, loff_t, int);
};
struct dentry { bool live; void *data; const struct file_operations *fops; };
static struct dentry diag_directory, diag_status, diag_control;
static void (*diag_cleanup)(void *);
static bool copy_fault;

static int simple_open(struct inode *inode, struct file *file)
{
	file->private_data = inode->i_private;
	return 0;
}
static void *kmalloc(size_t size, int flags)
{
	(void)flags; assert(!locks_held); return malloc(size);
}
#define kfree free
static int copy_from_user(void *target, const void *source, size_t size)
{
	assert(!locks_held);
	if (copy_fault) return 1;
	memcpy(target, source, size);
	return 0;
}
static ssize_t simple_read_from_buffer(char *target, size_t size, loff_t *position,
				       const char *buffer, size_t length)
{
	assert(!locks_held);
	if (copy_fault) return -EFAULT;
	if ((size_t)*position >= length) return 0;
	size_t count = length - *position;
	if (count > size) count = size;
	memcpy(target, buffer + *position, count);
	*position += count;
	return count;
}
static int scnprintf(char *buffer, size_t size, const char *format, ...)
{
	assert(!locks_held);
	va_list args;
	va_start(args, format);
	int result = vsnprintf(buffer, size, format, args);
	va_end(args);
	return result < (int)size ? result : (int)size - 1;
}
static u64 ktime_get_ns(void) { return (u64)jiffies * 1000000; }
static struct dentry *debugfs_create_dir(const char *name, struct dentry *parent)
{
	assert(!strcmp(name, "gameshellneo-usb") && !parent);
	assert(irq_count == 2 && !diag_directory.live);
	if (fail_at == DIAG_DIR) return ERR_PTR(-ENOMEM);
	diag_directory.live = true;
	return &diag_directory;
}
static void debugfs_remove_recursive(struct dentry *directory)
{
	assert(directory == &diag_directory && directory->live);
	assert(irq_count == 2); /* The proxy must stop access before IRQ release. */
	directory->live = diag_status.live = diag_control.live = false;
}
static int devm_add_action_or_reset(struct device *dev, void (*action)(void *), void *data)
{
	(void)dev;
	if (fail_at == DIAG_ACTION) { action(data); return -ENOMEM; }
	diag_cleanup = action;
	push(DIAGNOSTICS);
	return 0;
}
static struct dentry *debugfs_create_file(const char *name, unsigned int mode,
	struct dentry *parent, void *data, const struct file_operations *fops)
{
	bool status = !strcmp(name, "status");
	assert(parent == &diag_directory && parent->live);
	assert(mode == (status ? 0400U : 0200U));
	if (fail_at == (status ? DIAG_STATUS : DIAG_CONTROL)) return ERR_PTR(-ENOMEM);
	struct dentry *file = status ? &diag_status : &diag_control;
	*file = (struct dentry){ .live = true, .data = data, .fops = fops };
	return file;
}
static ssize_t proxy_read(struct dentry *entry, struct file *file, char *buffer,
			  size_t size, loff_t *position)
{
	return entry->live ? entry->fops->read(file, buffer, size, position) : -EIO;
}
static ssize_t proxy_write(struct dentry *entry, struct file *file, const char *buffer,
			   size_t size, loff_t *position)
{
	return entry->live ? entry->fops->write(file, buffer, size, position) : -EIO;
}
