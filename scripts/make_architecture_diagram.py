#!/usr/bin/env python3
"""Render the architecture diagram as a PNG for the Devpost submission.

Devpost accepts pdf/ppt/pptx/png/jpg — not SVG, and not Mermaid source. The
`.mmd` files stay the maintained source for readers of the repository; this
produces the artefact the submission form requires.

Written as plain SVG rather than through the Mermaid CLI: that tool downloads a
headless browser, which this environment cannot reach, and a diagram that only
one machine can rebuild is a diagram nobody rebuilds.

Usage:
    python scripts/make_architecture_diagram.py
    -> docs/diagrams/architecture.png
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "diagrams"

INK = "#0d1117"
LINE = "#30363d"
TEXT = "#e6edf3"
DIM = "#8b949e"
ACCENT = "#58a6ff"
WARN = "#d29922"
DANGER = "#f85149"
OK = "#3fb950"


def box(x, y, w, h, label, sub="", stroke=LINE, fill="#161b22", label_size=15):
    parts = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
    ]
    text_y = y + h / 2 + (0 if not sub else -6)
    parts.append(
        f'<text x="{x + w / 2}" y="{text_y}" fill="{TEXT}" font-size="{label_size}" '
        f'font-family="DejaVu Sans, Arial, sans-serif" font-weight="600" '
        f'text-anchor="middle" dominant-baseline="middle">{label}</text>'
    )
    if sub:
        parts.append(
            f'<text x="{x + w / 2}" y="{y + h / 2 + 12}" fill="{DIM}" font-size="11" '
            f'font-family="DejaVu Sans, Arial, sans-serif" '
            f'text-anchor="middle" dominant-baseline="middle">{sub}</text>'
        )
    return "".join(parts)


def arrow(x1, y1, x2, y2, colour=DIM, dashed=False, label=""):
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    out = (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{colour}" '
        f'stroke-width="1.6"{dash} marker-end="url(#a)"/>'
    )
    if label:
        out += (
            f'<text x="{(x1 + x2) / 2 + 6}" y="{(y1 + y2) / 2 - 5}" fill="{DIM}" '
            f'font-size="10" font-family="DejaVu Sans, Arial, sans-serif">{label}</text>'
        )
    return out


def band(x, y, w, h, title, colour):
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="none" '
        f'stroke="{colour}" stroke-width="1" stroke-dasharray="3 5" opacity="0.7"/>'
        f'<text x="{x + 12}" y="{y + 18}" fill="{colour}" font-size="11" '
        f'font-family="DejaVu Sans, Arial, sans-serif" font-weight="700" '
        f'letter-spacing="1.5">{title}</text>'
    )


def build() -> str:
    W, H = 1200, 900
    s = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}">',
        f'<rect width="{W}" height="{H}" fill="{INK}"/>',
        '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{DIM}"/></marker></defs>',
        f'<text x="40" y="46" fill="{TEXT}" font-size="24" font-weight="700" '
        f'font-family="DejaVu Sans, Arial, sans-serif">ACC — Autonomous Mission Control</text>',
        f'<text x="40" y="70" fill="{DIM}" font-size="13" '
        f'font-family="DejaVu Sans, Arial, sans-serif">'
        f'The agent can fail. The mission doesn\'t have to. '
        f'— Fortified Enterprise Fleet on Google Cloud</text>',
    ]

    # --- Operator -----------------------------------------------------------
    s.append(box(480, 100, 240, 52, "Mission Control", "Next.js 15 · Cloud Run"))
    s.append(arrow(600, 152, 600, 190, ACCENT, label="REST + SSE"))

    # --- Control plane ------------------------------------------------------
    s.append(band(60, 190, 1080, 330, "ACC CONTROL PLANE  ·  FastAPI on Cloud Run", ACCENT))
    s.append(box(100, 230, 200, 56, "Mission Engine", "state · checkpoints"))
    s.append(box(330, 230, 200, 56, "Recovery Engine", "Failure Twin"))
    s.append(box(560, 230, 200, 56, "Policy Engine", "ALLOW / APPROVAL / DENY"))
    s.append(box(790, 230, 200, 56, "Approvals", "durable human authority"))

    s.append(box(100, 316, 200, 50, "Memory Bank", "mission-scoped"))
    s.append(box(330, 316, 200, 50, "Agent Registry", "identity · capabilities"))
    s.append(box(560, 316, 200, 50, "Audit + OTel", "trace_id correlated"))
    s.append(box(790, 316, 200, 50, "Model Armor", "prompt injection"))

    # Gateway
    s.append(box(330, 400, 430, 62, "AGENT GATEWAY", "the only way out", DANGER, "#1c1417", 17))
    s.append(
        f'<text x="545" y="484" fill="{DIM}" font-size="11" text-anchor="middle" '
        f'font-family="DejaVu Sans Mono, monospace">'
        f'IDENTITY → CAPABILITY → POLICY → APPROVAL → IDEMPOTENCY → TOOL → ARMOR → AUDIT</text>'
    )
    for x in (200, 430, 660, 890):
        s.append(arrow(x, 286 if x in (200, 430, 660, 890) else 286, x, 314, LINE))
    s.append(arrow(430, 366, 470, 398, LINE))
    s.append(arrow(660, 366, 620, 398, LINE))

    # --- Agent fleet --------------------------------------------------------
    s.append(band(60, 545, 1080, 130, "AGENT FLEET  ·  Google ADK + Gemini 3.6 Flash", OK))
    s.append(box(100, 580, 220, 62, "Supply Agent", "supplier.status"))
    s.append(box(345, 580, 220, 62, "Risk Agent", "risk.assess"))
    s.append(box(590, 580, 220, 62, "Procurement Agent", "purchase.execute"))
    s.append(box(835, 580, 220, 62, "Failure Twin", "recovery.plan"))
    for x in (210, 455, 700, 945):
        s.append(arrow(x, 578, x, 466, LINE, dashed=True))

    # --- Enterprise ---------------------------------------------------------
    s.append(box(400, 705, 400, 56, "Enterprise systems", "suppliers · production · procurement"))
    # Routed around the fleet: a straight line would cut through an agent box
    # and read as "the Gateway calls Risk Agent", which is the opposite of the
    # architecture.
    s.append(
        f'<path d="M 760 431 H 1105 V 733 H 802" fill="none" stroke="{DANGER}" '
        f'stroke-width="1.8" marker-end="url(#a)"/>'
    )
    s.append(
        f'<text x="1160" y="545" fill="{DANGER}" font-size="11" text-anchor="end" '
        f'font-family="DejaVu Sans, Arial, sans-serif" font-weight="600">'
        f'the ONLY path to enterprise systems</text>'
    )

    # --- Google Cloud services ---------------------------------------------
    s.append(band(60, 790, 1080, 78, "GOOGLE CLOUD", WARN))
    services = ["Cloud Run", "Firestore", "Pub/Sub", "Vertex AI",
                "Model Armor", "Secret Manager", "IAM", "Cloud Logging"]
    for index, name in enumerate(services):
        x = 90 + index * 132
        s.append(
            f'<text x="{x}" y="{843}" fill="{DIM}" font-size="12" '
            f'font-family="DejaVu Sans, Arial, sans-serif">{name}</text>'
        )

    s.append(
        f'<text x="{W - 40}" y="{H - 14}" fill="{DIM}" font-size="10" '
        f'text-anchor="end" font-family="DejaVu Sans, Arial, sans-serif">'
        f'Mission state is durable. Agent sessions are disposable.</text>'
    )
    s.append("</svg>")
    return "".join(s)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    svg = build()
    (OUT_DIR / "architecture.svg").write_text(svg, encoding="utf-8")

    import cairosvg

    cairosvg.svg2png(bytestring=svg.encode("utf-8"),
                     write_to=str(OUT_DIR / "architecture.png"),
                     output_width=2400)
    cairosvg.svg2pdf(bytestring=svg.encode("utf-8"),
                     write_to=str(OUT_DIR / "architecture.pdf"))

    for name in ("architecture.svg", "architecture.png", "architecture.pdf"):
        size = (OUT_DIR / name).stat().st_size
        print(f"  {name:<22} {size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
