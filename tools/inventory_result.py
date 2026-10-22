"""Replay raw charging inventory on the host without collector or device I/O."""
import hashlib
import json
from pathlib import Path

from awake_clock import validate as validate_awake
from charge_result import checkpoint
import charge_inventory as inventory


def require(condition, message):
    if not condition:
        raise ValueError('Inventory result: ' + message)


def unique_object(pairs):
    value = {}
    for key, entry in pairs:
        require(key not in value, 'duplicate JSON member')
        value[key] = entry
    return value


def admit(result, *, kernel, image):
    """Check saved-stream consistency, not fresh device/image or electrical proof."""
    require(all(type(value) is str and bool(value) for value in (kernel, image)),
            'invalid expected operation')
    require(type(result) is dict and type(result.get('schema_version')) is int and
            result['schema_version'] == inventory.SCHEMA_VERSION and
            result.get('kind') == 'axp223-charge-inventory' and result.get('completed') is True and
            result.get('kernel') == kernel and type(result.get('image')) is dict and
            result['image'].get('kernel') == kernel and result['image'].get('version') == image and
            result['image'].get('board') == 'gameshellneo-cpi31' and result.get('limits') == inventory.LIMITS,
            'missing or changed inventory identity, schema or limits')
    profile, volatile = inventory.profile_for(kernel, image)
    masked = (image, kernel) in (inventory.MASKED_ADC_PROFILE, inventory.NO_LEGACY_PTY_PROFILE)
    require(result.get('cache_profile') == profile and type(result.get('adc_width_masked')) is bool and
            result['adc_width_masked'] == masked, 'profile or ADC-width claim differs')
    try:
        meta = result['metadata']
        require(type(meta) is dict and set(meta) == {'name', 'range', 'access', 'cache_only', 'cache_bypass'} and
                all(type(value) is str for value in meta.values()), 'missing metadata fields')
        inventory.validate_metadata(meta, volatile)
        supplies = result['supplies']
        fields = {
            'axp20x-battery': {'type', 'present', 'status', 'health', 'capacity', 'current_now',
                              'voltage_now', 'voltage_max', 'constant_charge_current',
                              'constant_charge_current_max'},
            'axp20x-usb': {'type', 'present', 'online', 'input_current_limit'},
            'axp22x-ac': {'type', 'present', 'online'},
        }
        require(type(supplies) is dict and set(supplies) == set(fields) and
                all(type(supplies[name]) is dict and set(supplies[name]) == names and
                    all(type(value) is str for value in supplies[name].values())
                    for name, names in fields.items()), 'missing supply strings or containers')
        registers = result['registers']
        require(type(registers) is dict and set(registers) == {f'{n:02x}' for n in inventory.REGISTERS},
                'missing or unexpected registers')
        first, first_observation = checkpoint(result['before'])
        last, last_observation = checkpoint(result['after'])
        inventory.validate_continuity(first, last)
        observations = [first_observation]
        for address in inventory.REGISTERS:
            entry = registers[f'{address:02x}']
            source = 'volatile-regmap-read' if address in volatile else 'regmap-cache-possible'
            require(type(entry) is dict and type(entry.get('value')) is int and
                    0 <= entry['value'] <= 255 and entry.get('source') == source,
                    'invalid register byte or source claim')
            for point in ('before', 'after'):
                # Register clocks have no independently read boot/PM counters.
                # This explicit wrapper carries observed boundary context only.
                _, observation = checkpoint(dict(boot_id=first['boot_id'], pm=first['pm'],
                                                 clock=entry[point]))
                observations.append(observation)
        observations.append(last_observation)
        validation = validate_awake(observations)
        assessment = inventory.decode(registers, adc_width_masked=masked)
        stored = result.get('assessment')
        require(type(stored) is dict and json.dumps(stored, sort_keys=True, allow_nan=False) ==
                json.dumps(assessment, sort_keys=True, allow_nan=False),
                'stored assessment differs from raw registers and admitted profile')
    except (KeyError, TypeError, IndexError, OverflowError) as error:
        raise ValueError('Inventory result: incomplete or malformed raw evidence') from error
    return dict(schema=1, operation='host-charge-inventory-result-admission', expected_kernel=kernel,
        expected_image=image, boot_id=first['boot_id'], cache_profile=profile, adc_width_masked=masked,
        register_count=len(inventory.REGISTERS), awake_validation=validation,
        register_clock_context='Boot/PM context comes from observed boundary checkpoints; '
            'register read clocks have no independent boot/PM observations.',
        metadata_limit='One returned metadata snapshot; a second producer snapshot is not independently replayed.',
        assessment=assessment, limits=list(inventory.LIMITS), calibrated=False,
        charging_safety_qualified=False, sleep_charge_measured=False,
        current_device_or_image_admitted=False, clock_reliability_qualified=False)


def admit_capture(path, *, kernel, image):
    """Keep original bytes on every refusal and exclusively save successful replay."""
    path = Path(path)
    raw = path.read_bytes()
    result = json.loads(raw, object_pairs_hook=unique_object)
    admitted = admit(result, kernel=kernel, image=image)
    with path.with_suffix('.admission.json').open('x') as output:
        json.dump(dict(admitted, raw_sha256=hashlib.sha256(raw).hexdigest()), output, indent=2)
        output.write('\n')
    return admitted
