"""Takeoff from labeled drawing lines: runs per system, length in real units, fitting counts.

Input is the sheet's vector primitives plus a label per primitive (from a reviewed graph or a line-by-line model).
Lengths are measured on the source geometry (PDF points / CAD units), so they do not depend on the render size.

* Runs: segments of one system that touch end-to-end or end-to-side (a branch meeting a main) form one run.
* Double-line systems (ducts, walls) are drawn as two parallel lines: each pair is counted once, along its centerline.
* Fittings at each joint of a run: 2 segments that turn = elbow, 3 = tee, 4+ = cross, 1 = open end.
* Scale: an explicit ``feet_per_unit`` wins; CAD files use their $INSUNITS (model space is 1:1); PDFs use a scale note
  found in the sheet text (1/8" = 1'-0", 1" = 20', 1:100). Scans need an explicit calibration.
"""

from __future__ import annotations

import math
import re

import numpy as np

DOUBLE_LINE_HINTS = ('duct', 'wall')
INSUNITS_FT = {1: 1 / 12, 2: 1.0, 4: 1 / 304.8, 5: 1 / 30.48, 6: 3.280839895, 8: 1 / 12000, 10: 3.0}  # in, ft, mm, cm, m, mil, yd

_ARCH = re.compile(r'''(\d+(?:\s*/\s*\d+)?|\d+\s+\d+\s*/\s*\d+)\s*(?:"|''|in\.?)\s*=\s*1\s*'\s*-?\s*0\s*"?''', re.I)
_ENG = re.compile(r'''\b1\s*(?:"|in\.?)\s*=\s*(\d+(?:\.\d+)?)\s*(?:'|ft\.?)''', re.I)
_METRIC = re.compile(r'\b1\s*:\s*(\d{1,5})\b')


def _frac(s: str) -> float:
    s = s.strip()
    if ' ' in s and '/' in s:
        whole, fr = s.split(None, 1)
        return float(whole) + _frac(fr)
    if '/' in s:
        a, b = s.split('/')
        return float(a) / float(b)
    return float(s)


def parse_scale(text: str) -> float | None:
    """Real length per paper length (e.g. 1/8" = 1'-0" -> 96), or None."""
    t = (text or '').replace('′', "'").replace('″', '"').replace('”', '"').replace('’', "'")
    m = _ARCH.search(t)
    if m:
        paper_in = _frac(m.group(1))
        return 12.0 / paper_in if paper_in > 0 else None
    m = _ENG.search(t)
    if m:
        return float(m.group(1)) * 12.0
    m = _METRIC.search(t)
    if m and ('scale' in t.lower() or re.fullmatch(r'\s*1\s*:\s*\d+\s*', t)):  # bare ratios elsewhere are too ambiguous
        return float(m.group(1))
    return None


def detect_scale(primitives: list) -> tuple[float | None, str | None]:
    """Scale from the sheet's own text. Words are joined per line first (PDF text arrives word by word)."""
    texts = [p for p in primitives if p.get('type') == 'text' and p.get('text')]
    rows: dict[int, list] = {}
    for p in texts:
        y = round(float(np.mean([q[1] for q in p['pts']])) / 4)
        rows.setdefault(y, []).append(p)
    candidates = [p['text'] for p in texts] + [' '.join(q['text'] for q in sorted(r, key=lambda q: q['pts'][0][0])) for r in rows.values()]
    for t in candidates:
        r = parse_scale(t)
        if r:
            return r, t.strip()
    return None, None


def feet_per_unit(source_units: str, metadata: dict, primitives: list, override: float | None = None) -> tuple[float | None, str]:
    if override:
        return float(override), 'given'
    if source_units == 'cad_units':
        f = INSUNITS_FT.get(int((metadata or {}).get('insunits') or 0))
        return (f, 'CAD file units') if f else (None, 'CAD file has no units ($INSUNITS)')
    if source_units == 'pt':
        ratio, txt = detect_scale(primitives)
        if ratio:
            return ratio / 72.0 / 12.0, f'scale note "{txt}"'
        return None, 'no scale note found on the sheet'
    return None, 'scanned sheet: calibrate with a known length'


# --------------------------------------------------------------------------- geometry
def _segments(prim) -> list:
    pts = np.asarray(prim.get('pts') or [], dtype=float)
    if prim.get('type') == 'text' or len(pts) < 2:
        return []
    if prim.get('type') == 'rect' or prim.get('closed'):
        pts = np.vstack([pts, pts[:1]]) if not np.allclose(pts[0], pts[-1]) else pts
    return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1) if np.linalg.norm(pts[i + 1] - pts[i]) > 1e-9]


def _pt_seg_dist(p, a, b):
    ab = b - a
    t = float(np.clip(np.dot(p - a, ab) / max(np.dot(ab, ab), 1e-12), 0, 1))
    return float(np.linalg.norm(p - (a + t * ab))), t


def _pair_centerlines(segs, max_gap):
    """Collapse parallel, overlapping pairs (double-line ducts / walls) into one centerline segment each.
    Returns the segments and the widest pair found (centerlines meet half a width short of a corner)."""
    n = len(segs)
    used = [False] * n
    out = []
    widest = 0.0
    dirs = [(b - a) / np.linalg.norm(b - a) for a, b in segs]
    for i in range(n):
        if used[i]:
            continue
        a, b = segs[i]
        best, bj = None, None
        for j in range(i + 1, n):
            if used[j] or abs(abs(float(np.dot(dirs[i], dirs[j]))) - 1) > 1.5e-3:  # within ~3 degrees
                continue
            c, d = segs[j]
            v = c - a
            dist = abs(float(dirs[i][0] * v[1] - dirs[i][1] * v[0]))
            if not (1e-6 < dist <= max_gap):
                continue
            ta = sorted([0.0, float(np.dot(b - a, dirs[i]))])
            tb = sorted([float(np.dot(c - a, dirs[i])), float(np.dot(d - a, dirs[i]))])
            ov = min(ta[1], tb[1]) - max(ta[0], tb[0])
            la, lb = ta[1] - ta[0], tb[1] - tb[0]
            if ov < 0.5 * min(la, lb) or min(la, lb) < 0.25 * max(la, lb):  # a short end cap beside a long face is not its partner
                continue
            if min(la, lb) < dist:  # two caps facing each other across a gap, not a double-line run
                continue
            if best is None or dist < best:
                best, bj = dist, j
        if bj is None:
            out.append((a, b))
            continue
        used[i] = used[bj] = True
        widest = max(widest, best)
        c, d = segs[bj]
        if np.dot(d - c, b - a) < 0:
            c, d = d, c
        out.append(((a + c) / 2, (b + d) / 2))
    if widest:  # short leftovers in a double-line system are end caps (closing a duct or wall end), not run length
        keep = [k for k in range(len(out)) if float(np.linalg.norm(out[k][1] - out[k][0])) > 1.5 * widest]
        out = [out[k] for k in keep]
    return out, widest


def _runs(segs, snap):
    """Union segments that touch end-to-end or end-to-side; return runs with fitting counts."""
    n = len(segs)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    joints = []  # (point, [(seg, direction away from joint)])
    ends = [(i, k) for i in range(n) for k in (0, 1)]
    for i, k in ends:
        p = segs[i][k]
        q = segs[i][1 - k]
        away = (q - p) / max(np.linalg.norm(q - p), 1e-12)
        placed = False
        for jt in joints:
            if np.linalg.norm(jt[0] - p) <= snap:
                jt[1].append((i, away))
                placed = True
                break
        if not placed:
            joints.append([p, [(i, away)]])
    for jt in joints:  # an end landing on the side of another segment (branch off a main) is a tee
        for j in range(n):
            if any(s == j for s, _ in jt[1]):
                continue
            a, b = segs[j]
            d, t = _pt_seg_dist(jt[0], a, b)
            if d <= snap and 0.02 < t < 0.98:
                u = (b - a) / np.linalg.norm(b - a)
                jt[1] += [(j, u), (j, -u)]
    for jt in joints:
        ids = [s for s, _ in jt[1]]
        for s in ids[1:]:
            parent[find(s)] = find(ids[0])
    runs = {}
    for i in range(n):
        runs.setdefault(find(i), []).append(i)
    out = []
    for members in runs.values():
        mset = set(members)
        r = {'length': sum(float(np.linalg.norm(segs[i][1] - segs[i][0])) for i in members), 'segments': len(members),
             'elbows': 0, 'tees': 0, 'crosses': 0, 'ends': 0}
        for p, inc in joints:
            inc = [(s, v) for s, v in inc if s in mset]
            if not inc:
                continue
            deg = len(inc)
            if deg == 1:
                r['ends'] += 1
            elif deg == 2:
                cosang = float(np.dot(inc[0][1], inc[1][1]))
                if cosang > -math.cos(math.radians(15)):  # not a straight continuation
                    r['elbows'] += 1
            elif deg == 3:
                r['tees'] += 1
            else:
                r['crosses'] += 1
        pts = np.array([q for i in members for q in segs[i]])
        r['bbox'] = [float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())]
        out.append(r)
    return sorted(out, key=lambda r: -r['length'])


def takeoff(primitives: list, labels: dict, fpu: float | None, *, double_line=None, ignore=('other', 'room_tag', 'unknown'),
            snap=None, max_pair_gap_ft=3.0) -> dict:
    """``labels``: primitive id -> system label. ``fpu``: feet per source unit (None = report drawing units)."""
    by = {}
    allpts = []
    for p in primitives:
        lab = labels.get(p['id'])
        segs = _segments(p)
        allpts += [q for s in segs for q in s]
        if lab and lab not in ignore and segs:
            by.setdefault(lab, []).extend(segs)
    if not by:
        return {'systems': {}, 'units': 'ft' if fpu else 'drawing units'}
    a = np.asarray(allpts)
    diag = float(np.linalg.norm(a.max(0) - a.min(0))) or 1.0
    snap = snap or 0.003 * diag
    gap = (max_pair_gap_ft / fpu) if fpu else 0.02 * diag
    systems = {}
    for lab, segs in sorted(by.items()):
        dbl = (double_line or {}).get(lab, any(h in lab.lower() for h in DOUBLE_LINE_HINTS))
        run_snap = snap
        if dbl:
            segs, widest = _pair_centerlines(segs, gap)
            run_snap = max(snap, 0.75 * widest)
        runs = _runs(segs, run_snap)
        k = fpu or 1.0
        for r in runs:
            r['length'] = round(r['length'] * k, 2)
        systems[lab] = {'total_length': round(sum(r['length'] for r in runs), 2), 'runs': runs, 'double_line': bool(dbl),
                        'elbows': sum(r['elbows'] for r in runs), 'tees': sum(r['tees'] for r in runs), 'crosses': sum(r['crosses'] for r in runs)}
    return {'systems': systems, 'units': 'ft' if fpu else 'drawing units'}
