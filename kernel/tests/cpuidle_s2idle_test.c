// SPDX-License-Identifier: GPL-2.0-only
/* Actual source functions; modeled IRQ, CPU, RCU and hardware boundaries. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef uint64_t u64;
typedef int64_t s64;
typedef int64_t ktime_t;
#define U64_MAX UINT64_MAX
#define BIT(n) (1U << (n))
#define CONFIG_SUSPEND 1
#define noinstr
#define __cpuidle
#define __init
#define THIS_MODULE NULL
#define device_initcall(fn)
#define pr_err(...) ((void)0)
#define TPS(text) text
#define SYSTEM_RUNNING 0
#define SYSTEM_SUSPEND 1
struct cpuidle_device;
struct cpuidle_driver;
#include "cpuidle_defs.h"

struct cpumask { unsigned bits; };
struct cpuidle_device {
	unsigned enabled, registered, cpu;
	u64 last_residency_ns, forced_idle_latency_limit_ns;
	struct cpuidle_state_usage states_usage[4];
};
struct cpuidle_driver {
	const char *name;
	void *owner;
	struct cpuidle_state states[4];
	int safe_state_index, state_count;
	struct cpumask *cpumask;
};

static struct cpuidle_device cpuidle_dev[4], dev;
static struct cpuidle_driver drv, *active_driver;
static struct cpumask possible = { .bits = 15 };
#define per_cpu(var, cpu) ((var)[cpu])
#define for_each_cpu(cpu, mask) for ((cpu) = 0; (cpu) < 4; (cpu)++) if ((mask)->bits & BIT(cpu))
static int off, initialized, online, current_cpu, system_state;
static int irq_disabled, polling, resched, race_resched, s2idle;
static int tick_freeze_lock, tick_freeze_map, lock_held, map_held;
static unsigned tick_freeze_depth;
static int local_suspended[4], time_suspended, sched_suspended;
static int time_freezes, time_resumes, trace_depth, warnings, raw_disables;
static int rcu_idle, instrumentation, critical_stopped, clock_reads;
static int callbacks, ordinary_calls, default_calls, selected, reflected;
static int tick_stops, tick_retains, tick_stopped, callback_irq_leak, callback_error;
static int board_match, register_error, fail_cpu, driver_registers, driver_removes;
static int device_registers, device_removes, wfi_calls, cases;

static void raw_spin_lock(int *lock)
{
	assert(lock == &tick_freeze_lock && irq_disabled && !lock_held);
	lock_held = 1;
}
static void raw_spin_unlock(int *lock)
{
	assert(lock == &tick_freeze_lock && lock_held);
	lock_held = 0;
}
static void lock_map_acquire_try(int *map)
{
	assert(map == &tick_freeze_map && lock_held && !map_held);
	map_held = 1;
}
static void lock_map_release(int *map)
{
	assert(map == &tick_freeze_map && map_held);
	map_held = 0;
}
static unsigned num_online_cpus(void) { return online; }
static int smp_processor_id(void) { return current_cpu; }
static void trace_suspend_resume(const char *name, int cpu, bool start)
{
	assert(!strcmp(name, "timekeeping_freeze") && cpu == current_cpu);
	assert(trace_depth == !start);
	trace_depth = start;
}
static void tick_suspend_local(void)
{
	assert(irq_disabled && !local_suspended[current_cpu]);
	local_suspended[current_cpu] = 1;
}
static void tick_resume_local(void)
{
	assert(irq_disabled && local_suspended[current_cpu]);
	local_suspended[current_cpu] = 0;
}
static void sched_clock_suspend(void)
{
	assert(!sched_suspended && !time_suspended && system_state == SYSTEM_SUSPEND);
	sched_suspended = 1;
}
static void timekeeping_suspend(void)
{
	assert(sched_suspended && !time_suspended && tick_freeze_depth == (unsigned)online);
	assert(map_held);
	tick_suspend_local();
	time_suspended = 1;
	time_freezes++;
}
static void timekeeping_resume(void)
{
	assert(sched_suspended && time_suspended && map_held);
	time_suspended = 0;
	time_resumes++;
	tick_resume_local();
}
static void sched_clock_resume(void)
{
	assert(sched_suspended && !time_suspended);
	sched_suspended = 0;
}
static void touch_softlockup_watchdog(void) { assert(irq_disabled); }
static bool irqs_disabled(void) { return irq_disabled; }
static void local_irq_enable(void)
{
	assert(!local_suspended[current_cpu] && !time_suspended && !lock_held);
	irq_disabled = 0;
}
static void raw_local_irq_disable(void) { irq_disabled = 1; raw_disables++; }
static bool warn(bool condition) { warnings += condition; return condition; }
#define WARN_ON_ONCE(value) warn(value)
static void instrumentation_begin(void) { instrumentation++; }
static void instrumentation_end(void) { assert(instrumentation > 0); instrumentation--; }
static void ct_cpuidle_enter(void)
{
	assert(irq_disabled && !rcu_idle && critical_stopped);
	rcu_idle = 1;
	instrumentation_end();
}
static void ct_cpuidle_exit(void)
{
	assert(irq_disabled && rcu_idle);
	rcu_idle = 0;
	instrumentation_begin();
}
static void stop_critical_timings(void) { assert(!critical_stopped); critical_stopped = 1; }
static void start_critical_timings(void) { assert(critical_stopped); critical_stopped = 0; }
static ktime_t ns_to_ktime(u64 value) { return value; }
static u64 local_clock_noinstr(void) { return (u64)clock_reads++ * 1000; }
static s64 ktime_us_delta(ktime_t end, ktime_t start) { return (end - start) / 1000; }
static int callback(struct cpuidle_device *device, struct cpuidle_driver *driver, int index)
{
	assert(device == &dev && driver == &drv && index >= 0 && index < drv.state_count);
	assert(irq_disabled && local_suspended[current_cpu] && critical_stopped);
	assert(rcu_idle == !(drv.states[index].flags & CPUIDLE_FLAG_RCU_IDLE));
	callbacks++;
	if (callback_irq_leak)
		irq_disabled = 0; /* Deliberately broken callback for the kernel's WARN recovery. */
	return callback_error ? -EIO : index;
}
static void cpu_do_idle(void) { assert(irq_disabled); wfi_calls++; }
static struct cpuidle_device *cpuidle_get_device(void) { return &dev; }
static struct cpuidle_driver *cpuidle_get_cpu_driver(struct cpuidle_device *device)
{
	assert(device == &dev);
	return active_driver;
}
static bool need_resched(void) { return resched; }
static bool current_clr_polling_and_test(void) { polling = 0; return race_resched; }
static void __current_set_polling(void) { polling = 1; }
static bool idle_should_enter_s2idle(void) { return s2idle; }
static bool tick_nohz_tick_stopped(void) { return tick_stopped; }
static void tick_nohz_idle_stop_tick(void) { tick_stops++; }
static void tick_nohz_idle_retain_tick(void) { tick_retains++; }
static void default_idle_call(void) { default_calls++; local_irq_enable(); }
static int cpuidle_enter(struct cpuidle_driver *driver, struct cpuidle_device *device, int state)
{
	assert(driver == &drv && device == &dev && state >= 0 && state < drv.state_count);
	ordinary_calls++;
	local_irq_enable();
	return state;
}
static int cpuidle_select(struct cpuidle_driver *driver, struct cpuidle_device *device, bool *stop)
{
	assert(driver == &drv && device == &dev && *stop);
	selected++;
	return 1;
}
static void cpuidle_reflect(struct cpuidle_device *device, int state)
{
	assert(device == &dev && state == 1);
	reflected++;
}
static bool of_machine_is_compatible(const char *name)
{
	assert(!strcmp(name, "clockwork,clockworkpi-cpi3"));
	return board_match;
}
static int cpuidle_register_driver(struct cpuidle_driver *driver)
{
	driver_registers++;
	if (register_error)
		return register_error;
	driver->cpumask = &possible;
	return 0;
}
static void cpuidle_unregister_driver(struct cpuidle_driver *driver)
{
	assert(driver->cpumask == &possible);
	driver_removes++;
}
static int cpuidle_register_device(struct cpuidle_device *device)
{
	device_registers++;
	if ((int)device->cpu == fail_cpu)
		return -ENOMEM;
	assert(!device->registered);
	device->registered = 1;
	return 0;
}
static void cpuidle_unregister_device(struct cpuidle_device *device)
{
	if (device->registered) {
		device->registered = 0;
		device_removes++;
	}
}

#include "cpuidle_functions.h"

static void reset(void)
{
	memset(&dev, 0, sizeof(dev));
	memset(&drv, 0, sizeof(drv));
	memset(cpuidle_dev, 0, sizeof(cpuidle_dev));
	memset(local_suspended, 0, sizeof(local_suspended));
	active_driver = &drv;
	drv.state_count = 1;
	drv.states[0].enter_s2idle = callback;
	dev.enabled = 1;
	off = 0; initialized = 1; online = 1; current_cpu = 0;
	system_state = SYSTEM_RUNNING;
	irq_disabled = polling = 1;
	resched = race_resched = 0; s2idle = 1;
	lock_held = map_held = tick_freeze_depth = 0;
	time_suspended = sched_suspended = time_freezes = time_resumes = trace_depth = 0;
	warnings = raw_disables = rcu_idle = instrumentation = critical_stopped = clock_reads = 0;
	callbacks = ordinary_calls = default_calls = selected = reflected = 0;
	tick_stops = tick_retains = tick_stopped = callback_irq_leak = callback_error = 0;
	board_match = 1; register_error = 0; fail_cpu = -1;
	driver_registers = driver_removes = device_registers = device_removes = wfi_calls = 0;
}
static void balanced(void)
{
	assert(!lock_held && !map_held && !tick_freeze_depth);
	assert(!time_suspended && !sched_suspended && !trace_depth && time_freezes == time_resumes);
	assert(!rcu_idle && !instrumentation && !critical_stopped);
	assert(system_state == SYSTEM_RUNNING);
	for (int i = 0; i < 4; i++)
		assert(!local_suspended[i]);
}
static void selection_tests(void)
{
	reset();
	assert(cpuidle_enter_s2idle(&drv, &dev) == 0);
	assert(callbacks == 1 && !irq_disabled && time_freezes == 1);
	assert(dev.states_usage[0].s2idle_usage == 1 && dev.states_usage[0].s2idle_time == 1);
	balanced(); cases++;
	for (int variant = 0; variant < 5; variant++) {
		reset();
		if (variant == 0) drv.states[0].enter_s2idle = NULL;
		if (variant == 1) dev.states_usage[0].disable = CPUIDLE_STATE_DISABLED_BY_USER;
		if (variant == 2) dev.states_usage[0].disable = CPUIDLE_STATE_DISABLED_BY_DRIVER;
		if (variant == 3) drv.states[0].flags = CPUIDLE_FLAG_COUPLED;
		if (variant == 4) {
			drv.states[0].flags = CPUIDLE_FLAG_UNUSABLE;
			dev.states_usage[0].disable = CPUIDLE_STATE_DISABLED_BY_DRIVER;
		}
		assert(cpuidle_enter_s2idle(&drv, &dev) == -ENODEV);
		assert(irq_disabled && !callbacks && !clock_reads);
		balanced(); cases++;
	}
	/* OFF means initially disabled; a user can explicitly re-enable it. */
	reset(); drv.states[0].flags = CPUIDLE_FLAG_OFF;
	assert(cpuidle_enter_s2idle(&drv, &dev) == 0 && callbacks == 1);
	balanced(); cases++;
	for (int variant = 0; variant < 4; variant++) {
		reset(); drv.state_count = 3;
		for (int i = 1; i < 3; i++) {
			drv.states[i].enter_s2idle = callback;
			drv.states[i].exit_latency_ns = i * 1000;
		}
		int expected = 2;
		if (variant == 1) { dev.states_usage[2].disable = 1; expected = 1; }
		if (variant == 2) { drv.states[2].enter_s2idle = NULL; expected = 1; }
		if (variant == 3) { drv.states[2].exit_latency_ns = 500; expected = 1; }
		assert(cpuidle_enter_s2idle(&drv, &dev) == expected && callbacks == 1);
		assert(dev.states_usage[expected].s2idle_usage == 1);
		balanced(); cases++;
	}
	reset(); drv.state_count = 2; drv.states[1].exit_latency_ns = 5000;
	assert(cpuidle_find_deepest_state(&drv, &dev, U64_MAX) == 1);
	assert(cpuidle_find_deepest_state(&drv, &dev, 1000) == 0);
	assert(find_deepest_state(&drv, &dev, U64_MAX, 0, true) == 0);
	assert(cpuidle_enter_s2idle(&drv, &dev) == 0);
	balanced(); cases++;
	for (int variant = 0; variant < 3; variant++) {
		reset();
		if (variant == 0) callback_irq_leak = 1;
		if (variant == 1) callback_error = 1; /* Callback return is deliberately not a residency proof. */
		if (variant == 2) drv.states[0].flags = CPUIDLE_FLAG_RCU_IDLE;
		assert(cpuidle_enter_s2idle(&drv, &dev) == 0 && callbacks == 1);
		assert(warnings == (variant == 0) && raw_disables == (variant == 0));
		balanced(); cases++;
	}
}
static void scheduler_tests(void)
{
	for (int variant = 0; variant < 12; variant++) {
		reset();
		if (variant == 1) drv.states[0].enter_s2idle = NULL;
		if (variant == 2) dev.states_usage[0].disable = 1;
		if (variant == 3) resched = 1;
		if (variant == 4) race_resched = 1;
		if (variant == 5) active_driver = NULL;
		if (variant == 6) dev.enabled = 0;
		if (variant == 7) off = 1;
		if (variant >= 8) s2idle = 0;
		if (variant == 9) drv.state_count = 2;
		if (variant == 10) dev.forced_idle_latency_limit_ns = 1000;
		if (variant == 11) tick_stopped = 1;
		cpuidle_idle_call(false);
		assert(!irq_disabled && polling && !warnings);
		assert(callbacks == (variant == 0));
		assert(ordinary_calls == (variant == 1 || variant == 2 || variant >= 8));
		assert(default_calls == (variant >= 5 && variant <= 7));
		assert(selected == (variant == 9) && reflected == (variant == 9));
		assert(tick_stops == (variant == 1 || variant == 2 || variant == 4 || variant >= 9));
		assert(tick_retains == ((variant >= 5 && variant <= 8)));
		balanced(); cases++;
	}
	reset(); drv.state_count = 2;
	drv.states[1].enter_s2idle = callback; drv.states[1].exit_latency_ns = 1000;
	cpuidle_idle_call(false);
	assert(callbacks == 1 && !ordinary_calls && dev.states_usage[1].s2idle_usage == 1);
	balanced(); cases++;
}
static void board_tests(void)
{
	reset();
	assert(!strcmp(cpi_wfi_driver.name, "cpi_wfi") && cpi_wfi_driver.state_count == 1);
	assert(cpi_wfi_driver.safe_state_index == 0 && cpi_wfi_driver.cpumask == NULL);
	struct cpuidle_state *state = &cpi_wfi_driver.states[0];
	assert(state->enter == arm_cpuidle_simple_enter && state->enter_s2idle == state->enter);
	assert(state->exit_latency == 1 && state->target_residency == 1 && !state->power_usage && !state->flags);
	assert(!strcmp(state->name, "WFI") && !strcmp(state->desc, "ARM WFI"));
	assert(state->enter(&dev, &drv, 0) == 0 && wfi_calls == 1 && irq_disabled);
	assert(state->enter_s2idle(&dev, &drv, 2) == 2 && wfi_calls == 2 && irq_disabled);
	cases++;
	reset(); board_match = 0;
	assert(cpi_wfi_init() == -ENODEV && !driver_registers && !device_registers);
	cases++;
	const int errors[] = { -EBUSY, -ENODEV, -EINVAL, -ENOMEM };
	for (unsigned i = 0; i < sizeof(errors) / sizeof(errors[0]); i++) {
		reset(); register_error = errors[i];
		assert(cpi_wfi_init() == errors[i] && driver_registers == 1 && !device_registers && !driver_removes);
		cases++;
	}
	for (int i = 0; i < 4; i++) {
		reset(); fail_cpu = i;
		assert(cpi_wfi_init() == -ENOMEM);
		assert(device_registers == i + 1 && device_removes == i && driver_removes == 1);
		for (int cpu = 0; cpu < 4; cpu++) assert(!cpuidle_dev[cpu].registered);
		cases++;
	}
	reset();
	assert(cpi_wfi_init() == 0 && driver_registers == 1 && device_registers == 4);
	for (int cpu = 0; cpu < 4; cpu++) assert(cpuidle_dev[cpu].registered);
	cpuidle_unregister(&cpi_wfi_driver);
	assert(device_removes == 4 && driver_removes == 1);
	cases++;
}
static void tick_tests(void)
{
	/* Enumerate every four-CPU freeze and return ordering (24 * 24). */
	for (int entry = 0; entry < 256; entry++) {
		int in[4], seen = 0;
		for (int i = 0; i < 4; i++) { in[i] = (entry >> (2 * i)) & 3; seen |= BIT(in[i]); }
		if (seen != 15) continue;
		for (int exit = 0; exit < 256; exit++) {
			int out[4]; seen = 0;
			for (int i = 0; i < 4; i++) { out[i] = (exit >> (2 * i)) & 3; seen |= BIT(out[i]); }
			if (seen != 15) continue;
			reset(); online = 4;
			for (int i = 0; i < 4; i++) {
				current_cpu = in[i]; tick_freeze();
				assert(time_freezes == (i == 3));
			}
			for (int i = 0; i < 4; i++) {
				current_cpu = out[i]; tick_unfreeze();
				assert(time_resumes == 1);
			}
			balanced(); cases++;
		}
	}
	for (int count = 1; count < 4; count++) {
		reset(); online = 4;
		for (int i = 0; i < count; i++) { current_cpu = i; tick_freeze(); }
		for (int i = 0; i < count; i++) { current_cpu = i; tick_unfreeze(); }
		assert(!time_freezes && !time_resumes);
		balanced(); cases++;
	}
}
int main(void)
{
	selection_tests();
	scheduler_tests();
	board_tests();
	tick_tests();
	printf("PASS: %d CPU-idle/scheduler/registration/tick scenarios\n", cases);
	return 0;
}
