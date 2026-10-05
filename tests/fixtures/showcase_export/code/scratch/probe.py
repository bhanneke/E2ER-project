import json
import math

spec = json.load(open("identification_spec.json"))["primary"]
e = json.load(open("estimation_results.json"))
r = json.load(open("robustness_results.json"))
m = e["main"]

ok = True
print("declared FE:", spec["fixed_effects"], "| main FE:", m["fixed_effects"])
for fe in spec["fixed_effects"]:
    if fe not in m["fixed_effects"]:
        print("  FAIL missing FE", fe); ok = False
print("declared controls:", spec["controls"], "| main controls:", m["controls"])
for c in spec["controls"]:
    if c not in m["controls"] and c not in m["coefficients"]:
        print("  FAIL missing control", c); ok = False
print("declared cluster:", spec["cluster_level"], "| main:", m["cluster_level"],
      "n_clusters:", m["n_clusters"])
if m["cluster_level"] != spec["cluster_level"] or not m["n_clusters"]:
    print("  FAIL cluster"); ok = False
print("declared outcome:", spec["outcome"], "| main outcome:", m["outcome"])
print("declared unit:", spec["unit_of_analysis"], "| main unit:", m["unit_of_analysis"])
print("main diagnostics:", m["diagnostics"])
if any(v is None for k, v in m["diagnostics"].items() if k != "note"):
    print("  WARN null diagnostic"); ok = False
print("main is first key:", list(e.keys())[0] == "main")

REQ = ["specification", "n_observations", "n_clusters", "cluster_level", "fixed_effects",
       "controls", "coefficients", "diagnostics", "n_pre_treatment", "n_post_treatment"]
for fname, obj in [("estimation_results.json", e), ("robustness_results.json", r)]:
    for k, v in obj.items():
        miss = [f for f in REQ if f not in v]
        if miss:
            print(f"  {fname}:{k} missing {miss}"); ok = False


def walk(o, path=""):
    bad = []
    if isinstance(o, dict):
        for k, v in o.items():
            bad += walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            bad += walk(v, f"{path}[{i}]")
    elif isinstance(o, float) and not math.isfinite(o):
        bad.append(path)
    elif isinstance(o, str) and o.strip() in ("NaN", "N/A", "nan", "Infinity"):
        bad.append(path)
    return bad


for fname, obj in [("estimation_results.json", e), ("robustness_results.json", r)]:
    b = walk(obj)
    print(fname, "keys:", len(obj), "| non-finite/NA leaves:", b if b else "none")

overlap = set(e) & set(r)
print("key overlap between the two files:", overlap if overlap else "none")
print("\nRESULT:", "PASS" if ok else "FAIL")
