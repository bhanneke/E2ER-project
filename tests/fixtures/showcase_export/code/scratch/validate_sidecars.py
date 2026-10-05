"""Validate the two machine-readable sidecars before handoff."""
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
ok = True

for fn in ("summary_statistics.json", "figure_spec.json"):
    p = os.path.join(ROOT, fn)
    raw = open(p).read()
    for bad in ("NaN", "Infinity", '"N/A"', "-999"):
        if bad in raw:
            print("FAIL %s contains %s" % (fn, bad)); ok = False
    obj = json.loads(raw)
    print("%-26s parses OK, %d bytes" % (fn, len(raw)))

s = json.load(open(os.path.join(ROOT, "summary_statistics.json")))
for k in ("n_observations", "n_units", "time_coverage", "outcome", "sample_flow"):
    if k not in s:
        print("FAIL missing mandatory key %s" % k); ok = False
for k in ("start_iso", "end_iso", "n_periods"):
    if k not in s["time_coverage"]:
        print("FAIL time_coverage missing %s" % k); ok = False
for k in ("mean", "sd", "min", "p25", "median", "p75", "max"):
    if k not in s["outcome"]:
        print("FAIL outcome missing %s" % k); ok = False
last = s["sample_flow"][-1]
if last["n"] != s["n_observations"]:
    print("FAIL sample_flow last n=%s != n_observations=%s" % (last["n"], s["n_observations"])); ok = False
else:
    print("sample_flow last step n == n_observations == %d" % last["n"])


def leaves(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from leaves(v, path + "." + str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from leaves(v, path + "[%d]" % i)
    else:
        yield path, o


bad_leaves = [(p, v) for p, v in leaves(s)
              if not isinstance(v, (int, float, type(None))) and not isinstance(v, bool)]
strkeys = [p for p, v in bad_leaves if isinstance(v, str)]
print("non-numeric leaves in summary_statistics.json: %d (expected: step labels + ISO dates)"
      % len(strkeys))

f = json.load(open(os.path.join(ROOT, "figure_spec.json")))
print("figures: %d" % len(f["figures"]))
total_pts = 0


def check_ts(spec, tag):
    global ok, total_pts
    for sr in spec.get("series", []):
        n = len(sr["x"])
        total_pts += n
        if n != len(sr["y"]):
            print("FAIL %s series '%s' x/y length mismatch %d vs %d"
                  % (tag, sr["label"], n, len(sr["y"]))); ok = False
        if n == 0:
            print("FAIL %s series '%s' is empty" % (tag, sr["label"])); ok = False


for fig in f["figures"]:
    tag = fig["filename"]
    assert "label" in fig and "caption_hint" in fig, tag
    t = fig["figure_type"]
    if t == "time_series":
        check_ts(fig, tag)
        print("  %-38s time_series, %d series" % (tag, len(fig["series"])))
    elif t == "multi_panel":
        for p in fig["panels"]:
            check_ts(p, tag)
        print("  %-38s multi_panel, %d panels" % (tag, len(fig["panels"])))
    elif t == "bar":
        n = len(fig["categories"])
        total_pts += n
        if not (n == len(fig["values"]) == len(fig["errors"])):
            print("FAIL %s bar lengths differ" % tag); ok = False
        print("  %-38s bar, %d categories: %s" % (tag, n, fig["categories"]))
    else:
        print("  %-38s %s" % (tag, t))

print("total data points across figures: %d (limit ~10000 per figure)" % total_pts)
print("VALIDATION %s" % ("PASS" if ok else "FAIL"))
