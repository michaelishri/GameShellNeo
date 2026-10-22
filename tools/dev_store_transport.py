"""Reuse the selected hardware checkout's existing pinned SSH implementation.

The caller must resolve its own artifact paths first: loading the established
hardware context changes the working directory, just like running its Tasks.
No credentials, keys or known-host records are copied or rewritten.
"""
import importlib.util
import os
from pathlib import Path
import sys


def load_hardware(path):
    """Return ``(remote_module, private_config_dict)`` from an explicit checkout."""
    if not path:
        raise ValueError('Select the established hardware checkout explicitly')
    selected = Path(path).expanduser().absolute()
    if ('..' in selected.parts or selected.resolve(strict=True) != selected or
            not selected.is_dir() or not (selected / '.git').exists()):
        raise ValueError('Hardware checkout must be an existing real Git checkout')
    directory = selected / 'tools'
    if directory.resolve(strict=True) != directory or not directory.is_dir():
        raise ValueError('Hardware tools directory must be real')
    loaded = {}
    # Import dependencies from that same checkout. Refuse an already imported
    # module from elsewhere instead of silently mixing access implementations.
    for name in ('private_config', 'host_timing', 'forward_socket',
                 'socket_observation', 'remote'):
        source = directory / (name + '.py')
        if source.resolve(strict=True) != source or not source.is_file():
            raise ValueError('Hardware helper must be an existing real file: ' + name)
        module = sys.modules.get(name)
        if module is None:
            spec = importlib.util.spec_from_file_location(name, source)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            try:
                spec.loader.exec_module(module)
            except BaseException:
                sys.modules.pop(name, None)
                raise
        origin = getattr(module, '__file__', None)
        if origin is None or Path(origin).resolve(strict=True) != source:
            raise ValueError('Imported hardware helper has a different origin: ' + name)
        loaded[name] = module
    remote = loaded['remote']
    if (Path(remote.ROOT) != selected or Path(remote.LOCAL) != selected / '.local' or
            remote.load_env is not loaded['private_config'].load_env):
        raise ValueError('Hardware SSH and private configuration contexts differ')
    config = loaded['private_config'].load_env(selected / '.env')
    os.chdir(selected)
    return remote, config
