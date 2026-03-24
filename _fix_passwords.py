#!/usr/bin/env python3
import json, os

base = '/home/whitefalcon/gitstuff/CyberangeANU/backend/trainings'
for f in sorted(os.listdir(base)):
    if not f.endswith('.json'): continue
    path = os.path.join(base, f)
    d = json.load(open(path))
    changed = False
    for level in d.get('levels', []):
        t = level.get('topology')
        if not t: continue
        for vm in t.get('vms', []):
            ci = vm.get('cloud_init')
            if ci and 'password' in ci:
                print(f'{f}: {vm["name"]} had password={ci["password"]!r}')
                del ci['password']
                changed = True
    if changed:
        with open(path, 'w') as fh:
            json.dump(d, fh, indent=2)
        print(f'  -> Updated {f}')
print('Done')
