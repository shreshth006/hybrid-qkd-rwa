#!/usr/bin/env python3
"""
Shows where the numbers in the report come from.

Part A recomputes the physics equations by hand (plain math, constants typed in)
and checks each result against the simulator's own function.
Part B rebuilds the headline table values from the per-run raw data, so you can
show that every number in Table 2 is an average of individual simulation runs.

    .venv/bin/python verify_values.py                  # uses results_final/
    .venv/bin/python verify_values.py results_full50   # after the 50 x 100k run
"""
import csv
import math
import statistics
import sys

import tdpc_rwa_simulator as sim

RES = sys.argv[1] if len(sys.argv) > 1 else "results_final"


def line(title):
    print(f"\n{'─' * 92}\n{title}\n{'─' * 92}")


def check(label, by_hand, by_code, unit=""):
    ok = math.isclose(by_hand, by_code, rel_tol=1e-9, abs_tol=1e-12)
    print(f"  {label:<46} by hand = {by_hand:>12.6g} {unit:<6} simulator = {by_code:>12.6g} {unit:<6} {'MATCH' if ok else 'DIFFERENT'}")


# ============================================================================== PART A
line("PART A.  Physics equations, worked by hand and checked against the simulator code")

alpha_q = 0.32 / (10 * math.log10(math.e))       # dB/km -> Np/km
alpha_c = 0.17 / (10 * math.log10(math.e))
print(f"  α_q = 0.32 dB/km = 0.32 / 4.343 = {alpha_q:.4f} Np/km      α_c = 0.17 dB/km = {alpha_c:.4f} Np/km")
check("α_q (Np/km)", alpha_q, sim.ALPHA_Q)
check("α_c (Np/km)", alpha_c, sim.ALPHA_C)

# --- Eq. (2): QSNR of the demo's monitored link with no Raman noise
L = 43.6
t = math.exp(-alpha_q * L)                       # channel transmittance t_q
mu = t                                           # μ_p = t_q (report, Section 7.1)
p_tx = mu * 0.10                                 # P_tx,q = μ_p · η_D
signal = t * p_tx                                # numerator e^{-α_q L} P_tx,q
qsnr = 10 * math.log10(signal / 1e-4)            # denominator N_F = 1e-4, no Raman
print(f"\n  Eq. (2), monitored demo link, L_q = {L} km, no classical interferers:")
print(f"    t_q = e^(-{alpha_q:.4f} × {L}) = {t:.5f};  P_tx,q = μ_p·η_D = {t:.5f} × 0.10 = {p_tx:.6f}")
print(f"    QSNR = 10·log10( t_q·P_tx,q / N_F ) = 10·log10( {signal:.3e} / 1e-4 ) = {qsnr:+.2f} dB")
check("Eq. (2) QSNR, clean (dB)", qsnr, sim.calc_qsnr_db(L, 0.0), "dB")

# --- Eq. (1): Raman sensitivity κ of that link to one 1 mW channel on its 17.6 km bottleneck
l, d = 17.6, 0.0
kappa = 2.25e-4 * math.exp(-alpha_c * d) * (math.exp(-alpha_c * l) - math.exp(-alpha_q * l))
print(f"\n  Eq. (1)/κ, burst link 2-4: shared length l = {l} km starting d = {d} km into the classical path:")
print(f"    κ = γ_nl·e^(-α_c d)·(e^(-α_c l) − e^(-α_q l)) = 2.25e-4 × ({math.exp(-alpha_c * l):.5f} − {math.exp(-alpha_q * l):.5f}) = {kappa:.4e} per mW")
check("κ for 17.6 km overlap (per mW)", kappa, sim.calc_kappa(l, d))

# --- Burst 1: 7 channels at 1 mW on that link
n_burst = 7
N_R = n_burst * kappa * 1.0
q_burst = 10 * math.log10(signal / (1e-4 + N_R))
print(f"\n  Burst at t = 30 s: {n_burst} channels × 1 mW → N_R = {n_burst} × {kappa:.4e} = {N_R:.4e}")
print(f"    QSNR = 10·log10( {signal:.3e} / (1e-4 + {N_R:.3e}) ) = {q_burst:+.2f} dB   (trace log: −4.52 dB; the 0.01 dB")
print(f"    gap is only because the path length is rounded to 43.6 km here)")
check("QSNR with 7 burst channels (dB)", q_burst, sim.calc_qsnr_db(L, N_R), "dB")

# --- Eq. (4): noise reduction needed to get back to the -3.5 dB guard
dN = 1e-4 + N_R - signal / 10 ** (-3.5 / 10)
print(f"\n  Eq. (4): ΔN* = N_F + N_R − signal / 10^(−3.5/10) = {dN:.4e}  (must remove this much noise)")
check("Eq. (4) ΔN*", dN, sim.calc_target_noise_reduction(L, N_R))
hq = n_burst * kappa * (1.0 - 0.0)
print(f"  Headroom H_q (managed channels can be throttled almost to zero) ≈ {hq:.3e} ≥ ΔN* → Level 1 throttling, as logged")

# --- Eq. (3): minimum classical launch power for a 50 km segment
Lc, eta = 50.0, 1.0
p_rx = 10 ** (-36.8 / 10)
p_min = p_rx / (math.exp(-alpha_c * Lc) * eta)
print(f"\n  Eq. (3), classical segment of {Lc} km: P_min = 10^(−36.8/10) mW / e^(−α_c·L) = {p_rx:.3e} / {math.exp(-alpha_c * Lc):.4f} = {p_min:.4e} mW")
check("Eq. (3) P_min (mW)", p_min, sim.calc_classical_power_bounds(Lc, eta)[0], "mW")
print(f"  vs P_max = 1 mW without power control → {100 * (1 - p_min):.2f}% less launch power (why 'Power saved' ≈ 98–99%)")

# --- Eq. (6): BB84 key rate for a 20 km clean segment
Lk = 20.0
tk = math.exp(-alpha_q * Lk); eta_ch = 0.10 * tk; mu_k = tk; y0 = 1e-4; e_d = (1 - 0.98) / 2


def h2(x):
    return 0.0 if x <= 0 else 1.0 if x >= 0.5 else -x * math.log2(x) - (1 - x) * math.log2(1 - x)


q_mu = y0 + 1 - math.exp(-eta_ch * mu_k)
e_mu = (0.5 * y0 + e_d * (1 - math.exp(-eta_ch * mu_k))) / q_mu
y1 = y0 + eta_ch; e1 = (0.5 * y0 + e_d * eta_ch) / y1; q1 = y1 * mu_k * math.exp(-mu_k)
R = max(0.0, 0.5 * (-q_mu * 1.16 * h2(e_mu) + q1 * (1 - h2(e1))))
print(f"\n  Eq. (6), BB84 key rate on a clean {Lk} km segment: Q_μ = {q_mu:.4e}, E_μ = {e_mu:.4f}, Q_1 = {q1:.4e}, e_1 = {e1:.4f}")
print(f"    R = ½[−Q_μ·f_EC·H2(E_μ) + Q_1·(1 − H2(e_1))] = {R:.4e} bits/pulse")
check("Eq. (6) SKR (bits/pulse)", R, sim.calc_bb84_skr(Lk, 0.0))

# ============================================================================== PART B
line(f"PART B.  Table 2 values rebuilt from individual runs ({RES}/raw_runs.csv)")
raw = list(csv.DictReader(open(f"{RES}/raw_runs.csv")))
tab = {r["model"]: r for r in csv.DictReader(open(f"{RES}/table2_ablation.csv"))}


def runs(config, topo, metric="rbr"):
    return [float(r[metric]) for r in raw if r["experiment"] == "ablation" and r["config"] == config and r["topo"] == topo]


for config, label in [("MQCCO + Static PC", "3. Base Paper MQCCO + Static PC"),
                      ("Full T-DPC-RWA", "9. Full Proposed T-DPC-RWA Framework")]:
    for topo in ("gabriel", "waxman"):
        v = runs(config, topo)
        mean = statistics.fmean(v)
        print(f"\n  {config} on 20-node {topo.capitalize()}, 80 Erlang: {len(v)} runs (one per realisation)")
        print("    per-run RBR: " + ", ".join(f"{x:.4f}" for x in v))
        print(f"    mean = sum / {len(v)} = {mean:.4f}   (95% CI ±{1.96 * statistics.stdev(v) / math.sqrt(len(v)):.4f})")
        check(f"RBR {topo} in table2_ablation.csv", mean, float(tab[label][f"rbr_{topo}"]))

mq_g, fu_g = statistics.fmean(runs("MQCCO + Static PC", "gabriel")), statistics.fmean(runs("Full T-DPC-RWA", "gabriel"))
mq_w, fu_w = statistics.fmean(runs("MQCCO + Static PC", "waxman")), statistics.fmean(runs("Full T-DPC-RWA", "waxman"))
print(f"\n  Reduction quoted in the abstract: Gabriel (1 − {fu_g:.4f}/{mq_g:.4f}) = {100 * (1 - fu_g / mq_g):.1f}%,"
      f"  Waxman (1 − {fu_w:.4f}/{mq_w:.4f}) = {100 * (1 - fu_w / mq_w):.1f}%")

one = next(r for r in raw if r["experiment"] == "ablation" and r["config"] == "Full T-DPC-RWA" and r["topo"] == "gabriel")
print(f"\n  How one run's RBR is formed (realisation seed {one['seed']}): RBR = blocked requests / arrivals measured after warm-up,")
print(f"  counted in Simulator._block() and Simulator.handle_arrival(); this run measured {int(float(one['arrivals'])):,} arrivals → RBR = {float(one['rbr']):.4f}")
print(f"  Blocked share by cause in this run: spectrum {float(one['rbr_spectrum']):.4f}, QSNR {float(one['rbr_qsnr']):.4f}, reach {float(one['rbr_reach']):.4f}")
print("\nEvery report number follows this chain: simulator run → raw_runs.csv → averaged into table2_ablation.csv /"
      "\nsweep_results.csv / oeo_k_sweep.csv → read by report/tools/build_report.py into the document.\n")
