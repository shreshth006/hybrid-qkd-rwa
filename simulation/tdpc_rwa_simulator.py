#!/usr/bin/env python3
"""
T-DPC-RWA: Dynamic Routing and Wavelength Assignment for Hybrid QKD Networks
with Adaptive Power Control and Sparse Wavelength Conversion.

Discrete-event simulator (simpy) for the proposal that extends
  L. Ruiz and J. C. Garcia-Escartin, "Routing and wavelength assignment in
  quantum key distribution networks: Power control heuristics for
  quantum-classical multiplexing", Computer Communications 256 (2026) 108572.

Modes
  --mode demo   live telemetry trace + 10/20-node sweeps, tables, CSVs, figures
  --mode full   Monte-Carlo campaign over many seeds (default 50) and loads 10..100 Erl

Modelling notes (read before presenting results)
  * Raman noise is the co-propagating, undepleted-pump spontaneous anti-Stokes
    model with a lumped coefficient gamma_nl. It is expressed directly in
    detector-click probability per gate, so it adds to N_F = p_d in the QSNR
    denominator, and Y0 = N_F + N_R in the key-rate model.
  * The quantum launch level follows the brief: P_tx,q = mu_p * eta_D with
    mu_p = t_q = exp(-alpha_q L_q). This makes the QSNR fall off as t_q^2, so a
    single quantum segment is limited to roughly 50 km. Change MU_MODE to
    "fixed" to use a constant mean photon number MU_FIXED instead.
  * Classical "traffic bursts" are short-lived lightpaths set up by an external
    fast path, with no QSNR admission check, at the 1 mW default launch power.
    A "managed" burst can be power-throttled by the SDN controller. A
    "fixed-power" burst cannot (fixed-output transceivers), but it can be
    re-routed. Bursts are injected identically in every configuration. Only
    configurations that run the T-DPC telemetry loop can react to them.
  * All configurations see the same request and burst sequence for a given
    seed and load (common random numbers).
"""
from __future__ import annotations

import argparse
import csv
import heapq
import itertools
import math
import multiprocessing as mp
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from functools import lru_cache

import networkx as nx
import numpy as np
import simpy

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

try:
    from tabulate import tabulate
except ImportError:  # minimal fallback so the script still runs without tabulate
    tabulate = None

# =============================================================================
# 1. Physical-layer and control-plane parameters
# =============================================================================
W_Q = 10                        # O-band quantum wavelengths per fibre (CWDM, 1310 nm)
W_C = 40                        # C-band classical wavelengths per fibre (DWDM 100 GHz)
W_T = W_Q + W_C

ALPHA_Q_DB = 0.32               # dB/km at 1310 nm
ALPHA_C_DB = 0.17               # dB/km at 1550 nm
ALPHA_Q = ALPHA_Q_DB / (10 * math.log10(math.e))   # 0.0737 Np/km
ALPHA_C = ALPHA_C_DB / (10 * math.log10(math.e))   # 0.0391 Np/km

BETA_Q = 1e-12                  # spontaneous Raman coefficient (100 GHz filter), folded into GAMMA_NL
GAMMA_NL = 2.25e-4              # lumped nonlinear coefficient (click probability per mW)
ETA_D = 0.10                    # SPD efficiency
P_D = 1e-4                      # dark-count probability per 10 ns gate
N_F = P_D                       # fixed noise term in the QSNR denominator
VISIBILITY = 0.98
E_D = (1 - VISIBILITY) / 2      # optical misalignment error
F_EC = 1.16                     # error-correction inefficiency
MU_MODE = "transmittance"       # "transmittance": mu_p = t_q (as specified) | "fixed"
MU_FIXED = 0.5

RX_SENS_DBM = -36.8             # classical receiver sensitivity (= SNR_th * N_c)
P_RX_MIN = 10 ** (RX_SENS_DBM / 10)   # mW
P_MAX = 1.0                     # mW, maximum / default classical launch power
P_BURST = 1.0                   # mW, fast-path default for burst lightpaths

GAMMA_Q = -5.0                  # dB, hard QSNR outage threshold
EPSILON = 1.5                   # dB, telemetry guard band
HYST = 0.5                      # dB, hysteresis for power recovery
GUARD = GAMMA_Q + EPSILON       # -3.5 dB
M_0 = 0.25                      # initial launch-power margin (adaptive PC)
M_FLOOR = 0.05                  # hard lower safety floor
DELTA_P_DB = 0.5                # throttling step
DELTA_T = 1.0                   # s, telemetry polling interval
I_MAX = 400                     # max throttling steps per quantum channel per tick
MAX_MBB = 6                     # max make-before-break re-grooms per quantum channel per tick

AREA_KM = 100.0                 # nodes placed on a 100 km x 100 km plane
ALPHA_W = 100.0                 # km, Waxman distance scale
BETA_W = 0.45                   # Waxman link density
MEAN_HOLD = 60.0                # s, 1/mu
MU_RATE = 1.0 / MEAN_HOLD
F_Q = 0.3                       # probability that a request is quantum
K_PATHS = 4                     # candidate paths per node pair
W_CONV = 15.0                   # km-equivalent cost of one O-E-O conversion in the auxiliary graph
W_OVERLAP = 1.0                 # weight of quantum-overlap cost in the auxiliary graph
TRANSPONDERS = 16               # R, transponder pairs per O-E-O hub
MAX_RELAY_SEGMENTS = 3          # M <= 3
STRESS_LOAD = 250               # Erl: load at which the 20-node C-band saturates (O-E-O placement study)

BURST_RATE = 1 / 45.0           # bursts per second
BURST_HOLD = 20.0               # s, mean burst duration
BURST_FIXED_PROB = 0.4          # share of bursts that use fixed-power transceivers
ETA_STEP = 0.002                # random-walk step of connector/fibre excess loss per tick
ETA_MIN, ETA_MAX = 0.85, 1.0


def hubs_for(n): return 2 if n <= 10 else 4
def relays_for(n): return 2 if n <= 10 else 3


# =============================================================================
# 2. Physics: equations (1)-(6) of the brief
# =============================================================================
def lin_to_db(x: float) -> float:
    return 10 * math.log10(x) if x > 0 else -math.inf


def calc_kappa(l_shared: float, d_before: float, alpha_c: float = ALPHA_C, alpha_q: float = ALPHA_Q) -> float:
    """Closed-form Raman sensitivity of one quantum channel to 1 mW on one classical
    segment: kappa = gamma_nl e^{-a_c d} (e^{-a_c l} - e^{-a_q l})."""
    if l_shared <= 0:
        return 0.0
    return GAMMA_NL * math.exp(-alpha_c * d_before) * (math.exp(-alpha_c * l_shared) - math.exp(-alpha_q * l_shared))


def calc_raman_noise(interferers) -> tuple[float, list[float]]:
    """Eq. (1): N_R = sum_j kappa_j P_j over (kappa, power) pairs. Returns the total and each term."""
    terms = [k * p for k, p in interferers]
    return sum(terms), terms


def quantum_signal(L_q: float, alpha_q: float = ALPHA_Q) -> float:
    """Numerator of eq. (2): e^{-a_q L} P_tx,q with P_tx,q = mu_p eta_D."""
    t = math.exp(-alpha_q * L_q)
    mu = t if MU_MODE == "transmittance" else MU_FIXED
    return t * mu * ETA_D


def calc_qsnr_db(L_q: float, noise_raman: float) -> float:
    """Eq. (2): QSNR = 10 log10( e^{-a_q L} P_tx,q / (N_F + N_R) )."""
    return lin_to_db(quantum_signal(L_q) / (N_F + noise_raman))


def calc_classical_power_bounds(L: float, eta: float, alpha_c: float = ALPHA_C) -> tuple[float, float, float]:
    """Eq. (3): returns (P_min, lower bound P_min(1+m_floor), P_max)."""
    p_min = P_RX_MIN / (math.exp(-alpha_c * L) * eta)
    return p_min, p_min * (1 + M_FLOOR), P_MAX


def calc_target_noise_reduction(L_q: float, noise_raman: float) -> float:
    """Eq. (4): noise reduction needed to bring QSNR back to Gamma_Q + epsilon."""
    return N_F + noise_raman - quantum_signal(L_q) / (10 ** (GUARD / 10))


def h2(x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 0.5:
        return 1.0
    return -x * math.log2(x) - (1 - x) * math.log2(1 - x)


def calc_bb84_skr(L_q: float, noise_raman: float) -> float:
    """Eq. (6): asymptotic decoy-state BB84 key rate per pulse (collective attacks)."""
    t = math.exp(-ALPHA_Q * L_q)
    eta = ETA_D * t
    mu = t if MU_MODE == "transmittance" else MU_FIXED
    y0 = N_F + noise_raman
    q_mu = y0 + 1 - math.exp(-eta * mu)
    e_mu = (0.5 * y0 + E_D * (1 - math.exp(-eta * mu))) / q_mu
    y1 = y0 + eta
    e1 = (0.5 * y0 + E_D * eta) / y1
    q1 = y1 * mu * math.exp(-mu)
    return max(0.0, 0.5 * (-q_mu * F_EC * h2(e_mu) + q1 * (1 - h2(e1))))


def chain_skr(rates: list[float]) -> float:
    """Trusted-relay chain s=r0 -> ... -> rM=d: the bottleneck segment sets the end-to-end rate."""
    return min(rates) if rates else 0.0


# =============================================================================
# 3. Topologies and O-E-O hub / trusted-relay selection
# =============================================================================
def link_key(u, v):
    return (u, v) if u < v else (v, u)


@lru_cache(maxsize=64)
def gen_topology(kind: str, n: int, seed: int) -> nx.Graph:
    """Gabriel (planar, sparse) or Waxman (p = beta e^{-d/alpha}, dense) graph on a
    100 km x 100 km plane. Edge attribute 'length' is the Euclidean distance in km."""
    rng = random.Random(f"{kind}-{n}-{seed}")
    while True:
        pos = {}
        while len(pos) < n:  # keep nodes >= 8 km apart so no link is unrealistically short
            p = (rng.uniform(0, AREA_KM), rng.uniform(0, AREA_KM))
            if all(math.dist(p, q) >= 8.0 for q in pos.values()):
                pos[len(pos)] = p
        G = nx.Graph()
        for i, p in pos.items():
            G.add_node(i, pos=p)
        pairs = list(itertools.combinations(range(n), 2))
        if kind == "gabriel":
            for i, j in pairs:
                mid = ((pos[i][0] + pos[j][0]) / 2, (pos[i][1] + pos[j][1]) / 2)
                r2 = math.dist(pos[i], pos[j]) ** 2 / 4
                if all(math.dist(pos[k], mid) ** 2 >= r2 for k in range(n) if k not in (i, j)):
                    G.add_edge(i, j, length=math.dist(pos[i], pos[j]))
        else:
            for i, j in pairs:
                d = math.dist(pos[i], pos[j])
                if rng.random() < BETA_W * math.exp(-d / ALPHA_W):
                    G.add_edge(i, j, length=d)
            if not nx.is_connected(G):  # bridge components with minimum-spanning-tree edges
                K = nx.Graph()
                for i, j in pairs:
                    K.add_edge(i, j, length=math.dist(pos[i], pos[j]))
                for u, v, d in nx.minimum_spanning_edges(K, weight="length", data=True):
                    if not nx.has_path(G, u, v):
                        G.add_edge(u, v, length=d["length"])
        if nx.is_connected(G) and min(dict(G.degree()).values()) >= 1:
            return G


def select_oeo_hubs(G: nx.Graph, K: int, method: str = "betweenness", seed: int = 0,
                    traffic_weight: dict | None = None) -> list:
    """Eq. (5): top-K nodes by length-weighted betweenness centrality, or the
    comparison placements 'random' and 'traffic' (traffic-weighted degree)."""
    if method == "betweenness":
        bc = nx.betweenness_centrality(G, weight="length", normalized=True)
        return sorted(G.nodes, key=lambda v: (-bc[v], v))[:K]
    if method == "random":
        return sorted(random.Random(f"oeo-{seed}").sample(list(G.nodes), K))
    if method == "traffic":
        tw = traffic_weight or {v: 1.0 for v in G.nodes}
        return sorted(G.nodes, key=lambda v: (-G.degree(v) * tw.get(v, 1.0), v))[:K]
    raise ValueError(method)


# =============================================================================
# 4. Traffic generation (common random numbers across configurations)
# =============================================================================
@dataclass
class Request:
    rid: int
    t: float
    src: int
    dst: int
    quantum: bool
    hold: float


@dataclass
class Burst:
    t: float
    n: int
    fixed: bool
    hold: float
    selector: float
    link: tuple | None = None   # forced link (demo); otherwise chosen at run time


def gen_traffic(n: int, load: float, t_end: float, seed: int) -> tuple[list[Request], list[Burst]]:
    rng = random.Random(f"traffic-{n}-{load}-{seed}")
    lam = load * MU_RATE
    reqs, t, rid = [], 0.0, 0
    while True:
        t += rng.expovariate(lam)
        if t > t_end:
            break
        s, d = rng.sample(range(n), 2)
        reqs.append(Request(rid, t, s, d, rng.random() < F_Q, rng.expovariate(MU_RATE)))
        rid += 1
    bursts, t = [], 0.0
    brng = random.Random(f"bursts-{n}-{load}-{seed}")
    while True:
        t += brng.expovariate(BURST_RATE)
        if t > t_end:
            break
        bursts.append(Burst(t, brng.randint(3, 6), brng.random() < BURST_FIXED_PROB,
                            brng.expovariate(1 / BURST_HOLD), brng.random()))
    return reqs, bursts


# =============================================================================
# 5. Network state
# =============================================================================
@dataclass
class Config:
    name: str
    routing: str          # "sp" | "mqdo" | "mqcco" | "qtd"
    pc: str               # "none" | "static" | "adaptive"
    tdpc: bool = False    # closed-loop telemetry (Algorithm 1)
    oeo: bool = False     # sparse classical wavelength conversion
    relays: bool = False  # trusted-relay segmentation

    @property
    def threshold(self) -> float:
        return GUARD if self.tdpc else GAMMA_Q


CONFIGS = {c.name: c for c in [
    Config("SP-FF (No PC)", "sp", "none"),
    Config("MQDO + Static PC", "mqdo", "static"),
    Config("MQCCO + Static PC", "mqcco", "static"),
    Config("QTD + Static PC", "qtd", "static"),
    Config("T-DPC Only", "mqcco", "adaptive", tdpc=True),
    Config("Sparse O-E-O Only", "mqcco", "static", oeo=True),
    Config("Trusted Relays Only", "mqcco", "static", relays=True),
    Config("T-DPC + O-E-O", "mqcco", "adaptive", tdpc=True, oeo=True),
    Config("Full T-DPC-RWA", "mqcco", "adaptive", tdpc=True, oeo=True, relays=True),
]}
CORE = ["SP-FF (No PC)", "MQDO + Static PC", "MQCCO + Static PC", "QTD + Static PC", "Full T-DPC-RWA"]
ABLATION = list(CONFIGS)


@dataclass(eq=False)
class Segment:
    sid: int
    lp: "ClassicalLP"
    nodes: list
    links: list
    lam: int
    length: float
    offset: dict              # link -> distance from the transmitter to that link
    power: float
    eta: float
    throttleable: bool
    qs: dict = field(default_factory=dict)   # QuantumLP -> kappa
    throttled: bool = False


@dataclass(eq=False)
class ClassicalLP:
    cid: int
    src: int
    dst: int
    kind: str                 # "demand" | "control" | "data" | "burst"
    fixed_power: bool
    segments: list = field(default_factory=list)
    hubs: list = field(default_factory=list)  # nodes where an O-E-O transponder is used


@dataclass(eq=False)
class QuantumLP:
    qid: int
    nodes: list
    links: list
    lam: int
    length: float
    segs: dict = field(default_factory=dict)  # Segment -> kappa
    noise: float = 0.0
    dirty: bool = True
    degraded: bool = False


@dataclass(eq=False)
class QRequest:
    req: Request
    qlps: list
    clps: list


class Simulator:
    """One run of one configuration on one topology with one traffic sequence."""

    def __init__(self, G: nx.Graph, cfg: Config, requests, bursts, seed: int,
                 t_warm: float, t_end: float, hub_method: str = "betweenness",
                 log=None, monitor_hook=None, pre_control_hook=None, k_hubs=None):
        self.G, self.cfg, self.requests, self.bursts = G, cfg, requests, bursts
        self.t_warm, self.t_end = t_warm, t_end
        self.rng = random.Random(f"sim-{seed}")
        self.log = log
        self.monitor_hook = monitor_hook
        self.pre_control_hook = pre_control_hook
        self.length = {link_key(u, v): d["length"] for u, v, d in G.edges(data=True)}
        self.q_free = {lk: np.ones(W_Q, bool) for lk in self.length}
        self.c_free = {lk: np.ones(W_C, bool) for lk in self.length}
        self.link_q = {lk: set() for lk in self.length}
        self.link_seg = {lk: set() for lk in self.length}
        n = G.number_of_nodes()
        traffic_w = {v: 1.0 for v in G.nodes}
        for r in requests:
            traffic_w[r.src] += 1
            traffic_w[r.dst] += 1
        k = hubs_for(n) if k_hubs is None else (n if k_hubs == "all" else int(k_hubs))
        self.hubs = select_oeo_hubs(G, k, hub_method, seed, traffic_w) if cfg.oeo and hub_method != "none" and k > 0 else []
        self.hub_free = {h: TRANSPONDERS for h in self.hubs}
        self.relays = select_oeo_hubs(G, relays_for(n), "betweenness") if cfg.relays else []
        self._ksp_cache: dict = {}
        self._ids = itertools.count(1)
        self.active_q: list[QRequest] = []
        self.active_c: list[ClassicalLP] = []
        self.m = dict(arrivals=0, blocked=0, q_arrivals=0, q_blocked=0, relay_chains=0,
                      net_skr_sum=0.0, ticks=0, b_spectrum=0, b_qsnr=0, b_reach=0,
                      cpu_ms=0.0, cpu_n=0,
                      qsnr_sum=0.0, qsnr_n=0, outage=0, skr_sum=0.0, skr_n=0,
                      p_sum=0.0, p_ref=0.0, c_viol=0, c_samples=0,
                      l1=0, l2=0, repairs=0, recover=0, degraded=0, bursts=0)

    # ----------------------------------------------------------------- logging
    def _log(self, tag: str, msg: str, t: float | None = None):
        if self.log:
            self.log(self.env.now if t is None else t, tag, msg)

    # ------------------------------------------------------------- geometry
    def path_links(self, nodes):
        return [link_key(a, b) for a, b in zip(nodes, nodes[1:])]

    def path_len(self, nodes):
        return sum(self.length[lk] for lk in self.path_links(nodes))

    def ksp(self, s, d, exclude: frozenset = frozenset()):
        key = (s, d, exclude)
        if key not in self._ksp_cache:
            G = self.G if not exclude else nx.restricted_view(self.G, [], list(exclude))
            try:
                self._ksp_cache[key] = list(itertools.islice(nx.shortest_simple_paths(G, s, d, weight="length"), K_PATHS))
            except nx.NetworkXNoPath:
                self._ksp_cache[key] = []
        return self._ksp_cache[key]

    def _offsets(self, nodes):
        off, acc = {}, 0.0
        for lk in self.path_links(nodes):
            off[lk] = acc
            acc += self.length[lk]
        return off

    def _kappa(self, seg_links, seg_off, q_links_set) -> float:
        shared = [lk for lk in seg_links if lk in q_links_set]
        if not shared:
            return 0.0
        l = sum(self.length[lk] for lk in shared)
        d = min(seg_off[lk] for lk in shared)
        return calc_kappa(l, d)

    # ------------------------------------------------------------- quantum noise / QSNR
    def q_noise(self, q: QuantumLP) -> float:
        if q.dirty:
            q.noise = calc_raman_noise((k, s.power) for s, k in q.segs.items())[0]
            q.dirty = False
        return q.noise

    def qsnr(self, q: QuantumLP) -> float:
        return calc_qsnr_db(q.length, self.q_noise(q))

    def skr(self, q: QuantumLP) -> float:
        return calc_bb84_skr(q.length, self.q_noise(q))

    def _set_power(self, seg: Segment, p: float):
        seg.power = p
        for q in seg.qs:
            q.dirty = True

    # ------------------------------------------------------------- allocation
    def _alloc_segment(self, lp: ClassicalLP, nodes, lam, power, eta, throttleable) -> Segment:
        links = self.path_links(nodes)
        seg = Segment(next(self._ids), lp, nodes, links, lam, self.path_len(nodes),
                      self._offsets(nodes), power, eta, throttleable)
        for lk in links:
            self.c_free[lk][lam] = False
            self.link_seg[lk].add(seg)
        qs = set().union(*(self.link_q[lk] for lk in links))
        for q in qs:
            k = self._kappa(links, seg.offset, set(q.links))
            if k > 0:
                seg.qs[q] = k
                q.segs[seg] = k
                q.dirty = True
        lp.segments.append(seg)
        return seg

    def _free_segment(self, seg: Segment):
        for lk in seg.links:
            self.c_free[lk][seg.lam] = True
            self.link_seg[lk].discard(seg)
        for q in seg.qs:
            q.segs.pop(seg, None)
            q.dirty = True
        seg.qs.clear()

    def _release_classical(self, lp: ClassicalLP):
        for seg in lp.segments:
            self._free_segment(seg)
        for h in lp.hubs:
            self.hub_free[h] += 1
        lp.segments, lp.hubs = [], []
        if lp in self.active_c:
            self.active_c.remove(lp)

    def _alloc_quantum(self, nodes, lam) -> QuantumLP:
        links = self.path_links(nodes)
        q = QuantumLP(next(self._ids), nodes, links, lam, self.path_len(nodes))
        lset = set(links)
        for lk in links:
            self.q_free[lk][lam] = False
            self.link_q[lk].add(q)
        for seg in set().union(*(self.link_seg[lk] for lk in links)):
            k = self._kappa(seg.links, seg.offset, lset)
            if k > 0:
                seg.qs[q] = k
                q.segs[seg] = k
        return q

    def _release_quantum(self, q: QuantumLP):
        for lk in q.links:
            self.q_free[lk][q.lam] = True
            self.link_q[lk].discard(q)
        for seg in q.segs:
            seg.qs.pop(q, None)
        q.segs.clear()

    # ------------------------------------------------------------- power policy
    def _launch_power(self, length, eta, fixed=False, kind="demand"):
        if fixed or kind == "burst":
            return P_BURST
        p_min, _, _ = calc_classical_power_bounds(length, eta)
        if self.cfg.pc == "none":
            return P_MAX
        if self.cfg.pc == "static":
            return min(P_MAX, p_min)            # one-shot minimum at set-up (base paper)
        return min(P_MAX, p_min * (1 + M_0))    # adaptive: set-up margin m_0

    # ------------------------------------------------------------- routing costs
    def _link_cost(self, lk):
        """Quantum-overlap cost of one link for the active routing policy."""
        if not self.link_q[lk]:
            return 0.0
        if self.cfg.routing == "mqcco" and self.link_seg[lk]:
            return 2 * self.length[lk]
        return self.length[lk]

    def _order_paths(self, paths):
        if self.cfg.routing == "sp":
            return paths
        if self.cfg.routing == "qtd":
            return [p for p in paths if not any(self.link_q[lk] for lk in self.path_links(p))]
        return sorted(paths, key=lambda p: (sum(self._link_cost(lk) for lk in self.path_links(p)), self.path_len(p)))

    def _qsnr_ok_with(self, seg_specs, thr) -> bool:
        """Would adding these classical segments (nodes, power) keep every affected
        quantum channel at or above thr?"""
        delta: dict = {}
        for nodes, power in seg_specs:
            links = self.path_links(nodes)
            off = self._offsets(nodes)
            for q in set().union(*(self.link_q[lk] for lk in links)):
                k = self._kappa(links, off, set(q.links))
                if k:
                    delta[q] = delta.get(q, 0.0) + k * power
        return all(calc_qsnr_db(q.length, self.q_noise(q) + dn) >= thr for q, dn in delta.items())

    # ------------------------------------------------------------- Algorithm 2: classical
    def route_classical(self, src, dst, kind="demand", fixed=False, exclude=frozenset(),
                        check=True, thr=None):
        """Returns ([(nodes, lam), ...], hubs, eta0) or None. Several segments means O-E-O conversion."""
        thr = self.cfg.threshold if thr is None else thr
        eta0 = self.rng.uniform(0.92, 1.0)
        saw_free = False
        for p in self._order_paths(self.ksp(src, dst, exclude)):
            links = self.path_links(p)
            free = np.logical_and.reduce([self.c_free[lk] for lk in links])
            idx = np.flatnonzero(free)
            if idx.size == 0:
                continue
            saw_free = True
            power = self._launch_power(self.path_len(p), eta0, fixed, kind)
            if check and not self._qsnr_ok_with([(p, power)], thr):
                continue
            return [(p, int(idx[0]))], [], eta0
        if self.cfg.oeo and self.hubs:
            res = self._aux_graph_route(src, dst, exclude)
            if res:
                segs, hubs = res
                specs = [(n, self._launch_power(self.path_len(n), eta0, fixed, kind)) for n, _ in segs]
                if not check or self._qsnr_ok_with(specs, thr):
                    return segs, hubs, eta0
                saw_free = True
        # spectrum: no continuous free wavelength on any candidate; qsnr: one existed but would push a quantum channel below threshold
        self.last_cause = "qsnr" if saw_free else "spectrum"
        return None

    def _aux_graph_route(self, src, dst, exclude):
        """Dijkstra on the layered auxiliary graph: one layer per C-band wavelength;
        inter-layer (conversion) edges only at O-E-O hubs with a free transponder."""
        qtd = self.cfg.routing == "qtd"
        dist, prev, heap = {}, {}, []
        for lam in range(W_C):
            dist[(src, lam)] = 0.0
            prev[(src, lam)] = None
            heap.append((0.0, src, lam))
        heapq.heapify(heap)
        end = None
        while heap:
            c, u, lam = heapq.heappop(heap)
            if c > dist.get((u, lam), math.inf):
                continue
            if u == dst:
                end = (u, lam)
                break
            for v in self.G[u]:
                lk = link_key(u, v)
                if lk in exclude or not self.c_free[lk][lam] or (qtd and self.link_q[lk]):
                    continue
                nc = c + self.length[lk] + W_OVERLAP * self._link_cost(lk)
                if nc < dist.get((v, lam), math.inf):
                    dist[(v, lam)] = nc
                    prev[(v, lam)] = (u, lam)
                    heapq.heappush(heap, (nc, v, lam))
            if u in self.hub_free and self.hub_free[u] > 0 and u != src:
                for lam2 in range(W_C):
                    if lam2 == lam:
                        continue
                    nc = c + W_CONV
                    if nc < dist.get((u, lam2), math.inf):
                        dist[(u, lam2)] = nc
                        prev[(u, lam2)] = (u, lam)
                        heapq.heappush(heap, (nc, u, lam2))
        if end is None:
            return None
        states = []
        s = end
        while s is not None:
            states.append(s)
            s = prev[s]
        states.reverse()
        segs, hubs, cur = [], [], [states[0][0]]
        lam = states[0][1]
        for (n1, l1), (n2, l2) in zip(states, states[1:]):
            if n1 == n2:          # conversion at hub n1
                segs.append((cur, lam))
                hubs.append(n1)
                cur, lam = [n1], l2
            else:
                cur.append(n2)
        segs.append((cur, lam))
        segs = [(n, l) for n, l in segs if len(n) > 1]
        if len(set(hubs)) != len(hubs):
            return None
        return segs, hubs

    def _install_classical(self, src, dst, kind, route, fixed=False) -> ClassicalLP:
        segs, hubs, eta0 = route
        lp = ClassicalLP(next(self._ids), src, dst, kind, fixed)
        for nodes, lam in segs:
            power = self._launch_power(self.path_len(nodes), eta0, fixed, kind)
            throttleable = self.cfg.tdpc and not fixed
            self._alloc_segment(lp, nodes, lam, power, eta0, throttleable)
        for h in hubs:
            self.hub_free[h] -= 1
        lp.hubs = list(hubs)
        self.active_c.append(lp)
        return lp

    # ------------------------------------------------------------- Algorithm 2: quantum
    def route_quantum(self, src, dst, thr, exclude=frozenset()):
        """Direct single-segment O-band lightpath: first-fit wavelength on the k shortest paths."""
        saw_free = noise_fail = False
        for p in self.ksp(src, dst, exclude):
            links = self.path_links(p)   # QTD constrains classical placement only
            free = np.logical_and.reduce([self.q_free[lk] for lk in links])
            idx = np.flatnonzero(free)
            if idx.size == 0:
                continue
            saw_free = True
            L = self.path_len(p)
            lset = set(links)
            noise = sum(self._kappa(s.links, s.offset, lset) * s.power
                        for s in set().union(*(self.link_seg[lk] for lk in links)))
            if calc_qsnr_db(L, noise) >= thr:
                return p, int(idx[0])
            if calc_qsnr_db(L, 0.0) >= thr:
                noise_fail = True     # feasible without Raman noise: blocked by cross-talk
        # reach: even a noise-free channel on every free path is below threshold
        self.last_cause = "qsnr" if noise_fail else ("reach" if saw_free else "spectrum")
        return None

    def route_quantum_chain(self, src, dst, thr):
        """Trusted-relay overlay: try every relay sequence (M <= 3 segments) and keep
        the chain with the highest bottleneck key rate. Segments are allocated
        tentatively in order so they cannot collide on a wavelength."""
        relays = [r for r in self.relays if r not in (src, dst)]
        best = None
        for m in range(1, MAX_RELAY_SEGMENTS):
            for seq in itertools.permutations(relays, m):
                hops = [src, *seq, dst]
                placed = []
                ok = True
                for a, b in zip(hops, hops[1:]):
                    r = self.route_quantum(a, b, thr)
                    if r is None:
                        ok = False
                        break
                    placed.append(self._alloc_quantum(*r))
                if ok:
                    rate = chain_skr([self.skr(q) for q in placed])
                    cand = (rate, -len(placed), [(q.nodes, q.lam) for q in placed])
                    if best is None or cand[:2] > best[:2]:
                        best = cand
                for q in placed:
                    self._release_quantum(q)
        return None if best is None else best[2]

    # ------------------------------------------------------------- request handling
    def handle_arrival(self, r: Request):
        t0 = time.perf_counter()
        self._handle_arrival(r)
        if r.t >= self.t_warm:
            self.m["cpu_ms"] += 1e3 * (time.perf_counter() - t0)
            self.m["cpu_n"] += 1

    def _handle_arrival(self, r: Request):
        measuring = r.t >= self.t_warm
        if measuring:
            self.m["arrivals"] += 1
            self.m["q_arrivals"] += r.quantum
        if not r.quantum:
            route = self.route_classical(r.src, r.dst, "demand")
            if route is None:
                return self._block(r, measuring, "no C-band path/wavelength meeting QSNR")
            lp = self._install_classical(r.src, r.dst, "demand", route)
            self._log("ARRIVE", f"req#{r.rid:<4} classical {r.src}->{r.dst}: {self._describe_lp(lp)}")
            self.env.process(self._lifetime(r, [], [lp]))
            return
        thr = self.cfg.threshold
        qroute = self.route_quantum(r.src, r.dst, thr)
        chain = [qroute] if qroute else None
        direct_cause = getattr(self, "last_cause", "reach")
        if chain is None and self.cfg.relays:
            chain = self.route_quantum_chain(r.src, r.dst, thr)
            self.last_cause = direct_cause
        if chain is None:
            return self._block(r, measuring, "no O-band path meeting QSNR (reach/noise)")
        qlps = [self._alloc_quantum(n, l) for n, l in chain]
        clps = []
        for kind in ("control", "control", "data"):
            route = self.route_classical(r.src, r.dst, kind)
            if route is None:
                for lp in clps:
                    self._release_classical(lp)
                for q in qlps:
                    self._release_quantum(q)
                return self._block(r, measuring, f"no C-band {kind} channel for QKD session")
            clps.append(self._install_classical(r.src, r.dst, kind, route))
        if measuring and len(qlps) > 1:
            self.m["relay_chains"] += 1
        qr = QRequest(r, qlps, clps)
        self.active_q.append(qr)
        desc = " | ".join(f"{'-'.join(map(str, q.nodes))} λq{q.lam} {q.length:.1f} km QSNR={self.qsnr(q):+.2f} dB"
                          for q in qlps)
        relay = f" via {len(qlps) - 1} trusted relay(s)" if len(qlps) > 1 else ""
        self._log("ARRIVE", f"req#{r.rid:<4} QUANTUM   {r.src}->{r.dst}{relay}: {desc} + 3 C-band ctrl/data")
        self.env.process(self._lifetime(r, qlps, clps, qr))

    def _block(self, r: Request, measuring: bool, why: str):
        cause = getattr(self, "last_cause", "spectrum")
        if measuring:
            self.m["blocked"] += 1
            self.m["q_blocked"] += r.quantum
            self.m["b_" + cause] += 1
        why = f"{why} [cause: {cause}]"
        self._log("BLOCK", f"req#{r.rid:<4} {'QUANTUM' if r.quantum else 'classical'} {r.src}->{r.dst}: {why}")

    def _lifetime(self, r: Request, qlps, clps, qr=None):
        yield self.env.timeout(r.hold)
        for lp in clps:
            self._release_classical(lp)
        for q in qlps:
            self._release_quantum(q)
        if qr is not None:
            self.active_q.remove(qr)
        self._log("DEPART", f"req#{r.rid:<4} {'QUANTUM' if r.quantum else 'classical'} {r.src}->{r.dst} released")

    def _describe_lp(self, lp: ClassicalLP) -> str:
        parts = [f"{'-'.join(map(str, s.nodes))} λc{s.lam} @{s.power:.4f} mW" for s in lp.segments]
        conv = f" (O-E-O at {', '.join(map(str, lp.hubs))})" if lp.hubs else ""
        return " => ".join(parts) + conv

    # ------------------------------------------------------------- bursts
    def _burst_proc(self):
        for b in self.bursts:
            yield self.env.timeout(max(0.0, b.t - self.env.now))
            link = b.link
            if link is None:
                busy = sorted(lk for lk in self.length if self.link_q[lk])
                pool = busy or sorted(self.length)
                link = pool[int(b.selector * len(pool)) % len(pool)]
            u, v = link
            lps = []
            for _ in range(b.n):
                idx = np.flatnonzero(self.c_free[link_key(u, v)])
                if idx.size == 0:
                    break
                lp = self._install_classical(u, v, "burst", ([([u, v], int(idx[0]))], [], 1.0), fixed=b.fixed)
                if not b.fixed and self.cfg.tdpc:
                    for s in lp.segments:
                        s.throttleable = True
                lps.append(lp)
            if self.env.now >= self.t_warm:
                self.m["bursts"] += 1
            kind = "fixed-power" if b.fixed else "managed"
            self._log("BURST", f"+{len(lps)} {kind} lightpaths on link {u}-{v} at {P_BURST:.3f} mW "
                               f"(external fast path, no admission check), hold {b.hold:.1f} s")
            self.env.process(self._burst_end(lps, b.hold, link))

    def _burst_end(self, lps, hold, link):
        yield self.env.timeout(hold)
        for lp in lps:
            self._release_classical(lp)
        self._log("BURST", f"-{len(lps)} burst lightpaths released (originally on {link[0]}-{link[1]})")

    # ------------------------------------------------------------- Algorithm 1: telemetry loop
    def _telemetry_proc(self):
        while True:
            yield self.env.timeout(DELTA_T)
            self._drift_and_repair()
            if self.pre_control_hook:
                self.pre_control_hook(self)
            if self.cfg.tdpc:
                self._control_loop()
            if self.env.now >= self.t_warm:
                self._sample()
            if self.monitor_hook:
                self.monitor_hook(self)

    def _drift_and_repair(self):
        measuring = self.env.now >= self.t_warm
        for lp in self.active_c:
            for s in lp.segments:
                s.eta = min(ETA_MAX, max(ETA_MIN, s.eta + self.rng.gauss(0, ETA_STEP)))
                p_min, p_floor, _ = calc_classical_power_bounds(s.length, s.eta)
                if s.power < p_min * (1 - 1e-9):
                    if self.cfg.tdpc and not lp.fixed_power:
                        self._set_power(s, min(P_MAX, p_floor))
                        self.m["repairs"] += 1
                    elif measuring:
                        self.m["c_viol"] += 1
                if measuring:
                    self.m["c_samples"] += 1

    def _control_loop(self):
        qs = [q for qr in self.active_q for q in qr.qlps]
        at_risk = sorted((q for q in qs if self.qsnr(q) < GUARD), key=self.qsnr)
        for q in at_risk:
            before = self.qsnr(q)
            if before >= GUARD:
                continue
            self._log("TELEM", f"q#{q.qid} ({'-'.join(map(str, q.nodes))}, {q.length:.1f} km) "
                               f"QSNR={before:+.2f} dB < guard {GUARD:+.1f} dB")
            noise = self.q_noise(q)
            dn = calc_target_noise_reduction(q.length, noise)
            headroom = 0.0
            for s, k in q.segs.items():
                if s.throttleable:
                    _, p_floor, _ = calc_classical_power_bounds(s.length, s.eta)
                    headroom += k * max(0.0, s.power - p_floor)
            if headroom >= dn:
                self._level1(q, dn, headroom)
            else:
                self._log("L1", f"headroom H={headroom:.2e} < ΔN*={dn:.2e}: throttling cannot restore q#{q.qid}, escalating")
            if self.qsnr(q) < GUARD:
                self._level2(q)
        self._recover()

    def _level1(self, q: QuantumLP, dn: float, headroom: float):
        self.m["l1"] += 1
        order = sorted((s for s in q.segs if s.throttleable), key=lambda s: -q.segs[s] * s.power)
        start = {s: s.power for s in order}
        step = 10 ** (-DELTA_P_DB / 10)
        i = 0
        while self.qsnr(q) < GUARD and i < I_MAX:
            progressed = False
            for s in order:
                if self.qsnr(q) >= GUARD:
                    break
                _, p_floor, _ = calc_classical_power_bounds(s.length, s.eta)
                if s.power > p_floor:
                    self._set_power(s, max(s.power * step, p_floor))
                    s.throttled = True
                    progressed = True
                    i += 1
            if not progressed:
                break
        self._log("L1", f"headroom H={headroom:.2e} >= ΔN*={dn:.2e}: sensitivity-ordered throttling of "
                        f"{len(order)} interferer(s), {i} step(s) of {DELTA_P_DB} dB")
        for s in order:
            if s.power < start[s]:
                self._log("L1", f"    c#{s.lp.cid} ({s.lp.kind}) on {'-'.join(map(str, s.nodes))}: "
                                f"{start[s]:.4f} -> {s.power:.4f} mW ({lin_to_db(s.power / start[s]):+.1f} dB)")
        self._log("L1", f"q#{q.qid} QSNR now {self.qsnr(q):+.2f} dB")

    def _level2(self, q: QuantumLP):
        tried = set()
        for _ in range(MAX_MBB):
            if self.qsnr(q) >= GUARD:
                return
            cands = [s for s in q.segs if s.lp not in tried]
            if not cands:
                break
            top = max(cands, key=lambda s: q.segs[s] * s.power)
            lp = top.lp
            top_kp = q.segs[top] * top.power
            tried.add(lp)
            excl = frozenset(q.links)
            route = self.route_classical(lp.src, lp.dst, lp.kind, lp.fixed_power, exclude=excl, thr=GUARD)
            if route is None:
                self._log("L2", f"no alternate route for c#{lp.cid} avoiding q#{q.qid}'s links")
                continue
            old = self._describe_lp(lp)
            new = self._install_classical(lp.src, lp.dst, lp.kind, route, lp.fixed_power)   # MAKE
            if lp.kind == "burst" and not lp.fixed_power and self.cfg.tdpc:
                for s in new.segments:
                    s.throttleable = True
            old_segments, old_hubs = lp.segments, lp.hubs                                 # BREAK
            lp.segments, lp.hubs = new.segments, new.hubs
            for s in lp.segments:
                s.lp = lp
            self.active_c.remove(new)
            tmp = ClassicalLP(-1, lp.src, lp.dst, lp.kind, lp.fixed_power, old_segments, old_hubs)
            self._release_classical(tmp)
            self.m["l2"] += 1
            self._log("L2", f"MBB re-groom c#{lp.cid} ({lp.kind}, top interferer κP={top_kp:.2e})")
            self._log("L2", f"    MAKE  {self._describe_lp(lp)}")
            self._log("L2", f"    BREAK {old}")
            self._log("L2", f"q#{q.qid} QSNR now {self.qsnr(q):+.2f} dB")
        if self.qsnr(q) < GUARD:
            self._reroute_quantum(q)

    def _reroute_quantum(self, q: QuantumLP):
        """Last resort: make-before-break move of the quantum lightpath itself."""
        excl = frozenset(lk for lk in q.links if any(s.power >= P_BURST * 0.5 for s in self.link_seg[lk]))
        r = self.route_quantum(q.nodes[0], q.nodes[-1], GUARD, exclude=excl)
        if r is None:
            if not q.degraded:
                q.degraded = True
                self.m["degraded"] += 1
            self._log("L2", f"q#{q.qid} cannot be restored this tick (QSNR {self.qsnr(q):+.2f} dB): marked degraded")
            return
        new = self._alloc_quantum(*r)
        old_desc = f"{'-'.join(map(str, q.nodes))} λq{q.lam}"
        self._release_quantum(q)
        q.nodes, q.links, q.lam, q.length, q.segs, q.dirty = new.nodes, new.links, new.lam, new.length, new.segs, True
        for lk in q.links:
            self.link_q[lk].discard(new)
            self.link_q[lk].add(q)
        for s in list(q.segs):
            s.qs[q] = s.qs.pop(new)
        self.m["l2"] += 1
        self._log("L2", f"MBB re-route of q#{q.qid}: {old_desc} -> {'-'.join(map(str, q.nodes))} λq{q.lam}, "
                        f"QSNR {self.qsnr(q):+.2f} dB")

    def _recover(self):
        """Hysteresis recovery: step throttled powers back up by +Δp towards P_min(1+m_0)."""
        step = 10 ** (DELTA_P_DB / 10)
        for lp in self.active_c:
            for s in lp.segments:
                if not s.throttled:
                    continue
                p_min, _, _ = calc_classical_power_bounds(s.length, s.eta)
                target = min(P_MAX, p_min * (1 + M_0))
                if s.power >= target:
                    s.throttled = False
                    continue
                if any(self.qsnr(q) < GUARD + HYST for q in s.qs):
                    continue
                old = s.power
                self._set_power(s, min(target, s.power * step))
                if any(self.qsnr(q) < GUARD for q in s.qs):
                    self._set_power(s, old)
                else:
                    self.m["recover"] += 1

    def _sample(self):
        self.m["ticks"] += 1
        for qr in self.active_q:
            vals = [self.qsnr(q) for q in qr.qlps]
            for v in vals:
                self.m["qsnr_sum"] += v
                self.m["qsnr_n"] += 1
            self.m["outage"] += min(vals) < GAMMA_Q
            rate = chain_skr([self.skr(q) for q in qr.qlps])
            self.m["skr_sum"] += rate
            self.m["net_skr_sum"] += rate
            self.m["skr_n"] += 1
        for lp in self.active_c:
            if lp.kind == "burst":
                continue
            for s in lp.segments:
                self.m["p_sum"] += s.power
                self.m["p_ref"] += P_MAX

    # ------------------------------------------------------------- run
    def run(self) -> dict:
        self.env = simpy.Environment()
        self.env.process(self._arrivals())
        self.env.process(self._burst_proc())
        self.env.process(self._telemetry_proc())
        self.env.run(until=self.t_end)
        return self.metrics()

    def _arrivals(self):
        for r in self.requests:
            yield self.env.timeout(max(0.0, r.t - self.env.now))
            self.handle_arrival(r)

    def metrics(self) -> dict:
        m = self.m
        div = lambda a, b: a / b if b else float("nan")
        return dict(
            rbr=div(m["blocked"], m["arrivals"]),
            q_rbr=div(m["q_blocked"], m["q_arrivals"]),
            c_rbr=div(m["blocked"] - m["q_blocked"], m["arrivals"] - m["q_arrivals"]),
            mean_qsnr=div(m["qsnr_sum"], m["qsnr_n"]),
            outage_pct=100 * div(m["outage"], m["skr_n"]),
            mean_skr=div(m["skr_sum"], m["skr_n"]),
            net_skr=div(m["net_skr_sum"], m["ticks"]),
            power_saved_pct=100 * (1 - div(m["p_sum"], m["p_ref"])),
            classical_viol_pct=100 * div(m["c_viol"], m["c_samples"]),
            rbr_spectrum=div(m["b_spectrum"], m["arrivals"]),
            rbr_qsnr=div(m["b_qsnr"], m["arrivals"]),
            rbr_reach=div(m["b_reach"], m["arrivals"]),
            ms_per_request=div(m["cpu_ms"], m["cpu_n"]),
            relay_chains=m["relay_chains"], l1=m["l1"], l2=m["l2"], repairs=m["repairs"],
            recover=m["recover"], degraded=m["degraded"], arrivals=m["arrivals"],
        )


# =============================================================================
# 6. Experiment runner
# =============================================================================
def job_window(job: dict) -> tuple[float, float]:
    """Simulation window: time-based (demo) or request-count based (full mode,
    e.g. 10,000 warm-up + 100,000 measured requests as in the report)."""
    if job.get("requests"):
        lam = job["load"] * MU_RATE
        warm = job["requests"] / 10
        return warm / lam, (warm + job["requests"]) / lam
    return job["t_warm"], job["t_end"]


def run_job(job: dict) -> dict:
    t_warm, t_end = job_window(job)
    G = gen_topology(job["topo"], job["n"], job["seed"])
    reqs, bursts = gen_traffic(job["n"], job["load"], t_end, job["seed"])
    sim = Simulator(G, CONFIGS[job["config"]], reqs, bursts, job["seed"], t_warm, t_end,
                    job.get("hub_method", "betweenness"), k_hubs=job.get("k_hubs"))
    out = sim.run()
    out.update({k: job[k] for k in ("topo", "n", "config", "load", "seed")})
    out["hub_method"] = job.get("hub_method", "betweenness")
    out["k_hubs"] = str(job.get("k_hubs", hubs_for(job["n"])))
    out["experiment"] = job["experiment"]
    return out


def run_jobs(jobs, procs):
    if procs <= 1:
        return [run_job(j) for j in jobs]
    with mp.Pool(procs) as pool:
        return pool.map(run_job, jobs, chunksize=1)


def aggregate(rows, keys, metrics):
    groups: dict = {}
    for r in rows:
        groups.setdefault(tuple(r[k] for k in keys), []).append(r)
    out = []
    for k, rs in groups.items():
        d = dict(zip(keys, k))
        for mname in metrics:
            vals = [r[mname] for r in rs if not math.isnan(r[mname])]
            d[mname] = statistics.fmean(vals) if vals else float("nan")
            d[mname + "_ci"] = (1.96 * statistics.stdev(vals) / math.sqrt(len(vals))) if len(vals) > 1 else 0.0
        d["runs"] = len(rs)
        out.append(d)
    return out


METRICS = ["rbr", "q_rbr", "c_rbr", "rbr_spectrum", "rbr_qsnr", "rbr_reach", "mean_qsnr", "outage_pct",
           "mean_skr", "net_skr", "power_saved_pct", "classical_viol_pct", "ms_per_request"]


# =============================================================================
# 7. Live demonstration trace (bottleneck quantum link, bursts at 30 s and 65 s)
# =============================================================================
class Console:
    COLORS = {"ARRIVE": "\033[36m", "DEPART": "\033[90m", "BLOCK": "\033[33m", "BURST": "\033[35m",
              "TELEM": "\033[93m", "L1": "\033[32m", "L2": "\033[94m", "QSNR": "\033[37m", "INFO": "\033[1m"}

    def __init__(self, color=True, silent=False):
        self.color = color and sys.stdout.isatty()
        self.silent = silent
        self.events = []

    def __call__(self, t, tag, msg):
        self.events.append((t, tag, msg))
        if self.silent:
            return
        c, r = (self.COLORS.get(tag, ""), "\033[0m") if self.color else ("", "")
        print(f"{c}[t={t:7.2f}s] {tag:<6} {msg}{r}")


def find_demo_scenario(seed_start=1):
    """Pick a 10-node Gabriel topology and a quantum pair whose path (36-46 km) has a
    link with an alternate route, so a burst on that link can be re-groomed."""
    for seed in range(seed_start, seed_start + 50):
        G = gen_topology("gabriel", 10, seed)
        cands = []
        for s, d in itertools.combinations(sorted(G.nodes), 2):
            p = nx.shortest_path(G, s, d, weight="length")
            L = nx.path_weight(G, p, "length")
            if len(p) < 3 or not 36 <= L <= 46:
                continue
            plinks = [link_key(a, b) for a, b in zip(p, p[1:])]
            for (u, v) in plinks:
                if G.edges[u, v]["length"] < 12:
                    continue
                H = nx.restricted_view(G, [], plinks)
                if nx.has_path(H, u, v) and nx.shortest_path_length(H, u, v, weight="length") <= 90:
                    cands.append((abs(L - 42), s, d, p, (u, v)))
        if cands:
            _, s, d, p, link = min(cands)
            return seed, G, s, d, p, link
    raise RuntimeError("no demo scenario found")


def _trace_run(G, cfg_name, reqs, bursts, seed, t_end, con):
    """Run the scripted scenario and record the monitored channel's QSNR each tick,
    measured before and after the control action."""
    trace, pre = [], {}

    def before(sim):
        qr = next((x for x in sim.active_q if x.req.rid == 10_000), None)
        if qr is not None:
            pre[sim.env.now] = sim.qsnr(qr.qlps[0])

    def after(sim):
        qr = next((x for x in sim.active_q if x.req.rid == 10_000), None)
        if qr is None:
            return
        q = qr.qlps[0]
        val = sim.qsnr(q)
        trace.append((sim.env.now, pre.get(sim.env.now, val), val, sim.skr(q), len(q.segs), sim.q_noise(q)))
        if not con.silent and int(round(sim.env.now)) % 5 == 0:
            con(sim.env.now, "QSNR", f"monitored q#{q.qid} {'-'.join(map(str, q.nodes))}: QSNR={val:+.2f} dB, "
                                     f"{len(q.segs)} co-propagating interferer(s), N_R={sim.q_noise(q):.2e}")

    sim = Simulator(G, CONFIGS[cfg_name], reqs, bursts, seed, 0.0, t_end, log=con,
                    monitor_hook=after, pre_control_hook=before)
    sim.run()
    return sim, trace


def run_demo_trace(outdir, color=True):
    seed, G, s, d, qpath, (u, v) = find_demo_scenario()
    L = nx.path_weight(G, qpath, "length")
    lk = link_key(u, v)
    l_link = G.edges[u, v]["length"]
    k = calc_kappa(l_link, 0.0)
    clean = calc_qsnr_db(L, 0.0)

    def bursts_needed(margin_db):
        for n in range(1, W_C):
            if calc_qsnr_db(L, n * k * P_BURST) <= GUARD - margin_db:
                return n
        return W_C // 2
    n1, n2 = min(bursts_needed(1.0), 12), min(bursts_needed(1.5), 12)

    t_end = 100.0
    reqs, _ = gen_traffic(10, 20, t_end, seed)
    reqs = [Request(10_000, 0.5, s, d, True, 1e9)] + [r for r in reqs if r.t > 1.0]
    bursts = [Burst(30.0, n1, False, 20.0, 0.0, (u, v)), Burst(65.0, n2, True, 25.0, 0.0, (u, v))]

    print(f"\n{'=' * 100}\n LIVE TELEMETRY TRACE: Full T-DPC-RWA on a 10-node Gabriel graph (seed {seed})\n{'=' * 100}")
    print(f" Monitored QKD link {s}->{d} on path {'-'.join(map(str, qpath))} ({L:.1f} km), clean QSNR {clean:+.2f} dB")
    print(f" Bottleneck link {u}-{v} ({l_link:.1f} km), kappa={k:.2e} per mW")
    print(f" Background traffic: 20 Erlang. Burst 1 at t=30 s: {n1} managed channels. "
          f"Burst 2 at t=65 s: {n2} fixed-power channels.")
    print(f" Guard Γ_Q+ε = {GUARD:+.1f} dB, outage Γ_Q = {GAMMA_Q:+.1f} dB, hysteresis h = {HYST} dB\n")
    con = Console(color)
    sim, trace = _trace_run(G, "Full T-DPC-RWA", reqs, bursts, seed, t_end, con)
    m = sim.m
    # Same scenario under the base paper's static one-shot power control, for Fig. 3(a)
    _, static_trace = _trace_run(G, "MQCCO + Static PC", reqs, bursts, seed, t_end, Console(silent=True))
    out_t = 100 * sum(x[2] < GAMMA_Q for x in trace) / max(1, len(trace))
    out_s = 100 * sum(x[2] < GAMMA_Q for x in static_trace) / max(1, len(static_trace))
    print(f"\n Trace: {m['l1']} Level-1 throttling action(s), {m['l2']} Level-2 MBB re-groom(s), "
          f"{m['repairs']} classical repair(s), {m['recover']} recovery step(s).")
    print(f" Monitored link below Γ_Q: T-DPC-RWA {out_t:.1f}% of ticks vs static MQCCO+PC {out_s:.1f}% of ticks.\n")
    with open(os.path.join(outdir, "demo_trace.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "tdpc_qsnr_before_control_db", "tdpc_qsnr_after_control_db", "tdpc_skr_per_pulse",
                    "interferers", "raman_noise", "static_pc_qsnr_db"])
        smap = {x[0]: x[2] for x in static_trace}
        w.writerows(list(x) + [smap.get(x[0], "")] for x in trace)
    with open(os.path.join(outdir, "demo_events.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "tag", "message"])
        w.writerows(con.events)
    return dict(trace=trace, static=static_trace, events=con.events, n1=n1, n2=n2,
                outage_tdpc=out_t, outage_static=out_s)


# =============================================================================
# 8. Tables
# =============================================================================
def show(title, headers, rows):
    print(f"\n{title}")
    if tabulate:
        print(tabulate(rows, headers=headers, tablefmt="fancy_grid", floatfmt=".4g"))
    else:
        widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
        print(" | ".join(str(h).ljust(w) for h, w in zip(headers, widths)))
        for r in rows:
            print(" | ".join(str(x).ljust(w) for x, w in zip(r, widths)))


def table1():
    rows = [
        ["Optical wavebands", "Quantum: O-band (1310 nm, CWDM) | Classical: C-band (1550 nm, DWDM 100 GHz)", "Base paper"],
        ["Wavelength capacity per fibre", f"W_q = {W_Q}, W_c = {W_C} (W_T = {W_T})", "Base paper"],
        ["Fibre attenuation", f"α_q = {ALPHA_Q_DB} dB/km ({ALPHA_Q:.4f} Np/km) | α_c = {ALPHA_C_DB} dB/km ({ALPHA_C:.4f} Np/km)", "Base paper"],
        ["Raman coupling & Rx filter", f"β_q = {BETA_Q:g} km^-1 (100 GHz), γ_nl = {GAMMA_NL:g}", "Base paper"],
        ["SPD efficiency & noise", f"η_D = {ETA_D}, p_d = N_F = {P_D:g} per 10 ns gate, V = {VISIBILITY}", "Base paper"],
        ["Classical receiver sensitivity", f"{RX_SENS_DBM} dBm minimum reception power", "Base paper"],
        ["QSNR thresholds & guard band", f"Γ_Q = {GAMMA_Q} dB | ε = {EPSILON} dB (trigger {GUARD} dB) | h = {HYST} dB", "Proposed work"],
        ["Dynamic power-control margins", f"m_0 = {M_0}, m_floor = {M_FLOOR}, Δp = {DELTA_P_DB} dB, Δt = {DELTA_T} s", "Proposed work"],
        ["Sparse O-E-O & trusted relays", f"K = 4 hubs (R = {TRANSPONDERS}), |T| = 3, M_max = {MAX_RELAY_SEGMENTS} (20-node); K = 2, |T| = 2 (10-node)", "Proposed work"],
        ["Stochastic traffic profile", f"Poisson arrivals, 1/μ = {MEAN_HOLD:g} s, A ∈ [10, 100] Erl, f_q = {F_Q}", "Proposed work"],
        ["Classical traffic bursts", f"1 per {1 / BURST_RATE:g} s, 3-6 ch @ {P_BURST} mW, {int(BURST_FIXED_PROB * 100)}% fixed-power, mean {BURST_HOLD:g} s", "Simulation assumption"],
    ]
    show("Table 1: Physical-layer and control-plane parameters used in the discrete-event simulations",
         ["Parameter", "Value / range", "Reference"], rows)
    return rows


def fmt(v, kind):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    return {"pct": f"{v:.2f}%", "rbr": f"{v:.4f}", "db": f"{v:.1f} dB", "skr3": f"{v * 1e3:.2f}",
            "ms": f"{v:.2f}"}[kind]


TABLE2_ROWS = [  # (label, config, T-DPC, O-E-O, relays) as laid out in the report's Table 2
    ("1. Baseline SP-FF (No Power Control)", "SP-FF (No PC)", "Off", "K = 0", "|T| = 0"),
    ("2. Base Paper MQDO + Static PC", "MQDO + Static PC", "Static", "K = 0", "|T| = 0"),
    ("3. Base Paper MQCCO + Static PC", "MQCCO + Static PC", "Static", "K = 0", "|T| = 0"),
    ("4. Base Paper QTD (Strict Disjoint)", "QTD + Static PC", "Static", "K = 0", "|T| = 0"),
    ("5. Proposed: T-DPC Loop Only", "T-DPC Only", "Active", "K = 0", "|T| = 0"),
    ("6. Proposed: Sparse O-E-O Only", "Sparse O-E-O Only", "Static", "K = 4", "|T| = 0"),
    ("7. Proposed: Trusted Relays Only", "Trusted Relays Only", "Static", "K = 0", "|T| = 3"),
    ("8. Proposed: T-DPC + Sparse O-E-O", "T-DPC + O-E-O", "Active", "K = 4", "|T| = 0"),
    ("9. Full Proposed T-DPC-RWA Framework", "Full T-DPC-RWA", "Active", "K = 4", "|T| = 3"),
]


# =============================================================================
# 9. Figures (numbered as in the report: Fig. 2, 3, 4; Fig. 1 is the architecture)
# =============================================================================
STYLE = {"SP-FF (No PC)": ("#8c8c8c", "o", "--", "SP-FF (No PC)"),
         "MQCCO + Static PC": ("#1f77b4", "s", "-.", "Base paper MQCCO (static PC)"),
         "T-DPC Only": ("#ff7f0e", "^", ":", "Proposed T-DPC (K=0)"),
         "Full T-DPC-RWA": ("#2ca02c", "D", "-", "Full T-DPC-RWA (K=4, |T|=3)")}
FIG_RBR = ["SP-FF (No PC)", "MQCCO + Static PC", "T-DPC Only", "Full T-DPC-RWA"]
FIG_QUALITY = ["SP-FF (No PC)", "MQCCO + Static PC", "Full T-DPC-RWA"]


def _curve(ax, agg, name, metric, scale=1.0):
    pts = sorted((r["load"], r[metric] * scale, r[metric + "_ci"] * scale) for r in agg if r["config"] == name)
    if not pts:
        return
    x, y, e = zip(*pts)
    c, mk, ls, label = STYLE[name]
    ax.errorbar(x, y, yerr=e, color=c, marker=mk, ls=ls, ms=5, lw=2, capsize=3, label=label)


def make_figures(outdir, sweep_agg, trace, ksweep_agg, sweep_title, k_title):
    plt.rcParams.update({"font.size": 11, "axes.titleweight": "bold", "figure.dpi": 110})

    # Fig. 2: (a) RBR vs load (log scale), (b) blocking-cause breakdown at 80 Erl
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(13, 5))
    for name in FIG_RBR:
        _curve(ax, sweep_agg, name, "rbr")
    ax.set_yscale("log", nonpositive="mask")
    ax.set_xlabel("Offered network traffic load (Erlang)")
    ax.set_ylabel("Request blocking ratio")
    ax.set_title(f"(a) Request blocking ratio vs. load ({sweep_title})")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=9)
    loads = sorted({r["load"] for r in sweep_agg})
    at = 80 if 80 in loads else loads[-1]
    names = FIG_RBR
    parts = [("rbr_spectrum", "#2f3e55", "Wavelength continuity / spectrum"),
             ("rbr_qsnr", "#e74c3c", f"QSNR violation (< {GAMMA_Q:g} dB / guard)"),
             ("rbr_reach", "#f39c12", "Single-segment reach")]
    bottom = np.zeros(len(names))
    for key, col, label in parts:
        vals = np.array([next((r[key] for r in sweep_agg if r["config"] == n and r["load"] == at), 0.0) for n in names])
        bx.bar(range(len(names)), vals, bottom=bottom, color=col, label=label, width=0.6)
        bottom += vals
    bx.set_xticks(range(len(names)), ["SP-FF\n(No PC)", "Base MQCCO\n(Static PC)", "T-DPC Only\n(K=0)",
                                      "Full Proposed\n(K=4, |T|=3)"], fontsize=9)
    bx.set_ylabel("Share of all requests blocked")
    bx.set_title(f"(b) Blocking cause breakdown at {at} Erlang")
    bx.grid(alpha=0.3, axis="y")
    bx.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "fig1_rbr.png"), dpi=300)
    plt.close(fig)

    # Fig. 3: (a) mean QSNR vs load, (b) BB84 SKR vs load
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(13, 5))
    for name in FIG_QUALITY:
        _curve(ax, sweep_agg, name, "mean_qsnr")
        _curve(bx, sweep_agg, name, "mean_skr", 1e3)
    ax.axhline(GUARD, color="#d4a017", ls=":", lw=1.3)
    ax.axhline(GAMMA_Q, color="k", ls="-", lw=1)
    ax.set_xlabel("Offered network load (Erlang)")
    ax.set_ylabel("Time-averaged QSNR (dB)")
    ax.set_title("(a) Time-averaged quantum SNR vs. load")
    bx.set_xlabel("Offered network load (Erlang)")
    bx.set_ylabel("Secret key rate (×10⁻³ bits/pulse)")
    bx.set_title("(b) Decoy-state BB84 secret key rate")
    for a in (ax, bx):
        a.grid(alpha=0.3)
        a.legend(fontsize=9)
    fig.suptitle(sweep_title)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "fig2_qsnr_skr.png"), dpi=300)
    plt.close(fig)

    # Fig. 4: (a) real-time QSNR trajectory, static PC vs T-DPC; (b) classical RBR vs K
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(13, 5))
    if trace["static"]:
        t, _, q, *_ = zip(*trace["static"])
        ax.plot(t, q, color="#c0392b", ls="--", lw=1.8, label=f"Static PC (MQCCO), {trace['outage_static']:.1f}% below Γ$_Q$")
    if trace["trace"]:
        t, _, q, *_ = zip(*trace["trace"])
        ax.plot(t, q, color="#2e8b57", lw=2.2, label=f"T-DPC-RWA, {trace['outage_tdpc']:.1f}% below Γ$_Q$")
    ax.axhline(GUARD, color="#d4a017", ls=":", lw=1.5, label=f"Guard band ({GUARD:g} dB)")
    ax.axhline(GAMMA_Q, color="k", lw=1.2, label=f"Outage Γ$_Q$ ({GAMMA_Q:g} dB)")
    ax.axvspan(30, 50, color="#9467bd", alpha=0.10)
    ax.axvspan(65, 90, color="#8c564b", alpha=0.10)
    ax.text(31, ax.get_ylim()[1], f" burst 1: {trace['n1']} managed", va="top", fontsize=8)
    ax.text(66, ax.get_ylim()[1], f" burst 2: {trace['n2']} fixed-power", va="top", fontsize=8)
    ax.set_xlabel("Simulation time (s)")
    ax.set_ylabel("QSNR (dB)")
    ax.set_title("(a) Real-time QSNR trajectory under bursts")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="lower left")
    order = ["0", "1", "2", "3", "4", "5", "6", "all"]
    for method, col, mk, ls, label in [("random", "#8c8c8c", "o", "--", "Random"),
                                       ("traffic", "#1f77b4", "s", "-.", "Traffic-weighted degree"),
                                       ("betweenness", "#e67e22", "D", "-", "Betweenness (proposed)")]:
        pts = []
        for i, kk in enumerate(order):
            r = next((x for x in ksweep_agg if x["k_hubs"] == kk and x["hub_method"] in (method, "any")), None)
            if r:
                pts.append((i, 100 * r["c_rbr"], 100 * r["c_rbr_ci"]))
        if pts:
            x, y, e = zip(*pts)
            bx.errorbar(x, y, yerr=e, color=col, marker=mk, ls=ls, lw=2, capsize=3, label=label)
    bx.set_xticks(range(len(order)), [k if k != "all" else "Full" for k in order])
    bx.set_xlabel("Number of sparse O-E-O converter nodes (K)")
    bx.set_ylabel("Classical request blocking ratio (%)")
    bx.set_title(f"(b) Classical RBR vs. O-E-O hubs\n({k_title})", fontsize=12)
    bx.grid(alpha=0.3)
    bx.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "fig3_telemetry_oeo.png"), dpi=300)
    plt.close(fig)


# =============================================================================
# 10. Main
# =============================================================================
def write_csv(path, rows):
    if not rows:
        return
    keys = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def mean_degree(kind, n, seeds):
    return statistics.fmean(2 * gen_topology(kind, n, s).number_of_edges() / n for s in seeds)


def main(argv=None):
    ap = argparse.ArgumentParser(description="T-DPC-RWA hybrid QKD network simulator")
    ap.add_argument("--mode", choices=["demo", "full"], default="demo")
    ap.add_argument("--seeds", type=int, default=None, help="independent topology/traffic realisations (demo 3, full 50)")
    ap.add_argument("--requests", type=int, default=None,
                    help="measured requests per run after a 10%% warm-up (full mode default 100000, as in the report)")
    ap.add_argument("--procs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--outdir", default="results")
    ap.add_argument("--sweep-topo", default="waxman", choices=["waxman", "gabriel"])
    ap.add_argument("--sweep-nodes", type=int, default=20, choices=[10, 20])
    ap.add_argument("--oeo-topo", default="gabriel", choices=["waxman", "gabriel"])
    ap.add_argument("--oeo-load", type=float, default=STRESS_LOAD)
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--skip-trace", action="store_true")
    args = ap.parse_args(argv)

    os.makedirs(args.outdir, exist_ok=True)
    t_start = time.time()
    if args.mode == "demo":
        seeds = list(range(1, (args.seeds or 3) + 1))
        loads = [20, 40, 60, 80, 100]
        base = dict(t_warm=120.0, t_end=420.0, requests=args.requests)
        window = f"{base['t_warm']:g}-{base['t_end']:g} s" if not args.requests else f"{args.requests} requests"
    else:
        seeds = list(range(1, (args.seeds or 50) + 1))
        loads = list(range(10, 101, 10))
        base = dict(t_warm=0.0, t_end=0.0, requests=args.requests or 100_000)
        window = f"{base['requests'] // 10} warm-up + {base['requests']} measured requests per run"

    print(f"T-DPC-RWA simulator | mode={args.mode} | realisations={len(seeds)} | loads={loads} | {window} | "
          f"{args.procs} worker process(es)")
    print(f"Mean nodal degree over these realisations: Gabriel-20 {mean_degree('gabriel', 20, seeds):.2f}, "
          f"Waxman-20 {mean_degree('waxman', 20, seeds):.2f}")
    table1()

    trace = {"trace": [], "static": [], "events": [], "n1": 0, "n2": 0, "outage_tdpc": 0, "outage_static": 0}
    if not args.skip_trace:
        trace = run_demo_trace(args.outdir, color=not args.no_color)

    sweep_title = f"{args.sweep_nodes}-node {args.sweep_topo.capitalize()}"
    k_title = f"20-node {args.oeo_topo.capitalize()}, {args.oeo_load:g} Erl"
    jobs = [dict(base, experiment="sweep", topo=args.sweep_topo, n=args.sweep_nodes, config=c, load=a, seed=s)
            for c in FIG_RBR for a in loads for s in seeds]
    jobs += [dict(base, experiment="ablation", topo=t, n=20, config=c, load=80, seed=s)
             for t in ("gabriel", "waxman") for c in ABLATION for s in seeds]
    jobs += [dict(base, experiment="ksweep", topo=args.oeo_topo, n=20, config="T-DPC + O-E-O", load=args.oeo_load,
                  seed=s, k_hubs=k, hub_method=h)
             for k in (1, 2, 3, 4, 5, 6) for h in ("betweenness", "random", "traffic") for s in seeds]
    jobs += [dict(base, experiment="ksweep", topo=args.oeo_topo, n=20, config="T-DPC + O-E-O", load=args.oeo_load,
                  seed=s, k_hubs=k, hub_method="betweenness") for k in (0, "all") for s in seeds]
    print(f"Running {len(jobs)} simulations ...")
    t0 = time.time()
    rows = run_jobs(jobs, args.procs)
    print(f"... done in {time.time() - t0:.1f} s")
    write_csv(os.path.join(args.outdir, "raw_runs.csv"), rows)
    by = lambda e: [r for r in rows if r["experiment"] == e]
    sweep_agg = aggregate(by("sweep"), ["topo", "n", "config", "load"], METRICS)
    abl_agg = aggregate(by("ablation"), ["topo", "n", "config", "load"], METRICS)
    ks_rows = [dict(r, hub_method="any") if r["k_hubs"] in ("0", "all") else r for r in by("ksweep")]
    ksweep_agg = aggregate(ks_rows, ["k_hubs", "hub_method"], METRICS)
    write_csv(os.path.join(args.outdir, "sweep_results.csv"), sweep_agg)
    write_csv(os.path.join(args.outdir, "oeo_k_sweep.csv"), ksweep_agg)

    # Table 2: 20-node factorial ablation at 80 Erl
    t2 = []
    for label, c, tdpc, oeo, rel in TABLE2_ROWS:
        g = next(x for x in abl_agg if x["topo"] == "gabriel" and x["config"] == c)
        w = next(x for x in abl_agg if x["topo"] == "waxman" and x["config"] == c)
        pool = lambda k: statistics.fmean([v for v in (g[k], w[k]) if not math.isnan(v)] or [float("nan")])
        t2.append(dict(model=label, t_dpc=tdpc, oeo=oeo, relays=rel, rbr_gabriel=g["rbr"], rbr_waxman=w["rbr"],
                       mean_qsnr_db=pool("mean_qsnr"), outage_pct=pool("outage_pct"), skr=pool("mean_skr"),
                       power_saved_pct=pool("power_saved_pct"), network_skr=pool("net_skr"),
                       classical_rbr=pool("c_rbr"), rbr_spectrum=pool("rbr_spectrum"), rbr_qsnr=pool("rbr_qsnr"),
                       rbr_reach=pool("rbr_reach"), classical_snr_viol_pct=pool("classical_viol_pct"),
                       ms_per_request=pool("ms_per_request")))
    show("Table 2: Factorial ablation across 20-node Gabriel and Waxman topologies at 80 Erlang "
         "(QSNR, outage, SKR and power pooled over both topologies)",
         ["Model configuration", "T-DPC", "O-E-O", "Relays", "RBR (Gabriel)", "RBR (Waxman)", "Mean QSNR",
          "Outage time %", "SKR (×10⁻³)", "Power saved"],
         [[r["model"], r["t_dpc"], r["oeo"], r["relays"], fmt(r["rbr_gabriel"], "rbr"), fmt(r["rbr_waxman"], "rbr"),
           fmt(r["mean_qsnr_db"], "db"), fmt(r["outage_pct"], "pct"), fmt(r["skr"], "skr3"),
           fmt(r["power_saved_pct"], "pct")] for r in t2])
    show("Table 2 (supplementary columns): blocking causes, network key throughput, compute time",
         ["Model configuration", "Spectrum", "QSNR", "Reach", "Classical RBR", "Network SKR (×10⁻³)",
          "Classical SNR viol.", "ms / request"],
         [[r["model"], fmt(r["rbr_spectrum"], "rbr"), fmt(r["rbr_qsnr"], "rbr"), fmt(r["rbr_reach"], "rbr"),
           fmt(r["classical_rbr"], "rbr"), fmt(r["network_skr"], "skr3"), fmt(r["classical_snr_viol_pct"], "pct"),
           fmt(r["ms_per_request"], "ms")] for r in t2])
    write_csv(os.path.join(args.outdir, "table2_ablation.csv"), t2)

    order = ["0", "1", "2", "3", "4", "5", "6", "all"]
    show(f"Fig. 4(b) data: classical RBR vs O-E-O hubs K ({k_title})",
         ["K", "Betweenness", "Random", "Traffic-weighted degree"],
         [[k if k != "all" else "Full (all nodes)"] +
          [fmt(next((x["c_rbr"] for x in ksweep_agg if x["k_hubs"] == k and x["hub_method"] in (m, "any")),
                    float("nan")), "rbr") for m in ("betweenness", "random", "traffic")] for k in order])

    make_figures(args.outdir, sweep_agg, trace, ksweep_agg, sweep_title, k_title)
    print(f"\nFigures (report numbering): fig1_rbr.png = Fig. 2, fig2_qsnr_skr.png = Fig. 3, "
          f"fig3_telemetry_oeo.png = Fig. 4, in {args.outdir}/")
    print(f"CSV: table2_ablation.csv, sweep_results.csv, oeo_k_sweep.csv, raw_runs.csv, demo_trace.csv, demo_events.csv")
    print(f"Total wall time {time.time() - t_start:.1f} s")


if __name__ == "__main__":
    main()
