import collections
import json
import pathlib
import struct

r = pathlib.Path(r'V:\给泽强\2.7版本\mesh\2.7.5新\藏经阁')
for block in ('Block_0', 'Block_1'):
    j = json.loads((r / '3dtiles' / block / 'tileset.json').read_text())
    counts = collections.Counter()
    uris = []
    def visit(n, depth=0):
        counts[(depth, bool(n.get('content')), bool(n.get('children')))] += 1
        if n.get('content'):
            uris.append(n['content']['uri'])
        if depth < 3:
            print(depth, {k:v for k,v in n.items() if k not in ['children', 'boundingVolume']})
        for c in n.get('children', []):
            visit(c, depth+1)
    visit(j['root'])
    print(block, counts, 'uris', len(uris), len(set(uris)), uris[:8])
print('extensions', collections.Counter(p.suffix for p in (r/'3dtiles').rglob('*') if p.is_file()))
with (r/'obj/Model.obj').open() as f:
    print(''.join(next(f) for _ in range(12)))
for path in [r/'glb/Model.glb', next((r/'3dtiles/Block_0').glob('*.glb'))]:
    with path.open('rb') as f:
        head=f.read(20)
        j=json.loads(f.read(struct.unpack('<I',head[12:16])[0]))
    print(path.name, 'extensions', j.get('extensionsUsed'), 'nodes', str(j.get('nodes'))[:500])
