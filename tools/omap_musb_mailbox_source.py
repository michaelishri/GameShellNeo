"""Bounded pinned source for the explicit OMAP mailbox lifetime candidate."""
import importlib.util
import re
import subprocess
import tarfile

from kernel_candidates import include_candidates

PROFILE = 'musb-omap-mailbox'
CORE = 'drivers/usb/musb/musb_core.c'
HEADER = 'drivers/usb/musb/musb_core.h'
OMAP = 'drivers/usb/musb/omap2430.c'
FILES = (CORE, HEADER, OMAP, 'drivers/usb/musb/Kconfig')


def queue_for(root, *, reference=False):
    spec = importlib.util.spec_from_file_location('omap_mailbox_inputs', root / 'tools/kernel-inputs.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not reference:
        return include_candidates(root, PROFILE, module.patches())
    queue = include_candidates(root, 'musb-retirement', module.patches())
    startup = root / 'kernel/candidates/musb-wake-startup/0029-musb-startup-runtime-pm.patch'
    queue.append((startup.name, startup.read_bytes()))
    return sorted(queue)


def selected_diffs(patch):
    chunks = re.split(r'(?=^diff --git |^--- (?:a/|/dev/null))', patch, flags=re.M)
    return [chunk for chunk in chunks
            if (match := re.match(r'^--- (?:a/[^\n]+|/dev/null)\n\+\+\+ b/([^\t\n]+)', chunk))
            and match.group(1) in FILES]


def prepare(root, archive, lock, directory, *, reference=False):
    prefix = 'linux-' + lock['linux']['tag'][1:] + '/'
    paths = {}
    with tarfile.open(archive, 'r|xz') as stream:
        for entry in stream:
            if not entry.name.startswith(prefix):
                continue
            name = entry.name[len(prefix):]
            if name not in FILES:
                continue
            if not entry.isfile() or entry.size > 2 * 1024 * 1024:
                raise ValueError('Unexpected pinned mailbox source: ' + name)
            data = stream.extractfile(entry).read(entry.size + 1)
            if len(data) != entry.size:
                raise ValueError('Incomplete pinned mailbox source: ' + name)
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            paths[name] = path
            if len(paths) == len(FILES):
                break
    if set(paths) != set(FILES):
        raise ValueError('Missing pinned mailbox source')
    queue = queue_for(root, reference=reference)
    for _, data in queue:
        selected = selected_diffs(data.decode())
        if selected:
            subprocess.run(['patch', '--batch', '--fuzz=0', '-p1'], cwd=directory,
                           input=''.join(selected), text=True, check=True)
    return paths, queue


def function(source, name):
    match = re.search(r'^(?:static\s+)?(?:inline\s+)?(?:void|int)\s+' +
                      re.escape(name) + r'\([^;{]*\)\n\{', source, re.M)
    if not match:
        raise ValueError('Missing actual mailbox function: ' + name)
    return source[match.start():source.index('\n}', match.end()) + 3] + '\n'


def once(source, before, after):
    if source.count(before) != 1:
        raise ValueError('Changed mailbox source anchor: ' + before)
    return source.replace(before, after, 1)


def reference_definitions(omap):
    start = omap.index('struct omap2430_glue {')
    end = omap.index('\n};', start) + 4
    declarations = omap[start:end]
    for name in ('#define glue_to_musb', 'static struct omap2430_glue'):
        declarations += next(line for line in omap.splitlines(True) if line.startswith(name))
    return declarations + '\nstatic int (*musb_phy_callback)(enum musb_vbus_id_status status);\n'


def reference_functions(sources):
    core, omap = sources[CORE], sources[OMAP]
    body = ''.join(function(source, name) for source, name in (
        (omap, 'omap2430_low_level_exit'), (omap, 'omap2430_musb_mailbox'),
        (omap, 'omap_musb_set_mailbox'), (omap, 'omap_musb_mailbox_work'),
        (omap, 'omap2430_musb_exit'), (omap, 'omap2430_remove'), (core, 'musb_mailbox')))
    # Exercise the unchanged real publication/fail2 arms. Surrounding probe
    # acquisitions are a declared seam; this is not a complete probe execution.
    probe = function(core, 'musb_init_controller')
    publish = '\tif (musb->ops->phy_callback)\n\t\tmusb_phy_callback = musb->ops->phy_callback;\n'
    if probe.count(publish) != 1:
        raise ValueError('Changed reference callback publication')
    fail = probe.split('\nfail2:\n', 1)[1].split('\nfail1:', 1)[0]
    if fail != ('\tmusb_shutdown_resume_work(musb);\n\tif (musb->irq_wake)\n'
                '\t\tdevice_init_wakeup(dev, 0);\n\tmusb_platform_exit(musb);\n'):
        raise ValueError('Changed reference fail2 arm')
    return body + ('\nstatic void reference_publish(struct musb *musb)\n{\n' + publish + '}\n' +
                   '\nstatic void reference_fail2(struct musb *musb)\n{\n'
                   '\tstruct device *dev = musb->controller;\n' + fail + '}\n')


def candidate_definitions(sources):
    omap, core = sources[OMAP], sources[CORE]
    start = omap.index('struct omap2430_glue {')
    end = omap.index('\n};', start) + 4
    declarations = omap[start:end]
    start = core.index('static DEFINE_MUTEX(musb_mailbox_lock);')
    end = core.index('\nstatic int musb_register_mailbox', start)
    return declarations + '\n' + core[start:end] + '\n'


def handoff_contract(sources):
    """Pin real caller placement separately from bounded reachability wrappers."""
    core = sources[CORE]
    probe = function(core, 'musb_init_controller')
    for label in ('fail3', 'fail2_5', 'err_usb_phy_init', 'fail2'):
        tail = probe.split('\n' + label + ':\n', 1)[1]
        if not tail.startswith('\tmusb_quiesce_mailbox(musb);\n'):
            raise ValueError('Mailbox handoff is not first in probe arm: ' + label)
    for name, before in (('musb_remove', '\tmusb_host_cleanup(musb);'),
                         ('musb_init_roles', '\t/* Keep core IRQ, DMA')):
        body = function(core, name)
        if body.index('musb_quiesce_mailbox(musb);') >= body.index(before):
            raise ValueError('Mailbox handoff is too late: ' + name)
    remove = function(core, 'musb_remove')
    if remove.index('pm_runtime_get_sync(musb->controller)') >= remove.index('musb_quiesce_mailbox(musb)'):
        raise ValueError('Parent can no longer resume before terminal handoff')
    return dict(probe_arms=('fail3', 'fail2_5', 'err_usb_phy_init', 'fail2'),
                callers=('musb_remove', 'musb_init_roles'),
                scope='Full caller bodies checked for order; reachability wrappers execute their '
                      'first handoff statement with modeled acquisition/stage selection.')


def candidate_functions(sources):
    handoff_contract(sources)
    core, omap = sources[CORE], sources[OMAP]
    body = ''.join(function(source, name) for source, name in (
        (omap, 'omap2430_cleanup_srcu'), (omap, 'omap2430_musb_quiesce'),
        (core, 'musb_register_mailbox'), (core, 'musb_quiesce_mailbox'), (core, 'musb_mailbox'),
        (omap, 'omap2430_low_level_exit'), (omap, 'omap2430_low_level_init'),
        (omap, 'omap2430_musb_mailbox'), (omap, 'omap_musb_set_mailbox'),
        (omap, 'omap_musb_mailbox_work'), (omap, 'omap2430_musb_init'),
        (omap, 'omap2430_musb_enable'), (omap, 'omap2430_musb_exit'),
        (omap, 'omap2430_remove'), (omap, 'omap2430_runtime_suspend'),
        (omap, 'omap2430_runtime_resume')))
    body += '''
/* First statement from each real failure label, with acquisition modeled. */
static void candidate_failed_probe(struct musb *musb)
{
	musb_quiesce_mailbox(musb);
}

'''
    return body


def variants(body):
    core = function(body, 'musb_quiesce_mailbox')
    omap = function(body, 'omap2430_musb_quiesce')
    exit_body = function(body, 'omap2430_musb_exit')
    late = once(core, '\t\tmusb->ops->phy_callback_quiesce(musb);', '\t\t(void)musb;')
    late_exit = once(exit_body, '\tomap2430_musb_quiesce(musb);\n', '')
    late_exit = once(late_exit, '\tmusb->phy = NULL;\n',
                     '\tmusb->phy = NULL;\n\tomap2430_musb_quiesce(musb);\n')
    ordering = '\tdisable_work_sync(&glue->omap_musb_mailbox_work);\n'
    close = '\tRCU_INIT_POINTER(glue->active_musb, NULL);\n\tsynchronize_srcu(&glue->child_srcu);\n'
    return {
        'candidate': body,
        'omit-dispatch-drain': once(body, '\t\tsynchronize_srcu(&musb_mailbox_srcu);\n', ''),
        'drain-work-after-PHY': once(once(body, core, late), exit_body, late_exit),
        'omit-failure-unpublish': once(body, function(body, 'candidate_failed_probe'),
            'static void candidate_failed_probe(struct musb *musb) { (void)musb; }\n'),
        'omit-owner-check': once(body, 'rcu_access_pointer(musb_mailbox_owner) == musb',
                                'rcu_access_pointer(musb_mailbox_owner) != NULL'),
        'allow-stale-generation': once(body,
            'srcu_dereference(glue->active_musb, &glue->child_srcu) != musb',
            'srcu_dereference(glue->active_musb, &glue->child_srcu) == NULL'),
        'omit-rebind-admission': once(body, '\tenable_work(&glue->omap_musb_mailbox_work);\n',
                                      '\t(void)enable_work;\n'),
        'lose-latest-status': once(body, '\tglue->status = status;\n', '\t(void)status;\n'),
        'omit-parent-drain': once(body, '\tsynchronize_srcu(&glue->child_srcu);\n', ''),
        'close-parent-before-worker-drain': once(body, omap,
            once(omap, ordering + close, close + ordering)),
    }
