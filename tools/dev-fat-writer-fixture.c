/* SPDX-License-Identifier: MIT */
/* Host-only platform shims around unchanged, pinned U-Boot FAT source.
 * No controller, bootloader binary, hush, DMA/cache or power-loss emulation.
 * Only a new 128 MiB regular FAT16 file can be opened for writing.
 */
#define _GNU_SOURCE
#include <assert.h>
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

typedef uint8_t __u8;
typedef uint16_t __u16;
typedef uint32_t __u32;
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
typedef unsigned long ulong;
typedef uint64_t lbaint_t;

#define CONFIG_FAT_WRITE 1
#define CONFIG_FS_FAT_MAX_CLUSTSIZE 65536
#define CONFIG_IS_ENABLED(option) 0
#define ARCH_DMA_MINALIGN 64
#define __aligned(value) __attribute__((aligned(value)))
#define ALLOC_CACHE_ALIGN_BUFFER(type, name, count) type name[count] __aligned(ARCH_DMA_MINALIGN)
#define debug(...) ((void)0)
#define min(a, b) ((a) < (b) ? (a) : (b))
#define max(a, b) ((a) > (b) ? (a) : (b))
#define cpu_to_le16(value) ((uint16_t)(value))
#define cpu_to_le32(value) ((uint32_t)(value))
#define FS_DT_DIR 4
#define FS_DT_REG 8

struct blk_desc { int devnum; ulong blksz; lbaint_t lba; };
typedef struct {
    lbaint_t start, size;
    ulong blksz;
    char name[64], type[32];
    int bootable;
} disk_partition_t;
struct fs_dir_stream { int unused; };
struct fs_dirent { char name[256]; int type; loff_t size; };

static int backing_fd = -1;
static unsigned long read_calls, write_calls;

static ulong transfer_blocks(struct blk_desc *dev, lbaint_t start, lbaint_t count,
                             void *buffer, int write_operation)
{
    if (backing_fd < 0 || start > dev->lba || count > dev->lba - start)
        return 0;
    size_t remaining = (size_t)count * dev->blksz;
    off_t offset = (off_t)(start * dev->blksz);
    unsigned char *bytes = buffer;
    while (remaining) {
        ssize_t amount = write_operation ? pwrite(backing_fd, bytes, remaining, offset) :
                                          pread(backing_fd, bytes, remaining, offset);
        if (amount < 0 && errno == EINTR)
            continue;
        if (amount <= 0)
            return 0;
        bytes += amount;
        offset += amount;
        remaining -= (size_t)amount;
    }
    if (write_operation)
        write_calls++;
    else
        read_calls++;
    return (ulong)count;
}

static ulong blk_dread(struct blk_desc *dev, lbaint_t start, lbaint_t count, void *buffer)
{
    return transfer_blocks(dev, start, count, buffer, 0);
}

static ulong blk_dwrite(struct blk_desc *dev, lbaint_t start, lbaint_t count, const void *buffer)
{
    return transfer_blocks(dev, start, count, (void *)buffer, 1);
}

static int part_get_info(struct blk_desc *dev, int number, disk_partition_t *info)
{
    (void)dev; (void)number; (void)info;
    return -1; /* The harness supplies an explicit unpartitioned FAT16 volume. */
}

static void *memalign(size_t alignment, size_t size)
{
    void *pointer = NULL;
    return posix_memalign(&pointer, alignment, size) ? NULL : pointer;
}

static void *malloc_cache_aligned(size_t size)
{
    return memalign(ARCH_DMA_MINALIGN, size);
}

static uint64_t div_u64_rem(uint64_t value, uint32_t divisor, uint32_t *remainder)
{
    *remainder = (uint32_t)(value % divisor);
    return value / divisor;
}

/* The include path resolves to the private, hash-verified upstream cache.
 * That file includes the unchanged fat.c and fat.h itself. Empty platform
 * headers only defer to the explicit shims above; no FAT code is rewritten.
 */
#include "fat_write.c"

int main(int argc, char **argv)
{
    struct stat volume, input;
    if (argc != 4 || (strcmp(argv[3], "NEXT.SCR") && strcmp(argv[3], "next.scr")))
        return 2;
    backing_fd = open(argv[1], O_RDWR | O_NOFOLLOW);
    if (backing_fd < 0 || fstat(backing_fd, &volume) || !S_ISREG(volume.st_mode) ||
        volume.st_size != 128 * 1024 * 1024)
        return 3;
    int payload_fd = open(argv[2], O_RDONLY | O_NOFOLLOW);
    if (payload_fd < 0 || fstat(payload_fd, &input) || !S_ISREG(input.st_mode) ||
        input.st_size <= 0 || input.st_size > 65536)
        return 4;
    unsigned char *payload = memalign(ARCH_DMA_MINALIGN, (size_t)input.st_size + 512);
    unsigned char *readback = memalign(ARCH_DMA_MINALIGN, 65536);
    if (!payload || !readback)
        return 5;
    memset(payload, 0, (size_t)input.st_size + 512);
    memset(readback, 0, 65536);
    if (read(payload_fd, payload, (size_t)input.st_size) != input.st_size)
        return 5;
    close(payload_fd);
    struct blk_desc device = { .devnum = 0, .blksz = 512, .lba = (uint64_t)volume.st_size / 512 };
    disk_partition_t partition = { .start = 0, .size = device.lba, .blksz = 512 };
    _Static_assert(sizeof(dir_entry) == 32, "FAT directory layout");
    _Static_assert(sizeof(boot_sector) == 64, "FAT boot-sector prefix layout");
    assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__);
    if (fat_set_blk_dev(&device, &partition))
        return 6;
    loff_t written = 0, read_bytes = 0;
    int status = file_fat_write(argv[3], payload, 0, input.st_size, &written);
    if (fsync(backing_fd))
        return 7;
    int read_status = file_fat_read_at(argv[3], 0, readback, 65536, &read_bytes);
    printf("FIXTURE_RESULT {\"writer_status\":%d,\"written\":%lld,\"read_status\":%d,"
           "\"read_bytes\":%lld,\"matches_payload\":%s,\"block_reads\":%lu,\"block_writes\":%lu}\n",
           status, (long long)written, read_status, (long long)read_bytes,
           read_bytes == input.st_size && !memcmp(readback, payload, (size_t)input.st_size) ? "true" : "false",
           read_calls, write_calls);
    free(readback);
    free(payload);
    close(backing_fd);
    return status || written != input.st_size || read_status;
}
