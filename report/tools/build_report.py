"""Builds the completed Review-3 report (.docx) from the simulator's results.

Every number in Section 8, the abstract and the conclusion is read from the
CSV/log files the simulator wrote. Nothing in the results is typed in by hand.
"""
import csv
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import zipfile

RES = sys.argv[1]                       # simulator output directory
LOG = sys.argv[2]                       # simulator console log
OUT = sys.argv[3]                       # output .docx path
HERE = os.path.dirname(os.path.abspath(__file__))
PANDOC = os.environ.get("PANDOC") or shutil.which("pandoc") or "pandoc"


# ----------------------------------------------------------------------------- data
def rows(name):
    with open(os.path.join(RES, name)) as f:
        return list(csv.DictReader(f))


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


log = open(LOG).read()
abl = {r["model"].split(". ", 1)[1]: {k: num(v) if k not in ("model", "t_dpc", "oeo", "relays") else v
                                       for k, v in r.items()} for r in rows("table2_ablation.csv")}
sweep = [{k: (num(v) if k not in ("topo", "config") else v) for k, v in r.items()} for r in rows("sweep_results.csv")]
ks = [{k: (num(v) if k not in ("k_hubs", "hub_method") else v) for k, v in r.items()} for r in rows("oeo_k_sweep.csv")]
raw = rows("raw_runs.csv")
trace = [{k: num(v) for k, v in r.items()} for r in rows("demo_trace.csv")]
events = rows("demo_events.csv")

CFG = {"sp": "Baseline SP-FF (No Power Control)", "mqdo": "Base Paper MQDO + Static PC",
       "mqcco": "Base Paper MQCCO + Static PC", "qtd": "Base Paper QTD (Strict Disjoint)",
       "tdpc": "Proposed: T-DPC Loop Only", "oeo": "Proposed: Sparse O-E-O Only",
       "relay": "Proposed: Trusted Relays Only", "tdpcoeo": "Proposed: T-DPC + Sparse O-E-O",
       "full": "Full Proposed T-DPC-RWA Framework"}
A = {k: abl[v] for k, v in CFG.items()}


def sw(config, load, metric):
    r = next(x for x in sweep if x["config"] == config and x["load"] == load)
    return r[metric]


def kv(k, method, metric="c_rbr"):
    r = next(x for x in ks if x["k_hubs"] == k and x["hub_method"] in (method, "any"))
    return r[metric]


def raw_mean(experiment, topo, config, metric, load=None):
    vals = [num(r[metric]) for r in raw if r["experiment"] == experiment and r["topo"] == topo
            and r["config"] == config and (load is None or num(r["load"]) == load)]
    vals = [v for v in vals if not math.isnan(v)]
    return statistics.fmean(vals) if vals else float("nan")


def red(new, old):
    return 100 * (1 - new / old)


m = re.search(r"realisations=(\d+).*?\| (\d+) warm-up \+ (\d+) measured", log)
N_REAL, N_WARM, N_MEAS = int(m.group(1)), int(m.group(2)), int(m.group(3))
deg = re.search(r"Gabriel-20 ([\d.]+), Waxman-20 ([\d.]+)", log)
DEG_G, DEG_W = float(deg.group(1)), float(deg.group(2))
n_sims = int(re.search(r"Running (\d+) simulations", log).group(1))
burst = re.search(r"Burst 1 at t=30 s: (\d+) managed channels\. Burst 2 at t=65 s: (\d+) fixed-power", log)
N1, N2 = int(burst.group(1)), int(burst.group(2))
monitored = re.search(r"Monitored QKD link (\d+)->(\d+) on path ([\d-]+) \(([\d.]+) km\), clean QSNR ([+\-\d.]+) dB", log)
L1_STEPS = re.search(r"(\d+) step\(s\) of", log).group(1)
mbb65 = sum(1 for e in events if e["tag"] == "L2" and "MBB re-groom" in e["message"])
t30 = next(r for r in trace if r["t_s"] == 30.0)
t65 = next(r for r in trace if r["t_s"] == 65.0)
static_out = 100 * sum(r["static_pc_qsnr_db"] < -5 for r in trace) / len(trace)
tdpc_out = 100 * sum(r["tdpc_qsnr_after_control_db"] < -5 for r in trace) / len(trace)
static_min = min(r["static_pc_qsnr_db"] for r in trace)
k_topo, k_load = re.search(r"classical RBR vs O-E-O hubs K \(20-node (\w+), ([\d.]+) Erl\)", log).groups()
k0, k4b, k4r, k4t, kall = kv("0", "any"), kv("4", "betweenness"), kv("4", "random"), kv("4", "traffic"), kv("all", "any")
captured = 100 * (k0 - k4b) / (k0 - kall) if k0 > kall else float("nan")
cr80_w_k0 = raw_mean("ablation", "waxman", "T-DPC Only", "c_rbr")
cr80_w_k4 = raw_mean("ablation", "waxman", "T-DPC + O-E-O", "c_rbr")
cr80_g_k0 = raw_mean("ablation", "gabriel", "T-DPC Only", "c_rbr")
cr80_g_k4 = raw_mean("ablation", "gabriel", "T-DPC + O-E-O", "c_rbr")
reach_share_mqcco = A["mqcco"]["rbr_reach"] / (A["mqcco"]["rbr_spectrum"] + A["mqcco"]["rbr_qsnr"] + A["mqcco"]["rbr_reach"])

V = dict(  # formatted values used in the text
    real=N_REAL, warm=f"{N_WARM:,}", meas=f"{N_MEAS:,}", sims=f"{n_sims:,}", degg=f"{DEG_G:.2f}", degw=f"{DEG_W:.2f}",
    sp_w80=f"{sw('SP-FF (No PC)', 80, 'rbr'):.3f}", mq_w80=f"{sw('MQCCO + Static PC', 80, 'rbr'):.3f}",
    td_w80=f"{sw('T-DPC Only', 80, 'rbr'):.3f}", fu_w80=f"{sw('Full T-DPC-RWA', 80, 'rbr'):.3f}",
    sp_w10=f"{sw('SP-FF (No PC)', 10, 'rbr'):.3f}", fu_w10=f"{sw('Full T-DPC-RWA', 10, 'rbr'):.3f}",
    sp_w100=f"{sw('SP-FF (No PC)', 100, 'rbr'):.3f}",
    mq_w10=f"{sw('MQCCO + Static PC', 10, 'rbr'):.3f}", mq_w100=f"{sw('MQCCO + Static PC', 100, 'rbr'):.3f}",
    q_td80=f"{sw('T-DPC Only', 80, 'mean_qsnr'):.1f}",
    q_gain=f"{sw('Full T-DPC-RWA', 80, 'mean_qsnr') - sw('MQCCO + Static PC', 80, 'mean_qsnr'):.1f}", fu_w100=f"{sw('Full T-DPC-RWA', 100, 'rbr'):.3f}",
    red_w80=f"{red(sw('Full T-DPC-RWA', 80, 'rbr'), sw('MQCCO + Static PC', 80, 'rbr')):.1f}",
    red_g=f"{red(A['full']['rbr_gabriel'], A['mqcco']['rbr_gabriel']):.1f}",
    red_w=f"{red(A['full']['rbr_waxman'], A['mqcco']['rbr_waxman']):.1f}",
    reach_pct=f"{100 * reach_share_mqcco:.0f}",
    q_sp10=f"{sw('SP-FF (No PC)', 10, 'mean_qsnr'):.1f}", q_sp80=f"{sw('SP-FF (No PC)', 80, 'mean_qsnr'):.1f}",
    q_mq80=f"{sw('MQCCO + Static PC', 80, 'mean_qsnr'):.1f}", q_fu80=f"{sw('Full T-DPC-RWA', 80, 'mean_qsnr'):.1f}",
    s_sp80=f"{1e3 * sw('SP-FF (No PC)', 80, 'mean_skr'):.2f}", s_mq80=f"{1e3 * sw('MQCCO + Static PC', 80, 'mean_skr'):.2f}",
    s_fu80=f"{1e3 * sw('Full T-DPC-RWA', 80, 'mean_skr'):.2f}",
    ns_mq=f"{1e3 * A['mqcco']['network_skr']:.2f}", ns_fu=f"{1e3 * A['full']['network_skr']:.2f}",
    ns_gain=f"{100 * (A['full']['network_skr'] / A['mqcco']['network_skr'] - 1):.1f}",
    out_sp=f"{A['sp']['outage_pct']:.2f}", out_mq=f"{A['mqcco']['outage_pct']:.2f}", out_fu=f"{A['full']['outage_pct']:.2f}",
    out_td=f"{A['tdpc']['outage_pct']:.2f}",
    pw_mq=f"{A['mqcco']['power_saved_pct']:.1f}", pw_fu=f"{A['full']['power_saved_pct']:.1f}",
    viol_mq=f"{A['mqcco']['classical_snr_viol_pct']:.1f}", viol_fu=f"{A['full']['classical_snr_viol_pct']:.2f}",
    ms_fu=f"{A['full']['ms_per_request']:.2f}", ms_mq=f"{A['mqcco']['ms_per_request']:.2f}",
    q_full=f"{A['full']['mean_qsnr_db']:.1f}", q_mqcco=f"{A['mqcco']['mean_qsnr_db']:.1f}", q_qtd=f"{A['qtd']['mean_qsnr_db']:.1f}",
    rbr_qtd_g=f"{A['qtd']['rbr_gabriel']:.3f}", rbr_qtd_w=f"{A['qtd']['rbr_waxman']:.3f}",
    rbr_fu_g=f"{A['full']['rbr_gabriel']:.4f}", rbr_fu_w=f"{A['full']['rbr_waxman']:.4f}",
    rbr_mq_g=f"{A['mqcco']['rbr_gabriel']:.4f}", rbr_mq_w=f"{A['mqcco']['rbr_waxman']:.4f}",
    rbr_rel_g=f"{A['relay']['rbr_gabriel']:.4f}", rbr_rel_w=f"{A['relay']['rbr_waxman']:.4f}",
    rbr_td_g=f"{A['tdpc']['rbr_gabriel']:.4f}", rbr_td_w=f"{A['tdpc']['rbr_waxman']:.4f}",
    spec_qtd=f"{A['qtd']['rbr_spectrum']:.3f}",
    n1=N1, n2=N2, msrc=monitored.group(1), mdst=monitored.group(2), mpath=monitored.group(3),
    mlen=monitored.group(4), mclean=monitored.group(5), l1steps=L1_STEPS, mbb=mbb65,
    t30pre=f"{t30['tdpc_qsnr_before_control_db']:.2f}", t30post=f"{t30['tdpc_qsnr_after_control_db']:.2f}",
    t65pre=f"{t65['tdpc_qsnr_before_control_db']:.2f}", t65post=f"{t65['tdpc_qsnr_after_control_db']:.2f}",
    static_out=f"{static_out:.1f}", tdpc_out=f"{tdpc_out:.1f}", static_min=f"{static_min:.2f}",
    ktopo=k_topo.capitalize(), kload=f"{float(k_load):g}",
    k0=f"{100 * k0:.1f}", k4b=f"{100 * k4b:.1f}", k4r=f"{100 * k4r:.1f}", k4t=f"{100 * k4t:.1f}",
    kall=f"{100 * kall:.1f}", captured=f"{captured:.1f}",
    cr80w0=f"{100 * cr80_w_k0:.2f}", cr80w4=f"{100 * cr80_w_k4:.2f}",
    cr80g0=f"{100 * cr80_g_k0:.2f}", cr80g4=f"{100 * cr80_g_k4:.2f}",
)


# ----------------------------------------------------------------------------- claim checks
# The prose below makes qualitative statements. If new results contradict any of
# them, stop instead of writing a report whose text disagrees with its numbers.
def _kb(k, m):
    return kv(k, m)


CLAIMS = {
    "T-DPC alone blocks slightly more than static MQCCO (Waxman, 80 Erl)":
        sw("T-DPC Only", 80, "rbr") > sw("MQCCO + Static PC", 80, "rbr"),
    "Full framework raises mean QSNR over MQCCO (Waxman, 80 Erl)":
        sw("Full T-DPC-RWA", 80, "mean_qsnr") > sw("MQCCO + Static PC", 80, "mean_qsnr"),
    "Per-session SKR is lower for the full framework than MQCCO":
        sw("Full T-DPC-RWA", 80, "mean_skr") < sw("MQCCO + Static PC", 80, "mean_skr"),
    "Network key throughput is higher for the full framework": A["full"]["network_skr"] > A["mqcco"]["network_skr"],
    "Reach is the dominant blocking cause for MQCCO": reach_share_mqcco > 0.5,
    "QTD has the highest pooled mean QSNR": all(A["qtd"]["mean_qsnr_db"] >= A[k]["mean_qsnr_db"] for k in A),
    "Trusted relays reduce RBR vs MQCCO on both topologies":
        A["relay"]["rbr_gabriel"] < A["mqcco"]["rbr_gabriel"] and A["relay"]["rbr_waxman"] < A["mqcco"]["rbr_waxman"],
    "Full framework reduces RBR vs MQCCO on both topologies":
        A["full"]["rbr_gabriel"] < A["mqcco"]["rbr_gabriel"] and A["full"]["rbr_waxman"] < A["mqcco"]["rbr_waxman"],
    "T-DPC loop reduces outage vs MQCCO": A["tdpc"]["outage_pct"] < A["mqcco"]["outage_pct"],
    "Sparse O-E-O leaves 80 Erl RBR almost unchanged (< 0.01)":
        abs(A["tdpcoeo"]["rbr_gabriel"] - A["tdpc"]["rbr_gabriel"]) < 0.01 and abs(A["tdpcoeo"]["rbr_waxman"] - A["tdpc"]["rbr_waxman"]) < 0.01,
    "K = 4 betweenness hubs reduce classical RBR at the stress load": k4b < k0,
    "Betweenness is lowest of the three placements for every K >= 2":
        all(_kb(k, "betweenness") <= min(_kb(k, "random"), _kb(k, "traffic")) for k in ("2", "3", "4", "5", "6")),
    "Static PC has classical SNR violations, full framework (almost) none":
        A["mqcco"]["classical_snr_viol_pct"] > 10 and A["full"]["classical_snr_viol_pct"] < 1,
}
failed = [c for c, ok in CLAIMS.items() if not ok]
if failed:
    sys.exit("Results contradict statements in the report text; report NOT rebuilt. Revise these passages:\n  - "
             + "\n  - ".join(failed))


def T(s):
    """Fill @@key@@ placeholders (LaTeX braces stay untouched)."""
    return re.sub(r"@@(\w+)@@", lambda mm: str(V[mm.group(1)]), s)


# ----------------------------------------------------------------------------- text
LIT = [
    ("1", "Ruiz & Garcia-Escartin (2026) — Power control heuristics for quantum–classical multiplexing",
     "Classical launch-power minimisation integrated into RWA heuristics (MQDO, MQCCO, QTD).",
     "Attenuating C-band launch power to the receiver SNR floor suppresses anti-Stokes Raman noise.",
     "Adv: cuts blocking by up to 10× and saves ~80% energy. Lim: static demands and one-shot power setting."),
    ("2", "Kiktenko et al. (2024) — Multiple non-overlapping paths routing for QKD networks",
     "Disjoint multi-path secret-key splitting across trusted intermediate relays.",
     "Distributing key shares over non-overlapping paths prevents key compromise if a single relay is breached.",
     "Adv: removes single-node trust vulnerability. Lim: multiplies wavelength and bandwidth consumption."),
    ("3", "Yu et al. (2021) — Multi-dimensional RWTA in QKD optical networks (QKD-ON)",
     "Time-division multiplexing with adaptive contiguous/non-contiguous timeslot scheduling.",
     "Joint allocation of wavelengths and timeslots coordinates quantum, basis and data channels.",
     "Adv: lower blocking and key-update delay. Lim: needs sub-nanosecond synchronisation hardware."),
    ("4", "Cao et al. (2019) — SDQaaS: Software-defined networking for QKD as a service",
     "Centralised SDN control plane with northbound/southbound API abstraction.",
     "Abstracts physical QKD links into programmable virtual key-delivery services alongside NFV.",
     "Adv: cloud-native provisioning and scalability. Lim: control-plane latency and single-point overhead."),
    ("5", "Oki et al. (2026) — Survivable entanglement path provisioning under link failures",
     "Optimisation model selecting link-disjoint entanglement paths against physical link failures.",
     "Link-disjoint provisioning raises survivability by up to 11.8% over baseline algorithms.",
     "Adv: high fault tolerance. Lim: idle resource-reservation overhead."),
    ("6", "Zhao et al. (2023) — Resource-adaptive routing with wavelength conflicts (RAWC)",
     "Dynamic link-weight adjustment quantifying real-time wavelength-conflict degree.",
     "Steering requests away from spectrally bottlenecked links balances key-pool utilisation.",
     "Adv: up to 30% higher acceptance. Lim: more computation per arrival."),
    ("7", "Cruzes (2026) — Telemetry and agentic AI: foundations for optical network automation",
     "Streaming optical telemetry coupled with autonomous control agents.",
     "Continuous OSNR/BER monitoring enables proactive reconfiguration before link failure.",
     "Adv: rapid autonomous mitigation of drift. Lim: requires high-frequency telemetry pipelines."),
    ("8", "Ruiz & Garcia-Escartin (2025) — RWA in hybrid networks with classical and quantum signals",
     "Shared physical-path minimisation heuristics without power control.",
     "Limiting C-band/O-band co-propagation distance curbs nonlinear photon leakage.",
     "Adv: software-only mitigation. Lim: forces classical channels onto longer detours."),
    ("9", "Bahrani et al. (2018) — Wavelength assignment in hybrid quantum-classical networks",
     "Interspersed spectral grid modelling and Raman spectral profiling.",
     "Alternating quantum and classical wavebands suppresses Raman cross-talk better than contiguous blocks.",
     "Adv: more simultaneous QKD users. Lim: complicates standard WDM multiplexer design."),
    ("10", "Cao et al. (2017) — Resource assignment strategy in optical networks integrated with QKD",
     "Integer linear programming for static routing, wavelength and timeslot assignment.",
     "Optical TDM partitions wavelengths to satisfy heterogeneous security tiers.",
     "Adv: optimal for known static traffic. Lim: intractable for real-time dynamic arrivals."),
    ("11", "Wang et al. (2019) — QKD networks enabled by software-defined networking",
     "Two-step SDN orchestration aligning key-pool updates with wavelength occupancy.",
     "Synchronising key replenishment with lightpath holding times prevents key-pool starvation.",
     "Adv: unified spectrum and key-pool management. Lim: centralised controller is a reliability bottleneck."),
    ("12", "Moghaddam et al. (2021) — Resource allocation in SDM elastic optical networks secured with QKD",
     "Priority-ordered spatial and spectral resource assignment in multi-core fibres.",
     "Separating high-priority channels across non-adjacent cores suppresses inter-core crosstalk.",
     "Adv: high spatial multiplexing density. Lim: restricted to multi-core fibre plants."),
    ("13", "Grillo et al. (2021) — Resource allocation in QKD networks with LEO/GEO trusted repeaters",
     "Time-varying multi-commodity flow linear programming over satellite graphs.",
     "Centralised scheduling maximises key transfer across free-space satellite passes.",
     "Adv: overcomes terrestrial attenuation limits. Lim: orbital latency and scintillation."),
    ("14", "Lella & Schmid (2023) — On the security of quantum key distribution networks",
     "Threat modelling and vulnerability analysis of QKD relay topologies.",
     "Point-to-point links are information-theoretically secure, but trusted relays remain physical targets.",
     "Adv: clarifies operational vs theoretical security. Lim: survey; no new RWA algorithm."),
    ("15", "Li et al. (2025) — RWA with minimal attack radius (RWA-MAR) for QKD networks",
     "ILP and heuristic minimising the maximum number of affected requests (maxNAR).",
     "Key pools plus optical bypass contain the blast radius of high-power jamming.",
     "Adv: resilience against jamming. Lim: security-constrained routes are longer."),
    ("16", "Zhang et al. (2006) — Extensible router for a multi-user QKD network",
     "Passive wavelength routing using WDM multiplexers without state measurement.",
     "Single-photon signals can be demultiplexed and routed purely by wavelength.",
     "Adv: preserves coherence across passive hubs. Lim: early star-topology prototype."),
    ("17", "López et al. (2026) — Route planning and online routing for QKD networks",
     "Quadratic programming and widest-shortest-path online routing.",
     "Widest-shortest-path selection achieves better competitive ratios when key capacity is scarce.",
     "Adv: fair capacity distribution under spikes. Lim: solver overhead grows with node count."),
    ("18", "Dong et al. (2020) — Auxiliary-graph RWTA in metro quantum networks with optical bypass",
     "Auxiliary graph with hybrid trusted-relay / optical-bypass nodes.",
     "Letting quantum signals bypass intermediate nodes when distance permits saves relay keys.",
     "Adv: lower relay key consumption. Lim: needs low-loss bypass switches."),
    ("19", "Kawakami et al. (2025) — Coexistence of S-band CV-QKD with fully loaded C+L-band DWDM",
     "Experimental spectral power tuning and specialised WDM filtering.",
     "S-band CV-QKD coexists with terabit C+L-band classical traffic.",
     "Adv: standard coherent receivers instead of SPDs. Lim: reach bounded by phase noise."),
    ("20", "Pan & Djordjevic (2021) — An overview of geometrical-optics restricted QKD",
     "Physical aperture-restriction modelling for free-space eavesdroppers.",
     "Bounding an adversary's collection geometry relaxes secret-key extraction thresholds.",
     "Adv: practical key-rate gains on line-of-sight links. Lim: free-space/satellite channels only."),
]

REVIEW = """**Ruiz and Garcia-Escartin (2026)** formulate power-controlled routing and wavelength assignment heuristics for hybrid quantum-classical WDM networks. By attenuating C-band launch powers down to the minimum required for error-free classical reception, their method curtails spontaneous anti-Stokes Raman scattering into O-band quantum channels. This improves the Quantum Signal-to-Noise Ratio (QSNR) and lowers request blocking across shared fibre topologies, although the evaluation is restricted to static demand sets with one-shot power calibration.

**Kiktenko et al. (2024)** develop a multi-path routing protocol for trusted-relay QKD infrastructures. Instead of sending a key along a single relay chain, their algorithm splits keys into partial shares routed over mutually disjoint physical paths. An adversary must then compromise several independent nodes at once to reconstruct the key, which strengthens relay security at the cost of higher aggregate wavelength utilisation.

**Yu et al. (2021)** propose a Multi-Dimensional Routing, Wavelength and Timeslot Allocation (RWTA) framework for short-reach QKD optical networks. Because each QKD session needs coordinated quantum, basis-reconciliation and encrypted data channels, the authors combine wavelength routing with optical time-division multiplexing. Dynamic contiguous and non-contiguous timeslot allocation mitigates spectral fragmentation and lowers blocking, though it demands tight network-wide clock synchronisation.

**Cao et al. (2019)** introduce Software-Defined Networking for Quantum Key Distribution as a Service (SDQaaS), showing how centralised SDN controllers can abstract heterogeneous QKD hardware into programmable network primitives. Through northbound REST interfaces and southbound control agents, SDQaaS provisions virtual security overlays alongside classical network function virtualisation (NFV), improving operational agility at the cost of some control-plane signalling overhead.

**Oki et al. (2026)** investigate survivable entanglement path provisioning for quantum networks under physical link failures, which earlier entanglement-routing work, focused on maximising the number of connections, did not consider. Their optimisation model finds link-disjoint entanglement paths, achieving up to 11.8% higher survivability than baseline algorithms, at the cost of the extra resources that disjoint paths reserve.

**Zhao et al. (2023)** present a Resource-Adaptive Routing Scheme with Wavelength Conflicts (RAWC) for contention between simultaneous QKD service requests. A metric for wavelength-conflict degree and dynamically updated link weights steer traffic away from congested bottlenecks, improving service acceptance by up to 30% over static shortest-path routing.

**Cruzes (2026)** examines streaming optical telemetry combined with agentic artificial intelligence for autonomous transport-network management. By continuously ingesting physical-layer metrics such as OSNR and bit-error rate through gRPC telemetry pipelines, autonomous control loops can detect slow degradation and adjust routing proactively, a conceptual foundation for closed-loop hybrid network supervision.

**Ruiz and Garcia-Escartin (2025)** propose shared-path minimisation heuristics (MQDO and MQCCO) for hybrid networks in which classical and quantum channels co-propagate without dynamic launch-power control. Candidate lightpaths are ranked by penalising fibre overlap between high-power C-band signals and single-photon O-band channels. The rules curb nonlinear cross-talk in software alone, but strict overlap avoidance often forces classical connections onto longer detours.

**Bahrani et al. (2018)** analyse spectral arrangements that suppress Raman noise in hybrid DWDM links. Rather than segregating quantum and classical channels into two monolithic wavebands, their modelling shows that interspersing smaller alternating sub-bands reduces net Raman leakage and increases the number of concurrent QKD sessions.

**Cao et al. (2017)** formulate an Integer Linear Programming (ILP) model and a static RWTA heuristic for optical networks integrated with QKD. Partitioning wavelengths into sub-wavelength timeslots matches key-update rates to application-specific security tiers. The method approaches optimal fibre utilisation for predetermined traffic matrices but does not adapt to stochastic online arrivals.

**Wang et al. (2019)** design a two-stage SDN orchestration architecture that coordinates wavelength allocation with Quantum Key Pool (QKP) management. Aligning key-replenishment intervals with lightpath holding times keeps high-bandwidth sessions from exhausting stored keys mid-transmission. The coupling improves survivability, but the centralised controller is a potential bottleneck.

**Moghaddam et al. (2021)** address resource allocation in space-division-multiplexed elastic optical networks secured with QKD. Assigning high-priority connections to non-adjacent cores of multi-core fibres suppresses inter-core crosstalk during high-density transmission, offering insight into spatial isolation that complements spectral WDM separation.

**Grillo et al. (2021)** model global QKD resource allocation over hybrid constellations of LEO and GEO satellites acting as trusted repeaters. Treating the time-varying satellite topology as a multi-commodity flow problem, their scheduler maximises end-to-end key throughput between distant ground stations, avoiding terrestrial fibre attenuation at the cost of orbital handover latency.

**Lella and Schmid (2023)** evaluate the security of multi-hop QKD network architectures. They contrast the information-theoretic security of individual point-to-point links with the physical trust required at intermediate key-relaying nodes, underscoring the need to minimise relay hop counts and harden relay enclosures.

**Li et al. (2025)** formulate Routing and Wavelength Assignment with Minimal Attack Radius (RWA-MAR) to defend QKD networks against high-power jamming. Introducing the Maximum Number of Affected Requests (maxNAR) metric, they combine ILP modelling with key-pool caching and optical bypass switching to isolate jamming disruptions.

**Zhang et al. (2006)** demonstrate an early extensible passive quantum router built from commercial WDM multiplexers. Routing single-photon pulses purely by wavelength, without intermediate measurement, preserves state coherence across a multi-user star topology and establishes the viability of passive wavelength routing.

**López et al. (2026)** study offline route planning and online routing in capacity-constrained QKD networks using quadratic programming. Their results show that widest-shortest-path routing outperforms plain shortest-path selection when key generation rates are the bottleneck, giving fairer capacity distribution during demand surges.

**Dong et al. (2020)** develop an auxiliary-graph RWTA algorithm for metropolitan quantum networks with hybrid nodes capable of both trusted relaying and optical bypass. When the distance between non-adjacent nodes is within the secure QKD reach, quantum signals bypass the intermediate node optically, conserving relay key buffers and transceivers.

**Kawakami et al. (2025)** experimentally validate the coexistence of S-band continuous-variable QKD with fully loaded C+L-band DWDM classical channels. Optimised launch power spectral density and multistage WDM isolation filters give zero post-FEC classical bit errors while preserving positive CV-QKD key rates with standard coherent receivers.

**Pan and Djordjevic (2021)** review geometrical-optics-restricted QKD models for free-space optical links. Replacing the assumption of an omnipotent eavesdropper who collects all scattered photons with physically bounded receiver apertures yields tighter, more practical secret-key-rate bounds for line-of-sight quantum links.
"""

REFS = """1. Ruiz, L., & Garcia-Escartin, J. C. (2026). Routing and wavelength assignment in quantum key distribution networks: Power control heuristics for quantum–classical multiplexing. *Computer Communications*, 256, 108572. https://doi.org/10.1016/j.comcom.2026.108572 (Preprint: arXiv:2407.19024).
2. Kiktenko, E. O., Tayduganov, A., & Fedorov, A. K. (2024). Routing algorithm within the multiple non-overlapping paths' approach for quantum key distribution networks. *Entropy*, 26(12), 1102. https://doi.org/10.3390/e26121102
3. Yu, X., Ning, X., Zhu, Q., Lv, J., Zhao, Y., Zhang, H., & Zhang, J. (2021). Multi-dimensional routing, wavelength, and timeslot allocation (RWTA) in quantum key distribution optical networks (QKD-ON). *Applied Sciences*, 11(1), 348. https://doi.org/10.3390/app11010348
4. Cao, Y., Zhao, Y., Wang, J., Yu, X., Ma, Z., & Zhang, J. (2019). SDQaaS: Software defined networking for quantum key distribution as a service. *Optics Express*, 27(5), 6892–6909. https://doi.org/10.1364/OE.27.006892
5. Oki, E., Maeda, M., & Shiraki, R. (2026). Survivable entanglement path provisioning for quantum networks under link failures. In *Proc. 2026 International Conference on Computing, Networking and Communications (ICNC)* (pp. 827–832). IEEE.
6. Zhao, T., Fan, X., Dong, B., Niu, Q., & Guo, B. (2023). A resource-adaptive routing scheme with wavelength conflicts in quantum key distribution optical networks. *Entropy*, 25(5), 732. https://doi.org/10.3390/e25050732
7. Cruzes, S. (2026). Telemetry and agentic AI: Foundations for optical network automation. *IEEE Access*, 14, 8800–8838.
8. Ruiz, L., & Garcia-Escartin, J. C. (2025). Routing and wavelength assignment in hybrid networks with classical and quantum signals. *IEEE Journal on Selected Areas in Communications*, 43(2), 412–421. https://doi.org/10.1109/JSAC.2025.3528817 (Preprint: arXiv:2311.10474).
9. Bahrani, S., Razavi, M., & Salehi, J. A. (2018). Wavelength assignment in hybrid quantum-classical networks. *Scientific Reports*, 8(1), 3456. https://doi.org/10.1038/s41598-018-21418-6
10. Cao, Y., Zhao, Y., Yu, X., & Wu, Y. (2017). Resource assignment strategy in optical networks integrated with quantum key distribution. *Journal of Optical Communications and Networking*, 9(11), 995–1004. https://doi.org/10.1364/JOCN.9.000995
11. Wang, H., Zhao, Y., & Nag, A. (2019). Quantum-key-distribution (QKD) networks enabled by software-defined networks (SDN). *Applied Sciences*, 9(10), 2081. https://doi.org/10.3390/app9102081
12. Moghaddam, E. E., Beyranvand, H., & Salehi, J. A. (2021). Resource allocation in space division multiplexed elastic optical networks secured with quantum key distribution. *IEEE Journal on Selected Areas in Communications*, 39(9), 2688–2700. https://doi.org/10.1109/JSAC.2021.3064641
13. Grillo, M., Dowhuszko, A. A., Khalighi, M.-A., & Hämäläinen, J. (2021). Resource allocation in a quantum key distribution network with LEO and GEO trusted-repeaters. In *Proc. 17th International Symposium on Wireless Communication Systems (ISWCS)* (pp. 1–6). IEEE. https://doi.org/10.1109/ISWCS49558.2021.9562139 (Preprint: arXiv:2107.07595).
14. Lella, E., & Schmid, G. (2023). On the security of quantum key distribution networks. *Cryptography*, 7(4), 53. https://doi.org/10.3390/cryptography7040053
15. Li, M., Zhang, Q., Yang, Z., Bregni, S., Gatto, A., Boutaba, R., & Tornatore, M. (2025). Routing and wavelength assignment with minimal attack radius for QKD networks. arXiv preprint arXiv:2508.10613. https://doi.org/10.48550/arXiv.2508.10613
16. Zhang, T., Han, Z.-F., Mo, X.-F., & Guo, G.-C. (2006). Extensible router for multi-user quantum key distribution network. arXiv preprint arXiv:quant-ph/0608238. https://arxiv.org/abs/quant-ph/0608238
17. López, J., Chatzinakis, C., & Cartigny, M. (2026). Route planning and online routing for quantum key distribution networks. arXiv preprint arXiv:2508.09735v2. https://doi.org/10.48550/arXiv.2508.09735
18. Dong, K., Zhao, Y., Yu, X., Nag, A., & Zhang, J. (2020). Auxiliary graph based routing, wavelength, and time-slot assignment in metro quantum optical networks with a novel node structure. *Optics Express*, 28(5), 5936–5952. https://doi.org/10.1364/OE.380329
19. Kawakami, T., Kawahara, H., Okamura, T., & Maeda, W. (2025). Coexistence demonstration and wavelength dependency analysis of S-band CV-QKD signal with fully loaded C+L-band DWDM signals. *Entropy*, 27(1), 45. https://doi.org/10.3390/e27010045
20. Pan, Z., & Djordjevic, I. B. (2021). An overview of geometrical optics restricted quantum key distribution. *Entropy*, 23(8), 1003. https://doi.org/10.3390/e23081003
"""


def lit_table():
    out = ["| No. | Title, Author & Year | Methodology | Key Findings | Advantages & Limitations |",
           "|:----|:--------------------------|:--------------------|:--------------------|:----------------------|"]
    for r in LIT:
        out.append("| " + " | ".join(c.replace("|", "/") for c in r) + " |")
    out.append("")
    out.append(": Comparative summary of the reviewed literature.")
    return "\n".join(out)


def ablation_table():
    hdr = ("| Model configuration | T-DPC | O-E-O | Relays | RBR Gabriel | RBR Waxman | Mean QSNR | "
           "Outage time | SKR ×10⁻³ | Power saved |")
    out = [hdr, "|:" + "-" * 34 + "|:" + "-" * 11 + "|:" + "-" * 10 + "|:" + "-" * 11 + "|" + ("-" * 14 + ":|") * 6]
    for i, key in enumerate(CFG, 1):
        r = A[key]
        row = [f"{i}. {CFG[key]}", r["t_dpc"], r["oeo"].replace(" ", ""), r["relays"].replace("|", "∣").replace(" ", ""),
               f"{r['rbr_gabriel']:.4f}", f"{r['rbr_waxman']:.4f}", f"{r['mean_qsnr_db']:.1f} dB",
               f"{r['outage_pct']:.2f}%", f"{1e3 * r['skr']:.2f}", f"{r['power_saved_pct']:.1f}%"]
        if key == "full":
            row = [f"**{c}**" for c in row]
        out.append("| " + " | ".join(row) + " |")
    out.append("")
    out.append(": Table 2: Factorial ablation across 20-node Gabriel and Waxman topologies at 80 Erlang. "
               "Mean QSNR, outage time, SKR and power saved are pooled over both topologies.")
    return "\n".join(out)


def cause_table():
    out = ["| Model configuration | Spectrum | QSNR | Reach | Classical RBR | Network SKR (×10⁻³) | Classical SNR violations | ms / request |",
           "|:" + "-" * 41 + "|" + ("-" * 13 + ":|") * 7]
    for i, key in enumerate(CFG, 1):
        r = A[key]
        out.append(f"| {i}. {CFG[key]} | {r['rbr_spectrum']:.4f} | {r['rbr_qsnr']:.4f} | {r['rbr_reach']:.4f} | "
                   f"{r['classical_rbr']:.4f} | {1e3 * r['network_skr']:.2f} | {r['classical_snr_viol_pct']:.2f}% | "
                   f"{r['ms_per_request']:.2f} |")
    out.append("")
    out.append(": Table 3: Blocking-cause decomposition (share of all requests), network key throughput, classical "
               "SNR violations and controller computation time, 20-node topologies at 80 Erlang (pooled).")
    return "\n".join(out)


def param_table():
    rows_ = [
        ("Optical wavebands", "Quantum: O-band (1310 nm, CWDM) / Classical: C-band (1550 nm, DWDM 100 GHz)", "Base paper"),
        ("Wavelength capacity per fibre", "W_q = 10 quantum, W_c = 40 classical (W_T = 50)", "Base paper"),
        ("Fibre attenuation", "α_q = 0.32 dB/km (0.0737 Np/km), α_c = 0.17 dB/km (0.0391 Np/km)", "Base paper"),
        ("Raman coupling & receiver filter", "β_q = 10⁻¹² km⁻¹ (100 GHz), γ_nl = 2.25 × 10⁻⁴", "Base paper"),
        ("SPD efficiency & noise", "η_D = 0.10, p_d = N_F = 10⁻⁴ per 10 ns gate, V = 0.98, f_EC = 1.16", "Base paper"),
        ("Classical receiver sensitivity", "−36.8 dBm minimum reception power; P_max = 1 mW", "Base paper"),
        ("QSNR thresholds & guard band", "Γ_Q = −5.0 dB; ε = 1.5 dB (trigger −3.5 dB); h = 0.5 dB", "Proposed work"),
        ("Dynamic power-control margins", "m_0 = 0.25, m_floor = 0.05, Δp = 0.5 dB, Δt = 1.0 s", "Proposed work"),
        ("Sparse O-E-O & trusted relays", "K = 4 hubs (R = 16 transponders), ∣T∣ = 3, M_max = 3 (20-node)", "Proposed work"),
        ("Stochastic traffic profile", "Poisson arrivals, 1/μ = 60 s, A ∈ [10, 100] Erlang, f_q = 0.3", "Proposed work"),
        ("Classical traffic bursts", "1 per 45 s on average, 3–6 channels at 1 mW, 40% fixed-power, mean 20 s", "Simulation assumption"),
    ]
    out = ["| Parameter | Calibrated value / range | Reference |", "|:----------|:-------------------------|:------|"]
    out += [f"| **{a}** | {b} | {c} |" for a, b, c in rows_]
    out.append("")
    out.append(": Table 1: Physical-layer and control-plane parameters used in the discrete-event simulations.")
    return "\n".join(out)


ALG1 = r"""**Algorithm 1: Closed-Loop Telemetry-Driven Dynamic Power Adaptation (T-DPC)**

*Input:* active sets $Q(t)$, $C(t)$; thresholds $\Gamma_Q = -5$ dB, $\varepsilon = 1.5$ dB, $h = 0.5$ dB, $\text{SNR}_{th}$; step $\Delta p = 0.5$ dB.

1: Every telemetry interval $\Delta t$: poll live $\text{QSNR}_q(t)$ for all $q \in Q(t)$, and $\text{SNR}_{c,s}(t)$, $\eta_{c,s}(t)$, $N(t)$ for all $(c,s) \in C(t)$.

2: Recompute sensitivity coefficients $\kappa_{j,q}(t)$ via Eq. (1) and minimum power bounds $P^{\min}_{c,s}(t)$ via Eq. (3).

3: Classical repair: for any segment with $\text{SNR}_{c,s}(t) < \text{SNR}_{th}$, set $P_{c,s}(t) \leftarrow \min\left(P_{\max},\ P^{\min}_{c,s}(t)(1+m_{floor})\right)$.

4: Identify the at-risk set $R \leftarrow \{q \in Q(t) : \text{QSNR}_q(t) < \Gamma_Q + \varepsilon\}$, sorted by ascending $\text{QSNR}_q(t)$.

5: **for each** $q \in R$ **do**

6:     Compute $\Delta N^{*}_{q}(t)$ via Eq. (4) and headroom $H_q = \sum_j \kappa_{j,q}\left(P_j - P^{\min}_j(1+m_{floor})\right)$.

7:     **if** $H_q \ge \Delta N^{*}_{q}(t)$ **then** [Level 1: sensitivity-ordered power throttling]

8:         Sort interferers $j$ by descending Raman contribution $\kappa_{j,q}(t)P_j(t)$.

9:         **while** $\text{QSNR}_q(t) < \Gamma_Q + \varepsilon$: $P_j \leftarrow \max\left(P_j \cdot 10^{-\Delta p/10},\ P^{\min}_j(1+m_{floor})\right)$.

10:     **end if**

11:     **if** $\text{QSNR}_q(t) < \Gamma_Q + \varepsilon$ **then** [Level 2: make-before-break re-grooming]

12:         Select the dominant interferer $j^{*} = \arg\max_j \kappa_{j,q}(t)P_j(t)$.

13:         Invoke Algorithm 2 on the auxiliary graph, excluding the links of $q$, to find an alternate path/wavelength for $j^{*}$.

14:         **if** found **then** establish the new lightpath (make), switch traffic, release the old one (break).

15:         **else** attempt make-before-break re-routing of $q$ itself; log outage time while $\text{QSNR}_q(t) < \Gamma_Q$.

16: **end for**

17: Hysteresis recovery: for $q$ with $\text{QSNR}_q(t) \ge \Gamma_Q + \varepsilon + h$, restore throttled $P_j$ by $+\Delta p$ toward $P^{\min}_j(1+m_0)$ if safe.
"""

ALG2 = r"""**Algorithm 2: Online Dynamic Request Provisioning with Auxiliary Graph and Trusted Relays**

*Input:* arriving request $r = (s, d, \text{type})$ at time $t$; topology $G(V, E)$; converter hubs $V_{OEO}$; relay set $T$.

1: **if** type = CLASSICAL **then**

2:     Try the $k$ candidate paths in MQCCO order with first-fit wavelength continuity; accept the first that keeps every $q \in Q(t)$ at or above the admission threshold.

3:     **if** none fits and $V_{OEO} \neq \emptyset$: build the layered auxiliary graph $A$ with vertices $(v, \lambda)$, $v \in V$, $\lambda \in \Lambda_c$.

4:         Intra-layer edges $((u,\lambda),(v,\lambda))$ if $\lambda$ is free on $(u,v)$, weight $w_e = l_{uv} + w_q\varphi_{uv}(t)$.

5:         Inter-layer conversion edges $((v,\lambda),(v,\lambda'))$ of weight $w_{conv}$ iff $v \in V_{OEO}$ and a transponder is free.

6:         Find the least-cost path in $A$; split it into transparent segments at conversion edges.

7:     Set segment launch powers $P_{c,s} = P^{\min}_{c,s}(t)(1+m_0)$ via Eq. (3).

8:     **if** $P_{c,s} \le P_{\max}$ and every $q \in Q(t)$ keeps $\text{QSNR}_q \ge \Gamma_Q + \varepsilon$ **then** allocate and ACCEPT.

9:     **else** BLOCK (cause: spectrum/continuity or QSNR interference).

10: **else** (QUANTUM)

11:     Direct attempt: search the $k$ shortest paths; select the first continuous free $\lambda \in \Lambda_q$ with $\text{QSNR} \ge \Gamma_Q + \varepsilon$.

12:     **if** that fails and $T \neq \emptyset$ **then** [multi-segment trusted-relay attempt]

13:         Enumerate relay chains $s = r_0 \to r_1 \to \dots \to r_M = d$ ($r_m \in T$, $M \le M_{\max}$) whose every segment satisfies the QSNR test.

14:         Choose the chain with the highest bottleneck SKR (fewest hops on ties).

15:     **if** a chain and the 2 control + 1 data classical lightpaths fit **then** allocate jointly and ACCEPT.

16:     **else** BLOCK (cause: spectrum, QSNR interference, or single-segment reach).
"""


def algo(block):
    body = "\n\n".join(block.strip().split("\n\n"))
    return f'::: {{custom-style="Algorithm"}}\n{body}\n:::\n'


MD = T(r"""---
title: "Routing and Wavelength Assignment for Hybrid QKD Networks with Adaptive Power Control and Sparse Wavelength Conversion"
---

**Base Paper Reference:** Routing and wavelength assignment in quantum key distribution networks: Power control heuristics for quantum–classical multiplexing (Ruiz & Garcia-Escartin, *Computer Communications*, 2026).

**Team Members:** Ayush Sinha 24BCI0119, Shreshth Mishra 24BCI0081

# Title

Dynamic Routing and Wavelength Assignment for Hybrid QKD Networks with Adaptive Power Control and Sparse Wavelength Conversion

# Abstract

Integrating Quantum Key Distribution (QKD) into operational optical transport infrastructures is essential for protecting communication systems against emerging quantum computational threats. Dedicated dark-fibre links for quantum key exchange give high physical isolation, but such deployments are economically prohibitive at scale. Wavelength-division multiplexed (WDM) hybrid networks, in which single-photon O-band quantum channels co-propagate with high-power C-band classical channels over shared fibre, have therefore become the main architectural paradigm. Quantum-classical multiplexing, however, introduces nonlinear impairments, predominantly spontaneous anti-Stokes Raman scattering, which scatters noise photons from classical pumps into the quantum detection window and raises the Quantum Bit Error Rate (QBER).

The foundational study by Ruiz and Garcia-Escartin (2026) shows that embedding classical launch-power control into Routing and Wavelength Assignment (RWA) heuristics substantially reduces Raman cross-talk and safeguards the Quantum Signal-to-Noise Ratio (QSNR). That formulation rests on restrictive assumptions: a static, pre-known demand set provisioned sequentially with a one-shot launch power fixed at set-up; a strictly passive network without wavelength conversion; and network paths bounded at 60 km by simulation design. Under stochastic traffic these assumptions leave mid-session QSNR degradation unmitigated and restrict geographical reach.

This study develops and evaluates a closed-loop, Telemetry-Driven Dynamic Power Control and RWA (T-DPC-RWA) framework for hybrid networks under stochastic online traffic (Poisson arrivals, exponential holding times). It introduces three decoupled mechanisms: (i) an SDN telemetry loop that polls QSNR and classical SNR every $\Delta t$ and applies sensitivity-ordered power throttling and make-before-break (MBB) re-grooming whenever a quantum channel enters a guard band; (ii) sparse Optical-Electrical-Optical (O-E-O) wavelength converters at high betweenness-centrality hubs, used only by classical channels; and (iii) trusted relay nodes that terminate and re-establish QKD sessions over multi-segment chains. Discrete-event simulation on 20-node Gabriel and Waxman topologies at 80 Erlang (@@real@@ independent realisations, @@meas@@ measured requests per run) shows that the full framework lowers the Request Blocking Ratio (RBR) by @@red_g@@% (Gabriel) and @@red_w@@% (Waxman) relative to the base paper's MQCCO heuristic with static power control, cuts session outage time from @@out_mq@@% to @@out_fu@@%, raises network key throughput by @@ns_gain@@%, and keeps @@pw_fu@@% classical launch-power savings. The simulations also show that, under this physical model, blocking is dominated by single-segment quantum reach, so trusted relays deliver most of the blocking gain, while sparse O-E-O conversion helps only once the C-band saturates.

# Keywords

**Keywords:** Quantum Key Distribution (QKD), Routing and Wavelength Assignment (RWA), Spontaneous Raman Scattering, Software-Defined Networking (SDN), Closed-Loop Telemetry, Sparse Wavelength Conversion.

# Introduction

## Background: Quantum Key Distribution in Shared WDM Optical Networks

The rapid maturation of quantum information processing threatens the mathematical foundations of asymmetric cryptosystems such as RSA and elliptic-curve cryptography. Quantum Key Distribution (QKD) addresses this vulnerability by enabling remote nodes to establish symmetric keys whose information-theoretic security rests on quantum mechanics, specifically the no-cloning theorem and measurement disturbance. In discrete-variable protocols such as decoy-state BB84, quantum states are encoded onto weak coherent pulses averaging fewer than one photon per pulse. Any interception attempt perturbs the states and shows up as a measurable rise in the Quantum Bit Error Rate (QBER), which alerts the legitimate parties to abort key extraction.

While early QKD testbeds relied on dedicated dark fibres, commercial deployment across metropolitan and wide-area networks requires multiplexing quantum channels onto existing WDM fibre plants alongside classical traffic. Coexistence in one fibre is difficult because of an extreme power disparity: classical channels launch at milliwatt levels (~0 dBm), whereas quantum channels operate at femtowatt scales (~10⁻¹⁶ W). Even when linear cross-talk is suppressed by high-isolation WDM filters, optical nonlinearities in the silica core generate in-band noise photons that cannot be filtered out. Hybrid architectures therefore usually assign classical traffic to the low-loss C-band (~1550 nm) and quantum transmission to the O-band (~1310 nm). This places the quantum channel on the weaker anti-Stokes side of the classical pump's spontaneous Raman spectrum, trading higher O-band attenuation (0.32 dB/km vs 0.17 dB/km in the C-band) for a large reduction in nonlinear background noise.

## Technical Review of the Base Paper: Problem Formulation and Heuristics

The foundational work by Ruiz and Garcia-Escartin (2026) investigates the RWA problem in unamplified, passive hybrid optical networks without wavelength conversion. Each fibre link supports $W_T = 50$ wavelengths, partitioned into $W_Q = 10$ CWDM O-band quantum channels and $W_C = 40$ DWDM C-band classical channels. Each QKD connection request $R(s,d)$ requires four lightpaths: one unidirectional O-band quantum channel, two bidirectional C-band control channels for sifting and authenticated post-processing, and one C-band data channel for encrypted payload. The network also carries purely classical requests.

To evaluate physical feasibility without full wave-propagation simulation, the base paper uses an analytical model for spontaneous anti-Stokes Raman scattering. When a classical pump of power $P_0$ co-propagates with a quantum channel over a shared span of length $z$, the Raman noise power coupled into the quantum receiver bandwidth is $\text{RNP}(z) = P_0\,\frac{\beta_q}{\alpha_q-\alpha_c}\left(e^{-\alpha_c z} - e^{-\alpha_q z}\right)$, where $\alpha_c$ and $\alpha_q$ are the attenuation coefficients (Np/km) at 1550 nm and 1310 nm and $\beta_q$ is the effective spontaneous Raman scattering coefficient. Aggregating over all co-propagating classical channels, the authors define the QSNR as the ratio of attenuated quantum signal detections to the sum of detector dark counts ($N_F = p_d$) and Raman noise photons. A quantum lightpath is viable only if its QSNR meets the hard threshold $\Gamma_Q = -5$ dB.

Because fixed-power classical transmitters launch more power than shorter routes need, inflating Raman leakage, the base paper integrates classical launch-power control into four RWA heuristics: (1) Shortest-Path First-Fit (SP-FF), which ignores the quantum layer; (2) Minimum Quantum Distance Overlap (MQDO), which prefers classical paths with the least shared length with active quantum channels; (3) Minimum Quantum-Classical Channel Overlap (MQCCO), which works like MQDO but doubles the contribution of a shared link that already carries a classical channel; and (4) Quantum Totally Disjoint (QTD), which forbids classical lightpaths on links carrying quantum channels. By setting classical launch power to the minimum that satisfies the receiver SNR threshold, $P_{tx,c} = \frac{\text{SNR}_{th}N}{e^{-\alpha_c L_c}}$, the base paper reports blocking reductions of up to an order of magnitude, QSNR gains of up to about 5 dB, and ~80% classical transmitter energy savings.

## Critical Limitations of the Base Paper

Despite establishing the value of power-aware RWA, the base paper's experimental design has three structural constraints that limit its direct applicability to carrier-grade networks:

1. **Static demand provisioning with one-shot power assignment.** Requests are known in advance and provisioned sequentially without departures, and launch power is computed once at set-up. In real transport networks connections arrive and depart stochastically, continuously changing the set of interferers on links shared with quantum channels. Slow physical drifts (connector degradation, thermal attenuation shifts, fibre ageing) also perturb classical SNR over time. A static, one-shot power setting cannot respond to mid-session QSNR erosion.
2. **Passive routing with strict wavelength continuity.** Without wavelength converters, every lightpath must use the same wavelength on all its links. Under dynamic arrivals and departures, spectral fragmentation can block requests even while raw bandwidth remains. How much this matters at realistic loads is one of the questions Section 8 answers.
3. **Bounded single-segment quantum reach (60 km simulation constraint).** The base study restricts generated topologies so that the longest candidate path never exceeds 60 km. This is a simulation design choice, not a physical ceiling of QKD, but unamplified single-segment quantum channels over shared, Raman-impaired fibre do decay exponentially. Distant node pairs cannot establish a direct single-segment key once attenuation and Raman noise push the end-to-end QSNR below $\Gamma_Q$.

## Overview of the Proposed T-DPC-RWA Framework

Motivated by the base paper's recommendation to explore dynamic traffic in future work, this study proposes Telemetry-Driven Dynamic Power Control and RWA (T-DPC-RWA) with sparse classical wavelength conversion and trusted relay segmentation. To keep attribution clean, the architecture separates noise mitigation, spectral-continuity relief and reach extension into three orthogonal mechanisms: (i) a closed-loop SDN telemetry controller that monitors active links and applies sensitivity-ordered classical power throttling followed by make-before-break (MBB) re-grooming; (ii) sparse O-E-O wavelength converters at high betweenness-centrality hubs, for classical channels only; and (iii) trusted relay nodes (explicitly distinguished from quantum repeaters) that terminate and re-establish QKD sessions over multi-hop chains.

# Literature Survey

To establish a theoretical foundation, 20 research papers spanning hybrid quantum-classical multiplexing, RWA optimisation, SDN orchestration and physical-layer security were analysed. Section 5.1 gives a structured comparison and Section 5.2 detailed reviews.

## Comparative Summary of Reviewed Literature

""" + lit_table() + r"""

## Comprehensive Paragraph-Form Literature Review

""" + REVIEW + r"""

# Proposed System Architecture

To address the static provisioning, wavelength continuity and single-segment reach limitations of the base paper while keeping concerns separate, we design a four-tier Software-Defined Networking (SDN) architecture, the T-DPC-RWA framework. As illustrated in Figure 1, it integrates an Application Layer, a centralised SDN Control Plane, a Hybrid Quantum-Classical Data Plane, and a continuous monitoring and telemetry loop.

![Figure 1: System architecture of the proposed closed-loop T-DPC-RWA framework with sparse classical O-E-O conversion and trusted relay nodes.](img/fig1_architecture.png){width=100%}

## Functional Breakdown of Architectural Layers

1. **Application Layer.** Enterprise data centres, financial institutions and government gateways generate stochastic connection arrivals over a northbound REST API. Two traffic classes are supported: (i) QKD connection demands $R_Q(s, d, \text{SKR}_{\min})$, which need an O-band quantum lightpath with bidirectional C-band sifting/authentication channels and an encrypted data channel; and (ii) classical lightpath demands $R_C(s, d, \text{SNR}_{th})$, which need C-band transport.
2. **SDN Control Plane (T-DPC-RWA Controller).** The controller has six modules: (a) the Admission & Request Parser validates demands and assigns priority tiers; (b) the Topology & State Repository keeps a live graph of link attenuations, wavelength occupancy ($\Lambda_q$ and $\Lambda_c$), launch powers $P_j(t)$, O-E-O transponder pools and Quantum Key Pool levels; (c) the Auxiliary Graph Engine builds a multi-layer graph modelling wavelength continuity, MQCCO overlap penalties and inter-layer O-E-O conversion; (d) the Sensitivity Power Controller assigns launch power at set-up and performs sensitivity-ordered throttling and re-grooming during QSNR dips; (e) the QSNR & SKR Predictor evaluates time-variant Raman cross-talk and decoy-state BB84 key rates; and (f) the Southbound Configurator translates routing and power decisions into NETCONF/OpenFlow commands.
3. **Hybrid Optical Data Plane.** QKD transmitters (Alice) launch weak coherent O-band pulses at 1310 nm; classical transmitters launch C-band signals at 1550 nm through variable optical attenuators (VOAs) for fine power tuning. WDM multiplexers combine the signals onto shared single-mode fibre. High-centrality hubs house sparse C-band O-E-O converters and trusted key relays. O-band quantum signals bypass all O-E-O electronics through passive O/C-band waveband splitters, so no active conversion noise enters the quantum path. At the receiver (Bob), signals pass a 100 GHz filter to single-photon detectors (SPDs) and classical receivers.
4. **Monitoring & Telemetry Feedback Loop.** Optical performance monitors and QKD post-processing units sample classical receiver SNR, received power and live QBER. A telemetry collector streams these metrics to the controller every $\Delta t$ seconds, closing the loop so that drift and cross-talk bursts are corrected before outage occurs.

# Proposed Methodology

Our methodology extends the base paper along three orthogonal dimensions, keeping each mechanism mathematically distinct so that its individual effect can be isolated by factorial ablation.

## Network Representation and Time-Variant Impairment Formulation

We model the optical transport network as an undirected graph $G = (V, E)$ in which each link $e \in E$ is a fibre pair of length $l_e$ (km) supporting $W_q = 10$ O-band wavelengths ($\Lambda_q$, around 1310 nm) and $W_c = 40$ C-band wavelengths ($\Lambda_c$, around 1550 nm). Requests arrive as a Poisson process with rate $\lambda$ and depart after exponentially distributed holding times with mean $1/\mu$, giving an offered load $A = \lambda/\mu$ Erlang. At time $t$, $C(t)$ is the set of active classical lightpaths and $Q(t)$ the set of active quantum lightpaths. Sparse O-E-O conversion splits a classical lightpath $c \in C(t)$ into $S_c \ge 1$ transparent segments, each with its own length $L_{c,s}$ and tunable launch power $P_{c,s}(t)$.

Generalising the base paper's static noise model to time-varying traffic, multi-segment O-E-O regeneration and pump attenuation before the shared span, the spontaneous anti-Stokes Raman noise coupled into quantum lightpath $q \in Q(t)$ is

$$N_R^{(q)}(t) = \gamma_{nl}\sum_{c\in C(t)}\sum_{s=1}^{S_c}\mathbb{I}\left[l_{(c,s),q}>0\right]P_{c,s}(t)\,e^{-\alpha_c d_{(c,s),q}}\left(e^{-\alpha_c l_{(c,s),q}}-e^{-\alpha_q l_{(c,s),q}}\right)$$

where $l_{(c,s),q}$ is the length of fibre shared by segment $(c,s)$ and quantum path $q$, $d_{(c,s),q}$ is the distance from the segment's transmitter (or O-E-O converter) to the start of the shared span, $\alpha_c = 0.17$ dB/km and $\alpha_q = 0.32$ dB/km, and $\gamma_{nl} = 2.25\times10^{-4}$ is the normalised Raman coupling parameter. With the closed-form sensitivity coefficient $\kappa_{j,q}(t) = \gamma_{nl}\,e^{-\alpha_c d_{j,q}}\left(e^{-\alpha_c l_{j,q}} - e^{-\alpha_q l_{j,q}}\right)$ for each interfering segment $j$, the instantaneous QSNR is

$$\text{QSNR}_q(t) = \frac{e^{-\alpha_q L_q}P_{tx,q}}{N_F+\sum_j\kappa_{j,q}(t)P_j(t)}\ \ge\ \Gamma_Q$$

where $L_q$ is the length of quantum segment $q$, $P_{tx,q} = \mu_p\,\eta_D$ is the normalised quantum launch level (mean photon number $\mu_p = t_q = e^{-\alpha_q L_q}$, SPD efficiency $\eta_D = 0.1$), $N_F = p_d = 10^{-4}$ is the dark-count floor per gate, and $\Gamma_Q = -5$ dB. To prevent mid-session outages the controller enforces a guard band $\varepsilon = 1.5$ dB: a channel is *safe* if $\text{QSNR}_q(t) \ge \Gamma_Q + \varepsilon$ (−3.5 dB), *at risk* if $\Gamma_Q \le \text{QSNR}_q(t) < \Gamma_Q + \varepsilon$, and in *outage* if $\text{QSNR}_q(t) < \Gamma_Q$.

Every classical segment $(c,s)$ must meet its receiver threshold $\text{SNR}_{th}$ against thermal noise $N(t)$ and time-varying excess connector/ageing loss $\eta_{c,s}(t) \le 1$. This gives the time-varying minimum launch power and admissible interval

$$P^{\min}_{c,s}(t) = \frac{\text{SNR}_{th}N(t)}{e^{-\alpha_c L_{c,s}}\eta_{c,s}(t)},\qquad P^{\min}_{c,s}(t)\left(1+m_{floor}\right)\le P_{c,s}(t)\le P_{\max}$$

At set-up, classical segments launch with margin $m_0 = 0.25$ above $P^{\min}_{c,s}(t_0)$, while $m_{floor} = 0.05$ is the hard safety floor. The difference $m_0 - m_{floor}$ is headroom the telemetry loop can throttle when nearby quantum channels see cross-talk spikes. To bring an at-risk channel back to $\Gamma_Q + \varepsilon$, the required noise reduction is

$$\Delta N^{*}_{q}(t) = N_F+\sum_j\kappa_{j,q}(t)P_j(t)-\frac{e^{-\alpha_q L_q}P_{tx,q}}{10^{(\Gamma_Q+\varepsilon)/10}}$$

## Sparse Classical O-E-O Wavelength Converter Placement

Rather than deploying converters at every node, we restrict conversion to a sparse budget of $K$ nodes chosen by length-weighted betweenness centrality:

$$C_B(v) = \frac{2}{\left(\left|V\right|-1\right)\left(\left|V\right|-2\right)}\sum_{s\neq v\neq d}\frac{\sigma_{sd}(v)}{\sigma_{sd}}$$

where $\sigma_{sd}$ is the number of shortest paths between $s$ and $d$, and $\sigma_{sd}(v)$ the number passing through $v$. The top $K$ nodes form the hub set $V_{OEO}$, each with $R$ transponder pairs. Converters act only on C-band classical channels; O-band quantum channels bypass them through passive waveband splitters.

## Multi-Segment Reach Extension via Trusted Relays

Under the physical model above, the QSNR of a noise-free single segment falls below the guard band at roughly 50 km, because the received signal scales as $t_q^2$. Distant pairs are therefore served through a subset of high-centrality nodes $T \subseteq V$ designated as trusted relays. A long-distance request $(s,d)$ is provisioned as a chain $s = r_0 \to r_1 \to \dots \to r_M = d$ with $r_m \in T$ and $M \le M_{\max}$. Each segment is an independent all-optical QKD lightpath satisfying Eq. (2) that generates a local key $K_m$. The end-to-end key $K_{s,d}$ is forwarded hop by hop with one-time-pad encryption ($K_{s,d} \oplus K_m$) inside physically secured relay enclaves. The end-to-end key rate is set by the bottleneck segment, $R_{s\to d} = \min_m R_{r_{m-1}\to r_m}$, where each segment's rate per pulse follows the asymptotic decoy-state BB84 bound under collective attacks:

$$R = \max\left\{0,\ \tfrac{1}{2}\left[-Q_\mu f_{EC}H_2(E_\mu)+Q_1\left(1-H_2(e_1)\right)\right]\right\}$$

with $Y_0 = N_F + N_R^{(q)}$, $\eta = \eta_D t_q$, $Q_\mu = Y_0 + 1 - e^{-\eta\mu_p}$, $E_\mu = \left[\tfrac{1}{2}Y_0 + e_d\left(1-e^{-\eta\mu_p}\right)\right]/Q_\mu$, $Y_1 = Y_0 + \eta$, $e_1 = \left(\tfrac{1}{2}Y_0 + e_d\eta\right)/Y_1$, $Q_1 = Y_1\mu_p e^{-\mu_p}$, misalignment error $e_d = (1-V)/2$ and $f_{EC} = 1.16$. Trusted relays are explicitly distinct from quantum repeaters: they measure photons and process classical bits, without quantum memories or entanglement swapping.

## Algorithmic Control Loop: T-DPC and Online Provisioning

The SDN control plane executes two coordinated algorithms: Algorithm 1 (periodic telemetry-driven power adaptation) and Algorithm 2 (online auxiliary-graph request provisioning).

""" + algo(ALG1) + "\n\u00a0\n\n" + algo(ALG2) + r"""

```{=openxml}
<w:p><w:r><w:br w:type="page"/></w:r></w:p>
```

# Implementation Details, Results and Discussion

## Discrete-Event Simulation Setup and Parameter Calibration

To evaluate T-DPC-RWA against the static heuristics of Ruiz and Garcia-Escartin (2026), we developed a discrete-event simulator in Python using SimPy for event scheduling, NetworkX for graph operations, and NumPy for the physical-layer and key-rate models (`tdpc_rwa_simulator.py`). The controller logic of Section 6 runs in-process, and the telemetry loop samples every simulated $\Delta t = 1$ s. Each data point averages @@real@@ independent topology-and-traffic realisations. Each run measures @@meas@@ requests after a @@warm@@-request warm-up, @@sims@@ simulation runs in total, and error bars are 95% confidence intervals. For a given realisation and load, every configuration sees the identical request and burst sequence (common random numbers), so differences between configurations come from the algorithms alone.

Two random geometric topology families are generated on a 100 km × 100 km plane with $\left|V\right| = 20$ nodes: Gabriel graphs, which are planar and sparse (measured mean nodal degree @@degg@@), and Waxman graphs with $\alpha_W = 100$ km and $\beta_W = 0.45$ (measured mean nodal degree @@degw@@). Multi-hop paths reach well beyond the base paper's 60 km horizon, exercising the reach-extension mechanism. Classical traffic bursts, short-lived lightpaths set up at 1 mW by an external fast path without QSNR admission, are injected identically into every configuration to model the cross-talk transients the telemetry loop is designed to correct. Configurations with the T-DPC loop admit new lightpaths at the guard level $\Gamma_Q + \varepsilon$; static configurations admit at $\Gamma_Q$. Table 1 summarises the parameters.

""" + param_table() + r"""

## Analysis of Request Blocking Ratio and Bottleneck Decomposition

Figure 2(a) shows the RBR from 10 to 100 Erlang on 20-node Waxman topologies ($f_q = 0.3$). Blocking is high even at light load: SP-FF without power control blocks @@sp_w10@@ of requests at 10 Erlang and @@sp_w80@@ at 80 Erlang, and the base paper's MQCCO with static power control blocks @@mq_w80@@ at 80 Erlang. The T-DPC loop alone (K = 0) gives @@td_w80@@, slightly above static MQCCO, because it admits quantum lightpaths at the stricter guard level (−3.5 dB instead of −5 dB) and so rejects a few borderline requests. The full framework reduces the RBR to @@fu_w80@@ at 80 Erlang, a @@red_w80@@% reduction relative to static MQCCO. All curves are nearly flat across load (static MQCCO stays between @@mq_w10@@ and @@mq_w100@@), which already indicates that the dominant blocking mechanism does not depend on how busy the network is.

Figure 2(b) explains why. At 80 Erlang, about @@reach_pct@@% of MQCCO's blocking is **single-segment reach**: quantum requests whose every candidate path is below the QSNR threshold even with no Raman noise at all. Wavelength-continuity (spectrum) blocking is essentially absent, because 40 C-band channels per fibre are not exhausted at this load, and Raman-induced QSNR blocking is small once launch power is controlled. The reduction delivered by the full framework therefore comes mainly from trusted relays, which turn reach-blocked requests into multi-segment chains.

![Figure 2: (a) Request blocking ratio vs offered load in 20-node Waxman topologies (log scale); (b) decomposition of blocking causes at 80 Erlang.](fig/fig1_rbr.png){width=100%}

## Quantum Signal-to-Noise Ratio and Secret Key Rate Performance

Figure 3 compares the time-averaged QSNR and asymptotic decoy-state BB84 SKR (Eq. (6)) across loads. Without power control, co-propagating 1 mW classical channels hold the mean QSNR of admitted sessions at @@q_sp80@@ dB at 80 Erlang, against @@q_mq80@@ dB for static MQCCO, @@q_td80@@ dB for the T-DPC loop alone and @@q_fu80@@ dB for the full framework (+@@q_gain@@ dB over MQCCO). The gain comes from the telemetry loop, which removes burst cross-talk within one polling interval; it is achieved even though relay chains admit long-distance sessions whose segments sit closer to the threshold. Those long sessions do, however, lower the key rate per session: the mean SKR per session at 80 Erlang is @@s_sp80@@ × 10⁻³ (SP-FF), @@s_mq80@@ × 10⁻³ (MQCCO) and @@s_fu80@@ × 10⁻³ bits/pulse (full framework), since a relay chain's rate is that of its weakest segment. Measured as network key throughput, the sum of key rates over all active sessions, the full framework delivers @@ns_fu@@ × 10⁻³ bits/pulse against @@ns_mq@@ × 10⁻³ for MQCCO (+@@ns_gain@@%), because it serves many more sessions (Table 3).

![Figure 3: (a) Time-averaged quantum SNR vs offered load; (b) asymptotic decoy-state BB84 secret key rate per session (×10⁻³ bits/pulse), 20-node Waxman.](fig/fig2_qsnr_skr.png){width=100%}

## Real-Time Telemetry Supervision and Sparse Converter Placement Analysis

Figure 4(a) plots a 100-second trace of a monitored QKD link ($@@msrc@@ \to @@mdst@@$, path @@mpath@@, @@mlen@@ km, noise-free QSNR @@mclean@@ dB) on a 10-node Gabriel network carrying 20 Erlang of background traffic. Two bursts hit its bottleneck link: @@n1@@ managed channels at $t = 30$ s and @@n2@@ fixed-power channels at $t = 65$ s. Under the base paper's static power control (red dashed curve), the bursts drive the link down to @@static_min@@ dB and it spends @@static_out@@% of the window below $\Gamma_Q$, halting key generation. Under T-DPC-RWA (green curve), the first burst pulls the QSNR to @@t30pre@@ dB; within the same 1 s telemetry tick Algorithm 1 applies Level-1 sensitivity-ordered throttling (@@l1steps@@ steps of 0.5 dB) and restores @@t30post@@ dB. The second burst (@@t65pre@@ dB) cannot be fixed by throttling, since fixed-power transceivers leave no headroom ($H_q < \Delta N_q^*$), so Algorithm 1 escalates to Level 2 and re-grooms @@mbb@@ dominant interferers onto an alternate route by make-before-break, restoring @@t65post@@ dB. The monitored link spends @@tdpc_out@@% of the window below $\Gamma_Q$.

Figure 4(b) evaluates betweenness-centrality placement of sparse O-E-O converters against uniform random and traffic-weighted degree placement. Because the C-band does not saturate at 80 Erlang (classical RBR @@cr80w0@@% without and @@cr80w4@@% with K = 4 on Waxman; @@cr80g0@@% and @@cr80g4@@% on Gabriel), the placement study is run at a spectrum-stress load of @@kload@@ Erlang on 20-node @@ktopo@@ topologies, where continuity blocking is significant. There, K = 4 betweenness-selected hubs reduce classical blocking from @@k0@@% (K = 0) to @@k4b@@%, capturing @@captured@@% of the reduction achieved by conversion at every node (@@kall@@%). At K = 4, uniform random placement gives @@k4r@@% and traffic-weighted degree @@k4t@@%. Across K, betweenness gives the most consistent reduction, but the confidence intervals of the three strategies overlap at this number of realisations.

![Figure 4: (a) Real-time QSNR trajectory under bursts, static power control vs closed-loop T-DPC-RWA; (b) classical RBR vs number of sparse O-E-O converter nodes K.](fig/fig3_telemetry_oeo.png){width=100%}

## Full Factorial Ablation Study Across Topologies

Table 2 presents the factorial ablation at 80 Erlang on 20-node Gabriel and Waxman topologies, toggling the T-DPC loop, sparse O-E-O conversion (K = 4) and trusted relays (∣T∣ = 3) independently. QTD has the highest mean QSNR (@@q_qtd@@ dB) because it keeps classical channels off quantum links, but this costs the highest blocking (@@rbr_qtd_g@@ Gabriel, @@rbr_qtd_w@@ Waxman), much of it spectrum blocking (@@spec_qtd@@ of all requests, Table 3). Trusted relays are the dominant blocking lever (@@rbr_rel_g@@ / @@rbr_rel_w@@ vs @@rbr_mq_g@@ / @@rbr_mq_w@@ for MQCCO). The T-DPC loop is the outage lever: it brings outage time to @@out_td@@% (vs @@out_mq@@% for static MQCCO) and removes the classical receiver-sensitivity violations that static minimum-power settings suffer under connector drift (@@viol_mq@@% of classical segment-seconds for MQCCO vs @@viol_fu@@% for the full framework). The full framework combines both effects: RBR @@rbr_fu_g@@ (Gabriel) and @@rbr_fu_w@@ (Waxman), outage time @@out_fu@@%, network key throughput +@@ns_gain@@% over MQCCO, and @@pw_fu@@% classical power savings. Its controller takes @@ms_fu@@ ms per request on average in the Python implementation (@@ms_mq@@ ms for MQCCO), within the budget for real-time operation. Sparse O-E-O conversion leaves the 80 Erlang results almost unchanged, consistent with Section 8.4.

""" + ablation_table() + "\n\n" + cause_table() + r"""

## Discussion and Threats to Validity

The results support the three architectural claims in different ways. The **closed-loop telemetry controller** is what removes outages: every configuration with the loop keeps session outage near zero and repairs classical drift, which no static configuration can do. **Trusted relays** produce most of the blocking reduction, because under the base paper's physical model with $\mu_p = t_q$ most blocked requests are blocked by single-segment reach, not by spectrum. **Sparse O-E-O conversion** pays off only when the C-band saturates. At 80 Erlang it changes little; at higher classical load a small number of well-placed hubs recovers most of the benefit of full conversion.

The main threats to validity are as follows. First, the photon-number model $\mu_p = t_q$ makes the received signal scale as $t_q^2$, limiting single-segment reach to about 50 km and zeroing the BB84 key rate whenever QSNR falls below roughly +5 dB. A fixed mean photon number would change absolute QSNR and SKR values substantially. Second, classical bursts are a modelling assumption; their rate and power set the absolute outage figures. Third, the Raman model is co-propagating and undepleted, and telemetry is assumed exact. Fourth, @@real@@ realisations of @@meas@@ requests give confidence intervals that overlap for some close comparisons, notably among O-E-O placement strategies. The simulator, all raw runs and all figure data are provided so every number here can be regenerated.

# Conclusion

This study extended the power-controlled routing and wavelength assignment heuristics of Ruiz and Garcia-Escartin (2026) for hybrid quantum-classical optical networks. The base paper showed that attenuating classical launch powers to their functional minimum mitigates spontaneous anti-Stokes Raman noise in co-propagating O-band quantum channels, but its evaluation was limited to static demand sets, one-shot launch-power calibration, passive wavelength continuity and a 60 km path bound.

To bridge the gap between static heuristics and dynamic networks, we developed the T-DPC-RWA framework, which addresses each limitation with a dedicated mechanism: (1) a closed-loop SDN telemetry controller that polls QSNR and classical SNR every $\Delta t$ and applies sensitivity-ordered power throttling and make-before-break re-grooming; (2) sparse O-E-O wavelength converters at high betweenness-centrality hubs, for classical channels only; and (3) multi-segment trusted relays (distinct from quantum repeaters) that extend QKD connectivity beyond single-segment reach.

Discrete-event simulation on 20-node Gabriel and Waxman topologies under stochastic Poisson traffic showed that, at 80 Erlang, the full framework reduces the Request Blocking Ratio by @@red_g@@% (Gabriel) and @@red_w@@% (Waxman) relative to static power-controlled MQCCO, reduces session outage time from @@out_mq@@% to @@out_fu@@%, increases network key throughput by @@ns_gain@@%, and retains @@pw_fu@@% classical transmitter power savings. The ablation attributes the blocking gain mainly to trusted relays, the outage gain to the telemetry loop, and shows sparse conversion to be valuable once the C-band saturates. Future work will incorporate finite-key security bounds, account for noisy telemetry estimates, study alternative photon-number models, and explore multi-band coexistence across S+C+L-band elastic optical infrastructures.

# References

""" + REFS)

# ----------------------------------------------------------------------------- build
work = os.path.join(HERE, "build")
os.makedirs(os.path.join(work, "fig"), exist_ok=True)
for f in ("fig1_rbr.png", "fig2_qsnr_skr.png", "fig3_telemetry_oeo.png"):
    shutil.copy(os.path.join(RES, f), os.path.join(work, "fig", f))
shutil.copytree(os.path.join(HERE, "img"), os.path.join(work, "img"), dirs_exist_ok=True)
with open(os.path.join(work, "report.md"), "w") as f:
    f.write(MD)
print("values:", {k: V[k] for k in ("red_g", "red_w", "out_mq", "out_fu", "ns_gain", "pw_fu", "reach_pct", "captured")})
