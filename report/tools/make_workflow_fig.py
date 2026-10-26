"""Renders the T-DPC-RWA workflow (report Figure 1) to img/fig_workflow.png.
Same nodes and layout as ../introduction/fig1_workflow.drawio, which is the editable version."""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
BLUE, GREEN, ORANGE, GREY = "#DCE6F2", "#E2EFDA", "#FCE4D6", "#F2F2F2"

# id: (label, fill, x, y, w, h) in a 800 x 800 canvas, y downwards
N = {
    "req": ("Stochastic connection request r = (s, d, type)\nPoisson arrivals, exponential holding times", GREY, 140, 0, 520, 58),
    "cls": ("Classical request\nk candidate paths ranked by\nquantum-overlap cost; first-fit wavelength", BLUE, 0, 105, 340, 72),
    "qnt": ("Quantum request\ndirect O-band lightpath on k shortest\npaths; test QSNR ≥ Γ$_Q$ + ε", BLUE, 460, 105, 340, 72),
    "aux": ("Layered auxiliary graph\nconversion edges only at sparse\nO-E-O hubs (high betweenness)", BLUE, 0, 230, 340, 72),
    "rel": ("Trusted-relay chain s → r$_1$ → … → d\nkeep the chain with the highest\nbottleneck secret key rate", BLUE, 460, 230, 340, 72),
    "adm": ("Admission: all active quantum channels keep QSNR ≥ Γ$_Q$ + ε\nlaunch power P = P$_{min}$(1 + m$_0$); update network state", GREEN, 140, 355, 520, 62),
    "tel": ("SDN telemetry poll every Δt\nQSNR$_q$, SNR$_{c,s}$, excess loss η$_{c,s}$", ORANGE, 140, 470, 520, 58),
    "risk": ("At-risk channel\ncompute noise reduction ΔN*\nand throttling headroom H", ORANGE, 0, 585, 340, 58),
    "rec": ("Hysteresis recovery\nraise throttled powers by Δp\ntowards P$_{min}$(1 + m$_0$)", ORANGE, 460, 585, 340, 58),
    "l1": ("Level 1 (H ≥ ΔN*)\nsensitivity-ordered power throttling", ORANGE, 0, 700, 340, 58),
    "l2": ("Level 2\nmake-before-break re-grooming\nof the dominant interferer", ORANGE, 460, 700, 340, 58),
}


def anchor(nid, side):
    _, _, x, y, w, h = N[nid]
    return {"top": (x + w / 2, y), "bottom": (x + w / 2, y + h), "left": (x, y + h / 2), "right": (x + w, y + h / 2)}[side]


def arrow(ax, p, q, label="", style="-|>", ls="-", lab_off=(6, 0), ha="left"):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=13, lw=1.2, color="#333333", linestyle=ls))
    if label:
        mx, my = (p[0] + q[0]) / 2 + lab_off[0], (p[1] + q[1]) / 2 + lab_off[1]
        ax.text(mx, my, label, fontsize=9, ha=ha, va="center", style="italic", color="#333333", family="serif")


def main():
    plt.rcParams.update({"font.family": "serif", "mathtext.fontset": "dejavuserif"})
    fig, ax = plt.subplots(figsize=(9.2, 9.4))
    ax.set_xlim(-10, 860)
    ax.set_ylim(790, -15)
    ax.axis("off")
    for nid, (label, fill, x, y, w, h) in N.items():
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=8",
                                    fc=fill, ec="#404040", lw=1.1))
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=8.6, linespacing=1.3)
    # provisioning
    arrow(ax, (300, 58), anchor("cls", "top"), "classical", lab_off=(-8, 0), ha="right")
    arrow(ax, (500, 58), anchor("qnt", "top"), "quantum", lab_off=(8, 0))
    arrow(ax, anchor("cls", "bottom"), anchor("aux", "top"), "no continuous\nfree wavelength")
    arrow(ax, anchor("qnt", "bottom"), anchor("rel", "top"), "reach or QSNR\ntest fails")
    arrow(ax, anchor("aux", "bottom"), (300, 355))
    arrow(ax, anchor("rel", "bottom"), (500, 355))
    # direct success bypasses the second step (dashed lanes between the columns)
    for x0, xl in ((340, 372), (460, 428)):
        ax.plot([x0, xl, xl], [141, 141, 330], color="#333333", lw=1.2, ls="--")
        arrow(ax, (xl, 330), (xl, 355), "", ls="--")
    ax.text(400, 250, "found\ndirectly", fontsize=8, ha="center", va="center", style="italic", color="#555555", family="serif")
    # telemetry loop
    arrow(ax, anchor("adm", "bottom"), anchor("tel", "top"))
    arrow(ax, (300, 528), anchor("risk", "top"), "QSNR < Γ$_Q$ + ε", lab_off=(-8, 0), ha="right")
    arrow(ax, (500, 528), anchor("rec", "top"), "QSNR ≥ Γ$_Q$ + ε + h", lab_off=(8, 0))
    arrow(ax, anchor("risk", "bottom"), anchor("l1", "top"), "H ≥ ΔN*")
    arrow(ax, (340, 620), (460, 720), "H < ΔN*", lab_off=(6, -12))
    arrow(ax, anchor("l1", "right"), anchor("l2", "left"), "still at risk", lab_off=(-38, 12))
    # loop back to telemetry (right-hand rail)
    ax.plot([800, 830, 830], [729, 729, 499], color="#333333", lw=1.2)
    ax.plot([800, 830], [614, 614], color="#333333", lw=1.2)
    arrow(ax, (830, 499), anchor("tel", "right"))
    ax.text(842, 610, "next Δt", fontsize=9, rotation=90, va="center", style="italic", family="serif")
    os.makedirs(os.path.join(HERE, "img"), exist_ok=True)
    out = os.path.join(HERE, "img", "fig_workflow.png")
    fig.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
    print("wrote", out)


if __name__ == "__main__":
    main()
