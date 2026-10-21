/* SPDX-License-Identifier: ISC */
/* Diagnostic output with actual RAM/diagnostic functions and bounded sinks. */
#include "brcmfmac_shared_test.c"
#undef main

static struct sdpcm_shared output_begin(void)
{
	shared_begin(false); memset(&output_fixture, 0, sizeof(output_fixture));
	hw.bounds = true; hw.diagnostic_size = 16; hw.diagnostic_index = 2;
	memcpy(hw.diagnostic_file, "file.c", 7); memcpy(hw.diagnostic_expression, "value", 6);
	return (struct sdpcm_shared){.flags = SDPCM_SHARED_ASSERT_BUILT | SDPCM_SHARED_ASSERT,
		.assert_file_addr = 0x6100, .assert_exp_addr = 0x6200, .assert_line = 23, .console_addr = 0x2000};
}
static void output_end(void)
{
	assert(!output_fixture.buffer);
	assert(output_fixture.frees == output_fixture.allocations - output_fixture.allocation_failure);
	shared_end(false);
}
static void healthy(void)
{
	assert(!f.dev.io_error && !hw.quiesces && !hw.responses && !hw.controls);
	assert(f.dev.state == BRCMF_SDIOD_DATA && f.bus.wd_active && f.bus.ctrl_frame_stat);
}
struct console_case { u32 size, index; };
static const struct console_case valid_consoles[] = {
	{0, 0}, {1, 0}, {1, 1}, {16, 0}, {16, 1}, {16, 8}, {16, 15}, {16, 16},
	{CONSOLE_BUFFER_MAX, 0}, {CONSOLE_BUFFER_MAX, 1},
	{CONSOLE_BUFFER_MAX, CONSOLE_BUFFER_MAX - 1}, {CONSOLE_BUFFER_MAX, CONSOLE_BUFFER_MAX}
};
static const struct console_case invalid_consoles[] = {
	{0, 1}, {0, UINT32_MAX}, {16, 17}, {16, UINT32_MAX},
	{CONSOLE_BUFFER_MAX + 1, 0}, {CONSOLE_BUFFER_MAX + 1, 1},
	{UINT32_MAX, 0}, {UINT32_MAX, UINT32_MAX}, {CONSOLE_BUFFER_MAX, CONSOLE_BUFFER_MAX + 1}
};
static void console_metadata(unsigned index, bool valid)
{
	assert(index < (valid ? 12u : 9u)); struct sdpcm_shared sh = output_begin();
	struct console_case example = valid ? valid_consoles[index] : invalid_consoles[index];
	hw.diagnostic_size = example.size; hw.diagnostic_index = example.index;
	struct seq_file seq = {0};
	assert(brcmf_sdio_dump_console(&seq, &f.bus, &sh) == (valid ? 0 : -EINVAL));
	if (valid && example.size) {
		/* Preserve the existing split: tail, then index-1 prefix bytes. */
		unsigned position = 0;
		for (unsigned i = example.index; i < example.size; i++)
			assert(seq.data[position++] == (char)('A' + i % 23));
		for (unsigned i = 0; i + 1 < example.index; i++)
			assert(seq.data[position++] == (char)('A' + i % 23));
		assert(seq.length == position && seq.writes == 1u + (example.index > 0));
		assert(output_fixture.allocations == 1 && hw.ram_reads == 4);
	} else {
		assert(!seq.writes && !seq.length && !output_fixture.allocations && hw.ram_reads == 3);
	}
	healthy(); output_end();
}
static void console_allocation(unsigned index)
{
	assert(index < 5); struct sdpcm_shared sh = output_begin();
	if (!index) output_fixture.allocation_failure = true;
	else hw.ram_alloc_fail_at = index;
	struct seq_file seq = {0};
	assert(brcmf_sdio_dump_console(&seq, &f.bus, &sh) == -ENOMEM);
	assert(!seq.writes && !seq.length); healthy(); output_end();
}
static void console_output_failure(unsigned index)
{
	assert(index < 4); struct sdpcm_shared sh = output_begin();
	hw.diagnostic_index = index < 2 ? 2 : 16;
	struct seq_file seq = {.fail_at = 1 + index % 2, .error = index & 1 ? -ENOSPC : -EPIPE};
	assert(brcmf_sdio_dump_console(&seq, &f.bus, &sh) == seq.error);
	assert(seq.writes == seq.fail_at && output_fixture.frees == 1);
	assert(seq.length == (seq.fail_at == 1 ? 0u : 16 - hw.diagnostic_index));
	healthy(); output_end();
}
static void console_transport(unsigned index)
{
	assert(index < 24); struct sdpcm_shared sh = output_begin();
	hw.ram_fail_at = 1 + index % 4; hw.window_failure = index / 4 % 2;
	hw.ram_error = errors[index / 8];
	struct seq_file seq = {0};
	assert(brcmf_sdio_dump_console(&seq, &f.bus, &sh) == hw.ram_error);
	assert(hw.ram_reads == hw.ram_fail_at && !seq.length && !seq.writes);
	diagnosed(hw.ram_error); output_end();
}
static void console_admission(unsigned index)
{
	assert(index < 16); struct sdpcm_shared sh = output_begin();
	unsigned mode = index % 4; hw.inject_claim = 1 + index / 4;
	hw.admission = mode == 3 ? ADMIT_NOMEDIUM : (enum admission_fault)mode;
	int error = mode == 1 ? -EHOSTDOWN : mode == 3 ? -ENOMEDIUM : -EILSEQ;
	struct seq_file seq = {0};
	assert(brcmf_sdio_dump_console(&seq, &f.bus, &sh) == error);
	assert(hw.ram_reads == hw.inject_claim - 1 && !seq.length && !seq.writes);
	assert(!hw.quiesces && !hw.responses && !hw.controls); output_end();
}
enum assertion_text { SHORT_TEXT, EMPTY_TEXT, FULL_TEXT, LAST_BYTE_TERMINATOR };
static void assertion_strings(unsigned index)
{
	assert(index < 16); struct sdpcm_shared sh = output_begin();
	unsigned addresses = index % 4; enum assertion_text text = index / 4;
	if (!(addresses & 1)) sh.assert_file_addr = 0;
	if (!(addresses & 2)) sh.assert_exp_addr = 0;
	if (text == EMPTY_TEXT) {
		memset(hw.diagnostic_file, 0, 80); memset(hw.diagnostic_expression, 0, 80);
	} else if (text != SHORT_TEXT) {
		memset(hw.diagnostic_file, 'F', 80); memset(hw.diagnostic_expression, 'E', 80);
		if (text == LAST_BYTE_TERMINATOR) hw.diagnostic_file[79] = hw.diagnostic_expression[79] = 0;
	}
	char file[81] = {0}, expr[81] = {0}, expected[256];
	if (sh.assert_file_addr) memcpy(file, hw.diagnostic_file, 80); else strcpy(file, "?");
	if (sh.assert_exp_addr) memcpy(expr, hw.diagnostic_expression, 80); else strcpy(expr, "<???>");
	int count = snprintf(expected, sizeof(expected), "dongle assert: %s:23: assert(%s)\n", file, expr);
	assert(count > 0 && count < (int)sizeof(expected));
	struct seq_file seq = {0};
	assert(brcmf_sdio_assert_info(&seq, &f.bus, &sh) == 0);
	assert(seq.length == (unsigned)count && !memcmp(seq.data, expected, count));
	assert(hw.ram_reads == (unsigned)!!sh.assert_file_addr + !!sh.assert_exp_addr);
	healthy(); output_end();
}
static void assertion_flags(unsigned index)
{
	assert(index < 3); struct sdpcm_shared sh = output_begin();
	sh.flags = index == 1 ? SDPCM_SHARED_ASSERT : index == 2 ? SDPCM_SHARED_ASSERT_BUILT : 0;
	struct seq_file seq = {0};
	assert(brcmf_sdio_assert_info(&seq, &f.bus, &sh) == 0);
	assert(!seq.length && !hw.ram_reads); healthy(); output_end();
}
static void assertion_failure(unsigned index)
{
	assert(index < 16); struct sdpcm_shared sh = output_begin();
	const int faults[] = {-EIO, -ETIMEDOUT, -EILSEQ, -ENOMEM};
	hw.ram_fail_at = 1 + index % 2; hw.window_failure = index / 2 % 2;
	hw.ram_error = faults[index / 4];
	struct seq_file seq = {0};
	assert(brcmf_sdio_assert_info(&seq, &f.bus, &sh) == hw.ram_error);
	assert(hw.ram_reads == hw.ram_fail_at && !seq.length);
	if (hw.ram_error == -ENOMEM) healthy(); else diagnosed(hw.ram_error);
	output_end();
}
static void caller_output(unsigned index)
{
	assert(index < 4); output_begin();
	hw.shared_flags |= SDPCM_SHARED_ASSERT_BUILT | SDPCM_SHARED_ASSERT;
	memset(hw.diagnostic_file, 'F', 80); memset(hw.diagnostic_expression, 'E', 80);
	if (index == 1) hw.diagnostic_index = 17;
	if (index == 2) output_fixture.allocation_failure = true;
	struct seq_file seq = {.fail_at = index == 3 ? 1 : 0, .error = -ENOSPC};
	int expected[] = {0, -EINVAL, -ENOMEM, -ENOSPC};
	assert(brcmf_sdio_died_dump(&seq, &f.bus) == expected[index]);
	assert(hw.seq_lines == 1 && seq.length > 0); /* Assertion output precedes console output. */
	healthy(); output_end();
}
int main(int argc, char **argv)
{
	assert(argc == 3); unsigned index = strtoul(argv[2], NULL, 10);
	if (!strcmp(argv[1], "console_valid")) console_metadata(index, true);
	else if (!strcmp(argv[1], "console_invalid")) console_metadata(index, false);
	else if (!strcmp(argv[1], "console_allocation")) console_allocation(index);
	else if (!strcmp(argv[1], "console_output_failure")) console_output_failure(index);
	else if (!strcmp(argv[1], "console_transport")) console_transport(index);
	else if (!strcmp(argv[1], "console_admission")) console_admission(index);
	else if (!strcmp(argv[1], "assertion_strings")) assertion_strings(index);
	else if (!strcmp(argv[1], "assertion_flags")) assertion_flags(index);
	else if (!strcmp(argv[1], "assertion_failure")) assertion_failure(index);
	else if (!strcmp(argv[1], "caller_output")) caller_output(index);
	else assert(false);
	printf("%s %u passed\n", argv[1], index); return 0;
}
