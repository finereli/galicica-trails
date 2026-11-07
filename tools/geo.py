"""Shared geometry helpers."""
import math

def hav(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))

def densify(line, step=50):
    """Add points so no step is longer than `step` metres (for elevation sampling)."""
    out = []
    for i in range(len(line) - 1):
        a, b = line[i], line[i + 1]; n = max(1, math.ceil(hav(a, b) / step))
        out += [(a[0] + (b[0] - a[0]) * j / n, a[1] + (b[1] - a[1]) * j / n) for j in range(n)]
    return out + [tuple(line[-1])]

def seg_dist(p, a, b):
    k = math.cos(math.radians(p[0])); m = 111320
    P, A, B = (p[0] * m, p[1] * m * k), (a[0] * m, a[1] * m * k), (b[0] * m, b[1] * m * k)
    dx, dy = B[0] - A[0], B[1] - A[1]; L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((P[0] - A[0]) * dx + (P[1] - A[1]) * dy) / L))
    return math.hypot(P[0] - A[0] - t * dx, P[1] - A[1] - t * dy)

def dist_to_line(p, line):
    return min(seg_dist(p, line[i], line[i + 1]) for i in range(len(line) - 1))
