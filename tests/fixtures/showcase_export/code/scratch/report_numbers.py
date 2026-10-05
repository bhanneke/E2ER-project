"""Print the realized numbers that back-fill section 7 of data_summary.md."""
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
s = json.load(open(os.path.join(ROOT, "summary_statistics.json")))

print("TOP LEVEL")
for k in ("n_observations", "n_units", "n_periods", "n_daily_observations_crypto", "n_nyse_sessions"):
    print("  %-32s %s" % (k, s[k]))
print("  time_coverage", s["time_coverage"])
print("  estimation_panel_coverage", s["estimation_panel_coverage"])
print()
print("OUTCOME (headline sample, fisher-z):", s["outcome"])
print("RHO :", s["outcome_rho"])
print("BETA:", s["outcome_beta"])
print("RHO2:", s["outcome_rho2"])
print("LNSIG:", s["ln_sigma_ratio"])
print("NDAYS:", s["n_days_m"])
print()
print("PRE  :", s["subsample_pre_2024_01_10"])
print("POST :", s["subsample_post_2024_01_10"])
print()
print("BY GROUP:", json.dumps(s["by_group"], indent=1))
print()
for leg in ("SPY", "MKT"):
    c = s["raw_contrast"][leg]
    b = c["by_asset"]["BTC"]
    print("== leg %s ==" % leg)
    print("  BTC monthly-mean rho  %.4f -> %.4f  d=%+.4f" % (b["mean_rho_pre"], b["mean_rho_post"], b["d_mean_rho"]))
    print("  BTC monthly-mean beta %.4f -> %.4f  d=%+.4f" % (b["mean_beta_pre"], b["mean_beta_post"], b["d_mean_beta"]))
    print("  BTC pooled-daily rho  %.4f -> %.4f  d=%+.4f  (n_pre=%d n_post=%d)"
          % (b["pooled_daily_rho_pre"], b["pooled_daily_rho_post"], b["d_pooled_daily_rho"],
             b["n_days_pre"], b["n_days_post"]))
    print("  BTC pooled-daily beta %.4f -> %.4f  d=%+.4f"
          % (b["pooled_daily_beta_pre"], b["pooled_daily_beta_post"], b["d_pooled_daily_beta"]))
    print("  BTC fisher-z          %.4f -> %.4f  d=%+.4f" % (b["mean_fisherz_pre"], b["mean_fisherz_post"], b["d_mean_fisherz"]))
    cg = c["control_group_mean"]
    print("  CTRL rho  %.4f -> %.4f  d=%+.4f | beta %.4f -> %.4f d=%+.4f | pooled rho d=%+.4f beta d=%+.4f"
          % (cg["mean_rho_pre"], cg["mean_rho_post"], cg["d_mean_rho"],
             cg["mean_beta_pre"], cg["mean_beta_post"], cg["d_mean_beta"],
             cg["d_pooled_daily_rho"], cg["d_pooled_daily_beta"]))
    print("  DiD:", {k: round(v, 4) for k, v in c["did_raw"].items() if v is not None})
    for a in ("GLD", "SLV", "ETH", "ALTIDX_EW"):
        if a in c["by_asset"]:
            x = c["by_asset"][a]
            print("  %-10s rho %.4f -> %.4f d=%+.4f | beta %.4f -> %.4f d=%+.4f"
                  % (a, x["mean_rho_pre"], x["mean_rho_post"], x["d_mean_rho"],
                     x["mean_beta_pre"], x["mean_beta_post"], x["d_mean_beta"]))
    print()
print("ETF:", json.dumps(s["etf"], indent=1))
print("MISSINGNESS:", json.dumps(s["missingness"], indent=1))
print("DAILY RETURNS BTC:", s["daily_returns"]["BTC"])
print("DAILY RETURNS SPY:", s["daily_returns"]["SPY"])
print("MACRO vix:", s["macro"]["vix"])
