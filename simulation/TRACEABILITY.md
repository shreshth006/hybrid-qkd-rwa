# Traceability: report → code → data

Every equation, algorithm step and parameter in the Review 3 report, and every number in its results section, can be traced to a specific place in `tdpc_rwa_simulator.py` and to a specific CSV file. Line numbers refer to the current version of the file.

**Live proof for the viva:**

```bash
.venv/bin/python verify_values.py      # recomputes Eqs. (1)-(6) by hand and rebuilds Table 2 from individual runs
```

## 1. Equations (report Section 7)

| Report | What it computes | Function | Line |
|---|---|---|---|
| Eq. (1), Raman noise sum N_R | Σ κ_j·P_j over co-propagating segments | `calc_raman_noise`, used by `Simulator.q_noise` | 140, 454 |
| κ_{j,q}, sensitivity coefficient | γ_nl·e^(−α_c d)·(e^(−α_c l) − e^(−α_q l)) | `calc_kappa`; shared length l and offset d found by `Simulator._kappa` | 132, 445 |
| Eq. (2), QSNR | 10·log10(e^(−α_q L)·P_tx,q / (N_F + N_R)), with P_tx,q = μ_p·η_D | `quantum_signal`, `calc_qsnr_db`, `Simulator.qsnr` | 146, 153, 460 |
| Eq. (3), P_min and power bounds | P_rx,min / (e^(−α_c L)·η), floor (1+m_floor), P_max | `calc_classical_power_bounds` | 158 |
| Eq. (4), ΔN* | noise to remove to reach Γ_Q + ε | `calc_target_noise_reduction` | 164 |
| Eq. (5), betweenness C_B | top-K hubs, length-weighted | `select_oeo_hubs` (`networkx.betweenness_centrality`) | 240 |
| Eq. (6), BB84 key rate | asymptotic decoy-state bound, H2 = binary entropy | `calc_bb84_skr`, `h2` | 177, 169 |
| R_{s→d} = min over segments | trusted-relay bottleneck | `chain_skr` | 191 |

## 2. Algorithm 1: closed-loop T-DPC (report Section 7.4)

The loop runs every Δt = 1 s inside `Simulator._telemetry_proc` (line 829).

| Algorithm 1 line | Code | Line |
|---|---|---|
| 1–2: poll QSNR, SNR, η, N; recompute κ and P_min | `_telemetry_proc` → `_drift_and_repair` (η random walk) and `qsnr()`, which recomputes the noise of any channel whose interferers changed | 829, 842 |
| 3: classical repair if SNR < SNR_th | `if s.power < p_min` → set to P_min(1+m_floor) | 848 |
| 4: at-risk set R, sorted by QSNR | `at_risk = sorted(... qsnr(q) < GUARD ...)` in `_control_loop` | 859 |
| 6: ΔN* and headroom H_q | `_control_loop` (calls `calc_target_noise_reduction`, sums κ·(P − P_floor)) | 857–872 |
| 7–9: Level 1 sensitivity-ordered throttling, steps of 0.5 dB | `if headroom >= dn:` → `_level1` (sorted by κ·P, `step = 10**(-Δp/10)`) | 873, 881, 885 |
| 11–12: Level 2, dominant interferer j* = argmax κ·P | `_level2`, `top = max(cands, key=κ·P)` | 908, 916 |
| 13: Algorithm 2 on the auxiliary graph, excluding q's links | `route_classical(..., exclude=q.links, thr=GUARD)` | 908–925 |
| 14: make, switch, break | `# MAKE` (new lightpath installed first), `# BREAK` (old one released) | 926, 930 |
| 15: otherwise re-route q itself | `_reroute_quantum` | 945 |
| 17: hysteresis recovery (+Δp when QSNR ≥ Γ_Q + ε + h) | `_recover`, check `GUARD + HYST` | 968, 980 |

## 3. Algorithm 2: online provisioning (report Section 7.4)

| Algorithm 2 line | Code | Line |
|---|---|---|
| 1–2: classical, k paths in MQCCO order, first-fit wavelength | `route_classical` with `_order_paths` and `_link_cost` (MQCCO doubling) | 570, 549, 541 |
| 3–6: layered auxiliary graph, conversion edges at O-E-O hubs | `_aux_graph_route` (Dijkstra over (node, λ) states, `W_CONV` at hubs with a free transponder) | 599, 630 |
| 7: P = P_min(1+m_0) | `_launch_power` | 530 |
| 8: accept only if every q stays ≥ Γ_Q + ε | `_qsnr_ok_with` | 556 |
| 9: block cause spectrum / QSNR | `self.last_cause = ...` | 596 |
| 11: quantum, direct single segment | `route_quantum` | 672 |
| 12–14: trusted-relay chain, highest bottleneck SKR | `route_quantum_chain` | 694 |
| 15: allocate quantum + 2 control + 1 data jointly, else roll back | `_handle_arrival` | 728 |
| 16: block cause spectrum / QSNR / reach | `route_quantum` sets `last_cause`; `_block` counts it | 691, 771 |

## 4. Parameters (report Table 1)

| Parameter | Constant | Line |
|---|---|---|
| W_q = 10, W_c = 40 | `W_Q`, `W_C` | 65–66 |
| α_q = 0.32, α_c = 0.17 dB/km | `ALPHA_Q_DB`, `ALPHA_C_DB` (converted to Np/km on the next lines) | 69–72 |
| γ_nl = 2.25e-4 | `GAMMA_NL` | 75 |
| η_D = 0.1, p_d = N_F = 1e-4 | `ETA_D`, `P_D`, `N_F` | 76–78 |
| μ_p = t_q | `MU_MODE = "transmittance"` | 82 |
| −36.8 dBm, P_max = 1 mW | `RX_SENS_DBM`, `P_MAX` | 85, 87 |
| Γ_Q = −5, ε = 1.5, h = 0.5 dB | `GAMMA_Q`, `EPSILON`, `HYST`, `GUARD` | 90–93 |
| m_0 = 0.25, m_floor = 0.05, Δp = 0.5 dB, Δt = 1 s | `M_0`, `M_FLOOR`, `DELTA_P_DB`, `DELTA_T` | 94–97 |
| R = 16 transponders, K and ∣T∣ by network size | `TRANSPONDERS`, `hubs_for`, `relays_for` | 110, 121–122 |
| bursts | `BURST_RATE`, `BURST_HOLD`, `BURST_FIXED_PROB` | 114–116 |

## 5. Report numbers → data files

All files are in `results_final/` (the 10 × 20,000-request campaign). After the 50 × 100,000-request run they will also be in `results_full50/`.

| Report item | Source file | Columns / how it is formed |
|---|---|---|
| Table 2 RBR (Gabriel, Waxman) | `table2_ablation.csv` | `rbr_gabriel`, `rbr_waxman` = mean of the 10 per-run `rbr` values in `raw_runs.csv` (experiment = ablation) |
| Table 2 mean QSNR, outage, SKR, power saved | `table2_ablation.csv` | `mean_qsnr_db`, `outage_pct`, `skr`, `power_saved_pct`, each the average of the Gabriel and Waxman means |
| Table 3 blocking causes, network SKR, ms/request | `table2_ablation.csv` | `rbr_spectrum`, `rbr_qsnr`, `rbr_reach`, `network_skr`, `ms_per_request` |
| Fig. 2(a), Fig. 3 curves | `sweep_results.csv` | `rbr`, `mean_qsnr`, `mean_skr` per load, with `*_ci` = 95% confidence interval |
| Fig. 2(b) stacked bars | `sweep_results.csv` at load 80 | `rbr_spectrum`, `rbr_qsnr`, `rbr_reach` |
| Fig. 4(a) trace | `demo_trace.csv`, `demo_events.csv` | QSNR before and after control each second, static-PC QSNR, every L1/L2 action |
| Fig. 4(b) K-sweep | `oeo_k_sweep.csv` | `c_rbr` per K and placement method |
| "−59.8% / −39.8%", "+8.2%", outage 1.40% → 0.04% | computed in `report/tools/build_report.py` from `table2_ablation.csv` | e.g. 1 − 0.0704 / 0.1751 = 59.8% |
| Mean degree, protocol size, burst sizes | `results_final.log` | printed by the simulator at start-up |

**How a single run's numbers are formed** (`Simulator.metrics`, line 1022):
- **RBR** = blocked requests ÷ requests arriving after the warm-up, counted in `_block` and `handle_arrival`.
- **Mean QSNR** and **SKR** = averages over every active quantum session, sampled once per simulated second in `_sample` (line 989).
- **Outage time %** = the share of those samples below Γ_Q.
- **Power saved %** = 1 − Σ P / (number of segments × P_max), sampled the same way.

**Chain**: `tdpc_rwa_simulator.py` run → `raw_runs.csv` (one row per run) → averaged into `table2_ablation.csv` / `sweep_results.csv` / `oeo_k_sweep.csv` → read by `report/tools/build_report.py` into the report. No result is typed in by hand.
