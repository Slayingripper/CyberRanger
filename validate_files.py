#!/usr/bin/env python3
import yaml, json, sys

errors = []

for f in ['scenarios/basic-pentest.yaml', 'scenarios/sl1-2-smart-home-pv.yaml', 'scenarios/sl1-2-smart-home-pv-3vm.yaml']:
    try:
        data = yaml.safe_load(open(f))
        sources = (data.get('scenario') or {}).get('sources') or {}
        print(f"{f}: OK ({len(sources)} sources)")
        for k, v in sources.items():
            if isinstance(v, dict):
                checks = []
                if 'sha256' in v or 'archive_sha256' in v:
                    checks.append('checksum')
                if 'min_bytes' in v:
                    checks.append('min_bytes')
                print(f"  {k}: {checks if checks else ['none']}")
    except Exception as e:
        errors.append(f"{f}: {e}")
        print(f"{f}: FAIL - {e}")

for f in ['backend/trainings/example-scenario.json']:
    try:
        data = json.load(open(f))
        sources = data.get('sources') or {}
        print(f"{f}: OK ({len(sources)} sources)")
        for k, v in sources.items():
            if isinstance(v, dict):
                checks = []
                if 'sha256' in v:
                    checks.append('checksum')
                if 'min_bytes' in v:
                    checks.append('min_bytes')
                print(f"  {k}: {checks if checks else ['none']}")
    except Exception as e:
        errors.append(f"{f}: {e}")
        print(f"{f}: FAIL - {e}")

if errors:
    print(f"\n{len(errors)} errors found!")
    sys.exit(1)
else:
    print("\nAll files valid!")
