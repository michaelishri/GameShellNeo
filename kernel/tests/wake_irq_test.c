/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual IRQ-core/regmap/driver callbacks, deterministic IRQ/PM shims. */
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <errno.h>
#include <string.h>
#include <stdarg.h>
#define IRQ_GET_DESC_CHECK_GLOBAL 0
#define IRQCHIP_SKIP_SET_WAKE 1
#define IRQD_WAKEUP_STATE 1
#define WARN(test, ...) assert(!(test))
#define dev_err(...) ((void)0)
struct device { void *data; bool wake; };
static void *dev_get_drvdata(struct device *d) { return d->data; }
static bool device_may_wakeup(struct device *d) { return d->wake; }
struct irq_data { int irq, hwirq; unsigned flags; void *chip_data; struct irq_chip *chip; };
struct irq_chip { int flags; void (*irq_bus_lock)(void); void (*irq_bus_sync_unlock)(void); int (*irq_set_wake)(struct irq_data *, unsigned); };
struct irq_desc { struct irq_data irq_data; int wake_depth, disabled; bool locked; };
static struct irq_desc descs[16];
struct regmap { int reg_stride; };
struct regmap_irq { int reg_offset; unsigned mask; };
struct regmap_irq_chip_data { int irq, wake_count; bool wake_parent_atomic; unsigned *wake_buf; struct regmap *map; };
struct axp20x_pek { void *input; int irq_dbf, irq_dbr; bool wake_dbf, wake_dbr, irqs_disabled; };
struct sun6i_rtc_dev { int irq; bool wake_armed; };
struct power_supply { struct device dev; };
struct axp20x_ac_power { struct power_supply *supply; bool wake_armed, irqs_disabled; unsigned disabled_from, num_irqs, irqs[2]; };
static struct regmap map = {1};
static struct regmap_irq_chip_data regdata;
static struct regmap_irq regirqs[8];
static struct irq_chip parent_chip, child_chip;
static int fail_parent_on, fail_parent_off, fail_child, on_calls, off_calls;
static bool hardware_wake[16];
static void bus_callback(void) { assert(!"sleeping parent must not use direct path"); }
static struct irq_chip *irq_get_chip(int irq) { return descs[irq].irq_data.chip; }
static struct irq_desc *irq_to_desc(int irq) { return &descs[irq]; }
static struct irq_chip *irq_desc_get_chip(struct irq_desc *d) { return d->irq_data.chip; }
static bool irq_is_nmi(struct irq_desc *d) { (void)d; return false; }
static void irqd_set(struct irq_data *d, unsigned f) { d->flags |= f; }
static void irqd_clear(struct irq_data *d, unsigned f) { d->flags &= ~f; }
static void *irq_data_get_irq_chip_data(struct irq_data *d) { return d->chip_data; }
static const struct regmap_irq *irq_to_regmap_irq(struct regmap_irq_chip_data *d, int irq) { (void)d; return &regirqs[irq]; }
static struct irq_desc *get_desc(int irq) { struct irq_desc *d=&descs[irq]; assert(!d->locked); d->locked=true; return d; }
static struct irq_desc *put_desc(struct irq_desc *d) { if (d) { assert(d->locked); d->locked=false; } return NULL; }
static void cleanup_desc(struct irq_desc **d) { put_desc(*d); }
#define scoped_irqdesc_get_and_buslock(irq, check) \
 for (struct irq_desc *scoped_irqdesc __attribute__((cleanup(cleanup_desc)))=get_desc(irq); scoped_irqdesc; scoped_irqdesc=put_desc(scoped_irqdesc))
int irq_set_irq_wake(unsigned, unsigned);
static int enable_irq_wake(int irq) { return irq_set_irq_wake(irq,1); }
static int disable_irq_wake(int irq) { return irq_set_irq_wake(irq,0); }
static void disable_irq(int irq) { descs[irq].disabled++; }
static void enable_irq(int irq) { assert(descs[irq].disabled>0); descs[irq].disabled--; }
#include "wake_irq_functions.h"
static int parent_wake(struct irq_data *d, unsigned on)
{
 assert(d->irq==10 || d->irq==11);
 assert(descs[d->irq].locked);
 if (on) { on_calls++; if(fail_parent_on) return -EIO; }
 else { off_calls++; if(fail_parent_off) return -EIO; }
 hardware_wake[d->irq]=on; return 0;
}
static int child_wake(struct irq_data *d, unsigned on)
{
 assert(descs[d->irq].locked);
 if(on && fail_child==d->irq) return -EINVAL;
 return regmap_irq_set_wake(d,on);
}
static void reset(void)
{
 memset(descs,0,sizeof(descs)); memset(hardware_wake,0,sizeof(hardware_wake));
 parent_chip=(struct irq_chip){.irq_set_wake=parent_wake};
 child_chip=(struct irq_chip){.irq_set_wake=child_wake};
 regdata=(struct regmap_irq_chip_data){.irq=10,.map=&map};
 for(int i=0;i<16;i++) { descs[i].irq_data.irq=i; descs[i].irq_data.chip=&parent_chip; }
 for(int i=1;i<=6;i++) { descs[i].irq_data.chip=&child_chip; descs[i].irq_data.chip_data=&regdata; descs[i].irq_data.hwirq=i; regirqs[i]=(struct regmap_irq){0,1u<<i}; }
 regdata.wake_parent_atomic=regmap_irq_wake_parent_atomic(&regdata);
 fail_parent_on=fail_parent_off=fail_child=on_calls=off_calls=0;
}
static void clean(void)
{
 for(int i=1;i<16;i++) { assert(!descs[i].wake_depth); assert(!descs[i].disabled); assert(!descs[i].locked); assert(!descs[i].irq_data.flags); assert(!hardware_wake[i]); }
 assert(!regdata.wake_count);
}
static void eligibility(void)
{
 reset(); assert(regdata.wake_parent_atomic);
 parent_chip.irq_bus_lock=bus_callback; assert(!regmap_irq_wake_parent_atomic(&regdata));
 parent_chip.irq_bus_lock=NULL; parent_chip.irq_bus_sync_unlock=bus_callback; assert(!regmap_irq_wake_parent_atomic(&regdata));
 parent_chip.irq_bus_sync_unlock=NULL; unsigned wake=~0u; regdata.wake_buf=&wake; assert(!regmap_irq_wake_parent_atomic(&regdata));
 regdata.wake_parent_atomic=false;
 assert(!enable_irq_wake(1)); assert(regdata.wake_count==1 && !descs[10].wake_depth && !(wake&2));
 assert(!disable_irq_wake(1)); assert(!regdata.wake_count && (wake&2));
 clean();
}
static void pek_cases(void)
{
 for(int policy=0;policy<2;policy++) for(int changed=0;changed<2;changed++) {
  reset(); struct axp20x_pek p={.input=&p,.irq_dbf=1,.irq_dbr=2}; struct device d={&p,policy};
  assert(!axp20x_pek_suspend(&d)); d.wake=changed; assert(!axp20x_pek_resume(&d)); clean();
 }
 reset(); struct axp20x_pek p={.input=&p,.irq_dbf=1,.irq_dbr=2}; struct device d={&p,true};
 fail_parent_on=1; assert(axp20x_pek_suspend(&d)==-EIO); assert(!p.wake_dbf&&!p.wake_dbr); clean();
 fail_parent_on=0; fail_child=2; assert(axp20x_pek_suspend(&d)==-EINVAL); assert(!p.wake_dbf&&!p.wake_dbr); clean();
 fail_parent_off=1; assert(axp20x_pek_suspend(&d)==-EINVAL); assert(p.wake_dbf&&!p.wake_dbr);
 assert(descs[10].wake_depth==1&&descs[1].wake_depth==1); int calls=on_calls;
 assert(axp20x_pek_suspend(&d)==-EIO); assert(on_calls==calls);
 fail_parent_off=fail_child=0; assert(!axp20x_pek_suspend(&d)); assert(descs[10].wake_depth==2);
 fail_parent_off=1; assert(axp20x_pek_resume(&d)==-EIO); assert(p.wake_dbf&&!p.wake_dbr);
 d.wake=false; assert(axp20x_pek_suspend(&d)==-EIO); assert(!descs[1].disabled);
 fail_parent_off=0; assert(!axp20x_pek_suspend(&d)); assert(!axp20x_pek_resume(&d)); clean();
 p.input=NULL; d.wake=true; assert(!axp20x_pek_suspend(&d)); assert(!axp20x_pek_resume(&d)); clean();
}
static void rtc_cases(void)
{
 reset(); struct sun6i_rtc_dev r={.irq=11}; struct device d={&r,true};
 fail_parent_on=1; assert(sun6i_rtc_suspend(&d)==-EIO); assert(!r.wake_armed); clean();
 fail_parent_on=0; assert(!sun6i_rtc_suspend(&d)); assert(r.wake_armed);
 d.wake=false; fail_parent_off=1; assert(sun6i_rtc_resume(&d)==-EIO); assert(r.wake_armed);
 int calls=on_calls; assert(sun6i_rtc_suspend(&d)==-EIO); assert(on_calls==calls);
 fail_parent_off=0; assert(!sun6i_rtc_suspend(&d)); assert(!sun6i_rtc_resume(&d)); clean();
 for(int i=0;i<5;i++) { d.wake=true; assert(!sun6i_rtc_suspend(&d)); d.wake=false; assert(!sun6i_rtc_resume(&d)); clean(); }
}
static void ac_and_shared(void)
{
 for(int policy=0;policy<2;policy++) {
  reset(); struct power_supply ps={.dev={.wake=policy}};
  struct axp20x_ac_power ac={.supply=&ps,.num_irqs=2,.irqs={3,4}}; struct device d={&ac,false};
  assert(!axp20x_ac_power_suspend(&d)); ps.dev.wake=!policy; assert(!axp20x_ac_power_resume(&d)); clean();
 }
 reset(); struct power_supply ps={.dev={.wake=true}};
 struct axp20x_ac_power ac={.supply=&ps,.num_irqs=2,.irqs={3,4}}; struct device d={&ac,false};
 fail_parent_on=1; assert(axp20x_ac_power_suspend(&d)==-EIO); assert(!ac.irqs_disabled); clean();
 fail_parent_on=0; assert(!axp20x_ac_power_suspend(&d)); fail_parent_off=1;
 assert(axp20x_ac_power_resume(&d)==-EIO); assert(ac.wake_armed&&!ac.irqs_disabled); assert(!descs[4].disabled);
 assert(axp20x_ac_power_suspend(&d)==-EIO); fail_parent_off=0;
 assert(!axp20x_ac_power_suspend(&d)); assert(!axp20x_ac_power_resume(&d)); clean();
 for(int i=0;i<10;i++) {
  struct axp20x_pek p={.input=&p,.irq_dbf=1,.irq_dbr=2}; struct device pd={&p,true};
  assert(!axp20x_pek_suspend(&pd)); assert(!axp20x_ac_power_suspend(&d)); assert(!enable_irq_wake(5));
  assert(descs[10].wake_depth==4 && regdata.wake_count==0);
  assert(!axp20x_pek_resume(&pd)); assert(descs[10].wake_depth==2);
  assert(!disable_irq_wake(5)); assert(!axp20x_ac_power_resume(&d)); clean();
 }
}
int main(void) { eligibility(); pek_cases(); rtc_cases(); ac_and_shared(); puts("wake IRQ: eligibility, shared references, policy changes, arm/rollback/disarm failures and repeat cycles passed"); return 0; }
