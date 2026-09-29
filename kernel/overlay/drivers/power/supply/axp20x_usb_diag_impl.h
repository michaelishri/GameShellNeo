/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Included after the driver structure and the complete board/topology gate. */
#ifndef AXP20X_USB_DIAG_IMPL_H
#define AXP20X_USB_DIAG_IMPL_H

static bool gameshellneo_diagnostics;
module_param(gameshellneo_diagnostics, bool, 0444);
MODULE_PARM_DESC(gameshellneo_diagnostics,
	"Expose bounded root-only CPI v3.1 USB polling diagnostics (counting initially off)");

static void neo_usb_expire(struct neo_usb_diag *diag)
{
	if (time_after_eq(jiffies, diag->counts.expires))
		diag->counts.budget = 0;
}

/* An entry belongs to the generation enabled at entry, even if disabled before
 * completion. A new generation cannot start while such an entry is in flight.
 * No register access, allocation or logging takes place with this lock held.
 */
static int neo_usb_read(struct axp20x_usb_power *power, unsigned int *value,
			bool *counted, bool *injected)
{
	struct neo_usb_diag *diag = &power->diag;
	unsigned long flags;

	*counted = false;
	*injected = false;
	if (READ_ONCE(diag->enabled)) {
		spin_lock_irqsave(&diag->lock, flags);
		if (diag->enabled) {
			*counted = true;
			diag->counts.entries++;
			diag->counts.inflight++;
			neo_usb_expire(diag);
			if (diag->counts.budget) {
				diag->counts.budget--;
				*injected = true;
			}
		}
		spin_unlock_irqrestore(&diag->lock, flags);
	}
	if (*injected)
		return -EIO;
	return regmap_read(power->regmap, AXP20X_PWR_INPUT_STATUS, value);
}

static void neo_usb_complete(struct axp20x_usb_power *power, bool counted,
			     bool injected, int result, unsigned int retry_ms)
{
	struct neo_usb_diag *diag = &power->diag;
	struct neo_usb_counts *counts = &diag->counts;
	unsigned long flags;

	if (!counted)
		return;
	spin_lock_irqsave(&diag->lock, flags);
	counts->completed++;
	counts->inflight--;
	if (injected)
		counts->injected_errors++;
	else if (result)
		counts->real_errors++;
	else
		counts->success++;
	counts->status = power->old_status;
	counts->status_valid = true;
	if (diag->recording && counts->event_count < NEO_USB_EVENTS) {
		counts->events[counts->event_count++] = (struct neo_usb_event) {
			.result = result, .status = power->old_status,
			.retry_ms = retry_ms, .injected = injected,
		};
		if (!result || counts->event_count == NEO_USB_EVENTS)
			diag->recording = false;
	}
	spin_unlock_irqrestore(&diag->lock, flags);
}

/* Exact grammar; a single trailing newline is accepted by the write wrapper. */
static int neo_usb_command(struct axp20x_usb_power *power, const char *command)
{
	struct neo_usb_diag *diag = &power->diag;
	struct neo_usb_counts *counts = &diag->counts;
	unsigned long flags;
	u64 generation;
	bool kick = false;
	int result = 0;

	mutex_lock(&diag->control_lock);
	spin_lock_irqsave(&diag->lock, flags);
	neo_usb_expire(diag);
	if (!strcmp(command, "enable")) {
		if (diag->enabled || counts->inflight) {
			result = -EBUSY;
		} else {
			generation = counts->generation + 1;
			memset(counts, 0, sizeof(*counts));
			counts->generation = generation;
			diag->recording = false;
			WRITE_ONCE(diag->enabled, true);
		}
	} else if (!strcmp(command, "disable") || !strcmp(command, "disarm")) {
		counts->budget = 0;
		diag->recording = false;
		if (!strcmp(command, "disable"))
			WRITE_ONCE(diag->enabled, false);
	} else if (strlen(command) == 8 && !memcmp(command, "inject ", 7) &&
		   command[7] >= '1' && command[7] <= '0' + NEO_USB_MAX_ERRORS) {
		if (!diag->enabled) {
			result = -EINVAL;
		} else if (counts->inflight || counts->budget ||
			   (counts->synthetic_requests && time_before(jiffies, counts->expires))) {
			result = -EBUSY;
		} else {
			counts->budget = command[7] - '0';
			counts->expires = jiffies + msecs_to_jiffies(1000);
			counts->synthetic_requests++;
			counts->event_count = 0;
			diag->recording = true;
			kick = true;
		}
	} else {
		result = -EINVAL;
	}
	spin_unlock_irqrestore(&diag->lock, flags);
	/* Explicit synthetic request; queue preserves any existing IRQ deadline. */
	if (kick)
		queue_delayed_work(system_power_efficient_wq, &power->vbus_detect, 0);
	mutex_unlock(&diag->control_lock);
	return result;
}

static ssize_t neo_usb_write(struct file *file, const char __user *user,
			    size_t length, loff_t *position)
{
	char command[16];
	int result;
	size_t size = length;

	if (!size || size >= sizeof(command))
		return -EINVAL;
	if (copy_from_user(command, user, size))
		return -EFAULT;
	if (memchr(command, '\0', size))
		return -EINVAL;
	if (command[size - 1] == '\n')
		size--;
	command[size] = '\0';
	result = neo_usb_command(file->private_data, command);
	return result ? result : length;
}

static ssize_t neo_usb_read_snapshot(struct file *file, char __user *user,
				     size_t length, loff_t *position)
{
	struct axp20x_usb_power *power = file->private_data;
	struct neo_usb_diag *diag = &power->diag;
	struct neo_usb_counts snapshot;
	unsigned long flags;
	bool enabled;
	char *buffer;
	int size, i;
	ssize_t result;

	/* One whole snapshot per open/read sequence; never splice generations when
	 * a reader asks for small chunks. Reopen to obtain the next snapshot.
	 */
	if (*position)
		return 0;
	buffer = kmalloc(4096, GFP_KERNEL);
	if (!buffer)
		return -ENOMEM;
	spin_lock_irqsave(&diag->lock, flags);
	neo_usb_expire(diag);
	snapshot = diag->counts;
	enabled = diag->enabled;
	spin_unlock_irqrestore(&diag->lock, flags);
	size = scnprintf(buffer, 4096,
		"{\"version\":1,\"monotonic_ns\":%llu,\"enabled\":%u,"
		"\"experimental\":%u,\"generation\":%llu,\"entries\":%llu,"
		"\"completed\":%llu,\"success\":%llu,\"real_errors\":%llu,"
		"\"injected_errors\":%llu,\"inflight\":%u,\"budget\":%u,"
		"\"status\":%u,\"status_valid\":%u,\"synthetic_requests\":%llu,\"events\":[",
		(unsigned long long)ktime_get_ns(), enabled,
		READ_ONCE(power->gameshellneo_slow_poll),
		(unsigned long long)snapshot.generation,
		(unsigned long long)snapshot.entries, (unsigned long long)snapshot.completed,
		(unsigned long long)snapshot.success, (unsigned long long)snapshot.real_errors,
		(unsigned long long)snapshot.injected_errors, snapshot.inflight, snapshot.budget,
		snapshot.status, snapshot.status_valid, (unsigned long long)snapshot.synthetic_requests);
	for (i = 0; i < snapshot.event_count; i++) {
		struct neo_usb_event *event = &snapshot.events[i];

		size += scnprintf(buffer + size, 4096 - size,
			"%s{\"result\":%d,\"status\":%u,\"retry_ms\":%u,\"injected\":%u}",
			i ? "," : "", event->result, event->status, event->retry_ms, event->injected);
	}
	size += scnprintf(buffer + size, 4096 - size, "]}\n");
	result = length < size ? -EINVAL :
		simple_read_from_buffer(user, length, position, buffer, size);
	kfree(buffer);
	return result;
}

/* Normal debugfs proxies pin active read/write operations during removal.
 * An open descriptor alone does not pin devm memory: never dereference it from
 * release, and never use debugfs_create_file_unsafe for these operations.
 */
static const struct file_operations neo_usb_status_fops = {
	.owner = THIS_MODULE, .open = simple_open, .read = neo_usb_read_snapshot,
};
static const struct file_operations neo_usb_control_fops = {
	.owner = THIS_MODULE, .open = simple_open, .write = neo_usb_write,
};

static void neo_usb_remove(void *directory)
{
	debugfs_remove_recursive(directory);
}

static int neo_usb_register(struct axp20x_usb_power *power, struct axp20x_dev *pmic)
{
	struct dentry *directory, *file;
	const char *refusal;
	int result;

	if (!gameshellneo_diagnostics)
		return 0;
	refusal = gameshellneo_hardware_refusal(power, pmic);
	if (refusal) {
		dev_info(power->dev, "GameShellNeo USB diagnostics refused: %s\n", refusal);
		return 0;
	}
	directory = debugfs_create_dir("gameshellneo-usb", NULL);
	if (IS_ERR(directory))
		return PTR_ERR(directory);
	/* Added after IRQ resources: files disappear before IRQ/work/supply unwind. */
	result = devm_add_action_or_reset(power->dev, neo_usb_remove, directory);
	if (result)
		return result;
	file = debugfs_create_file("status", 0400, directory, power, &neo_usb_status_fops);
	if (IS_ERR(file))
		return PTR_ERR(file);
	file = debugfs_create_file("control", 0200, directory, power, &neo_usb_control_fops);
	if (IS_ERR(file))
		return PTR_ERR(file);
	return 0;
}

#endif
