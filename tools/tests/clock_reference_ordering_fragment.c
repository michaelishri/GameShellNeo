/* NEO-221 compile-only comparison, NEVER executed or linked into a kernel.
 * Models the pinned ARM accessor spellings; it is not a kernel interface.
 */
#include <stdint.h>

#if !defined(__arm__) || !defined(__ARM_EABI__) || !defined(__ARM_PCS_VFP)
#error Compile this observation fragment only for ARM EABI hard float
#endif
_Static_assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__, "ARM byte order");
_Static_assert(sizeof(uint64_t) == 8 && sizeof(uint32_t) == 4, "fixed counter widths");
_Static_assert(sizeof(void *) == 4 && sizeof(long) == 4, "ARM word ABI");

struct observation { uint32_t before, after; uint64_t cycles; };

static inline uint64_t architectural(void)
{
	uint64_t value;
	__asm__ __volatile__("isb" : : : "memory");
	__asm__ __volatile__("mrrc p15, 0, %Q0, %R0, c14" : "=r" (value));
	return value;
}

static inline uint32_t relaxed(const volatile uint32_t *address)
{
	uint32_t value;
	__asm__ __volatile__("ldr %0, %1" : "=r" (value) : "Qo" (*address));
	return value;
}

static inline uint32_t ordered(const volatile uint32_t *address)
{
	uint32_t value = relaxed(address);
	__asm__ __volatile__("dsb sy" : : : "memory");
	return value;
}

uint64_t neo_reference_fragment_original(void)
{
	return architectural();
}

void neo_reference_fragment_relaxed(const volatile uint32_t *address, struct observation *out)
{
	uint32_t before = relaxed(address);
	uint64_t cycles = architectural();
	uint32_t after = relaxed(address);
	out->before = before;
	out->after = after;
	out->cycles = cycles;
}

void neo_reference_fragment_readl(const volatile uint32_t *address, struct observation *out)
{
	uint32_t before = ordered(address);
	uint64_t cycles = architectural();
	uint32_t after = ordered(address);
	out->before = before;
	out->after = after;
	out->cycles = cycles;
}
