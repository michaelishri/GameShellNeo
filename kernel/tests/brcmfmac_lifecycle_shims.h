/* SPDX-License-Identifier: ISC */
/* The driver core holds callback device locks; reset runs on a workqueue. */
#define SINGLE_DEPTH_NESTING 1
static _Thread_local struct device *device_locks[2];
static _Thread_local unsigned device_depth;
static struct device *first_dev, *second_dev;
static struct gate reset_gate;
static bool drain_worker, destroy_bus, reset_on_drain;
static pthread_t drain_thread;
static unsigned freed_objects;
static atomic_bool nested_waiting;
static void lifecycle_setup(struct device *f1, struct device *f2)
{
 first_dev = f1; second_dev = f2;
 assert(!pthread_mutex_init(&f1->mutex, NULL));
 assert(!pthread_mutex_init(&f2->mutex, NULL));
 gate_init(&reset_gate);
 drain_worker = destroy_bus = reset_on_drain = false;
 freed_objects = 0;
 nested_waiting = false;
}
static void lifecycle_teardown(struct device *f1, struct device *f2)
{
 assert(!device_depth);
 assert(!pthread_mutex_destroy(&f1->mutex));
 assert(!pthread_mutex_destroy(&f2->mutex));
 gate_destroy(&reset_gate);
}
static void device_lock_assert(struct device *dev)
{
 assert(device_depth && device_locks[device_depth - 1] == dev);
}
static void device_lock(struct device *dev)
{
 assert(!host_claimed && !device_depth);
 assert(!pthread_mutex_lock(&dev->mutex));
 device_locks[device_depth++] = dev;
}
static void mutex_lock_nested(pthread_mutex_t *lock, unsigned subclass)
{
 assert(!host_claimed && subclass == SINGLE_DEPTH_NESTING);
 assert(device_depth == 1 && device_locks[0] == first_dev);
 assert(lock == &second_dev->mutex);
 nested_waiting = true;
 assert(!pthread_mutex_lock(lock));
 device_locks[device_depth++] = second_dev;
}
static bool device_trylock(struct device *dev)
{
 assert(!host_claimed && !device_depth && dev == second_dev);
 int ret = pthread_mutex_trylock(&dev->mutex);
 assert(!ret || ret == EBUSY);
 if (ret) return false;
 device_locks[device_depth++] = dev;
 return true;
}
static void device_unlock(struct device *dev)
{
 device_lock_assert(dev);
 device_depth--;
 assert(!pthread_mutex_unlock(&dev->mutex));
}
static void dev_set_drvdata(struct device *dev, void *data)
{ device_lock_assert(second_dev); dev->data = data; }
