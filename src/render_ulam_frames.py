#!/usr/bin/env python3
"""
Render one visualization frame per N from the rich Ulam line-cover CSV.

v4.1
- ordinary prime dots shrink gently as N grows
- newest prime is labeled almost on top of the point
- 1 has a permanent colored marker and label
- faint integer grid
- line color is a cyclic function of unoriented line angle
- side arrow shows mean NON-HORIZONTAL line orientation
- arrow length shows orientation coherence/strength R

Example:
    python3 render_ulam_frames_v4_1.py ulam_line_covers_2048.csv \
        --out frames_v4 --start 1400 --end 1700
"""

import argparse
import math
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt

# Matplotlib compatibility helper:
# newer versions expose `matplotlib.colormaps`, older ones may prefer pyplot.
try:
    from matplotlib import colormaps
    def get_cmap(name):
        return colormaps[name]
except Exception:
    def get_cmap(name):
        return plt.get_cmap(name)


def auto_foreground(background):
    """Choose white text for dark backgrounds, black for light ones."""
    from matplotlib.colors import to_rgb
    try:
        r, g, b = to_rgb(background)
        luminance = 0.2126*r + 0.7152*g + 0.0722*b
        return "white" if luminance < 0.45 else "black"
    except Exception:
        return "black"


def lerp_color(c1, c2, t):
    """Linear interpolation between two RGB colors."""
    from matplotlib.colors import to_rgb
    r1, g1, b1 = to_rgb(c1)
    r2, g2, b2 = to_rgb(c2)
    return (
        r1 + (r2-r1)*t,
        g1 + (g2-g1)*t,
        b1 + (b2-b1)*t,
    )


def angle_color(theta):
    """
    Color by diagonal tendency using sin(2 theta).

      +45°  -> cyan  (#56B4E9)
      135°  -> amber (#E69F00)
      0/90° -> neutral gray

    This avoids a rainbow palette and keeps the two competing diagonal
    families highly distinguishable and colorblind-friendly.
    """
    cyan = "#56B4E9"
    amber = "#E69F00"
    neutral = "#AAAAAA"

    s = math.sin(2.0 * theta)  # +1 at 45°, -1 at 135°
    if s >= 0:
        return lerp_color(neutral, cyan, s)
    else:
        return lerp_color(neutral, amber, -s)


def clip_line_to_box(a, b, c, xmin, xmax, ymin, ymax):
    pts = []

    if abs(b) > 1e-15:
        for x in (xmin, xmax):
            y = -(a * x + c) / b
            if ymin - 1e-9 <= y <= ymax + 1e-9:
                pts.append((x, y))

    if abs(a) > 1e-15:
        for y in (ymin, ymax):
            x = -(b * y + c) / a
            if xmin - 1e-9 <= x <= xmax + 1e-9:
                pts.append((x, y))

    uniq = []
    for p in pts:
        if not any(abs(p[0]-q[0]) < 1e-8 and abs(p[1]-q[1]) < 1e-8 for q in uniq):
            uniq.append(p)

    if len(uniq) < 2:
        return None

    best = None
    best_d2 = -1
    for i in range(len(uniq)):
        for j in range(i + 1, len(uniq)):
            dx = uniq[i][0] - uniq[j][0]
            dy = uniq[i][1] - uniq[j][1]
            d2 = dx*dx + dy*dy
            if d2 > best_d2:
                best_d2 = d2
                best = (uniq[i], uniq[j])
    return best


def smooth_half_extent(prime, margin):
    return max(4.0, math.sqrt(float(prime)) / 2.0 + margin)


def line_angle(a, b):
    """
    Unoriented angle in [0, pi).
    For ax + by + c = 0, a direction vector is (b, -a).
    """
    theta = math.atan2(-a, b)
    theta %= math.pi
    return theta


def orientation_stats(frame):
    """
    Circular mean for unoriented lines, ignoring horizontal lines.

    Returns:
        mean_angle in [0, pi), R in [0,1], number of included lines
    """
    csum = 0.0
    ssum = 0.0
    used = 0

    for row in frame.itertuples(index=False):
        a = float(row.a)
        b = float(row.b)

        # Horizontal line in ax + by + c = 0
        if abs(a) < 1e-15:
            continue

        theta = line_angle(a, b)
        csum += math.cos(2.0 * theta)
        ssum += math.sin(2.0 * theta)
        used += 1

    if used == 0:
        return None, 0.0, 0

    cmean = csum / used
    smean = ssum / used
    R = math.sqrt(cmean*cmean + smean*smean)

    theta = 0.5 * math.atan2(smean, cmean)
    theta %= math.pi
    return theta, R, used


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", help="Rich ulam_line_covers CSV")
    ap.add_argument("--out", default="ulam_frames", help="Output directory")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=None)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--margin", type=float, default=2.5)
    ap.add_argument("--point-size", type=float, default=9.0)
    ap.add_argument("--point-scale-exponent", type=float, default=0.12)
    ap.add_argument("--min-point-scale", type=float, default=0.45)
    ap.add_argument("--new-point-size", type=float, default=42.0)
    ap.add_argument("--origin-size", type=float, default=28.0)
    ap.add_argument("--origin-color", default="darkorange")
    ap.add_argument("--background", default="white",
                    help="Background color, e.g. white, black, #202020")
    ap.add_argument("--foreground", default=None,
                    help="Text/compass color. Default auto-selects black or white.")
    ap.add_argument("--line-width", type=float, default=1.1)
    ap.add_argument("--line-alpha", type=float, default=0.55)
    ap.add_argument("--grid-alpha", type=float, default=0.08)
    ap.add_argument("--label-new", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--label-origin", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--show-axes", action="store_true")
    args = ap.parse_args()
    fg = args.foreground if args.foreground is not None else auto_foreground(args.background)

    df = pd.read_csv(args.csv)
    required = {
        "N", "new_prime", "new_x", "new_y", "total_lines",
        "awkward", "a", "b", "c"
    }
    missing = required - set(df.columns)
    if missing:
        raise SystemExit("CSV is missing columns: " + ", ".join(sorted(missing)))

    points = (
        df[["N", "new_prime", "new_x", "new_y", "total_lines", "awkward"]]
        .drop_duplicates(subset=["N"])
        .sort_values("N")
        .reset_index(drop=True)
    )

    max_n = int(points["N"].max())
    start = max(1, args.start)
    end = min(max_n, args.end if args.end is not None else max_n)

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    grouped = {int(n): g for n, g in df.groupby("N", sort=False)}
    figsize = (args.width / args.dpi, args.height / args.dpi)

    for n in range(start, end + 1):
        prow = points.loc[points["N"] == n].iloc[0]
        prime = int(prow["new_prime"])
        total_lines = int(prow["total_lines"])
        awkward = bool(prow["awkward"])

        current = points[points["N"] <= n]
        xs = current["new_x"].to_numpy()
        ys = current["new_y"].to_numpy()

        half = smooth_half_extent(prime, args.margin)
        xmin = ymin = -half
        xmax = ymax = half

        fig = plt.figure(figsize=figsize, dpi=args.dpi, facecolor=args.background)
        # Main square plot leaves a clean strip at right for the compass.
        ax = fig.add_axes([0.055, 0.065, 0.80, 0.86], facecolor=args.background)
        compass = fig.add_axes([0.87, 0.36, 0.11, 0.22], facecolor=args.background)
        compass.set_xlim(-1.15, 1.15)
        compass.set_ylim(-1.15, 1.15)
        compass.set_aspect("equal")
        compass.set_axis_off()

        lo = math.ceil(xmin)
        hi = math.floor(xmax)
        for g in range(lo, hi + 1):
            ax.axvline(g, linewidth=0.45, alpha=args.grid_alpha, color=fg, zorder=0)
            ax.axhline(g, linewidth=0.45, alpha=args.grid_alpha, color=fg, zorder=0)

        scale = max(
            args.min_point_scale,
            (max(n, 20) / 20.0) ** (-args.point_scale_exponent)
        )
        current_point_size = args.point_size * scale
        ax.scatter(xs, ys, s=current_point_size, color=fg, alpha=0.88, zorder=3)

        new_x = float(prow["new_x"])
        new_y = float(prow["new_y"])
        ax.scatter(
            [new_x], [new_y],
            s=args.new_point_size,
            facecolors="none",
            linewidths=1.6,
            edgecolors=fg,
            zorder=5
        )

        ax.scatter(
            [0], [0],
            s=args.origin_size,
            marker="o",
            color=args.origin_color,
            zorder=7
        )

        if args.label_origin:
            ax.annotate(
                "1", (0, 0),
                xytext=(2, -2),
                textcoords="offset points",
                fontsize=8,
                color=fg,
                alpha=0.85,
                zorder=8
            )

        if args.label_new:
            ax.annotate(
                str(prime),
                (new_x, new_y),
                xytext=(1.5, 1.5),
                textcoords="offset points",
                fontsize=8,
                color=fg,
                alpha=0.92,
                zorder=8
            )

        frame = grouped[n]

        for row in frame.itertuples(index=False):
            a = float(row.a)
            b = float(row.b)
            c = float(row.c)

            seg = clip_line_to_box(a, b, c, xmin, xmax, ymin, ymax)
            if seg:
                theta = line_angle(a, b)
                color = angle_color(theta)
                (x1, y1), (x2, y2) = seg
                ax.plot(
                    [x1, x2], [y1, y2],
                    linewidth=args.line_width,
                    alpha=args.line_alpha,
                    color=color,
                    zorder=2
                )

        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        ax.set_aspect("equal", adjustable="box")

        marker = "  AWKWARD" if awkward else ""
        ax.set_title(
            f"N = {n:,}    prime = {prime:,}    L(N) = {total_lines}{marker}",
            color=fg
        )

        theta_mean, R, used = orientation_stats(frame)
        if theta_mean is not None:
            # Dedicated compass outside the prime field.
            # Full circle gives an immediate visual reference; arrow length = R.
            circle = plt.Circle(
                (0, 0), 1.0,
                fill=False, linewidth=1.0, alpha=0.25, color=fg
            )
            compass.add_patch(circle)

            # faint diagonal guides make 45° / 135° flips especially obvious
            guide = 1.0 / math.sqrt(2.0)
            compass.plot([-guide, guide], [-guide, guide],
                         linewidth=0.6, alpha=0.14, color=fg)
            compass.plot([-guide, guide], [guide, -guide],
                         linewidth=0.6, alpha=0.14, color=fg)

            # Because lines are unoriented, show a double-ended axis.
            # Its half-length is exactly R on this unit compass.
            dx = R * math.cos(theta_mean)
            dy = R * math.sin(theta_mean)
            arrow_color = angle_color(theta_mean)

            compass.annotate(
                "",
                xy=(dx, dy),
                xytext=(-dx, -dy),
                arrowprops=dict(
                    arrowstyle="<|-|>",
                    linewidth=3.0,
                    alpha=0.95,
                    color=arrow_color,
                    mutation_scale=12
                )
            )

            compass.text(
                0, -1.22,
                f"mean orientation\nR = {R:.2f}",
                ha="center", va="top",
                fontsize=9, color=fg, alpha=0.9
            )
        if not args.show_axes:
            ax.set_axis_off()

        outfile = outdir / f"frame_{n:05d}.png"
        fig.savefig(outfile)
        plt.close(fig)

        if n == start or n == end or n % 50 == 0:
            print(f"Rendered N={n} -> {outfile}")

    print(f"Done. Frames {start}..{end} are in {outdir}")


if __name__ == "__main__":
    main()
