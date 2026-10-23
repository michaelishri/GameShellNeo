/* SPDX-License-Identifier: GPL-2.0-only */
/* Complete selected driver bodies; deterministic framework/hardware boundaries.
 * Linux DPM, SRCU, work and IRQ waits belong to the separate KUnit qualification.
 * An admitted-frame counter below models ownership, not a real native thread. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
typedef int irqreturn_t;
#define __iomem
#define CONFIG_PM 1
#define CONFIG_PM_SLEEP 1
#define CONFIG_USB_PHY 1
#define CONFIG_MUSB_PIO_ONLY 1
#define IS_ENABLED(value) (value)
#define RPM_GET_PUT 1
#define BIT(n) (1UL << (n))
#define container_of(p, t, m) ((t *)((char *)(p) - offsetof(t, m)))
#define to_sun4i_usb_phy_data(p) container_of(p, struct sun4i_usb_phy_data, phys[(p)->index])
#define IS_ERR(p) ((intptr_t)(p) < 0 && (intptr_t)(p) > -4096)
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define IRQ_GET_DESC_CHECK_GLOBAL 0
#define IRQCHIP_SKIP_SET_WAKE 1
#define IRQD_WAKEUP_STATE 1
#define IRQF_SHARED 1
#define IRQ_HANDLED 1
#define NOTIFY_DONE 0
#define EXTCON_USB_HOST 0
#define EXTCON_USB 1
#define MUSB_HOST 1
#define MUSB_PERIPHERAL 2
#define MUSB_OTG 3
#define MUSB_INDEXED_EP 1
#define MUSB_G_NO_SKB_RESERVE 2
#define MUSB_NO_ULPI_BUSCONTROL 4
#define MUSB_PRESERVE_SESSION 8
#define MUSB_CONTROLLER_MHDRC 1
#define MUSB_CONTROLLER_HDRC 2
#define MUSB_DEVCTL 0
#define MUSB_POWER 1
#define MUSB_ULPI_BUSCONTROL 2
#define MUSB_TESTMODE 3
#define MUSB_ULPI_USE_EXTVBUS 1
#define MUSB_DEVCTL_SESSION 1
#define MUSB_DEVCTL_VBUS 24
#define MUSB_DEVCTL_BDEVICE 128
#define MUSB_DEVCTL_FSDEV 64
#define MUSB_DEVCTL_LSDEV 32
#define MUSB_POWER_ISOUPDATE 128
#define MUSB_POWER_HSENAB 32
#define SUNXI_MUSB_DEVCTL 0
#define SUNXI_MUSB_VEND0 4
#define SUNXI_MUSB_VEND0_PIO_MODE 1
#define SUNXI_MUSB_FL_ENABLED 0
#define SUNXI_MUSB_FL_HOSTMODE_PEND 2
#define SUNXI_MUSB_FL_VBUS_ON 3
#define SUNXI_MUSB_FL_PHY_ON 4
#define SUNXI_MUSB_FL_PHY_MODE_PEND 5
#define SUNXI_MUSB_FL_HAS_SRAM 6
#define SUNXI_MUSB_FL_HAS_RESET 7
#define SUNXI_MUSB_FL_NO_CONFIGDATA 8
#define USB_SPEED_UNKNOWN 0
#define USB_SPEED_HIGH 3
#define USB_EVENT_ID 1
#define USB_PORT_STAT_ENABLE 2
#define OTG_STATE_B_IDLE 1
#define OTG_STATE_A_WAIT_VRISE 2
#define OTG_STATE_A_WAIT_BCON 3
#define USB_DR_MODE_OTG 0
#define USB_DR_MODE_PERIPHERAL 1
#define USB_DR_MODE_HOST 2
#define PHY_CTL_VBUSVLDEXT 1
#define PHY_CTL_SIDDQ 2
#define PHY_RES45_CAL_EN 0
#define PHY_TX_AMPLITUDE_TUNE 1
#define PHY_DISCON_TH_SEL 2
#define ISCR_DPDM_PULLUP_EN 1
#define ISCR_ID_PULLUP_EN 2
#define REG_HCI_PHY_CTL 0
#define POLL_TIME 250
#define DEBOUNCE_TIME 50

enum phy_mode { PHY_MODE_USB_DEVICE, PHY_MODE_USB_HOST, PHY_MODE_USB_OTG };
struct musb;
struct device {
	void *drvdata, *platdata;
	struct device *parent;
	void *dma_mask;
	bool capable, wake, runtime_enabled;
	int refs;
	struct { void *wakeup, *wakeirq; } power;
};
struct platform_device { struct device dev; };
struct work_struct { bool initialized, disabled, pending, running; };
struct delayed_work { struct work_struct work; };
struct notifier_block { int unused; };
struct mutex { bool held; };
struct phy { struct device dev; struct mutex mutex; void *data; unsigned init_count; };
struct sun4i_usb_phy {
	struct phy *phy;
	void *clk, *clk2, *reset, *pmu;
	unsigned index;
};
struct sun4i_usb_phy_cfg {
	bool needs_phy2_siddq, siddq_in_base, phy0_dual_route;
	u32 hci_phy_ctl_clear;
	unsigned phyctl_offset, disc_thresh;
};
struct sun4i_usb_phy_data {
	struct sun4i_usb_phy phys[3];
	struct sun4i_usb_phy_cfg *cfg;
	struct delayed_work detect;
	void *base, *extcon;
	bool phy0_init, force_session_end;
	u64 phy0_generation;
	int id_det, vbus_det, dr_mode;
};
struct otg { int state; };
struct transceiver { void *io_ops, *io_dev, *io_priv; struct otg *otg; int last_event; };
struct config { bool multipoint; int maximum_speed; };
struct usb_gadget { bool quirk_avoids_skb_reserve; int speed; };
struct usb_gadget_driver { int max_speed; };
typedef void (*io_fn)(void);
struct musb_platform_ops {
	unsigned quirks, fifo_mode;
	io_fn ep_offset, ep_select, fifo_offset, busctl_offset;
	io_fn read_fifo, write_fifo, get_toggle, set_toggle, phy_callback;
	u8 (*readb)(void *, unsigned), (*clearb)(void *, unsigned);
	void (*writeb)(void *, unsigned, u8);
	u16 (*readw)(void *, unsigned), (*clearw)(void *, unsigned);
	void (*writew)(void *, unsigned, u16);
};
struct musb_hdrc_platform_data {
	struct config *config;
	struct musb_platform_ops *platform_ops;
	int min_power, mode, power;
	bool extvbus;
};
struct musb {
	struct device *controller;
	struct musb_platform_ops *ops;
	struct config *config;
	struct transceiver *xceiv;
	struct phy *phy;
	struct usb_gadget g;
	struct usb_gadget_driver *gadget_driver;
	void *mregs, *dma_controller;
	struct { io_fn ep_offset, ep_select, fifo_offset, busctl_offset;
		io_fn read_fifo, write_fifo, get_toggle, set_toggle; } io;
	struct { u8 devctl; } context;
	struct delayed_work irq_work, finish_resume_work, deassert_reset_work;
	unsigned pending_list, port1_status;
	int nIrq, lock, list_lock, min_power, port_mode, otg_timer;
	bool irq_wake, wakeup_initialized, is_initialized, session, resume_work_stopping;
	bool gadget_suspended, softconnect, is_active, flush_irq_work;
	io_fn isr;
};
struct sunxi_glue {
	struct device *dev;
	struct musb *musb;
	struct phy *phy;
	struct transceiver *xceiv;
	void *clk, *rst, *extcon;
	enum phy_mode phy_mode, initial_phy_mode;
	unsigned long flags;
	struct work_struct work;
	struct notifier_block host_nb;
};
struct irq_chip;
struct irq_data { unsigned flags; struct irq_chip *chip; };
struct irq_chip { unsigned flags; int (*irq_set_wake)(struct irq_data *, unsigned); };
struct irq_desc { struct irq_data irq_data; unsigned wake_depth; bool locked; };

static struct musb instance;
static struct platform_device child;
static struct device parent;
static struct sunxi_glue glue;
static struct sun4i_usb_phy_data detector;
static struct sun4i_usb_phy_cfg phy_config;
static struct phy phy0;
static struct transceiver xceiv;
static struct otg otg;
static struct musb_hdrc_platform_data pdata;
static struct musb_platform_ops ops;
static struct config config;
static struct usb_gadget_driver gadget_driver = { .max_speed = USB_SPEED_HIGH };
static struct irq_desc desc;
static struct irq_chip chip;
static struct musb *sunxi_musb;
static void *system_wq;
static u8 registers[256];
static unsigned backend_clock, phy_clock, mmio, bad_access, errors;
static unsigned arms, disarms, frees, notifier_readers, work_waits, irq_waits, notifier_waits;
static unsigned phy_reads, generation_returns, dpm_walks, dpm_late_errors, initial_gets, udc_starts;
static bool action, peer_action, notifier, usb_phy_live, gadget_registered;
static bool runtime_ready, autosuspend, irq_running;
static bool fail_phy, fail_arm, fail_disarm, fail_initial_get, rebind_after_dispatch;
static bool control_cleanup, control_work;
static unsigned failures;
static const char *active_case;
static int fifo_mode, musb_ulpi_access;
static bool use_dma;
static io_fn musb_phy_callback;
static void *(*musb_dma_controller_create)(struct musb *, void *);
static void (*musb_dma_controller_destroy)(void *);

#define dev_err(...) do { errors++; } while (0)
#define dev_err_probe(...) do { errors++; } while (0)
#define dev_info(...) do { } while (0)
#define musb_dbg(...) do { } while (0)
#define WARN_ON(x) assert(!(x))
#define WARN(x, ...) assert(!(x))
#define spin_lock_init(p) (*(p) = 0)
#define spin_lock_irqsave(p, f) do { (f) = 0; assert(!*(p)); *(p) = 1; } while (0)
#define spin_unlock_irqrestore(p, f) do { (void)(f); assert(*(p)); *(p) = 0; } while (0)
#define INIT_DELAYED_WORK(p, fn) do { (void)(fn); (p)->work.initialized = true; } while (0)
#define timer_setup(p, fn, flags) do { (void)(fn); (void)(flags); *(p) = 1; } while (0)
#define MUSB_DEV_MODE(m) ((void)(m))
#define MUSB_HST_MODE(m) ((void)(m))
#define list_empty(p) (*(p) == 0)
static void set_bit(unsigned bit, unsigned long *flags) { *flags |= BIT(bit); }
static void clear_bit(unsigned bit, unsigned long *flags) { *flags &= ~BIT(bit); }
static bool test_bit(unsigned bit, const unsigned long *flags) { return !!(*flags & BIT(bit)); }
static bool test_and_set_bit(unsigned bit, unsigned long *flags)
{ bool was = test_bit(bit, flags); set_bit(bit, flags); return was; }
static bool test_and_clear_bit(unsigned bit, unsigned long *flags)
{ bool was = test_bit(bit, flags); clear_bit(bit, flags); return was; }
static void noop(void) { }
#define musb_indexed_ep_offset noop
#define musb_indexed_ep_select noop
#define musb_flat_ep_offset noop
#define musb_flat_ep_select noop
#define musb_default_fifo_offset noop
#define musb_default_busctl_offset noop
#define musb_default_read_fifo noop
#define musb_default_write_fifo noop
#define musb_default_get_toggle noop
#define musb_default_set_toggle noop
#define musb_irq_work noop
#define musb_deassert_reset noop
#define musb_host_finish_resume noop
#define musb_otg_timer_func noop

static void observe(bool okay, const char *field)
{
	if (!okay) {
		printf("FAIL %s %s\n", active_case, field);
		failures++;
	}
}
static void *dev_get_drvdata(struct device *dev) { return dev->drvdata; }
static void *dev_get_platdata(struct device *dev) { return dev->platdata; }
static const char *dev_name(struct device *dev) { (void)dev; return "combined-native"; }
static struct musb *dev_to_musb(struct device *dev) { return dev->drvdata; }
static struct musb *gadget_to_musb(struct usb_gadget *g) { return container_of(g, struct musb, g); }
static void mutex_lock(struct mutex *mutex) { assert(!mutex->held); mutex->held = true; }
static void mutex_unlock(struct mutex *mutex) { assert(mutex->held); mutex->held = false; }
static void *phy_get_drvdata(struct phy *phy) { return phy->data; }
static void hardware(void)
{
	if (!backend_clock) bad_access++;
	assert(backend_clock); mmio++;
}
static u8 readb(void *address) { hardware(); return *(u8 *)address; }
static void writeb(u8 value, void *address) { hardware(); *(u8 *)address = value; }
static u8 musb_default_readb(void *base, unsigned offset) { return readb((u8 *)base + offset); }
static void musb_default_writeb(void *base, unsigned offset, u8 value) { writeb(value, (u8 *)base + offset); }
static u16 musb_default_readw(void *base, unsigned offset) { return musb_default_readb(base, offset); }
static void musb_default_writew(void *base, unsigned offset, u16 value) { musb_default_writeb(base, offset, value); }
static u8 (*musb_readb)(void *, unsigned), (*musb_clearb)(void *, unsigned);
static void (*musb_writeb)(void *, unsigned, u8);
static u16 (*musb_readw)(void *, unsigned), (*musb_clearw)(void *, unsigned);
static void (*musb_writew)(void *, unsigned, u16);
static int clk_prepare_enable(void *clk)
{
	if (!clk) return 0;
	if (clk == &phy_clock && fail_phy) return -EIO;
	(*(unsigned *)clk)++; return 0;
}
static void clk_disable_unprepare(void *clk)
{ if (clk) { assert(*(unsigned *)clk); (*(unsigned *)clk)--; } }
static int reset_control_deassert(void *reset) { (void)reset; return 0; }
static void reset_control_assert(void *reset) { (void)reset; }
static int sunxi_sram_claim(struct device *dev) { (void)dev; assert(false); return -EINVAL; }
static void sunxi_sram_release(struct device *dev) { (void)dev; assert(false); }
static bool schedule_work(struct work_struct *work)
{ if (work->disabled || work->pending) return false; work->pending = true; return true; }
static void enable_work(struct work_struct *work) { assert(work->disabled); work->disabled = false; }
static void disable_work_sync(struct work_struct *work)
{
	assert(!instance.lock && backend_clock);
	if (work->running) { work_waits++; work->running = false; }
	work->pending = false; work->disabled = true;
}
static bool queue_delayed_work(void *queue, struct delayed_work *work, unsigned delay)
{ (void)delay; assert(queue == system_wq); return schedule_work(&work->work); }
static bool mod_delayed_work(void *queue, struct delayed_work *work, unsigned delay)
{ work->work.pending = false; return queue_delayed_work(queue, work, delay); }
static void phy_access(void)
{ assert(phy0.mutex.held && phy_clock); phy_reads++; }
static u32 readl(void *address) { (void)address; phy_access(); return 0; }
static void writel(u32 value, void *address) { (void)value; (void)address; phy_access(); }
static void sun4i_usb_phy_write(struct sun4i_usb_phy *phy, unsigned a, unsigned b, unsigned c)
{ (void)phy; (void)a; (void)b; (void)c; phy_access(); }
static void sun4i_usb_phy_passby(struct sun4i_usb_phy *phy, int on)
{ (void)phy; (void)on; phy_access(); }
static void sun4i_usb_phy0_update_iscr(struct phy *phy, unsigned clear, unsigned set)
{ (void)phy; (void)clear; (void)set; phy_access(); }
static void sun4i_usb_phy0_set_vbus_detect(struct phy *phy, int value)
{ (void)phy; (void)value; phy_access(); }
static void sun4i_usb_phy0_set_id_detect(struct phy *phy, int value)
{ (void)phy; (void)value; phy_access(); }
static void sun4i_usb_phy0_reroute(struct sun4i_usb_phy_data *data, int value)
{ (void)data; (void)value; phy_access(); }
static int sun4i_usb_phy0_get_id_det(struct sun4i_usb_phy_data *data)
{ assert(data->dr_mode == USB_DR_MODE_PERIPHERAL); phy_access(); return 1; }
static int sun4i_usb_phy0_get_vbus_det(struct sun4i_usb_phy_data *data)
{ (void)data; phy_access(); return 1; }
static bool sun4i_usb_phy0_have_vbus_det(struct sun4i_usb_phy_data *data) { (void)data; return true; }
static bool sun4i_usb_phy0_poll(struct sun4i_usb_phy_data *data)
{ assert(data->phy0_init && phy0.mutex.held); return false; }
static void msleep(unsigned delay) { assert(delay == 200 || delay == 1000); }
static int sun4i_usb_phy_init(struct phy *phy);
static int sun4i_usb_phy_exit(struct phy *phy);
static int sun4i_usb_phy_set_mode(struct phy *phy, enum phy_mode mode, int submode);
static int phy_init(struct phy *phy)
{
	mutex_lock(&phy->mutex); int ret = sun4i_usb_phy_init(phy);
	if (!ret) phy->init_count++;
	mutex_unlock(&phy->mutex); return ret;
}
static void phy_exit(struct phy *phy)
{
	assert(phy->init_count == 1 && (glue.work.disabled || control_work) && !notifier);
	mutex_lock(&phy->mutex); assert(!sun4i_usb_phy_exit(phy)); phy->init_count--;
	mutex_unlock(&phy->mutex);
}
static void phy_set_mode(struct phy *phy, enum phy_mode mode)
{ mutex_lock(&phy->mutex); assert(!sun4i_usb_phy_set_mode(phy, mode, 0)); mutex_unlock(&phy->mutex); }
static void phy_power_on(struct phy *phy) { assert(phy->init_count); }
static void phy_power_off(struct phy *phy) { assert(phy->init_count); }
static int extcon_register_notifier(void *edev, int cable, struct notifier_block *nb)
{ assert(edev == &detector && cable == EXTCON_USB_HOST && nb == &glue.host_nb && !notifier); notifier = true; return 0; }
static int extcon_unregister_notifier_sync(void *edev, int cable, struct notifier_block *nb)
{
	assert(edev == &detector && cable == EXTCON_USB_HOST && nb == &glue.host_nb && notifier);
	assert(!instance.lock && backend_clock); notifier = false;
	if (notifier_readers) { notifier_waits++; notifier_readers = 0; }
	return 0;
}
static int extcon_get_state(void *edev, int cable) { assert(edev == &detector && cable == EXTCON_USB_HOST); return 0; }
static int sunxi_musb_host_notifier(struct notifier_block *nb, unsigned long event, void *ptr);
static void modeled_rebind(void);
static void extcon_set_state_sync(void *edev, unsigned cable, int value)
{
	assert(edev == &detector && !phy0.mutex.held);
	if (cable == EXTCON_USB_HOST && notifier) {
		notifier_readers++;
		sunxi_musb_host_notifier(&glue.host_nb, value, NULL);
		notifier_readers--;
	}
	/* A process may retire/rebind after SRCU dispatch returns. */
	if (rebind_after_dispatch) { rebind_after_dispatch = false; modeled_rebind(); generation_returns++; }
}
static int __pm_runtime_resume(struct device *dev, int flags)
{
	assert(flags == RPM_GET_PUT && dev->runtime_enabled);
	dev->refs++; initial_gets++;
	if (fail_initial_get) return -EIO;
	runtime_ready = true; return 0;
}
static int pm_runtime_get_sync(struct device *dev) { return __pm_runtime_resume(dev, RPM_GET_PUT); }
static void pm_runtime_get(struct device *dev) { dev->refs++; }
static void pm_runtime_put(struct device *dev) { assert(dev->refs > 0); dev->refs--; }
static void pm_runtime_put_noidle(struct device *dev) { pm_runtime_put(dev); }
static void pm_runtime_put_autosuspend(struct device *dev) { pm_runtime_put(dev); }
static void pm_runtime_mark_last_busy(struct device *dev) { (void)dev; }
static void pm_runtime_enable(struct device *dev) { assert(!dev->runtime_enabled); dev->runtime_enabled = true; }
static void pm_runtime_disable(struct device *dev) { assert(dev->runtime_enabled); dev->runtime_enabled = false; }
static void pm_runtime_use_autosuspend(struct device *dev) { (void)dev; autosuspend = true; }
static void pm_runtime_dont_use_autosuspend(struct device *dev) { (void)dev; autosuspend = false; }
static void pm_runtime_set_autosuspend_delay(struct device *dev, int delay) { (void)dev; assert(delay == 500); }
static struct irq_desc *irq_to_desc(unsigned irq) { assert(irq == 164); return &desc; }
static struct irq_chip *irq_desc_get_chip(struct irq_desc *d) { return d->irq_data.chip; }
static bool irq_is_nmi(struct irq_desc *d) { (void)d; return false; }
static void irqd_set(struct irq_data *d, unsigned flag) { d->flags |= flag; }
static void irqd_clear(struct irq_data *d, unsigned flag) { d->flags &= ~flag; }
static struct irq_desc *get_desc(unsigned irq)
{ assert(irq == 164 && !desc.locked && !instance.lock); desc.locked = true; return &desc; }
static struct irq_desc *put_desc(struct irq_desc *d) { if (d) d->locked = false; return NULL; }
static void cleanup_desc(struct irq_desc **d) { put_desc(*d); }
#define scoped_irqdesc_get_and_buslock(irq, check) \
	for (struct irq_desc *scoped_irqdesc __attribute__((cleanup(cleanup_desc))) = get_desc(irq); \
	     scoped_irqdesc; scoped_irqdesc = put_desc(scoped_irqdesc))
int irq_set_irq_wake(unsigned irq, unsigned on);
static int chip_wake(struct irq_data *data, unsigned on)
{ assert(data == &desc.irq_data); if (on) { arms++; return fail_arm ? -EIO : 0; }
  disarms++; return fail_disarm ? -EIO : 0; }
static int enable_irq_wake(unsigned irq) { assert(action || peer_action); return irq_set_irq_wake(irq, 1); }
static int disable_irq_wake(unsigned irq) { assert(irq == 164); return irq_set_irq_wake(irq, 0); }
static bool device_can_wakeup(struct device *dev) { return dev->capable; }
static bool device_may_wakeup(struct device *dev) { return dev->wake; }
static int device_init_wakeup(struct device *dev, bool enable)
{ dev->capable = dev->wake = enable; dev->power.wakeup = enable ? dev : NULL; return 0; }
static struct musb *allocate_instance(struct device *dev, struct config *cfg, void *base)
{
	assert(!action); memset(&instance, 0, sizeof(instance));
	instance.controller = dev; instance.mregs = base; instance.config = cfg;
	instance.nIrq = -ENODEV; dev->drvdata = &instance; return &instance;
}
static int sunxi_musb_init(struct musb *musb);
static int sunxi_musb_exit(struct musb *musb);
static int control_sunxi_musb_exit(struct musb *musb);
static void sunxi_musb_enable(struct musb *musb);
static void sunxi_musb_disable(struct musb *musb);
static int sunxi_musb_set_mode(struct musb *musb, u8 mode);
static int musb_platform_init(struct musb *musb) { return sunxi_musb_init(musb); }
static void musb_platform_exit(struct musb *musb)
{ assert(!(action || gadget_registered)); assert(!(control_work ? control_sunxi_musb_exit(musb) : sunxi_musb_exit(musb))); }
static void musb_platform_enable(struct musb *musb) { sunxi_musb_enable(musb); }
static void musb_platform_disable(struct musb *musb) { sunxi_musb_disable(musb); }
static int musb_platform_set_mode(struct musb *musb, int mode) { return sunxi_musb_set_mode(musb, mode); }
static void musb_platform_set_vbus(struct musb *musb, int on) { (void)musb; (void)on; assert(false); }
static void sunxi_musb_interrupt(void) { }
static int usb_phy_init(struct transceiver *phy) { assert(phy == &xceiv && runtime_ready); usb_phy_live = true; return 0; }
static void usb_phy_shutdown(struct transceiver *phy) { assert(phy == &xceiv && usb_phy_live); usb_phy_live = false; }
static void musb_disable_interrupts(struct musb *musb) { (void)musb; hardware(); }
static void musb_enable_interrupts(struct musb *musb) { (void)musb; hardware(); }
static int musb_core_init(int type, struct musb *musb) { (void)type; assert(musb == &instance && runtime_ready); return 0; }
static int request_irq(int irq, io_fn fn, int flags, const char *name, struct musb *musb)
{ (void)name; assert(irq == 164 && fn && flags == IRQF_SHARED && musb == &instance && !action); action = true; return 0; }
static void free_irq(int irq, struct musb *musb)
{
	assert(irq == 164 && action && !musb->lock && backend_clock && !gadget_registered);
	if (irq_running) { irq_waits++; irq_running = false; }
	action = false; frees++;
}
static void musb_host_free(struct musb *musb) { (void)musb; }
static int musb_host_setup(struct musb *musb, int power) { (void)musb; (void)power; assert(false); return -EINVAL; }
static int musb_gadget_setup(struct musb *musb) { assert(musb == &instance); gadget_registered = true; return 0; }
static void musb_host_cleanup(struct musb *musb) { assert(musb->port_mode == MUSB_PERIPHERAL); }
static void musb_gadget_cleanup(struct musb *musb) { (void)musb; gadget_registered = false; }
static void musb_set_state(struct musb *musb, int state) { musb->xceiv->otg->state = state; }
static int musb_get_state(struct musb *musb) { return musb->xceiv->otg->state; }
static void musb_root_disconnect(struct musb *musb) { (void)musb; assert(false); }
static void musb_init_debugfs(struct musb *musb) { (void)musb; }
static void musb_exit_debugfs(struct musb *musb) { (void)musb; }
static void musb_shutdown_resume_work(struct musb *musb) { assert(!musb->lock); musb->resume_work_stopping = true; }
static void cancel_delayed_work_sync(struct delayed_work *work) { work->work.pending = false; }
static bool flush_delayed_work(struct delayed_work *work) { work->work.pending = false; return false; }
static void disable_delayed_work_sync(struct delayed_work *work) { work->work.pending = false; work->work.disabled = true; }
static void timer_shutdown_sync(int *timer) { assert(*timer == 1); *timer = 2; }
static void musb_gadget_suspend(struct musb *musb) { musb->gadget_suspended = true; }
static void musb_gadget_resume(struct musb *musb) { musb->gadget_suspended = false; }
static void synchronize_irq(int irq) { assert(irq == 164); }
static void musb_g_disconnect(struct musb *musb) { musb->g.speed = USB_SPEED_UNKNOWN; }
static bool is_host_active(struct musb *musb) { (void)musb; return false; }
static void musb_save_context(struct musb *musb) { musb->context.devctl = musb_readb(musb->mregs, MUSB_DEVCTL); }
static void musb_restore_context(struct musb *musb) { musb_writeb(musb->mregs, MUSB_DEVCTL, musb->context.devctl); }
static int musb_run_resume_work(struct musb *musb) { assert(musb->lock && !musb->pending_list); return 0; }
static void otg_set_peripheral(struct otg *phy, struct usb_gadget *gadget) { (void)phy; (void)gadget; }

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-parameter"
#include "musb_combined_lifecycle_functions.h"
#pragma GCC diagnostic pop

static void drain_backend_work(void)
{
	if (!glue.work.pending) return;
	glue.work.pending = false; glue.work.running = true;
	sunxi_musb_work(&glue.work); glue.work.running = false;
}
static void scan(void)
{ detector.detect.work.pending = false; sun4i_usb_phy0_id_vbus_det_scan(&detector.detect.work); }
static int probe(void) { return musb_init_controller(&child.dev, 164, registers); }
static void remove_child(void)
{ if (control_cleanup) control_musb_remove(&child); else musb_remove(&child); }
static void modeled_rebind(void)
{
	remove_child(); assert(!backend_clock && !phy_clock && !child.dev.refs);
	assert(!probe());
	assert(!musb_gadget_start(&instance.g, &gadget_driver)); udc_starts++;
}
static void reset_case(const char *name)
{
	active_case = name; memset(&instance, 0, sizeof(instance)); memset(&child, 0, sizeof(child));
	memset(&parent, 0, sizeof(parent)); memset(&glue, 0, sizeof(glue));
	memset(&detector, 0, sizeof(detector)); memset(&phy0, 0, sizeof(phy0));
	memset(&phy_config, 0, sizeof(phy_config)); memset(&xceiv, 0, sizeof(xceiv));
	memset(registers, 0, sizeof(registers));
	backend_clock = phy_clock = mmio = bad_access = errors = 0;
	arms = disarms = frees = notifier_readers = work_waits = irq_waits = notifier_waits = 0;
	phy_reads = generation_returns = dpm_walks = dpm_late_errors = initial_gets = udc_starts = 0;
	action = peer_action = notifier = usb_phy_live = gadget_registered = false;
	runtime_ready = autosuspend = irq_running = false;
	fail_phy = fail_arm = fail_disarm = fail_initial_get = rebind_after_dispatch = false;
	parent.drvdata = &glue; child.dev.parent = &parent;
	ops = (struct musb_platform_ops){ .quirks = MUSB_INDEXED_EP | MUSB_NO_ULPI_BUSCONTROL };
	config = (struct config){ .multipoint = true, .maximum_speed = USB_SPEED_HIGH };
	pdata = (struct musb_hdrc_platform_data){ .config = &config, .platform_ops = &ops, .mode = MUSB_PERIPHERAL };
	child.dev.platdata = &pdata;
	xceiv.otg = &otg;
	glue.dev = &parent; glue.phy = &phy0; glue.xceiv = &xceiv;
	glue.clk = &backend_clock; glue.extcon = &detector;
	glue.initial_phy_mode = PHY_MODE_USB_DEVICE;
	glue.flags = BIT(SUNXI_MUSB_FL_HAS_RESET) | BIT(SUNXI_MUSB_FL_NO_CONFIGDATA);
	glue.work.disabled = true; glue.work.initialized = true;
	detector.extcon = &detector; detector.cfg = &phy_config;
	detector.phys[0].phy = &phy0; detector.phys[0].clk = &phy_clock;
	phy0.data = &detector.phys[0]; detector.dr_mode = USB_DR_MODE_PERIPHERAL;
	chip = (struct irq_chip){ .irq_set_wake = chip_wake };
	desc = (struct irq_desc){ .irq_data = { .chip = &chip } };
	use_dma = false; musb_phy_callback = NULL;
}
static void udc_start(void)
{ assert(gadget_registered); assert(!musb_gadget_start(&instance.g, &gadget_driver)); udc_starts++; drain_backend_work(); }
static void modeled_dpm(bool wake, bool late_error)
{
	/* Framework phase references/IRQ traversal are modeled here, real in KUnit. */
	int before = child.dev.refs; unsigned depth = desc.wake_depth;
	child.dev.wake = wake; pm_runtime_get(&child.dev);
	int ret = musb_suspend(&child.dev);
	observe(ret == (fail_arm ? -EIO : 0), "dpm_suspend_error");
	if (!ret) {
		assert(desc.wake_depth == depth + (unsigned)wake);
		if (late_error) dpm_late_errors++; /* A modeled late error enters the same resume path. */
		assert(musb_resume(&child.dev) == (fail_disarm ? -EIO : 0));
	}
	pm_runtime_put(&child.dev); assert(child.dev.refs == before);
	assert(!instance.lock); dpm_walks++;
}
static void settled(bool foreign, unsigned peer, bool debt)
{
	observe(!backend_clock && !phy_clock && !phy0.init_count, "resource_balance");
	observe(!notifier && !action && !gadget_registered, "owner_balance");
	observe(!child.dev.refs && !child.dev.runtime_enabled && !autosuspend, "pm_balance");
	observe(!bad_access, "register_lifetime");
	if (!foreign) {
		observe(!instance.wakeup_initialized, "wakeup_initialized");
		observe(!child.dev.capable, "wakeup_capability");
		observe(!child.dev.power.wakeup, "wakeup_source");
	}
	observe(desc.wake_depth == peer + (unsigned)debt && instance.irq_wake == debt, "wake_debt");
	bool accepted = schedule_work(&glue.work);
	observe(!accepted, "late_work_queue");
	if (accepted) drain_backend_work(); /* ENABLED=false: no hardware. */
	if (!glue.work.disabled) { glue.work.disabled = true; glue.work.pending = false; }
	if (control_cleanup) musb_cleanup_wakeup(&instance); /* source observations precede fixture cleanup */
}
static void run_case(unsigned index, const char *name)
{
	reset_case(name); unsigned before_failures = failures;
	if (index == 3) fail_initial_get = true;
	if (index == 4) fail_phy = true;
	bool foreign = index == 5;
	if (foreign) device_init_wakeup(&child.dev, true);
	if (index == 2) { peer_action = true; assert(!enable_irq_wake(164)); }
	int ret = probe();
	if (index >= 3 && index <= 5) {
		observe(ret == (foreign ? -EEXIST : -EIO), "probe_error");
		settled(foreign, 0, false);
		if (foreign) { observe(child.dev.capable && child.dev.power.wakeup == &child.dev, "foreign_source"); device_init_wakeup(&child.dev, false); }
	} else {
		assert(!ret && child.dev.refs == 1 && action && phy0.init_count == 1);
		if (index <= 1) udc_start();
		if (index == 6) fail_arm = true;
		if (index == 8) fail_disarm = true;
		modeled_dpm(index != 0, index == 7);
		drain_backend_work();
		if (index == 7) observe(dpm_late_errors == 1, "modeled_late_error_unwind");
		if (index == 9) notifier_readers = 1; /* admitted native framework frame */
		if (index == 10) { assert(!sunxi_musb_recover(&instance)); glue.work.running = true; }
		if (index == 11) irq_running = true;
		if (index == 12) {
			u64 generation = detector.phy0_generation;
			rebind_after_dispatch = true; scan();
			observe(generation_returns == 1 && detector.phy0_generation == generation + 1, "detector_generation");
			observe(detector.detect.work.pending, "replacement_scan");
			drain_backend_work();
		}
		remove_child();
		if (index == 9) observe(notifier_waits == 1, "notifier_wait");
		if (index == 10) observe(work_waits == 1, "work_wait");
		if (index == 11) observe(irq_waits == 1, "irq_wait");
		settled(false, index == 2, index == 8);
		if (index == 8) {
			unsigned attempts = disarms; musb_free_irq(&instance);
			observe(disarms == attempts && desc.wake_depth == 1, "no_terminal_retry");
			fail_disarm = false; assert(!disable_irq_wake(164)); instance.irq_wake = false;
		}
		if (index == 2 || index == 13) {
			unsigned reads = phy_reads;
			sun4i_usb_phy0_id_vbus_det_irq(164, &detector); scan();
			observe(phy_reads == reads, "inactive_producer");
			assert(!probe()); udc_start(); scan();
			observe(detector.phy0_generation == 2, "fresh_generation");
			remove_child(); settled(false, index == 2, false);
		}
		if (index == 2) { assert(desc.wake_depth == 1 && peer_action); assert(!disable_irq_wake(164)); peer_action = false; }
	}
	printf("CASE %s %s\n", name, failures == before_failures ? "PASS" : "FAIL");
}

int main(int argc, char **argv)
{
	const char *names[] = {
		"combined_policy_disabled_remove_test", "combined_policy_enabled_remove_test",
		"combined_shared_peer_rebind_test", "combined_startup_pm_error_test",
		"combined_phy_init_error_test", "combined_foreign_wakeup_probe_error_test",
		"combined_dpm_arm_error_remove_test", "combined_dpm_late_error_remove_test",
		"combined_resume_debt_remove_test", "combined_held_notifier_remove_test",
		"combined_held_work_remove_test", "combined_held_irq_remove_test",
		"combined_detector_exit_rebind_test", "combined_closed_producer_rebind_test",
	};
	if (argc == 2) {
		control_cleanup = !strcmp(argv[1], "terminal-wake-cleanup");
		control_work = !strcmp(argv[1], "sunxi-work-disable");
		if (!control_cleanup && !control_work) return 2;
		unsigned index = control_cleanup ? 1 : 0;
		run_case(index, names[index]);
		printf("CONTROL %s %u observations\n", argv[1], failures);
		return failures ? 1 : 0;
	}
	assert(argc == 1);
	for (unsigned i = 0; i < sizeof(names) / sizeof(names[0]); i++) run_case(i, names[i]);
	if (failures) return 1;
	puts("MUSB combined lifecycle: 14 actual-source families passed");
	return 0;
}
