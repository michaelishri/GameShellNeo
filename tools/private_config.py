"""Read .env as data, with no shell evaluation or credential logging."""
import os
from pathlib import Path
import shlex

ROOT = Path(__file__).resolve().parents[1]


def load_env(path=ROOT / '.env'):
    values = {}
    path = Path(path)
    if path.exists():
        for raw in path.read_text().splitlines():
            raw = raw.strip()
            if not raw or raw.startswith('#'):
                continue
            if raw.startswith('export '):
                raw = raw[7:]
            key, separator, value = raw.partition('=')
            if not separator:
                raise ValueError('Invalid .env assignment')
            tokens = shlex.split(value, comments=True)
            if len(tokens) > 1:
                raise ValueError('Quote .env values containing spaces')
            values[key.strip()] = tokens[0] if tokens else ''
    values.update({k: v for k, v in os.environ.items()
                   if k.startswith(('GAMESHELL_', 'M2_MACBOOK_AIR_', 'NEO_'))})
    return values
