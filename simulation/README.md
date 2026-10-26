# T-DPC-RWA simulator

A discrete-event simulator for **Dynamic Routing and Wavelength Assignment for Hybrid QKD Networks with Adaptive Power Control and Sparse Wavelength Conversion**. Its outputs follow the layout of the Review 3 report: Table 1, Figs. 2–4 and Table 2. It extends Ruiz & Garcia-Escartin, *Computer Communications* 256 (2026) 108572.

## Setup and run

```bash
cd hybrid-qkd-rwa/simulation
.venv/bin/pip install -r requirements.txt          # the venv already exists on this machine
.venv/bin/python tdpc_rwa_simulator.py --mode demo # ~22 s on 12 cores
.venv/bin/python tdpc_rwa_simulator.py --mode full # 50 realisations, 10k warm-up + 100k requests per run
```

`--mode full` with the report's stated protocol (100,000 measured requests, 50 realisations) takes roughly **4–6 hours** on this machine. A Full T-DPC-RWA run alone takes about 70 s at 80 Erl. Use `--requests 20000` for about an hour, or `--seeds 10` to cut it further. Whatever you run, the report should state exactly that.

| Flag | Default | Meaning |
|---|---|---|
| `--mode demo\|full` | `demo` | Demo: 3 realisations, loads 20–100, 300 s measured window. Full: 50 realisations, loads 10–100, request-count windows |
| `--seeds N` | 3 / 50 | Independent topology + traffic realisations |
| `--requests N` | – / 100000 | Measured requests per run (warm-up = N/10) |
| `--sweep-topo`, `--sweep-nodes` | `waxman`, `20` | Topology for Figs. 2 and 3 |
| `--oeo-topo`, `--oeo-load` | `gabriel`, `250` | Setting for the Fig. 4(b) K-sweep (see below) |
| `--procs`, `--outdir`, `--skip-trace`, `--no-color` | | Parallelism, output folder, skip the live trace, plain output |

## Outputs (report numbering)

| Report | File / console output | Content |
|---|---|---|
| Table 1 | console | Parameters, with Base paper / Proposed work / Simulation assumption sources |
| Fig. 2 | `fig1_rbr.png` | (a) RBR vs load, 20-node Waxman, log scale; (b) blocking causes at 80 Erl: spectrum, QSNR, reach |
| Fig. 3 | `fig2_qsnr_skr.png` | (a) mean QSNR vs load; (b) decoy-state BB84 SKR (×10⁻³ bits/pulse) |
| Fig. 4 | `fig3_telemetry_oeo.png` | (a) 100 s QSNR trajectory with bursts at 30 s and 65 s, static PC vs T-DPC; (b) classical RBR vs K for betweenness, random and traffic-weighted degree |
| Table 2 | console + `table2_ablation.csv` | 9-configuration factorial ablation at 80 Erl, plus supplementary columns: blocking causes, network SKR, classical SNR violations, ms/request |
| – | `demo_trace.csv`, `demo_events.csv`, `sweep_results.csv`, `oeo_k_sweep.csv`, `raw_runs.csv` | Raw data behind every figure and table |

## Final results and the completed report

The numbers in `../report/Review_3_completed.docx` come from `results_final/` and `results_final.log`, produced by:

```bash
.venv/bin/python tdpc_rwa_simulator.py --mode full --seeds 10 --requests 20000 --outdir results_final > results_final.log
```

That is 780 runs, 10 realisations × 20,000 measured requests after a 2,000-request warm-up, and about 26 minutes on 12 cores. To regenerate the report from new results (needs `pandoc` and LibreOffice for the PDF):

```bash
cd ../report/tools
python3 build_report.py ../../simulation/results_final ../../simulation/results_final.log x
python3 make_docx.py ../Review_3_completed.docx
```

## Modelling choices you should be able to defend

- Raman noise is in detector-click probability per gate. It adds to N_F = p_d, and Y0 = N_F + N_R in the key-rate model.
- μ_p = t_q follows the report's Eq. (2) text. Set `MU_MODE = "fixed"` for a constant mean photon number.
- Bursts are lightpaths set up by an external fast path at 1 mW with no admission check. Managed bursts can be throttled. Fixed-power bursts can only be re-routed. They are applied identically to every configuration.
- Static PC uses the exact minimum power with no margin, so drift makes it violate the receiver sensitivity about half the time. T-DPC uses margin m_0 = 0.25 plus repair.
- T-DPC configurations admit at the −3.5 dB guard. Static ones admit at −5 dB.
- Blocking causes: **spectrum** means no continuous free wavelength on any candidate path. **QSNR** means a path existed but Raman cross-talk breaks the threshold. **Reach** means even a noise-free quantum channel is below threshold.
- Common random numbers: every configuration sees the same requests and bursts for a given realisation and load.
