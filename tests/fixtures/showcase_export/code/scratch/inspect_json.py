import json, sys

path = sys.argv[1]
maxdepth = int(sys.argv[2]) if len(sys.argv) > 2 else 2
d = json.load(open(path))


def walk(o, p='', depth=0):
    if depth > maxdepth:
        return
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, dict):
                print(p + k + '/', '{' + ', '.join(list(v.keys())[:16]) + '}')
                walk(v, p + '  ', depth + 1)
            elif isinstance(v, list):
                print(p + k, '= list[%d]' % len(v), str(v[:2])[:160])
            else:
                print(p + k, '=', str(v)[:140])


walk(d)
