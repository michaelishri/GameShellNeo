"""Deterministic clock evidence for measurement fixtures; no real sysfs reads."""
def observation(seconds=0, *, boot='boot', sleep_ns=0, success=0, fail=0, width_ns=100):
    start = int(seconds * 1e9)
    return dict(schema_version=1, boot_id=boot, monotonic_before_ns=start,
                boottime_ns=start + width_ns // 2 + sleep_ns,
                monotonic_after_ns=start + width_ns, pm_counts=dict(success=success, fail=fail))


def window(seconds=0, **kwargs):
    return [observation(seconds, **kwargs), observation(seconds + .001, **kwargs)]


def proof(seconds, **kwargs):
    return dict(schema_version=1, observations=[observation(0, **kwargs), observation(seconds + .01, **kwargs)])


def clock():
    index = 0
    def next_observation():
        nonlocal index
        index += 1
        return observation(index)
    return next_observation
