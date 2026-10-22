"""Pinned managed-wakeup inline bodies and the finite five-case contract."""
import json
import re
import subprocess
import tarfile

HEADER = 'include/linux/pm_wakeup.h'
DEVRES_HEADER = 'include/linux/device/devres.h'
PATCH = 'kernel/candidates/managed-wakeup-init/0072-managed-wakeup-init-error.patch'
CASES = ('managed_wakeup_success_test', 'managed_wakeup_source_error_test',
         'managed_wakeup_existing_source_test', 'managed_wakeup_action_error_test',
         'managed_wakeup_capable_disabled_test')
CONTROL_FAILURES = {
    CASES[1]: (('result', 0, -12), ('action_present', 1, 0),
               ('capable_after_release', 0, 1)),
    CASES[2]: (('result', 0, -17), ('action_present', 1, 0),
               ('source_preserved', 0, 1), ('id_preserved', 0, 1),
               ('capable_after_release', 0, 1)),
}
LIMITS = ('Actual managed/device-init/action-reset inline bodies; native device, '
          'allocation, source/IDA and devres effects are explicit models. '
          'Real PM/devres/IDA ownership requires the separate Linux suite. '
          'No concurrent policy, unbind, DPM, image or hardware qualification.')


def function(source, name):
    pattern = r'^(?:static (?:inline )?)?(?:int|void) ' + re.escape(name) + r'\([^;{]*\)\n\{'
    matches = list(re.finditer(pattern, source, re.M))
    if len(matches) != 1:
        raise ValueError('Expected one actual function definition: ' + name)
    match = matches[0]
    end = source.find('\n}', match.end())
    if end < 0:
        raise ValueError('Incomplete actual function: ' + name)
    return source[match.start():end + 2] + '\n'


def inline_functions(header, devres):
    pieces = [function(header, 'device_init_wakeup'),
              function(header, 'device_disable_wakeup'),
              function(devres, '__devm_add_action_or_reset'),
              '#define devm_add_action_or_reset(dev, action, data) '
              '__devm_add_action_or_reset(dev, action, data, #action)\n',
              function(header, 'devm_device_init_wakeup')]
    return '\n'.join(pieces)


def variants(before, after, devres):
    if function(before, 'devm_device_init_wakeup') == function(after, 'devm_device_init_wakeup'):
        raise ValueError('Candidate did not change managed initialization')
    for name in ('device_init_wakeup', 'device_disable_wakeup'):
        if function(before, name) != function(after, name):
            raise ValueError('Candidate changed underlying wakeup semantics: ' + name)
    return {'return-ignored': inline_functions(before, devres),
            'candidate': inline_functions(after, devres)}


def checked_native(name, result):
    if name not in ('candidate', 'return-ignored'):
        raise ValueError('Unknown managed-wakeup variant')
    control = name == 'return-ignored'
    if result.returncode != int(control) or result.stderr:
        raise ValueError('Inconclusive managed-wakeup execution: ' + name)
    report = json.loads(result.stdout)
    if set(report) != {'cases'} or not isinstance(report['cases'], list):
        raise ValueError('Malformed managed-wakeup observation')
    rows = report['cases']
    if tuple(row.get('name') for row in rows) != CASES:
        raise ValueError('Missing, duplicated or reordered managed-wakeup cases')
    for index, row in enumerate(rows):
        if set(row) != {'name', 'failures', 'observations'}:
            raise ValueError('Unexpected managed-wakeup case fields')
        expected_failures = CONTROL_FAILURES.get(row['name'], ()) if control else ()
        wanted = [dict(assertion=key, actual=actual, expected=expected)
                  for key, actual, expected in expected_failures]
        if (row['failures'] != wanted or any(
                type(failure['actual']) is not int or type(failure['expected']) is not int
                for failure in row['failures'])):
            raise ValueError('Different managed-wakeup assertion set: ' + row['name'])
        failed_init = index in (1, 2)
        action = index != 3 and (not failed_init or control)
        obs = dict(result=(0 if action else (-17 if index == 2 else -12)),
                   fault_hits=int(index in (1, 3)),
                   source_allocations=(0 if index == 1 else (2 if index == 2 else 1)),
                   source_frees_final=(0 if index == 1 else (2 if index == 2 else 1)),
                   action_present=int(action), action_resets=int(index == 3),
                   capable_after_release=int(failed_init and not control),
                   device_releases=1, final_sources=0)
        if row['observations'] != obs or any(type(v) is not int for v in row['observations'].values()):
            raise ValueError('Changed managed-wakeup ownership observation: ' + row['name'])
    return rows


def prepare(root, archive, lock, directory):
    """Extract only two locked headers; apply relevant production hunks and 0072."""
    names = (HEADER, DEVRES_HEADER)
    prefix = 'linux-' + lock['linux']['tag'][1:] + '/'
    remaining = set(names)
    with tarfile.open(archive, 'r|xz') as stream:
        for member in stream:
            relative = member.name.removeprefix(prefix)
            if relative in remaining and member.name == prefix + relative:
                target = directory / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(stream.extractfile(member).read())
                remaining.remove(relative)
                if not remaining:
                    break
    if remaining:
        raise ValueError('Locked inline header absent: ' + ', '.join(sorted(remaining)))
    selected = []
    for path in sorted((root / 'kernel/patches').glob('*.patch')):
        chunks = re.split(r'(?=^diff --git )', path.read_text(), flags=re.M)
        relevant = [chunk for chunk in chunks if any(
            chunk.startswith('diff --git a/' + name + ' ') for name in names)]
        if relevant:
            subprocess.run(['patch', '--batch', '--fuzz=0', '-p1'], cwd=directory,
                           input=''.join(relevant), text=True, check=True)
            selected.append(path)
    before = (directory / HEADER).read_text()
    patch = root / PATCH
    subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)],
                   cwd=directory, check=True)
    selected.append(patch)
    return before, (directory / HEADER).read_text(), (directory / DEVRES_HEADER).read_text(), selected
