/* SPDX-License-Identifier: MIT */
/* Temporary mount veto for one freshly identified whole disk and its slices. */
#include <stdio.h>
#include <stdbool.h>
#include <string.h>

static int valid_disk(const char *name)
{
    if (strncmp(name, "disk", 4) || name[4] < '1' || name[4] > '9')
        return 0;
    for (const char *p = name + 5; *p; p++)
        if (*p < '0' || *p > '9')
            return 0;
    return 1;
}

static int matches(const char *name, const char *whole)
{
    size_t length = strlen(whole);
    if (!name || strncmp(name, whole, length))
        return 0;
    if (!name[length])
        return 1;
    const char *p = name + length;
    if (*p++ != 's' || *p < '1' || *p > '9')
        return 0;
    for (p++; *p; p++)
        if (*p < '0' || *p > '9')
            return 0;
    return 1;
}

#ifdef NEO_MAC_GUARD_TEST
#include <assert.h>
int main(void)
{
    assert(valid_disk("disk16") && !valid_disk("disk0") && !valid_disk("disk16s1"));
    assert(!valid_disk("") && !valid_disk("disk") && !valid_disk("disk-1"));
    assert(matches("disk16", "disk16") && matches("disk16s1", "disk16"));
    assert(matches("disk16s12", "disk16") && !matches(NULL, "disk16"));
    assert(!matches("disk160", "disk16") && !matches("disk160s1", "disk16"));
    assert(!matches("disk16s", "disk16") && !matches("disk16s0", "disk16"));
    assert(!matches("disk16s1other", "disk16") && !matches("disk1", "disk16"));
    puts("Mac mount guard: whole-disk/slice matching checks passed");
    return 0;
}
#else
#include <CoreFoundation/CoreFoundation.h>
#include <DiskArbitration/DiskArbitration.h>
#include <poll.h>
#include <unistd.h>

static DADissenterRef deny_mount(DADiskRef disk, void *context)
{
    const char *name = DADiskGetBSDName(disk);
    if (!matches(name, context))
        return NULL;
    printf("BLOCKED %s\n", name);
    fflush(stdout);
    return DADissenterCreate(NULL, kDAReturnNotPermitted,
                            CFSTR("GameShellNeo card verification in progress"));
}

int main(int argc, char **argv)
{
    if (argc != 2 || !valid_disk(argv[1]) || geteuid() != 0) {
        fprintf(stderr, "Usage: sudo macos-mount-guard diskN (N > 0)\n");
        return 2;
    }
    DASessionRef session = DASessionCreate(NULL);
    if (!session)
        return 3;
    DARegisterDiskMountApprovalCallback(session, NULL, deny_mount, argv[1]);
    DASessionScheduleWithRunLoop(session, CFRunLoopGetCurrent(), kCFRunLoopDefaultMode);
    /* Parent verifies an actual veto before opening the disk for writing. */
    puts("READY");
    fflush(stdout);
    alarm(900);
    for (;;) {
        CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.25, false);
        struct pollfd input = { .fd = STDIN_FILENO, .events = POLLIN | POLLHUP };
        int result = poll(&input, 1, 0);
        if (result < 0)
            break;
        if (result && input.revents) {
            char byte;
            if (read(STDIN_FILENO, &byte, 1) <= 0)
                break;
        }
    }
    DASessionUnscheduleFromRunLoop(session, CFRunLoopGetCurrent(), kCFRunLoopDefaultMode);
    CFRelease(session);
    return 0;
}
#endif
