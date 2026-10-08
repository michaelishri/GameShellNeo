"""Pinned MUSB inputs and source-bound IRQ lifecycle test extraction."""
import re
import tarfile

PATCHES = ('0011-musb-sunxi-context.patch', '0025-musb-system-sleep-pullup.patch',
           '0030-musb-gadget-callback-lifetime.patch', '0033-musb-sleep-session-retirement.patch',
           '0037-musb-resume-request-ownership.patch', '0038-musb-probe-role-unwind.patch',
           '0039-musb-core-irq-retirement.patch')


def extract_source(archive, lock, queue, apply_queue, scratch):
    selected = [p for p in queue if p[0] in PATCHES]
    if tuple(name for name, _ in selected) != PATCHES:
        raise ValueError('Incomplete MUSB IRQ source queue')
    targets = {'drivers/usb/musb/Kconfig'}
    for _, data in selected:
        targets.update(re.findall(r'^\+\+\+ b/([^\t\n]+)', data.decode(), re.M))
    prefix = 'linux-' + lock['linux']['tag'].removeprefix('v') + '/'
    found = set()
    with tarfile.open(archive, 'r|xz') as stream:
        for entry in stream:
            name = entry.name.removeprefix(prefix)
            if entry.name.startswith(prefix) and name in targets:
                path = scratch / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(stream.extractfile(entry).read())
                found.add(name)
                if found == targets:
                    break
    if found != targets:
        raise ValueError('Incomplete pinned MUSB extraction')
    apply_queue(scratch, selected)


def function(text, name):
    match = re.search(r'^static (?:void|int)\s+' + name + r'\([^;{]*\)\n\{', text, re.M)
    if not match:
        raise ValueError('Missing function: ' + name)
    return text[match.start():text.index('\n}', match.end()) + 2] + '\n'


def test_functions(core):
    init_start = core.index('musb_init_controller(struct')
    init_end = core.index('\n}', init_start)
    init = core[init_start:init_end]
    # Bind the fixture to actual ownership publication and the actual fail3 tail.
    acquisition = ('\tif (request_irq(nIrq, musb->isr, IRQF_SHARED, dev_name(dev), musb)) {\n'
                   '\t\tdev_err(dev, "request_irq %d failed!\\n", nIrq);\n'
                   '\t\tstatus = -ENODEV;\n\t\tgoto fail3;\n\t}\n\tmusb->nIrq = nIrq;')
    if init.count(acquisition) != 1 or init.count(
            '\tstatus = musb_init_roles(musb, plat->power);\n\tif (status < 0)\n\t\tgoto fail3;') != 1:
        raise ValueError('Probe ownership/caller boundary changed')
    if core.count('\tmusb->nIrq = -ENODEV;') != 2:
        raise ValueError('Expected allocation and release IRQ ownership resets')
    tail = init[init.index('fail3:\n'):]
    probe = ('static int probe_failure(struct musb *musb, struct device *dev)\n{\n'
             '\tint status = -EIO;\n' + tail + '\n}\n')
    return ''.join(function(core, name) for name in
                   ('musb_free_irq', 'musb_shutdown_irq', 'musb_free', 'musb_remove')) + probe


def replace_once(text, old, new):
    if text.count(old) != 1 or old == new:
        raise ValueError('Expected a unique changed IRQ-test anchor')
    return text.replace(old, new, 1)


def mutations(functions):
    remove = function(functions, 'musb_remove')
    late_remove = replace_once(remove, '\tmusb_shutdown_irq(musb);\n', '')
    late_remove = replace_once(late_remove, '\tmusb_platform_exit(musb);',
                               '\tmusb_platform_exit(musb);\n\tmusb_shutdown_irq(musb);')
    early_remove = replace_once(remove, '\tmusb_shutdown_irq(musb);\n', '')
    early_remove = replace_once(early_remove, '\tmusb_exit_debugfs(musb);',
                                '\tmusb_exit_debugfs(musb);\n\tmusb_shutdown_irq(musb);')
    shutdown = function(functions, 'musb_shutdown_irq')
    locked = replace_once(shutdown, '\tmusb_free_irq(musb);\n', '')
    locked = replace_once(locked, '\tspin_unlock_irqrestore(&musb->lock, flags);',
                           '\tmusb_free_irq(musb);\n\tspin_unlock_irqrestore(&musb->lock, flags);')
    free = function(functions, 'musb_free_irq')
    wrong_number = replace_once(free, '\tmusb->nIrq = -ENODEV;\n', '')
    wrong_number = replace_once(wrong_number, '\tif (musb->irq_wake) {',
                                 '\tmusb->nIrq = -ENODEV;\n\tif (musb->irq_wake) {')
    return {
        'late-remove': replace_once(functions, remove, late_remove),
        'early-remove': replace_once(functions, remove, early_remove),
        'late-probe': replace_once(functions, 'fail3:\n\tmusb_shutdown_irq(musb);', 'fail3:\n'),
        'missing-free': replace_once(functions, '\tfree_irq(musb->nIrq, musb);', '\t(void)musb;'),
        'double-free': replace_once(functions, '\tmusb->nIrq = -ENODEV;\n', ''),
        'wait-under-lock': replace_once(functions, shutdown, locked),
        'global-line-disable': replace_once(functions, '\tfree_irq(musb->nIrq, musb);',
                                             '\tdisable_irq(musb->nIrq);\n\tfree_irq(musb->nIrq, musb);'),
        'invalid-wake-number': replace_once(functions, free, wrong_number),
        'unowned-mask': replace_once(functions, shutdown,
            replace_once(shutdown, '\tif (musb->nIrq < 0)\n\t\treturn;\n', '')),
    }
