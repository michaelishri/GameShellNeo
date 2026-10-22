"""Pinned source extraction for the explicit terminal IRQ/wake composition."""
import importlib.util
import re
import subprocess
import tarfile

from kernel_candidates import include_candidates

PROFILE = 'musb-terminal-wake'
CORE = 'drivers/usb/musb/musb_core.c'
HEADER = 'drivers/usb/musb/musb_core.h'
GADGET = 'drivers/usb/musb/musb_gadget.c'
FILES = (CORE, HEADER, GADGET, 'drivers/usb/musb/Kconfig',
         'kernel/irq/manage.c', 'include/linux/pm_runtime.h')


def queue_for(root, profile):
    specification = importlib.util.spec_from_file_location('terminal_kernel_inputs', root / 'tools/kernel-inputs.py')
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return include_candidates(root, profile, module.patches())


def prepare(root, archive, lock, directory, profile=PROFILE):
    """Apply the selected queue strictly to relevant, bounded archive members."""
    prefix = 'linux-' + lock['linux']['tag'][1:] + '/'
    found = set()
    with tarfile.open(archive, 'r|xz') as stream:
        for entry in stream:
            name = entry.name.removeprefix(prefix)
            if not entry.name.startswith(prefix) or name not in FILES:
                continue
            if not entry.isfile() or entry.size > 2 * 1024 * 1024:
                raise ValueError('Unexpected terminal IRQ/wake source: ' + name)
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            data = stream.extractfile(entry).read(entry.size + 1)
            if len(data) != entry.size:
                raise ValueError('Incomplete terminal IRQ/wake source: ' + name)
            path.write_bytes(data)
            found.add(name)
            if found == set(FILES):
                break
    if found != set(FILES):
        raise ValueError('Missing pinned terminal IRQ/wake source')
    queue = queue_for(root, profile)
    for name, data in queue:
        selected = selected_diffs(data.decode())
        if selected:
            subprocess.run(['patch', '--batch', '--fuzz=0', '-p1'], cwd=directory,
                           input=''.join(selected), text=True, check=True)
    return {name: directory / name for name in FILES}, queue


def selected_diffs(patch):
    # Maintained inputs include both Git-style and plain unified patches.
    chunks = re.split(r'(?=^diff --git |^--- (?:a/|/dev/null))', patch, flags=re.M)
    return [chunk for chunk in chunks
            if (match := re.match(r'^--- (?:a/[^\n]+|/dev/null)\n\+\+\+ b/([^\t\n]+)', chunk))
            and match.group(1) in FILES]


def function(source, name):
    match = re.search(r'^(?:static\s+)?(?:inline\s+)?(?:void|int|bool)\s+' +
                      re.escape(name) + r'\([^;{]*\)\n\{', source, re.M)
    if not match:
        raise ValueError('Missing terminal IRQ/wake function: ' + name)
    return source[match.start():source.index('\n}', match.end()) + 3] + '\n'


def once(source, before, after):
    if source.count(before) != 1 or before == after:
        raise ValueError('Changed terminal IRQ/wake anchor: ' + before)
    return source.replace(before, after, 1)


def reference_functions(wake, retirement, irq):
    """Keep the two qualified reference bodies distinct from a shipping fix."""
    free = function(retirement, 'musb_free_irq')
    reference = once(free, 'musb_free_irq(', 'reference_free_irq(')
    double = once(reference, 'reference_free_irq(', 'reference_free_irq_keeps_number(')
    double = once(double, '\tmusb->nIrq = -ENODEV;\n', '')
    return (''.join(function(irq, name) for name in ('set_irq_wake_real', 'irq_set_irq_wake')) +
            ''.join(function(wake, name) for name in ('musb_disarm_wake', 'musb_cleanup_wakeup')) +
            reference + double)


def compare_semantics(combined, wake):
    """The bridge changes terminal ownership, retaining qualified policy bodies."""
    compared = {}
    for name in ('musb_disarm_wake', 'musb_init_wakeup', 'musb_cleanup_wakeup',
                 'musb_suspend', 'musb_resume'):
        left, right = function(combined, name), function(wake, name)
        if left != right:
            raise ValueError('Wake policy function differs from 0026: ' + name)
        compared[name] = left
    return compared


def test_functions(paths):
    core = paths[CORE].read_text()
    free = function(core, 'musb_free_irq')
    expected = ('\tif (musb->nIrq < 0)\n\t\treturn;\n\n'
                '\t/* Attempt owned wake cleanup once, before losing the action identity. */\n'
                '\tmusb_cleanup_wakeup(musb);\n\tfree_irq(musb->nIrq, musb);\n'
                '\tmusb->nIrq = -ENODEV;')
    if expected not in free or core.count('\tmusb_cleanup_wakeup(musb);') != 1:
        raise ValueError('Terminal wake/action ownership boundary changed')
    early = ('\tstatus = pm_runtime_resume_and_get(musb->controller);\n'
             '\tif (status < 0) {\n\t\tpm_runtime_disable(musb->controller);\n'
             '\t\tpm_runtime_dont_use_autosuspend(musb->controller);\n\t\tgoto fail2;\n\t}')
    if early not in core:
        raise ValueError('Unchanged 0029 startup failure handoff is missing')
    return (''.join(function(paths['include/linux/pm_runtime.h'].read_text(), name)
                    for name in ('pm_runtime_get_active', 'pm_runtime_resume_and_get')) +
            ''.join(function(paths['kernel/irq/manage.c'].read_text(), name)
                    for name in ('set_irq_wake_real', 'irq_set_irq_wake')) +
            ''.join(function(core, name) for name in (
                'musb_disarm_wake', 'musb_init_wakeup', 'musb_cleanup_wakeup',
                'musb_free_irq', 'musb_shutdown_irq', 'musb_shutdown_work',
                'musb_disable_runtime_pm', 'musb_release_session', 'musb_free',
                'musb_init_roles', 'musb_init_controller', 'musb_remove')))


def mutations(body):
    free = function(body, 'musb_free_irq')
    cleanup = '\tmusb_cleanup_wakeup(musb);\n'
    late = once(free, cleanup, '')
    late = once(late, '\tmusb->nIrq = -ENODEV;', '\tmusb->nIrq = -ENODEV;\n' + cleanup.rstrip())
    return {
        'cleanup-after-invalidation': once(body, free, late),
        'missing-wake-cleanup': once(body, cleanup, '\t(void)musb_cleanup_wakeup;\n'),
        'duplicate-final-disarm': once(body, cleanup, cleanup + cleanup),
        'missing-action-invalidation': once(body, '\tmusb->nIrq = -ENODEV;\n', ''),
        'clear-failed-disarm': once(body, '\tif (!ret)\n\t\tmusb->irq_wake = false;',
                                  '\tmusb->irq_wake = false;'),
        'drop-foreign-capability': once(body, '\tif (musb->wakeup_initialized) {', '\tif (true) {'),
        'ignore-startup-power-failure': once(body, '\tif (status < 0) {\n\t\tpm_runtime_disable',
                                            '\tif (false) {\n\t\tpm_runtime_disable'),
    }
