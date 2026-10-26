# T-DPC-RWA: Dynamic RWA for Hybrid QKD Networks

Dynamic Routing and Wavelength Assignment for Hybrid QKD Networks with Adaptive Power Control and Sparse Wavelength Conversion. It extends Ruiz & Garcia-Escartin, *Computer Communications* 256 (2026) 108572.

| Folder | Contents |
|---|---|
| `simulation/` | Discrete-event simulator (`tdpc_rwa_simulator.py`), results, figures, `verify_values.py`, `TRACEABILITY.md` |
| `report/` | Review 3 report (`Review_3_completed.docx` / `.pdf`) and the scripts that build it from the simulation results |
| `run_full_and_rebuild.sh` | Runs the full 50 × 100,000-request campaign and rebuilds the report |

## Quick start

```bash
cd simulation
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python tdpc_rwa_simulator.py --mode demo   # ~22 s: live telemetry trace, tables, figures
.venv/bin/python verify_values.py                    # shows where every report number comes from
```

See `simulation/README.md` for all options and modelling assumptions, and `simulation/TRACEABILITY.md` for the equation → code → data mapping.
