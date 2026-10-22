"""Explicit offline candidate queues; production inputs remain in kernel-inputs.py."""
from pathlib import Path

PROFILES = {
    'musb-wake-startup': (
        'musb-wake-startup/0026-musb-wake-irq-policy.patch',
        'musb-wake-startup/0029-musb-startup-runtime-pm.patch',
    ),
    'power-supply-lifetime': (
        'power-supply-lifetime/0037-power-supply-unregister-producer.patch',
    ),
    'musb-retirement': tuple('musb-retirement/' + name for name in (
        '0038-musb-probe-role-unwind.patch',
        '0039-musb-core-irq-retirement.patch',
        '0040-musb-core-work-retirement.patch',
        '0041-musb-runtime-pm-retirement.patch',
        '0042-musb-resume-work-retirement.patch',
        '0043-extcon-notifier-drain.patch',
        '0044-sunxi-child-notifier-work.patch',
        '0045-extcon-provider-link.patch',
    )),
}


def patch_path(root, name):
    """Locate a named source input without falling back for missing candidates."""
    if Path(name).name != name or not name.endswith('.patch'):
        raise ValueError('Expected a patch basename')
    for paths in PROFILES.values():
        for relative in paths:
            if Path(relative).name == name:
                return root / 'kernel/candidates' / relative
    return root / 'kernel/patches' / name


def include_candidates(root, profile, production):
    """Add only the named profile; reject duplicate or already promoted inputs."""
    if profile not in PROFILES:
        raise ValueError('Unknown offline candidate profile: ' + str(profile))
    queue = list(production)
    names = [name for name, _ in queue]
    if len(set(names)) != len(names):
        raise ValueError('Duplicate production patch names')
    for relative in PROFILES[profile]:
        name = Path(relative).name
        if name in names:
            raise ValueError('Candidate is already in the production queue: ' + name)
        queue.append((name, (root / 'kernel/candidates' / relative).read_bytes()))
        names.append(name)
    return sorted(queue)


def candidate_paths(root, profile):
    if profile not in PROFILES:
        raise ValueError('Unknown offline candidate profile: ' + str(profile))
    return tuple(root / 'kernel/candidates' / relative for relative in PROFILES[profile])
