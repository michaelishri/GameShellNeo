/* SPDX-License-Identifier: GPL-2.0-only */
static unsigned int diagnostic_cases;

static void diag_invariants(struct neo_usb_diag *diag)
{
	struct neo_usb_counts *c = &diag->counts;
	assert(c->entries == c->completed + c->inflight);
	assert(c->completed == c->success + c->real_errors + c->injected_errors);
	assert(c->budget <= 4 && c->event_count <= NEO_USB_EVENTS);
	assert(!locks_held);
}

static void diag_poll(struct axp20x_usb_power *power)
{
	power->vbus_detect.pending = false;
	axp20x_usb_power_poll_vbus(&power->vbus_detect.work);
	diag_invariants(&power->diag);
	jiffies += 50;
}

static void diagnostic_state_tests(void)
{
	reset_graph();
	supply.live = true;
	for (unsigned int policy = 0; policy < 2; policy++)
	for (unsigned int status = 0; status <= 48; status += 16)
	for (unsigned int budget = 1; budget <= 4; budget++) {
		struct axp20x_usb_power power = {
			.supply = &supply, .axp_data = &test_data, .old_status = status,
			.online = status & 16, .gameshellneo_slow_poll = policy,
			.vbus_detect = { .initialized = true },
		};
		struct neo_usb_diag *diag = &power.diag;
		char command[] = "inject 1";
		command[7] += budget - 1;
		input_status = status;
		error_register = -1;
		jiffies = 10000;
		assert(neo_usb_command(&power, command) == -EINVAL);
		assert(!neo_usb_command(&power, "enable"));
		assert(neo_usb_command(&power, "enable") == -EBUSY);
		assert(!power.vbus_detect.pending); /* Enable never requests work. */
		assert(!neo_usb_command(&power, command));
		assert(neo_usb_command(&power, command) == -EBUSY);
		unsigned int other_reader;
		assert(!regmap_read(power.regmap, AXP20X_PWR_INPUT_STATUS, &other_reader));
		assert(other_reader == status && diag->counts.budget == budget);
		unsigned int reads = read_count;
		for (unsigned int i = 0; i < budget; i++) {
			/* For stock-online, additional callbacks simulate later IRQ work;
			 * they must not be mistaken for an automatic error retry.
			 */
			diag_poll(&power);
			assert(power.old_status == status && power.online == (status & 16));
			assert(read_count == reads);
			assert(diag->counts.injected_errors == i + 1);
			bool retries = policy || !(status & 16);
			assert(power.vbus_detect.pending == retries);
			assert(diag->counts.events[i].retry_ms == (retries ? 50U : 0U));
		}
		assert(neo_usb_command(&power, command) == -EBUSY); /* No extension. */
		diag_poll(&power);
		assert(read_count == reads + 1 && diag->counts.success == 1);
		assert(diag->counts.event_count == budget + 1 && !diag->recording);
		assert(!diag->counts.events[budget].injected);
		assert(!neo_usb_command(&power, "disable"));
		assert(!diag->enabled && !diag->counts.budget);
		diag_poll(&power);
		assert(diag->counts.completed == budget + 1);
		diagnostic_cases++;
	}
	struct axp20x_usb_power power = {
		.supply = &supply, .axp_data = &test_data, .gameshellneo_slow_poll = true,
		.vbus_detect = { .initialized = true },
	};
	struct neo_usb_diag *diag = &power.diag;
	assert(!neo_usb_command(&power, "enable"));
	const char *bad[] = {"", "enable ", " enable", "inject 0", "inject 5", "inject 9",
		"inject 01", "inject -1", "inject 1 extra", "reset", "inject 1\n\n"};
	for (unsigned int i = 0; i < sizeof(bad) / sizeof(bad[0]); i++)
		assert(neo_usb_command(&power, bad[i]) == -EINVAL);
	assert(!neo_usb_command(&power, "inject 4"));
	jiffies += 1000;
	input_status = 0;
	diag_poll(&power);
	assert(diag->counts.injected_errors == 0 && diag->counts.success == 1);
	assert(!diag->counts.budget); /* Expiration precedes the real read. */
	assert(!neo_usb_command(&power, "inject 4"));
	assert(!neo_usb_command(&power, "disarm"));
	diag_poll(&power);
	assert(diag->counts.injected_errors == 0 && diag->counts.success == 2);
	error_register = AXP20X_PWR_INPUT_STATUS;
	diag_poll(&power);
	assert(diag->counts.real_errors == 1);
	error_register = -1;
	bool counted, injected;
	unsigned int value;
	assert(!neo_usb_read(&power, &value, &counted, &injected) && counted && !injected);
	assert(!neo_usb_command(&power, "disable"));
	assert(neo_usb_command(&power, "enable") == -EBUSY);
	neo_usb_complete(&power, counted, injected, 0, 250);
	diag_invariants(diag);
	assert(diag->counts.completed == 4);
	assert(!neo_usb_command(&power, "enable"));
	assert(diag->counts.generation == 2 && diag->counts.entries == 0);
	/* Count boundaries around an unobserved callback do not invent an entry. */
	assert(!neo_usb_command(&power, "disable"));
	assert(!neo_usb_read(&power, &value, &counted, &injected) && !counted);
	assert(!neo_usb_command(&power, "enable"));
	neo_usb_complete(&power, counted, injected, 0, 250);
	assert(diag->counts.entries == 0 && diag->counts.completed == 0);
	/* An injected error still preserves a fast IRQ deadline. */
	jiffies += 2000;
	assert(!neo_usb_command(&power, "inject 1"));
	race_position = 1;
	diag_poll(&power);
	assert(!race_position && power.vbus_detect.delay == 50);
	assert(diag->counts.injected_errors == 1);
	diag_invariants(diag);
	diagnostic_cases++;
	/* Expiration remains bounded across unsigned jiffies wrap on ARM32. */
	assert(!neo_usb_command(&power, "disable"));
	assert(!neo_usb_command(&power, "enable"));
	jiffies = (unsigned long)-500;
	assert(!neo_usb_command(&power, "inject 4"));
	jiffies = 450;
	diag_poll(&power);
	assert(diag->counts.injected_errors == 1);
	assert(jiffies == 500);
	diag_poll(&power);
	assert(diag->counts.injected_errors == 1 && diag->counts.success == 1 && !diag->counts.budget);
	diagnostic_cases++;
	supply.live = false;
}

static void diagnostic_lifetime_tests(void)
{
	struct regmap regmap = {0};
	struct axp20x_dev pmic = {.regmap = &regmap, .variant = AXP223_ID};
	struct device parent = {.drvdata = &pmic, .of_node = &nodes[1]};
	struct platform_device pdev = {.dev = {.parent = &parent, .of_node = &nodes[2]}};
	for (unsigned int policy = 0; policy < 2; policy++)
	for (unsigned int diagnostics = 0; diagnostics < 2; diagnostics++) {
		reset_graph();
		gameshellneo_slow_poll = policy;
		gameshellneo_diagnostics = diagnostics;
		fail_at = NONE; run_early_work = false; immediate_mask = 0;
		assert(!axp20x_usb_power_probe(&pdev));
		assert(read_count == 2 * (policy + diagnostics));
		assert(diag_directory.live == (bool)diagnostics && !allocated->diag.enabled);
		unwind();
		diagnostic_cases++;
	}
	gameshellneo_diagnostics = true;
	for (unsigned int policy = 0; policy < 2; policy++)
	for (unsigned int failure = NONE; failure <= DIAG_CONTROL; failure++)
	for (unsigned int early = 0; early < 2; early++) {
		reset_graph();
		gameshellneo_slow_poll = policy;
		run_early_work = early;
		input_status = 0;
		fail_at = failure;
		immediate_mask = 3;
		faults = 0;
		struct file status_file = {0}, control_file = {0};
		loff_t position = 0;
		char buffer[4096];
		int result = axp20x_usb_power_probe(&pdev);
		assert((result == 0) == (failure == NONE));
		if (!result) {
			assert(diag_directory.live && !allocated->diag.enabled);
			struct inode inode = {.i_private = allocated};
			assert(!diag_status.fops->open(&inode, &status_file));
			assert(!diag_control.fops->open(&inode, &control_file));
			assert(proxy_write(&diag_control, &control_file, "enable\n", 7, &position) == 7);
			assert(proxy_write(&diag_control, &control_file, "enable\0garbage", 14, &position) == -EINVAL);
			assert(proxy_write(&diag_control, &control_file, "", 0, &position) == -EINVAL);
			assert(proxy_read(&diag_status, &status_file, buffer, 1, &position) == -EINVAL);
			assert(!position);
			ssize_t size = proxy_read(&diag_status, &status_file, buffer, sizeof(buffer), &position);
			assert(size > 0 && buffer[size - 1] == '\n');
			assert(proxy_read(&diag_status, &status_file, buffer, sizeof(buffer), &position) == 0);
			copy_fault = true; position = 0;
			assert(proxy_read(&diag_status, &status_file, buffer, sizeof(buffer), &position) == -EFAULT);
			assert(proxy_write(&diag_control, &control_file, "disable", 7, &position) == -EFAULT);
			copy_fault = false;
		}
		unwind();
		assert(!faults && !irq_count && !allocated && !supply.live && !diag_directory.live);
		if (!result) {
			/* Open descriptors persist, but proxy rejects access to freed data. */
			assert(proxy_read(&diag_status, &status_file, buffer, sizeof(buffer), &position) == -EIO);
			assert(proxy_write(&diag_control, &control_file, "enable", 6, &position) == -EIO);
		}
		diagnostic_cases++;
	}
	/* Diagnostics use the complete gate even in stock mode. */
	for (unsigned int policy = 0; policy < 2; policy++) {
		reset_graph();
		board_match = false;
		gameshellneo_slow_poll = policy;
		fail_at = NONE; run_early_work = false; immediate_mask = 0;
		assert(!axp20x_usb_power_probe(&pdev));
		assert(!diag_directory.live && !allocated->diag.enabled);
		unwind();
		diagnostic_cases++;
	}
	gameshellneo_diagnostics = false;
	printf("USB diagnostics: %u bounded-error/count/lifetime scenarios passed\n", diagnostic_cases);
}
