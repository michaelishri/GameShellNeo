/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual queue/dequeue/giveback/resume paths, with controlled PM/MMIO boundaries. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define __releases(x)
#define __acquires(x)
#define EXPORT_SYMBOL_GPL(x)
#define GFP_ATOMIC 0
#define DMA_ADDR_INVALID (-1)
#define WARN_ON(x) (x)
#define dev_err(...) ((void)0)
#define musb_dbg(...) ((void)0)
#define trace_musb_req_enq(x) ((void)(x))
#define trace_musb_req_deq(x) ((void)(x))
#define trace_musb_req_gb(x) ((void)(x))
#define trace_musb_req_free(x) ((void)(x))
#define container_of(p, type, member) ((type *)((char *)(p) - offsetof(type, member)))
typedef int gfp_t;
struct list_head { struct list_head *next, *prev; };
static void INIT_LIST_HEAD(struct list_head *h) { h->next = h->prev = h; }
static bool list_empty(const struct list_head *h) { return h->next == h; }
static void list_add_tail(struct list_head *n, struct list_head *h)
{ n->prev = h->prev; n->next = h; h->prev->next = n; h->prev = n; }
static void list_del(struct list_head *n)
{ n->prev->next = n->next; n->next->prev = n->prev; }
#define list_entry(p, type, member) container_of(p, type, member)
#define list_first_entry(h, type, member) list_entry((h)->next, type, member)
#define list_for_each_entry(p, h, member) \
 for ((p) = list_entry((h)->next, typeof(*(p)), member); &(p)->member != (h); \
      (p) = list_entry((p)->member.next, typeof(*(p)), member))
#define list_for_each_entry_safe(p, n, h, member) \
 for ((p) = list_entry((h)->next, typeof(*(p)), member), \
      (n) = list_entry((p)->member.next, typeof(*(p)), member); &(p)->member != (h); \
      (p) = (n), (n) = list_entry((n)->member.next, typeof(*(n)), member))
#define list_first_entry_or_null(h, type, member) \
 (list_empty(h) ? NULL : list_entry((h)->next, type, member))
typedef bool spinlock_t;
static void spin_lock(spinlock_t *p) { assert(!*p); *p = true; }
static void spin_unlock(spinlock_t *p) { assert(*p); *p = false; }
#define lockdep_assert_held(p) assert(*(p))
#define wake_up_all(p) ((void)(p))
#define spin_lock_irqsave(p, f) do { (f) = 0; spin_lock(p); } while (0)
#define spin_unlock_irqrestore(p, f) do { (void)(f); spin_unlock(p); } while (0)

struct device { int refs; };
struct usb_ep { const char *name; };
struct usb_request { void *buf; int actual, status, dma; };
struct musb;
struct musb_pending_work {
 int (*callback)(struct musb *musb, void *data);
 void *data;
 struct list_head node;
};
struct musb_ep {
 struct usb_ep end_point;
 struct musb *musb;
 struct list_head req_list;
 const void *desc;
 void *dma;
 unsigned busy, current_epnum, is_in;
 bool restart_pending, restart_deferred, restart_again;
};
struct musb_request {
 struct usb_request request;
 struct list_head list;
 struct musb_ep *ep;
 struct musb *musb;
 unsigned epnum, tx;
 bool mapped;
};
struct dma_controller { int (*channel_abort)(void *); };
struct musb {
 struct device *controller;
 struct { struct device dev; } g;
 spinlock_t lock, list_lock;
 struct list_head pending_list;
 bool is_runtime_suspended, resume_work_stopping;
 unsigned resume_work_count, resume_work_wait;
 struct dma_controller *dma_controller;
 void *mregs;
};
#define to_musb_ep(p) container_of(p, struct musb_ep, end_point)
#define to_musb_request(p) container_of(p, struct musb_request, request)

__attribute__((unused))
static struct musb_request *next_request(struct musb_ep *ep)
{
 if (list_empty(&ep->req_list))
  return NULL;
 return list_entry(ep->req_list.next, struct musb_request, list);
}

static struct musb instance;
static struct device controller;
static struct musb_ep endpoints[2];
struct allocation { struct musb_request *request; bool alive; unsigned starts; };
static struct allocation allocations[16];
static unsigned allocated, completed, freed, stale, detached, started, pending_allocs;
static unsigned scenarios, mappings, unmaps;
static int pm_result;
static bool fail_work_alloc, free_on_complete, requeue_on_complete, resume_on_complete;
static unsigned companion_calls, reentrant_count;
static unsigned complete_on_restart;
static struct musb_request *completion_target;

static struct allocation *allocation(struct musb_request *r)
{
 for (unsigned i = 0; i < allocated; i++)
  if (allocations[i].request == r)
   return &allocations[i];
 assert(!"Unknown request");
 return NULL;
}
static void *devm_kzalloc(struct device *dev, size_t size, gfp_t flags)
{
 (void)flags;
 assert(dev == &controller && instance.lock && instance.list_lock);
 if (fail_work_alloc)
  return NULL;
 void *p = calloc(1, size);
 assert(p); pending_allocs++;
 return p;
}
static void devm_kfree(struct device *dev, void *p)
{ assert(dev == &controller && pending_allocs); pending_allocs--; free(p); }
static void kfree(void *p)
{
 struct allocation *a = allocation(p);
 assert(a->alive); a->alive = false; freed++;
#ifdef REAL_FREE
 free(p);
#endif
}
static int pm_runtime_get(struct device *dev)
{ assert(dev == &controller); dev->refs++; return pm_result; }
static void pm_runtime_put_noidle(struct device *dev)
{ assert(dev == &controller && dev->refs > 0); dev->refs--; }
static void pm_runtime_put_autosuspend(struct device *dev) { pm_runtime_put_noidle(dev); }
static void __attribute__((unused)) pm_runtime_get_noresume(struct device *dev)
{ assert(dev == &controller && instance.lock); dev->refs++; }
static void pm_runtime_mark_last_busy(struct device *dev) { assert(dev == &controller); }
static void map_dma_buffer(struct musb_request *r, struct musb *m, struct musb_ep *ep)
{ assert(m == &instance && r->ep == ep && !r->mapped); r->mapped = true; mappings++; }
static void unmap_dma_buffer(struct musb_request *r, struct musb *m)
{ assert(m == &instance); if (r->mapped) { r->mapped = false; unmaps++; } }
static bool dma_mapping_error(struct device *dev, int dma)
{ assert(dev == &instance.g.dev); return dma == DMA_ADDR_INVALID; }
static bool is_dma_capable(void) { return false; }
static void musb_ep_select(void *p, unsigned n)
{ (void)p; (void)n; assert(!"PIO audit must not enter DMA abort"); }
static int musb_gadget_queue(struct usb_ep *, struct usb_request *, gfp_t);
static int musb_run_resume_work(struct musb *);
void musb_free_request(struct usb_ep *, struct usb_request *);
void musb_g_giveback(struct musb_ep *, struct usb_request *, int);

static void usb_gadget_giveback_request(struct usb_ep *ep, struct usb_request *req)
{
 struct musb_request *r = to_musb_request(req);
 assert(!instance.lock && r->ep == to_musb_ep(ep)); completed++;
 if (free_on_complete)
  musb_free_request(ep, req);
 if (resume_on_complete) {
  spin_lock(&instance.lock);
  assert(!musb_run_resume_work(&instance));
  instance.is_runtime_suspended = false;
  spin_unlock(&instance.lock);
 }
 if (requeue_on_complete)
  assert(!musb_gadget_queue(ep, req, 0));
 if (completion_target) {
  struct musb_request *target = completion_target;
  completion_target = NULL;
  assert(!musb_gadget_queue(&target->ep->end_point, &target->request, 0));
 }
}
static void musb_ep_restart(struct musb *m, struct musb_request *r)
{
 assert(m == &instance && m->lock);
 assert(!r->ep->busy);
#ifdef REAL_FREE
 /* The production restart first dereferences req->ep to find hardware regs. */
 volatile struct musb_ep *ep = r->ep;
 assert(ep);
#endif
 struct allocation *a = allocation(r);
 if (!a->alive) { stale++; return; }
 if (r->ep->req_list.next != &r->list) { detached++; return; }
 a->starts++; started++;
 if (complete_on_restart) {
  complete_on_restart--;
  musb_g_giveback(r->ep, &r->request, 0);
 }
}

#include "musb_request_resume_functions.h"

static struct musb_request *new_request(unsigned ep)
{
 assert(allocated < 16 && ep < 2);
 struct musb_request *r = calloc(1, sizeof(*r));
 assert(r);
 r->ep = &endpoints[ep]; r->request.buf = r; r->request.dma = 0;
 allocations[allocated++] = (struct allocation){ .request = r, .alive = true };
 return r;
}
static void setup(bool suspended, unsigned tx)
{
 assert(!pending_allocs);
 memset(&instance, 0, sizeof(instance)); memset(&controller, 0, sizeof(controller));
 memset(allocations, 0, sizeof(allocations)); memset(endpoints, 0, sizeof(endpoints));
 allocated = completed = freed = stale = detached = started = mappings = unmaps = 0;
 companion_calls = 0; reentrant_count = 0;
 fail_work_alloc = free_on_complete = requeue_on_complete = false;
 resume_on_complete = false; pm_result = suspended ? -EINPROGRESS : 0;
 complete_on_restart = 0; completion_target = NULL;
 instance.controller = &controller; instance.is_runtime_suspended = suspended;
 INIT_LIST_HEAD(&instance.pending_list);
 for (unsigned i = 0; i < 2; i++) {
  endpoints[i].musb = &instance; endpoints[i].desc = &instance;
  endpoints[i].end_point.name = "audit"; endpoints[i].current_epnum = i + 1;
  endpoints[i].is_in = tx; INIT_LIST_HEAD(&endpoints[i].req_list);
 }
}
static void enqueue(struct musb_request *r)
{ assert(!musb_gadget_queue(&r->ep->end_point, &r->request, 0)); assert(!controller.refs); }
static void cancel(struct musb_request *r)
{ assert(!musb_gadget_dequeue(&r->ep->end_point, &r->request)); assert(!controller.refs); }
static void resume_work(void)
{
 spin_lock(&instance.lock); assert(!musb_run_resume_work(&instance));
 instance.is_runtime_suspended = false; spin_unlock(&instance.lock);
 assert(!pending_allocs && list_empty(&instance.pending_list));
}
static void finish(void)
{
 assert(!instance.lock && !instance.list_lock && !controller.refs && !pending_allocs);
 assert(!endpoints[0].restart_deferred && !endpoints[1].restart_deferred);
 assert(!instance.resume_work_count);
 for (unsigned i = 0; i < allocated; i++) {
#ifdef REAL_FREE
  if (allocations[i].alive)
#endif
   free(allocations[i].request);
 }
 scenarios++;
}
static int companion_callback(struct musb *m, void *data)
{ assert(m == &instance && m->lock && data == &companion_calls); companion_calls++; return 0; }

static int error_callback(struct musb *m, void *data)
{ assert(m == &instance && m->lock); companion_calls++; return *(int *)data; }

static int companion_reentrant(struct musb *m, void *data)
{
 assert(m == &instance && m->lock && data == &reentrant_count);
 if (reentrant_count == 0) {
  reentrant_count++;
  /* Queuing further resume work from a callback must not deadlock. */
  assert(!musb_queue_resume_work(m, companion_callback, &companion_calls));
 }
 return 0;
}

/* Queue, complete and free a request before runtime resume: the deferred
 * restart must not touch the freed request and must not start anything. */
static void cancel_free(unsigned tx)
{
 setup(true, tx);
 struct musb_request *r = new_request(0);
 enqueue(r); assert(pending_allocs == 1 && !started);
 free_on_complete = true; cancel(r);
 assert(completed == 1 && freed == 1 && pending_allocs == 1);
 resume_work(); assert(!stale && !started && !detached && mappings == unmaps);
 finish();
}
int main(void)
{
 for (unsigned tx = 0; tx < 2; tx++) {
  struct musb_request *a, *b;
  for (unsigned suspended = 0; suspended < 2; suspended++) {
   setup(suspended, tx); a = new_request(0); enqueue(a); resume_work();
   assert(started == 1 && !stale && !detached); cancel(a); finish();
  }
  cancel_free(tx);
  /* Terminal rejection must cover active, suspended and coalesced queues,
   * including the mapping performed before the controller lock is taken. */
  for (unsigned suspended = 0; suspended < 2; suspended++) {
   setup(suspended, tx); a = new_request(0);
   instance.resume_work_stopping = true;
   endpoints[0].restart_pending = true;
   assert(musb_gadget_queue(&a->ep->end_point, &a->request, 0) == -ESHUTDOWN);
   spin_lock(&instance.lock);
   assert(musb_queue_resume_work(&instance, companion_callback, &companion_calls) == -ESHUTDOWN);
   spin_unlock(&instance.lock);
   assert(!started && !companion_calls && !pending_allocs && mappings == unmaps);
   assert(list_empty(&endpoints[0].req_list) && !instance.resume_work_count);
   endpoints[0].restart_pending = false;
   finish();
  }


  /* Direct restart after resume: the coalescing flag must be cleared. */
  setup(true, tx); a = new_request(0); enqueue(a); resume_work();
  assert(started == 1 && !endpoints[0].restart_pending);
  cancel(a); assert(completed == 1);
  b = new_request(0); enqueue(b);
  assert(started == 2 && allocation(b)->starts == 1 && !stale && !detached);
  cancel(b); finish();

  /* Dequeued but not freed: the deferred restart must not start it. */
  setup(true, tx); a = new_request(0); enqueue(a); cancel(a); resume_work();
  assert(!stale && !detached && !started); finish();

  /* A stale head must not block the request that follows it. */
  setup(true, tx); a = new_request(0); b = new_request(0); enqueue(a); enqueue(b);
  free_on_complete = true; cancel(a); resume_work();
  assert(!stale && started == 1 && allocation(b)->starts == 1); finish();

  setup(true, tx); a = new_request(0); b = new_request(0); enqueue(a); enqueue(b);
  free_on_complete = true; cancel(b); resume_work();
  assert(!stale && started == 1 && allocation(a)->starts == 1); finish();

  /* Cross-endpoint: cancelling one ep must not disturb the other. */
  setup(true, tx); a = new_request(0); b = new_request(1); enqueue(a); enqueue(b);
  free_on_complete = true; cancel(a); resume_work();
  assert(!stale && !detached && started == 1 && allocation(b)->starts == 1);
  finish();

  /* Re-queue from the caller after dequeue: one deferred restart. */
  setup(true, tx); a = new_request(0); enqueue(a); cancel(a); enqueue(a); resume_work();
  assert(!stale && !detached && started == 1 && allocation(a)->starts == 1); finish();

  /* Re-queue from the completion callback: still one deferred restart. */
  setup(true, tx); a = new_request(0); enqueue(a);
  requeue_on_complete = true; cancel(a); requeue_on_complete = false; resume_work();
  assert(!stale && started == 1 && pending_allocs == 0); finish();

  /* Completion callback runs resume work itself: no stale restart. */
  setup(true, tx); a = new_request(0); enqueue(a);
  free_on_complete = resume_on_complete = true; cancel(a);
  assert(!stale && completed == 1 && !started); finish();

  /* Endpoint disabled while suspended: nothing to restart. */
  setup(true, tx); a = new_request(0); b = new_request(0); enqueue(a); enqueue(b);
  free_on_complete = true;
  spin_lock(&instance.lock); endpoints[0].busy = 1;
  while (!list_empty(&endpoints[0].req_list)) {
   struct musb_request *r = list_first_entry(&endpoints[0].req_list, struct musb_request, list);
   musb_g_giveback(&endpoints[0], &r->request, -ESHUTDOWN);
  }
  endpoints[0].desc = NULL; spin_unlock(&instance.lock); resume_work();
  assert(!stale && completed == 2 && freed == 2); finish();

  /* Restart ownership is per endpoint; other queued work still runs. */
  setup(true, tx); a = new_request(0); enqueue(a); free_on_complete = true; cancel(a);
  spin_lock(&instance.lock);
  assert(!musb_queue_resume_work(&instance, companion_callback, &companion_calls));
  spin_unlock(&instance.lock); resume_work();
  assert(!stale && !started && companion_calls == 1); finish();

  /* Callbacks may queue further resume work without self-deadlock. */
  setup(true, tx);
  spin_lock(&instance.lock);
  assert(!musb_queue_resume_work(&instance, companion_reentrant, &reentrant_count));
  assert(!musb_run_resume_work(&instance));
  instance.is_runtime_suspended = false;
  spin_unlock(&instance.lock);
  assert(reentrant_count == 1 && companion_calls == 1 && list_empty(&instance.pending_list));
  finish();

  /* Failed work allocation must not strand the flag or the mapping. */
  setup(true, tx); a = new_request(0); fail_work_alloc = true;
  assert(musb_gadget_queue(&a->ep->end_point, &a->request, 0) == -ENOMEM);
  assert(list_empty(&a->ep->req_list) && !pending_allocs && mappings == 1 && !unmaps);
  assert(!endpoints[0].restart_pending);
  /* The failed queue leaves its mapping (tracked separately); a later
   * enqueue must still be able to defer its restart. */
  fail_work_alloc = false; b = new_request(0); enqueue(b); resume_work();
  assert(started == 1 && allocation(b)->starts == 1); cancel(b); finish();

  setup(true, tx); a = new_request(0); endpoints[0].desc = NULL;
  assert(musb_gadget_queue(&a->ep->end_point, &a->request, 0) == -ESHUTDOWN);
  assert(!pending_allocs && mappings == unmaps); finish();

  setup(true, tx); a = new_request(0); pm_result = -EIO;
  assert(musb_gadget_queue(&a->ep->end_point, &a->request, 0) == -EIO);
  assert(!mappings && !pending_allocs); finish();

  /* Resume inside non-head giveback: the surviving head must progress. */
  setup(true, tx); a = new_request(0); b = new_request(0); enqueue(a); enqueue(b);
  resume_on_complete = true; cancel(b); resume_on_complete = false;
  assert(started == 1 && allocation(a)->starts == 1 && !pending_allocs);
  assert(!endpoints[0].restart_pending && !controller.refs); finish();

  /* Resume with an empty queue, then requeue from that completion. */
  setup(true, tx); a = new_request(0); enqueue(a);
  resume_on_complete = requeue_on_complete = true; cancel(a);
  resume_on_complete = requeue_on_complete = false;
  assert(started == 1 && !pending_allocs && !endpoints[0].restart_pending); finish();

  /* Completion inside the restart can requeue the same endpoint. */
  setup(true, tx); a = new_request(0); enqueue(a);
  complete_on_restart = 1; requeue_on_complete = true; resume_work();
  requeue_on_complete = false;
  assert(started == 2 && completed == 1 && allocation(a)->starts == 2); finish();

  /* Completion inside restart can queue a different endpoint. */
  setup(true, tx); a = new_request(0); b = new_request(1); enqueue(a);
  complete_on_restart = 1; completion_target = b; resume_work();
  assert(started == 2 && completed == 1 && allocation(b)->starts == 1); finish();

  /* A completed head hands progress to the already queued follower. */
  setup(true, tx); a = new_request(0); b = new_request(0); enqueue(a); enqueue(b);
  complete_on_restart = 1; free_on_complete = true; resume_work();
  assert(started == 2 && freed == 1 && allocation(b)->starts == 1); finish();

  /* Stop retires a giveback-owned restart and its PM reference. */
  setup(true, tx); a = new_request(0); enqueue(a); endpoints[0].busy = 1;
  resume_work(); assert(!started && endpoints[0].restart_deferred && controller.refs == 1);
  spin_lock(&instance.lock); musb_g_giveback(&endpoints[0], &a->request, -ESHUTDOWN);
  musb_ep_finish_restart(&endpoints[0], false); spin_unlock(&instance.lock);
  assert(!endpoints[0].restart_pending && !controller.refs); finish();

  /* First error survives a later error and successful companion work. */
  setup(true, tx);
  int first = -EIO, second = -EINVAL;
  spin_lock(&instance.lock);
  assert(!musb_queue_resume_work(&instance, error_callback, &first));
  assert(!musb_queue_resume_work(&instance, error_callback, &second));
  assert(!musb_queue_resume_work(&instance, companion_callback, &companion_calls));
  assert(musb_run_resume_work(&instance) == first);
  spin_unlock(&instance.lock);
  assert(companion_calls == 3 && !pending_allocs); finish();
 }
 printf("MUSB deferred-request audit: %u source scenarios pass (%u per direction)\n", scenarios, scenarios / 2);
 return 0;
}
