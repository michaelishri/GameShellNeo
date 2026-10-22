"""Retain independent KUnit binaries, configuration and raw result files."""
import shutil
import uuid

from kernel_checks import sha256


def retain_run(root, scratch):
    """Detach accepted artifacts from paths that subsequent Kbuild/KUnit runs reuse."""
    accepted = scratch / 'accepted-runs' / uuid.uuid4().hex
    accepted.mkdir(parents=True, mode=0o700)
    record = dict(scratch=str(scratch.relative_to(root)),
                  artifact_dir=str(accepted.relative_to(root)))
    for field, path, name in (
        ('kernel_sha256', scratch / 'output/linux', 'linux'),
        ('config_sha256', scratch / 'output/.config', 'config'),
        ('log_sha256', scratch / 'output/test.log', 'test.log'),
        ('report_sha256', scratch / 'results.json', 'results.json'),
    ):
        digest = sha256(path)
        shutil.copyfile(path, accepted / name)
        if sha256(accepted / name) != digest:
            raise RuntimeError('Accepted artifact changed during retention: ' + name)
        record[field] = digest
    return record
