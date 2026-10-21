/* SPDX-License-Identifier: ISC */
/* Real bounded formatting, tracked allocation and controlled seq-write errors. */
#include <stdarg.h>
struct seq_file {
	char data[CONSOLE_BUFFER_MAX + 512];
	unsigned length, writes, fail_at;
	int error;
};
static struct {
	u8 *buffer;
	unsigned size, allocations, frees;
	bool allocation_failure;
} output_fixture;
static void seq_printf(struct seq_file *seq, const char *format, ...)
{
	assert(seq); va_list args; va_start(args, format);
	int count = vsnprintf(seq->data + seq->length, sizeof(seq->data) - seq->length, format, args);
	va_end(args);
	assert(count >= 0 && (unsigned)count < sizeof(seq->data) - seq->length);
	seq->length += count; hw.seq_lines++;
}
static int seq_write(struct seq_file *seq, const void *data, unsigned size)
{
	assert(seq && output_fixture.buffer);
	uintptr_t base = (uintptr_t)output_fixture.buffer, at = (uintptr_t)data;
	assert(at >= base && at - base <= hw.diagnostic_size);
	assert(size <= hw.diagnostic_size - (at - base));
	assert(seq->length + size < sizeof(seq->data));
	if (++seq->writes == seq->fail_at) return seq->error;
	memcpy(seq->data + seq->length, data, size); seq->length += size;
	hw.seq_bytes += size; return 0;
}
static void *vzalloc(unsigned size)
{
	assert(!output_fixture.buffer && size <= CONSOLE_BUFFER_MAX + 1);
	output_fixture.allocations++;
	if (output_fixture.allocation_failure) return NULL;
	output_fixture.size = size; output_fixture.buffer = calloc(1, size);
	assert(output_fixture.buffer); return output_fixture.buffer;
}
static void vfree(void *buffer)
{
	assert(buffer && buffer == output_fixture.buffer);
	free(buffer); output_fixture.buffer = NULL; output_fixture.frees++;
}
