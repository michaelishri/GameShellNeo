/* SPDX-License-Identifier: GPL-2.0-only */
/* Real map/unmap/queue/resume functions; modeled DMA API and hardware start. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define GFP_ATOMIC 0
#define DMA_ADDR_INVALID UINTPTR_MAX
#define DMA_TO_DEVICE 1
#define DMA_FROM_DEVICE 2
#define WARN_ON(x) (x)
#define EXPORT_SYMBOL_GPL(x)
#define dev_err(...) ((void)0)
#define dev_vdbg(...) ((void)0)
#define musb_dbg(...) ((void)0)
#define trace_musb_req_enq(x) ((void)0)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
typedef int gfp_t;
typedef uintptr_t dma_addr_t;
struct list_head { struct list_head *next, *prev; };
static void init(struct list_head *h) { h->next=h->prev=h; }
static bool list_empty(struct list_head *h) { return h->next==h; }
static void list_add_tail(struct list_head *n,struct list_head *h)
{ n->prev=h->prev; n->next=h; h->prev->next=n; h->prev=n; }
static void list_del(struct list_head *n)
{ n->prev->next=n->next; n->next->prev=n->prev; }
typedef bool spinlock_t;
static void take(spinlock_t *p) { assert(!*p); *p=true; }
static void drop(spinlock_t *p) { assert(*p); *p=false; }
#define spin_lock_irqsave(p,f) do { (f)=0; take(p); } while(0)
#define spin_unlock_irqrestore(p,f) do { (void)(f); drop(p); } while(0)
struct device { int refs; };
struct usb_ep { const char *name; };
struct usb_request { void *buf; unsigned length,actual; int status; dma_addr_t dma; };
struct dma_channel { int placeholder; };
struct dma_controller { int (*is_compatible)(struct dma_channel *,unsigned,void *,unsigned); };
struct musb;
struct musb_ep {
 struct usb_ep end_point; struct musb *musb; struct list_head req_list;
 void *desc; struct dma_channel *dma; unsigned packet_sz,current_epnum,is_in,busy;
 bool restart_pending,restart_deferred,restart_again;
};
enum buffer_map_state { UN_MAPPED=0, PRE_MAPPED, MUSB_MAPPED };
struct musb_request {
 struct usb_request request; struct list_head list; struct musb_ep *ep;
 struct musb *musb; unsigned tx,epnum; enum buffer_map_state map_state;
};
struct musb_pending_work {
 int (*callback)(struct musb *,void *); void *data; struct list_head node;
};
struct musb {
 struct device *controller; struct dma_controller *dma_controller;
 spinlock_t lock,list_lock; bool is_runtime_suspended; struct list_head pending_list;
};
#define to_musb_ep(p) container_of(p,struct musb_ep,end_point)
#define to_musb_request(p) container_of(p,struct musb_request,request)
static struct device dev;
static struct musb musb;
static struct musb_ep ep;
static struct dma_channel channel;
static struct dma_controller dma;
static bool capable,compatible,map_fails,alloc_fails,free_on_start;
static int pm_error;
static unsigned maps,unmaps,sync_dev,sync_cpu,starts,works,cases;
static unsigned direction;
static bool is_dma_capable(void) { return capable; }
static int compatibility(struct dma_channel *c,unsigned size,void *buf,unsigned len)
{ assert(c==&channel && size==64 && buf && len==32); return compatible; }
static void check_dma(struct device *d,dma_addr_t addr,unsigned len,int dir)
{ assert(d==&dev && (addr==0x1000 || addr==0x2000) && len==32 && (unsigned)dir==direction); }
static dma_addr_t dma_map_single(struct device *d,void *buf,unsigned len,int dir)
{ assert(buf); check_dma(d,0x1000,len,dir); maps++; return map_fails ? DMA_ADDR_INVALID:0x1000; }
static bool dma_mapping_error(struct device *d,dma_addr_t addr)
{ assert(d==&dev); return addr==DMA_ADDR_INVALID; }
static void dma_unmap_single(struct device *d,dma_addr_t addr,unsigned len,int dir)
{ check_dma(d,addr,len,dir); assert(addr==0x1000); unmaps++; }
static void dma_sync_single_for_device(struct device *d,dma_addr_t addr,unsigned len,int dir)
{ check_dma(d,addr,len,dir); assert(addr==0x2000); sync_dev++; }
static void __attribute__((unused)) dma_sync_single_for_cpu(struct device *d,dma_addr_t addr,unsigned len,int dir)
{ check_dma(d,addr,len,dir); assert(addr==0x2000); sync_cpu++; }
static int pm_runtime_get(struct device *d) { assert(d==&dev); d->refs++; return pm_error; }
static void pm_runtime_put_noidle(struct device *d) { assert(d==&dev && d->refs>0); d->refs--; }
static void pm_runtime_put_autosuspend(struct device *d) { pm_runtime_put_noidle(d); }
static void pm_runtime_mark_last_busy(struct device *d) { assert(d==&dev); }
static void pm_runtime_get_noresume(struct device *d) { assert(d==&dev); d->refs++; }
static void *devm_kzalloc(struct device *d,size_t size,gfp_t flags)
{ (void)flags; assert(d==&dev && musb.lock && musb.list_lock); if(alloc_fails)return NULL;
  void *p=calloc(1,size); assert(p); works++; return p; }
static struct musb_request *next_request(struct musb_ep *p)
{ return list_empty(&p->req_list)?NULL:container_of(p->req_list.next,struct musb_request,list); }
static inline void unmap_dma_buffer(struct musb_request *,struct musb *);
static void musb_ep_restart(struct musb *m,struct musb_request *r)
{ assert(m==&musb && musb.lock && r==next_request(&ep)); starts++;
  /* Defensive lifetime test only: gadget API forbids queue-time completion. */
  if(free_on_start) { list_del(&r->list); unmap_dma_buffer(r,m); free(r); } }

#include "musb_queue_dma_functions.h"

static struct musb_request *setup(unsigned tx,unsigned mode)
{
 assert(!works && !dev.refs);
 memset(&musb,0,sizeof(musb)); memset(&ep,0,sizeof(ep));
 maps=unmaps=sync_dev=sync_cpu=starts=0; capable=compatible=true;
 map_fails=alloc_fails=free_on_start=false; pm_error=-EINPROGRESS;
 direction=tx?DMA_TO_DEVICE:DMA_FROM_DEVICE;
 dma.is_compatible=compatibility; musb.controller=&dev; musb.dma_controller=&dma;
 musb.is_runtime_suspended=true; init(&musb.pending_list);
 ep.musb=&musb; ep.desc=&ep; ep.dma=&channel; ep.packet_sz=64; ep.is_in=tx;
 ep.current_epnum=1; init(&ep.req_list);
 struct musb_request *r=calloc(1,sizeof(*r)); assert(r);
 r->ep=&ep; r->request.buf=r; r->request.length=32;
 r->request.dma=mode==1?0x2000:DMA_ADDR_INVALID;
 if(mode==2)capable=false;
 if(mode==3)ep.dma=NULL;
 if(mode==4)compatible=false;
 if(mode==5)map_fails=true;
 if(mode==6)dma.is_compatible=NULL;
 return r;
}
static int enqueue(struct musb_request *r) { return musb_gadget_queue(&ep.end_point,&r->request,0); }
static void resume(void)
{
 assert(works==1); take(&musb.lock); musb.is_runtime_suspended=false;
 struct musb_pending_work *w=container_of(musb.pending_list.next,struct musb_pending_work,node);
 list_del(&w->node); assert(!w->callback(&musb,w->data)); free(w); works--; drop(&musb.lock);
}
static void returned(struct musb_request *r,unsigned mode)
{
 assert(!dev.refs && !works && !musb.lock && !musb.list_lock);
 assert(list_empty(&ep.req_list) && !ep.restart_pending && r->map_state==UN_MAPPED);
 assert(r->request.dma==(mode==1?0x2000:DMA_ADDR_INVALID));
 assert(!starts);
 if(mode==0 || mode==6)assert(maps==1 && unmaps==1 && !sync_cpu && !sync_dev);
 else if(mode==1)assert(!maps && !unmaps && sync_cpu==1 && sync_dev==1);
 else assert(!unmaps && !sync_cpu && !sync_dev && maps==(mode==5));
}
static void finish(struct musb_request *r)
{ assert(!works && !dev.refs); if(!list_empty(&ep.req_list))list_del(&r->list);
  unmap_dma_buffer(r,&musb); free(r); cases++; }
int main(void)
{
 for(unsigned tx=0;tx<2;tx++) {
  for(unsigned mode=0;mode<7;mode++) {
   struct musb_request *r=setup(tx,mode); alloc_fails=true;
   assert(enqueue(r)==-ENOMEM); returned(r,mode);
   /* Same request retry must map anew, or resync caller-owned memory. */
   alloc_fails=false; assert(!enqueue(r)); assert(works==1 && !starts);
   resume(); assert(starts==1 && !ep.restart_pending);
   if(mode==0 || mode==6)assert(maps==2 && !sync_dev && unmaps==1);
   if(mode==1)assert(sync_dev==2 && sync_cpu==1 && !maps);
   finish(r);
   if(mode==0 || mode==6)assert(maps==unmaps);
   if(mode==1)assert(sync_dev==sync_cpu);

   r=setup(tx,mode); assert(!enqueue(r)); assert(!unmaps && !sync_cpu);
   resume(); assert(starts==1); finish(r);

   r=setup(tx,mode); musb.is_runtime_suspended=false; pm_error=0;
   assert(!enqueue(r)); assert(starts==1 && !works && !unmaps && !sync_cpu); finish(r);

   r=setup(tx,mode); ep.desc=NULL;
   assert(enqueue(r)==-ESHUTDOWN); returned(r,mode); finish(r);

   r=setup(tx,mode); pm_error=-EIO;
   assert(enqueue(r)==-EIO); assert(!maps && !unmaps && !sync_dev && !sync_cpu); finish(r);
  }
  for(unsigned mode=0;mode<2;mode++) {
   struct musb_request *r=setup(tx,mode); musb.is_runtime_suspended=false;
   pm_error=0; free_on_start=true;
   assert(!enqueue(r)); assert(starts==1 && !works && !dev.refs && list_empty(&ep.req_list));
   if(mode==0)assert(maps==1 && unmaps==1);
   else assert(sync_dev==1 && sync_cpu==1);
   cases++;
  }
 }
 assert(cases==74);
 printf("MUSB queue DMA: %u source scenarios passed\n",cases);
 return 0;
}
