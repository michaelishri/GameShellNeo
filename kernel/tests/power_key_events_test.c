/* SPDX-License-Identifier: GPL-2.0-only */
/* Locked input-core/PEK functions, deterministic input delivery shims. */
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include "input-event-codes.h"

#define INPUT_IGNORE_EVENT 0
#define INPUT_PASS_TO_HANDLERS 1
#define INPUT_PASS_TO_DEVICE 2
#define INPUT_PASS_TO_ALL 3
#define INPUT_FLUSH 4
#define IRQ_HANDLED 1
typedef int irqreturn_t;
struct device { void *data; };
struct input_dev {
 struct device dev;
 bool inhibited;
 int event_lock, rep[REP_CNT];
 unsigned long evbit[KEY_CNT], keybit[KEY_CNT], key[KEY_CNT];
 unsigned long swbit[KEY_CNT], sw[KEY_CNT], absbit[KEY_CNT], relbit[KEY_CNT];
 unsigned long mscbit[KEY_CNT], ledbit[KEY_CNT], led[KEY_CNT], sndbit[KEY_CNT], snd[KEY_CNT];
 void *data;
};
struct axp20x_pek { int irq_dbf, irq_dbr; };
struct delivered { unsigned type, code; int value; };
static struct delivered delivered[64];
static unsigned count;
static bool test_bit(unsigned bit, const unsigned long *bits) { return bits[bit]; }
static void __change_bit(unsigned bit, unsigned long *bits) { bits[bit] = !bits[bit]; }
static bool is_event_supported(unsigned code, const unsigned long *bits, unsigned max)
{ return code <= max && test_bit(code, bits); }
#define for_each_set_bit(code, bits, size) for ((code)=0;(code)<(size);(code)++) if (test_bit(code,bits))
#define lockdep_assert_held(lock) ((void)(lock))
/* Locking is not simulated as concurrency; this is a single-thread function test. */
#define guard(kind) (void)
static struct input_dev *to_input_dev(struct device *dev) { return dev->data; }
static void *input_get_drvdata(struct input_dev *dev) { return dev->data; }
static void input_dev_toggle(struct input_dev *dev, bool value) { (void)dev; (void)value; }
static int input_handle_abs_event(struct input_dev *dev, unsigned code, int *value)
{ (void)dev; (void)code; (void)value; assert(!"ABS outside this PEK test"); return 0; }
static int input_get_disposition(struct input_dev *, unsigned, unsigned, int *);
static void input_handle_event(struct input_dev *dev, unsigned type, unsigned code, int value)
{
 int disposition = input_get_disposition(dev, type, code, &value);
 if (disposition & INPUT_PASS_TO_HANDLERS) {
  assert(count < sizeof(delivered)/sizeof(delivered[0]));
  delivered[count++] = (struct delivered){type, code, value};
 }
}
static void input_report_key(struct input_dev *dev, unsigned code, int value)
{ input_handle_event(dev, EV_KEY, code, value); }
static void input_sync(struct input_dev *dev) { input_handle_event(dev, EV_SYN, SYN_REPORT, 0); }
#include "power_key_event_functions.h"

static struct input_dev dev;
static struct axp20x_pek pek = {90, 91};
static void reset(void)
{
 memset(&dev, 0, sizeof(dev)); memset(delivered, 0, sizeof(delivered)); count=0;
 dev.dev.data=&dev; dev.data=&pek; dev.evbit[EV_KEY]=1; dev.keybit[KEY_POWER]=1;
}
static unsigned key_count(void)
{
 unsigned total=0;
 for (unsigned i=0;i<count;i++) if (delivered[i].type==EV_KEY) total++;
 return total;
}
static void edge(bool down)
{ assert(axp20x_pek_irq(down ? pek.irq_dbf : pek.irq_dbr, &dev)==IRQ_HANDLED); }

int main(void)
{
 /* Ordinary physical press/release pair. */
 reset(); edge(true); assert(dev.key[KEY_POWER]); edge(false);
 assert(!dev.key[KEY_POWER] && key_count()==2);
 assert(delivered[0].value==1 && delivered[2].value==0);
 /* A held key is logically cleared at input-device suspend. */
 reset(); edge(true); assert(input_dev_suspend(&dev.dev)==0);
 assert(!dev.key[KEY_POWER] && key_count()==2);
 assert(delivered[2].type==EV_KEY && delivered[2].value==0);
 assert(delivered[3].type==EV_SYN && delivered[3].value==1);
 assert(input_dev_resume(&dev.dev)==0 && key_count()==2);
 /* Actual release after resume adds no KEY_POWER edge: duplicate filtering. */
 edge(false); assert(key_count()==2 && !dev.key[KEY_POWER]);
 edge(true); edge(false); assert(key_count()==4 && !dev.key[KEY_POWER]);
 /* Physical release inside the suspend interval is filtered too. */
 reset(); edge(true); assert(input_dev_suspend(&dev.dev)==0);
 edge(false); assert(key_count()==2);
 assert(input_dev_resume(&dev.dev)==0 && key_count()==2);
 /* Releasing before entry is not evidence of a synthetic clear. */
 reset(); edge(true); edge(false); unsigned old=count;
 assert(input_dev_suspend(&dev.dev)==0 && count==old);
 /* A fresh wake press following an untouched suspend still reports both edges. */
 reset(); assert(input_dev_suspend(&dev.dev)==0 && !count);
 edge(true); assert(input_dev_resume(&dev.dev)==0 && dev.key[KEY_POWER]);
 edge(false); assert(key_count()==2 && !dev.key[KEY_POWER]);
 puts("PEK/input-core: six event scenarios passed; synthetic clear is not physical release");
 return 0;
}
