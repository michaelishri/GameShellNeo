/* SPDX-License-Identifier: GPL-2.0-only */
/* Optional, read-only AXP223 RSB control provenance diagnostic. */
#ifndef AXP223_CONTROL_DIAG_H
#define AXP223_CONTROL_DIAG_H

#include <linux/debugfs.h>
#include <linux/fs.h>
#include <linux/ktime.h>
#include <linux/mfd/axp20x.h>
#include <linux/mutex.h>
#include <linux/pm.h>
#include <linux/regmap.h>
#include <linux/slab.h>

struct axp223_control_diag {
	struct mutex lock;
	struct regmap *map;
	struct dentry *directory;
	bool enabled, prepared, removing;
};

/* Keep the existing MFD drvdata pointing at axp, including for its children. */
struct axp20x_rsb {
	struct axp20x_dev axp;
	struct axp223_control_diag controls;
};

struct axp223_control_read {
	u64 start_ns, end_ns;
	unsigned int reg, value;
	int error;
	bool bypass;
};

struct axp223_control_snapshot {
	struct axp223_control_read reads[4];
	char text[1024];
	size_t length;
};

static int axp223_control_capture(struct axp223_control_diag *diag,
				 struct axp223_control_snapshot *snapshot)
{
	int i, ret;

	ret = mutex_lock_interruptible(&diag->lock);
	if (ret)
		return ret;
	if (diag->removing)
		ret = -ENODEV;
	else if (!diag->enabled)
		ret = -EOPNOTSUPP;
	else if (diag->prepared)
		ret = -EBUSY;
	if (ret)
		goto out;

	/* Four ordered observations, not an atomic multi-register snapshot. */
	for (i = 0; i < ARRAY_SIZE(snapshot->reads); i++) {
		struct axp223_control_read *read = &snapshot->reads[i];

		read->reg = i < 2 ? AXP20X_CHRG_CTRL1 : AXP20X_CHRG_CTRL2;
		read->bypass = i & 1;
		read->value = 0;
		read->start_ns = ktime_get_ns();
		if (read->bypass)
			read->error = regmap_read_bypassed(diag->map, read->reg, &read->value);
		else
			read->error = regmap_read(diag->map, read->reg, &read->value);
		read->end_ns = ktime_get_ns();
		/* Never expose undefined data or a cached fallback on error. */
		if (read->error)
			read->value = 0;
	}
out:
	mutex_unlock(&diag->lock);
	return ret;
}

static int axp223_control_open(struct inode *inode, struct file *file)
{
	struct axp223_control_snapshot *snapshot;
	int i, ret;
	size_t length;

	if (!(file->f_mode & FMODE_READ) || (file->f_mode & FMODE_WRITE))
		return -EACCES;
	snapshot = kzalloc(sizeof(*snapshot), GFP_KERNEL);
	if (!snapshot)
		return -ENOMEM;
	ret = axp223_control_capture(inode->i_private, snapshot);
	if (ret) {
		kfree(snapshot);
		return ret;
	}
	length = scnprintf(snapshot->text, sizeof(snapshot->text),
		"{\"version\":1,\"variant\":\"AXP223\",\"atomic\":false,\"reads\":[");
	for (i = 0; i < ARRAY_SIZE(snapshot->reads); i++) {
		struct axp223_control_read *read = &snapshot->reads[i];
		char value[16];

		if (read->error)
			strscpy(value, "null");
		else
			scnprintf(value, sizeof(value), "%u", read->value);
		length += scnprintf(snapshot->text + length, sizeof(snapshot->text) - length,
			"%s{\"register\":%u,\"mode\":\"%s\",\"start_ns\":%llu,"
			"\"end_ns\":%llu,\"error\":%d,\"value\":%s}",
			i ? "," : "", read->reg, read->bypass ? "bypass" : "normal",
			read->start_ns, read->end_ns, read->error, value);
	}
	snapshot->length = length + scnprintf(snapshot->text + length,
					     sizeof(snapshot->text) - length, "]}\n");
	file->private_data = snapshot;
	return nonseekable_open(inode, file);
}

static ssize_t axp223_control_read_file(struct file *file, char __user *buffer,
				       size_t count, loff_t *position)
{
	struct axp223_control_snapshot *snapshot = file->private_data;

	return simple_read_from_buffer(buffer, count, position,
				       snapshot->text, snapshot->length);
}

static int axp223_control_release(struct inode *inode, struct file *file)
{
	/* No driver or inode-private access: the device may already be gone. */
	kfree(file->private_data);
	return 0;
}

static const struct file_operations axp223_control_fops = {
	.owner = THIS_MODULE,
	.open = axp223_control_open,
	.read = axp223_control_read_file,
	.release = axp223_control_release,
};

static void axp223_control_remove(struct axp223_control_diag *diag)
{
	mutex_lock(&diag->lock);
	diag->removing = true;
	mutex_unlock(&diag->lock);
	/* Drain protected debugfs operations without holding their mutex. */
	debugfs_remove(diag->directory);
	diag->directory = NULL;
}

static int axp223_control_init(struct axp20x_rsb *chip, bool requested)
{
	struct axp223_control_diag *diag = &chip->controls;
	struct dentry *file;
	char *name;
	int ret;

	mutex_init(&diag->lock);
	if (!requested || chip->axp.variant != AXP223_ID)
		return 0;
	diag->map = chip->axp.regmap;
	name = kasprintf(GFP_KERNEL, "axp223-controls-%s", dev_name(chip->axp.dev));
	if (!name)
		return -ENOMEM;
	diag->directory = debugfs_create_dir(name, NULL);
	kfree(name);
	if (IS_ERR(diag->directory)) {
		ret = PTR_ERR(diag->directory);
		diag->directory = NULL;
		return ret;
	}
	diag->enabled = true;
	file = debugfs_create_file("snapshot", 0400, diag->directory, diag,
				   &axp223_control_fops);
	if (IS_ERR(file)) {
		ret = PTR_ERR(file);
		axp223_control_remove(diag);
		return ret;
	}
	return 0;
}

static struct axp223_control_diag *axp223_controls(struct device *dev)
{
	struct axp20x_dev *axp = dev_get_drvdata(dev);

	return &container_of(axp, struct axp20x_rsb, axp)->controls;
}

static int axp223_control_prepare(struct device *dev)
{
	struct axp223_control_diag *diag = axp223_controls(dev);

	mutex_lock(&diag->lock);
	diag->prepared = true;
	mutex_unlock(&diag->lock);
	return 0; /* Never request direct-complete on the diagnostic's behalf. */
}

static void axp223_control_complete(struct device *dev)
{
	struct axp223_control_diag *diag = axp223_controls(dev);

	mutex_lock(&diag->lock);
	diag->prepared = false;
	mutex_unlock(&diag->lock);
}

static const struct dev_pm_ops axp223_control_pm_ops = {
	.prepare = axp223_control_prepare,
	.complete = axp223_control_complete,
};
#endif
