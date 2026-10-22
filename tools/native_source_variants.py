"""Execute extracted C candidates and require assertion failures for mutations."""
import resource
import subprocess

from kernel_checks import run, sha256


def run_variants(work, header, functions, variants, harness, flags, expected):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    results = {}
    try:
        for name, value in variants.items():
            header.write_text(value)
            binary = work / name
            run(['cc', *flags, '-I', str(work), str(harness), '-o', str(binary)])
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            log = work / (name + '.log')
            log.write_text(result.stdout + result.stderr)
            if name == 'candidate':
                result.check_returncode()
                if result.stdout.strip() != expected:
                    raise ValueError('Incomplete source scenario result')
            elif result.returncode == 0 or 'Assertion' not in result.stderr:
                raise RuntimeError('Negative control did not fail an assertion: ' + name)
            results[name] = dict(returncode=result.returncode, stdout=result.stdout.strip(),
                                 stderr=result.stderr.strip(), extracted_sha256=sha256(header),
                                 binary_sha256=sha256(binary), log_sha256=sha256(log))
            print(name + ': ' + (result.stdout.strip() or 'expected assertion failure'), flush=True)
    finally:
        header.write_text(functions)
    return results
