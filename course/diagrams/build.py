"""Builds the course diagrams as diagram-design HTML files, light and dark, from one geometry.

Run export.sh, which calls this and then exports the SVGs the lessons embed."""
import os, sys
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
SKINS = {
 "light": dict(paper="#f4f1ea", paper2="#ebe6db", ink="#1d2a35", muted="#5b6b78", soft="#5f6e7a",
               rule="rgba(29,42,53,0.12)", rule_solid="#b9b0a0", accent="#a64a24", accent_tint="rgba(166,74,36,0.08)",
               link="#1f6f8b", ink_rgb="29,42,53"),
 "dark":  dict(paper="#121a20", paper2="#192329", ink="#e8ece9", muted="#a3b0b8", soft="#8d9ba4",
               rule="rgba(232,236,233,0.12)", rule_solid="#43545f", accent="#e8865c", accent_tint="rgba(232,134,92,0.10)",
               link="#5fb9d3", ink_rgb="232,236,233"),
}
SANS = "'IBM Plex Sans', system-ui, sans-serif"
MONO = "'IBM Plex Mono', ui-monospace, monospace"
FONT_LINK = '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:ital,wght@0,400;0,500;0,600;1,400&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&display=swap" rel="stylesheet">'

def page(slug, eyebrow, title, desc, body, t, w=960, h=600):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  {FONT_LINK}
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{ --color-paper: {t['paper']}; --color-ink: {t['ink']}; --color-muted: {t['muted']}; --color-accent: {t['accent']};
            --font-sans: {SANS}; --font-mono: {MONO}; }}
    body {{ font-family: var(--font-sans); background: var(--color-paper); color: var(--color-ink); min-height: 100vh;
           display: flex; align-items: center; justify-content: center; padding: 3rem 2rem; }}
    .frame {{ max-width: 1200px; width: 100%; }}
    .diagram-container {{ width: 100%; overflow-x: auto; }}
    .eyebrow {{ font-family: var(--font-mono); font-size: 0.66rem; font-weight: 500; letter-spacing: 0.18em; text-transform: uppercase; color: var(--color-muted); margin-bottom: 0.5rem; }}
    h1 {{ font-family: var(--font-sans); font-size: clamp(1.5rem, 2.4vw + 0.75rem, 2rem); font-weight: 600; letter-spacing: -0.02em; line-height: 1.15; color: var(--color-ink); margin-bottom: 1.5rem; }}
    svg {{ width: 100%; min-width: {w}px; display: block; }}
    @media print {{ .diagram-container {{ overflow-x: visible; }} svg {{ min-width: 0; }} }}
  </style>
</head>
<body>
  <div class="frame">
    <p class="eyebrow">{eyebrow}</p>
    <h1>{title}</h1>
    <div class="diagram-container">
      <svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="{slug}-title {slug}-desc">
        <title id="{slug}-title">{title}</title>
        <desc id="{slug}-desc">{desc}</desc>
        <defs>
          <marker id="arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{t['muted']}"/></marker>
          <marker id="arrow-accent" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{t['accent']}"/></marker>
          <marker id="arrow-link" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{t['link']}"/></marker>
        </defs>
        <rect width="100%" height="100%" fill="{t['paper']}"/>
{body}
      </svg>
    </div>
  </div>
</body>
</html>
"""

# ---- primitives ---------------------------------------------------------------
def node(t, x, y, name, tag, sub, w=160, h=64, focal=False):
    stroke = t['accent'] if focal else t['muted']
    fill = t['accent_tint'] if focal else t['paper']
    cx = x + w/2
    return f"""        <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{t['paper']}"/>
        <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1"/>
        <rect x="{x+8}" y="{y+6}" width="{8+6*len(tag)}" height="12" rx="2" fill="transparent" stroke="{stroke}" stroke-opacity="0.4" stroke-width="0.8"/>
        <text x="{x+8+(8+6*len(tag))/2}" y="{y+15}" fill="{stroke}" fill-opacity="0.9" font-size="7" font-family="{MONO}" font-weight="500" text-anchor="middle" letter-spacing="0.08em">{tag}</text>
        <text x="{cx}" y="{y+38}" fill="{t['ink']}" font-size="12" font-weight="600" font-family="{SANS}" text-anchor="middle">{name}</text>
        <text x="{cx}" y="{y+53}" fill="{t['muted']}" font-size="9" font-family="{MONO}" text-anchor="middle">{sub}</text>
"""

def hline(t, x1, x2, y, label=None, kind="muted"):
    stroke = {"muted": t['muted'], "accent": t['accent'], "link": t['link']}[kind]
    marker = {"muted": "arrow", "accent": "arrow-accent", "link": "arrow-link"}[kind]
    s = f"""        <line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{stroke}" stroke-width="{1.2 if kind=='accent' else 1}" marker-end="url(#{marker})"/>
"""
    if label:
        mid = (x1 + x2) / 2; wdt = 6 + 5 * len(label)
        s += f"""        <rect x="{mid-wdt/2}" y="{y-20}" width="{wdt}" height="12" rx="2" fill="{t['paper']}"/>
        <text x="{mid}" y="{y-11}" fill="{t['soft']}" font-size="8" font-family="{MONO}" text-anchor="middle" letter-spacing="0.06em">{label}</text>
"""
    return s

def vline(t, x, y1, y2, label=None, kind="muted", dashed=False, side="right"):
    stroke = {"muted": t['muted'], "accent": t['accent'], "link": t['link']}[kind]
    marker = {"muted": "arrow", "accent": "arrow-accent", "link": "arrow-link"}[kind]
    dash = ' stroke-dasharray="5,4"' if dashed else ''
    s = f"""        <line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" stroke="{stroke}" stroke-width="1"{dash} marker-end="url(#{marker})"/>
"""
    if label:
        mid = (y1 + y2) / 2; wdt = 6 + 5 * len(label)
        lx = x + 8 if side == "right" else x - 8 - wdt
        s += f"""        <rect x="{lx}" y="{mid-6}" width="{wdt}" height="12" rx="2" fill="{t['paper']}"/>
        <text x="{lx+wdt/2}" y="{mid+3}" fill="{t['soft']}" font-size="8" font-family="{MONO}" text-anchor="middle" letter-spacing="0.06em">{label}</text>
"""
    return s

def legend(t, y, items, w=960):
    """items: list of (kind, label) with kind in muted|accent|dashed|filled|hollow|accent-dot|tag"""
    s = f"""        <line x1="30" y1="{y-8}" x2="{w-30}" y2="{y-8}" stroke="{t['rule']}" stroke-width="0.8"/>
        <text x="30" y="{y+8}" fill="{t['muted']}" font-size="8" font-family="{MONO}" font-weight="500" letter-spacing="0.14em">LEGEND</text>
"""
    x = 120
    for kind, label in items:
        if kind in ("muted", "accent", "dashed"):
            stroke = t['accent'] if kind == "accent" else t['muted']
            dash = ' stroke-dasharray="5,4"' if kind == "dashed" else ''
            s += f'        <line x1="{x}" y1="{y+4}" x2="{x+32}" y2="{y+4}" stroke="{stroke}" stroke-width="1"{dash} marker-end="url(#{"arrow-accent" if kind=="accent" else "arrow"})"/>\n'
        elif kind == "filled":
            s += f'        <circle cx="{x+16}" cy="{y+4}" r="4" fill="{t["ink"]}"/>\n'
        elif kind == "hollow":
            s += f'        <circle cx="{x+16}" cy="{y+4}" r="4" fill="{t["paper"]}" stroke="{t["ink"]}" stroke-width="1"/>\n'
        elif kind == "accent-dot":
            s += f'        <circle cx="{x+16}" cy="{y+4}" r="6" fill="{t["accent"]}"/>\n'
        elif kind == "focal":
            s += f'        <rect x="{x+4}" y="{y-2}" width="24" height="12" rx="2" fill="{t["accent_tint"]}" stroke="{t["accent"]}" stroke-width="1"/>\n'
        elif kind == "plain":
            s += f'        <rect x="{x+4}" y="{y-2}" width="24" height="12" rx="2" fill="{t["paper"]}" stroke="{t["muted"]}" stroke-width="1"/>\n'
        s += f'        <text x="{x+44}" y="{y+7}" fill="{t["muted"]}" font-size="8" font-family="{MONO}" letter-spacing="0.06em">{label}</text>\n'
        x += 60 + 5.4 * len(label) + 24
    return s

def callout(t, x, y, eyebrow, lines):
    s = f'        <text x="{x}" y="{y}" fill="{t["soft"]}" font-size="8" font-family="{MONO}" font-weight="500" letter-spacing="0.14em">{eyebrow}</text>\n'
    for i, ln in enumerate(lines):
        s += f'        <text x="{x}" y="{y+20+i*20}" fill="{t["ink"]}" font-size="14" font-style="italic" font-family="{SANS}">{ln}</text>\n'
    return s

# ---- 1. the descent ----------------------------------------------------------
def descent(t, slug):
    b = ""
    # arrows first
    b += hline(t, 208, 288, 128, "PRESENTS")
    b += hline(t, 448, 528, 128, "TRIGGERS", "accent")
    b += hline(t, 688, 768, 128, "DECIDED BY")
    b += vline(t, 608, 160, 280, "WRITES")
    b += f"""        <path d="M848,160 V304 Q848,312 840,312 H688" fill="none" stroke="{t['muted']}" stroke-width="1" stroke-dasharray="5,4" marker-end="url(#arrow)"/>
        <rect x="856" y="226" width="36" height="12" rx="2" fill="{t['paper']}"/>
        <text x="874" y="235" fill="{t['soft']}" font-size="8" font-family="{MONO}" text-anchor="middle" letter-spacing="0.06em">READS</text>
"""
    b += vline(t, 608, 344, 424, "LIFECYCLE")
    # nodes
    b += node(t, 48, 96, "Employee Portal", "C4", "arch:Container")
    b += node(t, 288, 96, "Expenses Page", "IFML", "ifml:ViewContainer · htmx")
    b += node(t, 528, 96, "Approval Process", "BPMN", "proc:Process · SpiffWorkflow", focal=True)
    b += node(t, 768, 96, "Route Approval", "DMN", "dec:Decision · dmn-js")
    b += node(t, 528, 280, "Expense", "SHACL", "sh:NodeShape · pySHACL")
    b += node(t, 528, 424, "Expense Lifecycle", "STATE", "state:StateMachine")
    b += callout(t, 768, 376, "THE BACKBONE", ["Zooming in is one query:", "follow seam:detailedBy,", "read seam:notation,", "mount the renderer."])
    b += legend(t, 568, [("muted", "SEAM PREDICATE"), ("accent", "THE CLICK (OPEN)"), ("dashed", "READ ONLY"), ("focal", "FOCAL")])
    return page(slug, "Architecture · Lesson 5", "The descent: one graph, four notations",
                "An architecture diagram of the expense app's canonical descent: a C4 container presents an IFML page whose submit event triggers a BPMN process, which is decided by a DMN table and writes a SHACL shape that has a statechart lifecycle, every arrow a seam predicate.", b, t)

# ---- 2. interpret vs generate -------------------------------------------------
def layers(t, slug):
    rows = [
        ("L1", "Interface", "IFML → htmx templates, FastAPI routes", "GENERATED", False),
        ("L2", "Process and decisions", "BPMN, DMN → SpiffWorkflow runs the native XML", "INTERPRETED", True),
        ("L3", "Data contracts", "SHACL → pySHACL validates at the call boundary", "INTERPRETED", False),
        ("L4", "Lifecycle and policy", "statecharts, ODRL → the worker's guard", "INTERPRETED", False),
        ("L5", "Deployment", "deploy: facts → compose files, Dockerfiles", "GENERATED", False),
    ]
    x, w, y0, h = 112, 720, 80, 72
    b = ""
    for i, (idx, name, sub, mode, focal) in enumerate(rows):
        y = y0 + i*h
        fill = t['accent_tint'] if focal else (t['paper2'] if i % 2 else t['paper'])
        stroke = t['accent'] if focal else t['rule']
        b += f'        <rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="{1 if focal else 0.8}"/>\n'
        b += f'        <text x="{x+24}" y="{y+h/2+3}" fill="{t["soft"]}" font-size="8" font-family="{MONO}" font-weight="500" letter-spacing="0.14em">{idx}</text>\n'
        b += f'        <text x="{x+80}" y="{y+h/2-4}" fill="{t["ink"]}" font-size="14" font-weight="600" font-family="{SANS}">{name}</text>\n'
        b += f'        <text x="{x+80}" y="{y+h/2+14}" fill="{t["muted"]}" font-size="9" font-family="{MONO}">{sub}</text>\n'
        tw = 12 + 5.4*len(mode); tx = x + w - 24 - tw
        tagc = t['accent'] if focal else t['muted']
        b += f'        <rect x="{tx}" y="{y+h/2-8}" width="{tw}" height="16" rx="2" fill="{t["paper"]}" stroke="{tagc}" stroke-opacity="0.5" stroke-width="0.8"/>\n'
        b += f'        <text x="{tx+tw/2}" y="{y+h/2+3}" fill="{tagc}" font-size="8" font-family="{MONO}" font-weight="500" text-anchor="middle" letter-spacing="0.08em">{mode}</text>\n'
    # outer silhouette
    b += f'        <rect x="{x}" y="{y0}" width="{w}" height="{h*len(rows)}" fill="none" stroke="{t["muted"]}" stroke-width="1"/>\n'
    # the one worker bracket on the right, spanning L2 to L4
    bx = 864; by1 = y0 + h + 8; by2 = y0 + 4*h - 8
    b += f'        <line x1="{bx}" y1="{by1}" x2="{bx}" y2="{by2}" stroke="{t["muted"]}" stroke-width="1"/>\n'
    b += f'        <line x1="{bx-6}" y1="{by1}" x2="{bx}" y2="{by1}" stroke="{t["muted"]}" stroke-width="1"/>\n'
    b += f'        <line x1="{bx-6}" y1="{by2}" x2="{bx}" y2="{by2}" stroke="{t["muted"]}" stroke-width="1"/>\n'
    cy = (by1 + by2)/2
    b += f'        <text x="{bx+10}" y="{cy-10}" fill="{t["soft"]}" font-size="8" font-family="{MONO}" font-weight="500" letter-spacing="0.14em">ONE</text>\n'
    b += f'        <text x="{bx+10}" y="{cy+2}" fill="{t["soft"]}" font-size="8" font-family="{MONO}" font-weight="500" letter-spacing="0.14em">WORKER</text>\n'
    b += f'        <text x="{bx+10}" y="{cy+16}" fill="{t["muted"]}" font-size="9" font-family="{MONO}">graph-literate</text>\n'
    # direction indicator left
    b += f'        <text x="40" y="{y0+8}" fill="{t["soft"]}" font-size="8" font-family="{MONO}" font-weight="500" letter-spacing="0.14em">SEEN</text>\n'
    b += f'        <text x="40" y="{y0+5*h}" fill="{t["soft"]}" font-size="8" font-family="{MONO}" font-weight="500" letter-spacing="0.14em">RUN</text>\n'
    b += callout(t, 112, 470, "ADR-0007", ["Generated code holds no business logic.", "An if about the domain in a generated file is a bug in the generator."])
    b += legend(t, 568, [("plain", "GENERATED · STRUCTURE, DISPOSABLE"), ("focal", "INTERPRETED · THE ENGINE RUNS THE MODEL")])
    return page(slug, "Layer stack · Lesson 7", "Interpret behaviour, generate structure",
                "A layer stack of the generated application's five layers, each marked interpreted by an existing engine or generated as logic-free structure, with one graph-literate worker spanning the interpreted layers.", b, t)

# ---- 3. notations timeline ----------------------------------------------------
def timeline(t, slug):
    X0, X1, Y = 80, 880, 272
    def xy(year): return X0 + (year - 1945) * (X1 - X0) / 82
    b = f'        <line x1="{X0}" y1="{Y}" x2="{X1}" y2="{Y}" stroke="{t["rule_solid"]}" stroke-width="1"/>\n'
    for dec in range(1950, 2030, 10):
        x = xy(dec)
        b += f'        <line x1="{x}" y1="{Y-4}" x2="{x}" y2="{Y+4}" stroke="{t["rule_solid"]}" stroke-width="1"/>\n'
        b += f'        <text x="{x}" y="{Y+20}" fill="{t["soft"]}" font-size="8" font-family="{MONO}" text-anchor="middle" letter-spacing="0.06em">{dec}</text>\n'
    # (year, name, sub, engine?, above?, drop, accent?)
    ev = [
        (1947, "Flow diagrams", "Goldstine, von Neumann", False, True, 56, False),
        (1976, "Entity-relationship", "Chen · the schema runs", True, False, 60, False),
        (1987, "Statecharts", "Harel · executable", True, True, 56, False),
        (1997, "UML 1.1", "OMG · failed socially", False, False, 110, False),
        (2001, "MDA", "OMG · PIM, PSM, XMI", False, True, 100, False),
        (2011, "BPMN 2.0", "execution semantics", True, False, 60, False),
        (2013, "IFML", "OMG · hooks never wired", False, True, 56, False),
        (2015, "DMN 1.0", "decision tables", True, False, 60, False),
        (2025, "SysML v2", "views are queries", False, True, 100, True),
    ]
    # Labels sit centred on their event, except at the ends and where two events are close:
    # BPMN 2.0 (2011) reads leftward and DMN 1.0 (2015) rightward, so neither drop line crosses text.
    anchors = {1947: ("start", -6), 2025: ("end", 6), 2011: ("end", -6), 2015: ("start", 6)}
    for year, name, sub, engine, above, drop, acc in ev:
        x = xy(year); ly = Y - drop if above else Y + drop
        b += f'        <line x1="{x}" y1="{Y}" x2="{x}" y2="{ly + (8 if above else -16)}" stroke="{t["rule"]}" stroke-width="1"/>\n'
        anchor, dx = anchors.get(year, ("middle", 0)); tx = x + dx
        b += f'        <text x="{tx}" y="{ly-6}" fill="{t["ink"]}" font-size="11" font-weight="600" font-family="{SANS}" text-anchor="{anchor}">{name}</text>\n'
        b += f'        <text x="{tx}" y="{ly+6}" fill="{t["muted"]}" font-size="8" font-family="{MONO}" text-anchor="{anchor}">{sub}</text>\n'
        if acc:
            b += f'        <circle cx="{x}" cy="{Y}" r="6" fill="{t["accent"]}"/>\n'
        elif engine:
            b += f'        <circle cx="{x}" cy="{Y}" r="4" fill="{t["ink"]}"/>\n'
        else:
            b += f'        <circle cx="{x}" cy="{Y}" r="4" fill="{t["paper"]}" stroke="{t["ink"]}" stroke-width="1"/>\n'
        # year under or over each dot
        yy = Y + 34 if above else Y - 12
        b += f'        <text x="{x}" y="{yy}" fill="{t["soft"]}" font-size="7" font-family="{MONO}" text-anchor="middle">{year}</text>\n'
    b += callout(t, 80, 456, "THE THESIS", ["The notations that survived had an engine. The rest became documentation."])
    b += legend(t, 568, [("filled", "A MACHINE RAN THE MODEL"), ("hollow", "DESCRIBED, NEVER EXECUTED"), ("accent-dot", "VIEWS AS QUERIES")])
    return page(slug, "Timeline · Lesson 1", "Seventy years of drawing software",
                "A timeline from 1947 to 2025 of the notations for drawing software, with the ones a machine executed filled in, the ones that stayed documentation hollow, and SysML v2's views-as-queries highlighted.", b, t)

# ---- 4. round trip in tiers ----------------------------------------------------
def roundtrip(t, slug):
    b = ""
    # forward pipeline, row y=96 (nodes 96..160)
    b += hline(t, 208, 272, 128, "READS")
    b += hline(t, 432, 496, 128, "VIEW")
    b += hline(t, 656, 720, 128, "TEXT")
    # render -> trace sidecar (dashed, vertical, x=576)
    b += vline(t, 576, 160, 240, "TRACE", dashed=True)
    # trace -> lock (horizontal y=272)
    b += hline(t, 656, 720, 272, "SOURCES")
    # output -> lock (vertical x=800)
    b += vline(t, 800, 160, 240, "SHA256")
    # output -> edited line: right of lock, down into Edit right edge
    b += f"""        <path d="M880,144 H904 Q912,144 912,152 V408 Q912,416 904,416 H880" fill="none" stroke="{t['muted']}" stroke-width="1" marker-end="url(#arrow)"/>
        <rect x="920" y="274" width="34" height="12" rx="2" fill="{t['paper']}"/>
        <text x="937" y="283" fill="{t['soft']}" font-size="8" font-family="{MONO}" text-anchor="middle" letter-spacing="0.06em">EDIT</text>
"""
    # edit -> trace (cites), dashed: leave Edit left edge at y=408, run to x=600, up into Trace bottom
    b += f"""        <path d="M720,408 H608 Q600,408 600,400 V304" fill="none" stroke="{t['muted']}" stroke-width="1" stroke-dasharray="5,4" marker-end="url(#arrow)"/>
        <rect x="640" y="382" width="34" height="12" rx="2" fill="{t['paper']}"/>
        <text x="657" y="391" fill="{t['soft']}" font-size="8" font-family="{MONO}" text-anchor="middle" letter-spacing="0.06em">CITES</text>
"""
    # edit -> patch (accent): leave Edit left edge at y=432 to Patch right edge (432)
    b += hline(t, 720, 432, 432, "ONE LITERAL", "accent")
    # patch -> model via write path: patch top (352,384) up to y=200, left to x=128, up into model bottom (128,160)
    b += f"""        <path d="M352,384 V208 Q352,200 344,200 H136 Q128,200 128,192 V160" fill="none" stroke="{t['accent']}" stroke-width="1.2" marker-end="url(#arrow-accent)"/>
        <rect x="200" y="176" width="56" height="12" rx="2" fill="{t['paper']}"/>
        <text x="228" y="185" fill="{t['soft']}" font-size="8" font-family="{MONO}" text-anchor="middle" letter-spacing="0.06em">APPLY</text>
"""
    # nodes
    b += node(t, 48, 96, "Model", "TRIG", "expenses.trig · named graphs")
    b += node(t, 272, 96, "Extract", "PYTHON", "facts → frozen view")
    b += node(t, 496, 96, "Render", "JINJA", "templates hold text")
    b += node(t, 720, 96, "Output", "HTML", "expenses_page.html")
    b += node(t, 496, 240, "Trace sidecar", "JSON", "line → template, terms")
    b += node(t, 720, 240, "Lock", "JSON", "seams.lock · hashes, sources")
    b += node(t, 720, 384, "Edited line", "VIEWER", "edit mode · generation view")
    b += node(t, 272, 384, "One-triple patch", "SEAMS_EDIT", "text edited in place", focal=True)
    b += callout(t, 48, 490, "ACCEPTED ONLY IF", ["regenerating with the patch gives back the edited line.", "No single literal, or a different line: refused, with the reason."])
    b += legend(t, 568, [("muted", "GENERATION"), ("dashed", "TRACE"), ("accent", "WRITE-BACK")])
    return page(slug, "Architecture · Lesson 10", "Getting an edit back into the model",
                "A diagram of the generation pipeline from model to output with its trace sidecar and lock, and the write-back path that turns an edited output line into a one-triple patch applied through the write path.", b, t)

DIAGRAMS = {"descent": descent, "interpret-generate": layers, "notations-timeline": timeline, "round-trip": roundtrip}
if __name__ == "__main__":
    for name, fn in DIAGRAMS.items():
        for skin, t in SKINS.items():
            slug = name if skin == "light" else f"{name}-dark"
            path = os.path.join(OUT, f"{slug}.html")
            open(path, "w").write(fn(t, slug))
            print("wrote", path)
