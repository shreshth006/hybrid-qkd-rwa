# 1. Introduction

## 1.1 Background and Context

The security of most deployed public-key cryptography rests on the presumed difficulty of problems such as integer factorisation and discrete logarithms, an assumption that large-scale quantum computation would undermine. Quantum key distribution (QKD) offers a different foundation: two parties expand a shared secret over an insecure quantum channel and an authenticated classical channel, and any attempt to intercept the quantum signals leaves a measurable trace in the observed error rate. Since the first protocol was proposed by Bennett and Brassard [1], the security of practical implementations with imperfect sources and detectors has been analysed in depth [2], and the decoy-state technique of Lo, Ma and Chen made weak coherent laser sources compatible with rigorous security bounds [3].

As point-to-point QKD links matured, attention moved to networks in which many node pairs obtain keys on demand. Cao et al. trace this evolution from isolated testbeds towards a large-scale quantum-secured infrastructure [4], and several groups have shown how a software-defined control plane can expose QKD resources as programmable network services [5], [6]. Dedicated dark fibre for every quantum link is, however, rarely affordable outside trial deployments. A sustainable path is to carry quantum channels over the same wavelength-division-multiplexed (WDM) fibre plant that already transports classical traffic.

Sharing a fibre between these two kinds of signal is physically demanding. A classical channel is launched at powers in the milliwatt range, whereas a quantum channel carries, on average, less than one photon per pulse. Filters suppress linear crosstalk effectively, but nonlinear processes in silica create new photons at the quantum wavelength that cannot be filtered away. Chapuran et al. and Peters et al. identified spontaneous Raman scattering as the dominant impairment when a quantum channel coexists with strong classical signals [7], [8]. Eraerds et al. operated QKD alongside gigabit data on a single fibre [9], Patel et al. used temporal filtering to extend coexistence to 90 km [10], and Ferreira da Silva et al. quantified how Raman noise from many telecom channels accumulates in a quantum receiver [11]. A widely adopted mitigation places the quantum channel in the O-band near 1310 nm and the classical traffic in the C-band near 1550 nm, so that the quantum signal sees only the weak anti-Stokes tail of the Raman spectrum, at the price of higher fibre attenuation.

These findings move part of the security problem into the network layer. Which classical lightpaths share fibre with a quantum lightpath, over what distance and at what launch power, is decided by routing and wavelength assignment (RWA). For classical optical networks RWA is known to be computationally hard [12], and practical networks rely on heuristics such as shortest-path first-fit [13]. In a hybrid network, every routing decision for a classical channel also changes the noise floor of the quantum channels it overlaps, so RWA must respect a quantum signal-to-noise constraint in addition to wavelength availability.

## 1.2 Literature Review and Related Work

A substantial body of work addresses resource allocation for QKD-secured optical networks. Cao et al. formulated an integer linear programme and companion heuristics that assign routes, wavelengths and time slots to the quantum, synchronisation and data channels of each QKD session [14], and Zhao et al. framed resource allocation in QKD-secured optical networks as a general architectural problem [15]. Dong et al. introduced a node structure able to bypass intermediate nodes optically and an auxiliary-graph algorithm that exploits it [16]. Zhang et al. jointly optimised routing, channel, key-rate and time-slot assignment [17], while Zhao et al. adjusted link weights according to a wavelength-conflict metric to raise the acceptance of simultaneous QKD requests [18].

Other studies concentrate on how spectrum and space are shared. Bahrani et al. showed that interleaving quantum and classical sub-bands, rather than separating them into two contiguous blocks, can increase the total secret key rate in noise-limited regimes [19]. Moghaddam et al. extended the allocation problem to space-division-multiplexed elastic optical networks built on multi-core fibre [20]. When end-to-end distances exceed what a single QKD link supports, keys are usually forwarded through trusted relay nodes; Kiktenko et al. reduced the trust placed in individual relays by spreading key material over non-overlapping paths [21], and Lella and Schmid examined the security assumptions that relay-based networks impose [22].

Closest to the present work are the physics-aware heuristics of Ruiz and Garcia-Escartin. Their first study ranked candidate routes for classical channels by the length of fibre they share with established quantum channels, leading to minimum-overlap and fully disjoint strategies [23]. A subsequent study added launch-power control: once a route is chosen, the classical transmitter power is lowered to the minimum that still satisfies the receiver signal-to-noise threshold, which reduces the Raman photons injected into co-propagating quantum channels [24]. Evaluated on random Gabriel [25] and Waxman [26] topologies, power control lowered blocking and raised the quantum signal-to-noise ratio compared with fixed-power operation. Outside the quantum domain, Birand et al. demonstrated real-time power control in dynamic optical networks [27], and the classical RWA literature has long shown that a small number of well-placed wavelength converters recovers much of the benefit of full conversion [28]. Table I compares these contributions.

**TABLE I. Comparative summary of related studies**

| Author(s) & Year [Citation] | Methodology / Approach | Key Findings / Strengths | Technical Limitations / Research Gaps |
|---|---|---|---|
| Chapuran et al., 2009 [7] | Experimental O-band QKD sharing fibre with amplified C-band data channels; Raman noise measurement and modelling. | Identified spontaneous anti-Stokes Raman scattering as the dominant coexistence impairment. | Link-level study; no routing or network-wide resource allocation. |
| Eraerds et al., 2010 [9] | QKD and 1 Gbps encrypted data multiplexed on one fibre with DWDM classical channels. | Showed practical single-fibre operation of QKD with its own classical channels. | Fixed point-to-point link; no dynamic multi-user network. |
| Patel et al., 2012 [10] | Temporal filtering of Raman noise photons in high-bit-rate QKD. | Coexistence with bidirectional gigabit data over fibres up to 90 km. | Hardware-level mitigation; does not address routing or power allocation. |
| Birand et al., 2014 [27] | Real-time power control for dynamic classical optical networks, with experimental validation. | Demonstrates feasible closed-loop power adjustment as channels are added and removed. | Classical networks only; quantum signal-to-noise constraints not considered. |
| Cao et al., 2017 [14] | Integer linear programming and heuristics for routing, wavelength and time-slot assignment in QKD-enabled networks. | Near-optimal resource use for known traffic matrices. | Static demands; Raman cross-talk between channels not modelled. |
| Bahrani et al., 2018 [19] | Optimisation of wavelength positions for quantum and classical channels in DWDM links. | Interleaved quantum and classical bands raise total secret key rate in noise-limited regimes. | Single-link spectral design; no path selection or temporal dynamics. |
| Dong et al., 2020 [16] | Auxiliary-graph RWTA with a node structure supporting optical bypass and trusted relaying. | Bypassing intermediate nodes within QKD reach saves relay keys and resources. | Physical-layer noise from co-propagating classical channels not considered. |
| Moghaddam et al., 2021 [20] | Resource allocation for QKD in space-division-multiplexed elastic optical networks. | Extends QKD resource allocation to multi-core fibre infrastructures. | Requires multi-core fibre; launch-power control not addressed. |
| Zhang et al., 2023 [17] | Joint routing, channel, key-rate and time-slot assignment for QKD in optical networks. | Unified treatment of key-rate demands within RWA. | Raman-aware power control and closed-loop supervision absent. |
| Zhao et al., 2023 [18] | Resource-adaptive routing using a wavelength-conflict degree to update link weights. | Up to 30% higher acceptance of simultaneous QKD requests. | Spectral contention only; nonlinear noise and physical drift not modelled. |
| Kiktenko et al., 2024 [21] | Key routing over multiple non-overlapping paths in trusted-relay QKD networks. | Security holds unless every path contains a compromised relay. | Assumes key-generation capacities as given; physical-layer coexistence not modelled. |
| Ruiz and Garcia-Escartin, 2025 [23] | Overlap-minimising and disjoint routing heuristics for classical channels in hybrid networks. | Shorter shared spans reduce Raman noise using software-only rules. | Fixed launch power; detours lengthen classical paths; static demands. |
| Ruiz and Garcia-Escartin, 2026 [24] | Minimum-power launch control combined with physics-aware RWA heuristics on random geometric graphs. | Lower blocking and higher quantum signal-to-noise ratio than fixed-power operation. | Static sequential demands, one-shot power setting, no wavelength conversion, paths bounded at 60 km. |

## 1.3 Research Gap and Limitations

The reviewed studies establish that resource allocation must account for the physical layer when quantum and classical signals share fibre. Several technical limitations, however, remain open.

**Static demand models.** The power-controlled heuristics of [24] are evaluated on demand sets known in advance and provisioned sequentially, without departures. In operational networks, connections arrive and leave stochastically, so the set of classical interferers seen by a quantum channel changes throughout its lifetime. The authors themselves identify dynamic traffic assignment as an open question [24].

**One-shot launch-power assignment.** Classical launch power is computed once, from the path length at set-up, and is never revisited. It therefore cannot react to new interferers, to transient bursts of classical traffic, or to slow drifts such as connector degradation, which may push a quantum channel below its viability threshold or a classical receiver below its sensitivity in mid-session.

**Strict wavelength continuity.** The physics-aware heuristics in [23], [24] assume networks without wavelength converters. Conversion below the single-photon level is impractical, but converting classical channels alone would not touch the quantum path, and the potential of sparse classical conversion [28] has not been examined in hybrid networks.

**Bounded single-segment reach.** The topologies in [24] are generated so that no path exceeds 60 km. This is a deliberate simulation choice rather than a physical limit of QKD, but it leaves open how physics-aware RWA should serve node pairs whose shortest path is too long for a single quantum segment. Trusted relays address reach in general [4], [21], yet they have not been combined with Raman-aware routing and power control.

**Open-loop control.** Software-defined QKD architectures [5], [6] manage keys and services but do not close a control loop on physical-layer measurements such as the quantum signal-to-noise ratio. No existing scheme detects a quantum channel drifting towards outage and corrects it while the session is active.

## 1.4 Proposed Contributions

This study develops and evaluates a Telemetry-Driven Dynamic Power Control and RWA framework (T-DPC-RWA) for hybrid quantum–classical networks under stochastic online traffic with Poisson arrivals and exponentially distributed holding times. Its objective is to extend physics-aware RWA from static provisioning to continuous operation, while keeping noise mitigation, spectrum relief and reach extension as separate mechanisms whose effects can be measured independently. The main contributions are:

- A time-variant, segment-aware model of anti-Stokes Raman noise that yields closed-form sensitivities of each quantum channel to the launch power of each classical segment.

- A closed-loop control algorithm that polls the quantum and classical signal-to-noise ratios at a fixed interval and, when a quantum channel enters a guard band, applies sensitivity-ordered power throttling and escalates to make-before-break re-grooming of the dominant interferer when throttling is insufficient, with hysteresis-based power recovery.

- Sparse optical-electrical-optical wavelength conversion for classical channels only, placed at nodes of high betweenness centrality [29] and exploited through a layered auxiliary graph, so that no active device enters the quantum path.

- Trusted-relay segmentation that serves long-distance quantum requests through the relay chain with the highest bottleneck secret key rate under the decoy-state BB84 model [3]; relays terminate and re-establish keys and are explicitly distinct from quantum repeaters.

- A reproducible discrete-event evaluation on Gabriel and Waxman topologies that uses common random numbers, a factorial ablation of the three mechanisms and a decomposition of blocking into spectrum, noise and reach causes.

Fig. 1 summarises the resulting workflow. The remainder of the paper presents the proposed architecture, the impairment model and algorithms, the simulation methodology and results, and concluding remarks.

*Figure 1: editable sources in `fig1_workflow.mmd` (Mermaid) and `fig1_workflow.drawio` (draw.io).*

Fig. 1. Conceptual workflow of the proposed T-DPC-RWA framework. Online provisioning (upper part) extends physics-aware RWA [23], [24] with sparse classical wavelength conversion [28] and trusted-relay segmentation; the telemetry loop (lower part) adds the closed-loop correction that static launch-power assignment lacks. Diagram by the authors.

## References

[1] C. H. Bennett and G. Brassard, "Quantum cryptography: Public key distribution and coin tossing," in *Proc. IEEE Int. Conf. Computers, Systems and Signal Processing*, Bangalore, India, 1984, pp. 175–179.
[2] V. Scarani, H. Bechmann-Pasquinucci, N. J. Cerf, M. Dušek, N. Lütkenhaus, and M. Peev, "The security of practical quantum key distribution," *Rev. Mod. Phys.*, vol. 81, no. 3, p. 1301, 2009.
[3] H.-K. Lo, X. Ma, and K. Chen, "Decoy state quantum key distribution," *Phys. Rev. Lett.*, vol. 94, no. 23, p. 230504, 2005.
[4] Y. Cao, Y. Zhao, Q. Wang, J. Zhang, S. X. Ng, and L. Hanzo, "The evolution of quantum key distribution networks: On the road to the Qinternet," *IEEE Commun. Surveys Tuts.*, vol. 24, pp. 839–894, 2022.
[5] Y. Cao, Y. Zhao, J. Wang, X. Yu, Z. Ma, and J. Zhang, "SDQaaS: Software defined networking for quantum key distribution as a service," *Opt. Express*, vol. 27, no. 5, pp. 6892–6909, 2019.
[6] H. Wang, Y. Zhao, and A. Nag, "Quantum-key-distribution (QKD) networks enabled by software-defined networks (SDN)," *Appl. Sci.*, vol. 9, no. 10, p. 2081, 2019.
[7] T. E. Chapuran *et al.*, "Optical networking for quantum key distribution and quantum communications," *New J. Phys.*, vol. 11, p. 105001, 2009.
[8] N. A. Peters *et al.*, "Dense wavelength multiplexing of 1550 nm QKD with strong classical channels in reconfigurable networking environments," *New J. Phys.*, vol. 11, p. 045012, 2009.
[9] P. Eraerds, N. Walenta, M. Legré, N. Gisin, and H. Zbinden, "Quantum key distribution and 1 Gbps data encryption over a single fibre," *New J. Phys.*, vol. 12, p. 063027, 2010.
[10] K. A. Patel *et al.*, "Coexistence of high-bit-rate quantum key distribution and data on optical fiber," *Phys. Rev. X*, vol. 2, no. 4, p. 041010, 2012.
[11] T. Ferreira da Silva, G. B. Xavier, G. P. Temporão, and J. P. von der Weid, "Impact of Raman scattered noise from multiple telecom channels on fiber-optic quantum key distribution systems," *J. Lightw. Technol.*, vol. 32, pp. 2332–2339, 2014.
[12] I. Chlamtac, A. Ganz, and G. Karmi, "Lightpath communications: An approach to high bandwidth optical WAN's," *IEEE Trans. Commun.*, vol. 40, pp. 1171–1182, 1992.
[13] H. Zang, J. P. Jue, and B. Mukherjee, "A review of routing and wavelength assignment approaches for wavelength-routed optical WDM networks," *Opt. Netw. Mag.*, vol. 1, pp. 47–60, 2000.
[14] Y. Cao, Y. Zhao, X. Yu, and Y. Wu, "Resource assignment strategy in optical networks integrated with quantum key distribution," *J. Opt. Commun. Netw.*, vol. 9, no. 11, pp. 995–1004, 2017.
[15] Y. Zhao *et al.*, "Resource allocation in optical networks secured by quantum key distribution," *IEEE Commun. Mag.*, vol. 56, pp. 130–137, 2018.
[16] K. Dong, Y. Zhao, X. Yu, A. Nag, and J. Zhang, "Auxiliary graph based routing, wavelength, and time-slot assignment in metro quantum optical networks with a novel node structure," *Opt. Express*, vol. 28, no. 5, pp. 5936–5952, 2020.
[17] Q. Zhang, O. Ayoub, A. Gatto, J. Wu, F. Musumeci, and M. Tornatore, "Routing, channel, key-rate, and time-slot assignment for QKD in optical networks," *IEEE Trans. Netw. Serv. Manag.*, early access, 2023.
[18] T. Zhao, X. Fan, B. Dong, Q. Niu, and B. Guo, "A resource-adaptive routing scheme with wavelength conflicts in quantum key distribution optical networks," *Entropy*, vol. 25, no. 5, p. 732, 2023.
[19] S. Bahrani, M. Razavi, and J. A. Salehi, "Wavelength assignment in hybrid quantum-classical networks," *Sci. Rep.*, vol. 8, p. 3456, 2018.
[20] E. E. Moghaddam, H. Beyranvand, and J. A. Salehi, "Resource allocation in space division multiplexed elastic optical networks secured with quantum key distribution," *IEEE J. Sel. Areas Commun.*, vol. 39, no. 9, pp. 2688–2700, 2021.
[21] E. O. Kiktenko, A. Tayduganov, and A. K. Fedorov, "Routing algorithm within the multiple non-overlapping paths' approach for quantum key distribution networks," *Entropy*, vol. 26, no. 12, p. 1102, 2024.
[22] E. Lella and G. Schmid, "On the security of quantum key distribution networks," *Cryptography*, vol. 7, no. 4, p. 53, 2023.
[23] L. Ruiz and J. C. Garcia-Escartin, "Routing and wavelength assignment in hybrid networks with classical and quantum signals," *IEEE J. Sel. Areas Commun.*, vol. 43, no. 2, pp. 412–421, 2025.
[24] L. Ruiz and J. C. Garcia-Escartin, "Routing and wavelength assignment in quantum key distribution networks: Power control heuristics for quantum–classical multiplexing," *Comput. Commun.*, vol. 256, p. 108572, 2026.
[25] K. R. Gabriel and R. R. Sokal, "A new statistical approach to geographic variation analysis," *Syst. Zool.*, vol. 18, no. 3, pp. 259–278, 1969.
[26] B. M. Waxman, "Routing of multipoint connections," *IEEE J. Sel. Areas Commun.*, vol. 6, no. 9, pp. 1617–1622, 1988.
[27] B. Birand, H. Wang, K. Bergman, D. Kilper, T. Nandagopal, and G. Zussman, "Real-time power control for dynamic optical networks—Algorithms and experimentation," *IEEE J. Sel. Areas Commun.*, vol. 32, pp. 1615–1628, 2014.
[28] S. Subramaniam, M. Azizoglu, and A. K. Somani, "All-optical networks with sparse wavelength conversion," *IEEE/ACM Trans. Netw.*, vol. 4, no. 4, pp. 544–557, 1996.
[29] U. Brandes, "A faster algorithm for betweenness centrality," *J. Math. Sociol.*, vol. 25, no. 2, pp. 163–177, 2001.
