#!/usr/bin/env python3
"""
Count optimal Ulam-prime line covers for successive N.

A "solution" is a finite canonical cover:
  * every distinct geometric line determined by >=2 of the N Ulam-prime points
    is one candidate;
  * each point also has one canonical singleton token.

This avoids the otherwise infinite number of geometrically distinct singleton
lines through an isolated point.

The program DOES NOT re-optimize L(N). It reads the already-certified optimum
L(N) from your CSV, then enumerates every Boolean selection of exactly L(N)
candidate lines/tokens that covers all N points.

Accepted input CSV formats:
  1) N,prime,L
  2) rich cover CSV with N,new_prime,total_lines,... (many rows per N)

Requires:
    pip install ortools

Example:
    python3 count_ulam_optimal_covers.py ulam_N_prime_L_2508.csv --max-n 50

With a 30-minute safety cap per N:
    python3 count_ulam_optimal_covers.py ulam_N_prime_L_2508.csv \
        --max-n 80 --seconds-per-n 1800

Resume:
    python3 count_ulam_optimal_covers.py ulam_N_prime_L_2508.csv \
        --start-n 37 --max-n 80 --output ulam_optimal_cover_counts.csv
"""

import argparse
import csv
import math
import os
import sys
import time
from collections import defaultdict

from ortools.sat.python import cp_model


def canonical_line(p, q):
    x1, y1 = p
    x2, y2 = q
    A = y1 - y2
    B = x2 - x1
    C = -(A * x1 + B * y1)

    g = math.gcd(math.gcd(abs(A), abs(B)), abs(C))
    if g:
        A //= g
        B //= g
        C //= g

    if A < 0 or (A == 0 and B < 0):
        A = -A
        B = -B
        C = -C

    return (A, B, C)


def ulam_coordinate(value):
    if value <= 1:
        return (0, 0)

    k = int(math.ceil((math.sqrt(float(value)) - 1.0) / 2.0))
    side = 2 * k
    max_value = (2 * k + 1) ** 2
    d = max_value - value

    if d < side:
        return (k - d, -k)
    if d < 2 * side:
        return (-k, -k + (d - side))
    if d < 3 * side:
        return (-k + (d - 2 * side), k)
    return (k, k - (d - 3 * side))


def first_primes(n):
    out = []
    x = 2
    while len(out) < n:
        prime = True
        r = int(math.isqrt(x))
        for p in out:
            if p > r:
                break
            if x % p == 0:
                prime = False
                break
        if prime:
            out.append(x)
        x += 1
    return out


def read_optima(path):
    """Return {N: (prime_or_None, L)} from simple or rich CSV."""
    by_n = {}

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])

        if "N" not in fields:
            raise SystemExit("Input CSV has no N column.")

        if "L" in fields:
            for row in reader:
                n = int(row["N"])
                prime = None
                if "prime" in fields and row.get("prime"):
                    prime = int(row["prime"])
                elif "new_prime" in fields and row.get("new_prime"):
                    prime = int(row["new_prime"])
                by_n[n] = (prime, int(row["L"]))

        elif "total_lines" in fields:
            for row in reader:
                n = int(row["N"])
                L = int(row["total_lines"])
                prime = int(row["new_prime"]) if row.get("new_prime") else None

                if n in by_n:
                    old_prime, old_L = by_n[n]
                    if old_L != L:
                        raise SystemExit(
                            "Inconsistent total_lines for N=%d: %d vs %d"
                            % (n, old_L, L)
                        )
                    if old_prime is None and prime is not None:
                        by_n[n] = (prime, L)
                else:
                    by_n[n] = (prime, L)
        else:
            raise SystemExit(
                "Input must have either N,L or N,total_lines columns."
            )

    return by_n


def build_candidates(points):
    """
    Return:
      candidates: list of tuples of point indices covered by each candidate
      pair_line_count: number of geometric lines determined by >=2 points
      incidence: candidate ids containing each point

    Each geometric line occurs once, even if it contains 3+ points.
    Singletons occur once per point.
    """
    n = len(points)
    line_points = defaultdict(set)

    for i in range(n):
        for j in range(i + 1, n):
            key = canonical_line(points[i], points[j])
            line_points[key].add(i)
            line_points[key].add(j)

    # Sort for reproducibility.  Longer lines first sometimes helps CP-SAT.
    geometric = [
        tuple(sorted(s))
        for s in line_points.values()
    ]
    geometric.sort(key=lambda s: (-len(s), s))

    candidates = list(geometric)

    # Canonical singleton tokens.
    for i in range(n):
        candidates.append((i,))

    incidence = [[] for _ in range(n)]
    for cid, pts in enumerate(candidates):
        for i in pts:
            incidence[i].append(cid)

    return candidates, len(geometric), incidence


class Counter(cp_model.CpSolverSolutionCallback):
    def __init__(self):
        super().__init__()
        self.count = 0

    def on_solution_callback(self):
        self.count += 1


def status_name(solver, status):
    if hasattr(solver, "StatusName"):
        return solver.StatusName(status)
    if hasattr(solver, "status_name"):
        return solver.status_name(status)
    return str(status)


def count_covers(points, optimum, seconds_per_n=0.0):
    candidates, geometric_count, incidence = build_candidates(points)

    model = cp_model.CpModel()
    x = [model.NewBoolVar("c%d" % j) for j in range(len(candidates))]

    # Every point must be covered.
    for i in range(len(points)):
        model.Add(sum(x[j] for j in incidence[i]) >= 1)

    # Count only optimal-cardinality covers.
    model.Add(sum(x) == optimum)

    solver = cp_model.CpSolver()

    # Enumeration is intentionally single-threaded. CP-SAT requires this for
    # exhaustive all-solution enumeration.
    solver.parameters.enumerate_all_solutions = True
    solver.parameters.num_search_workers = 1

    if seconds_per_n and seconds_per_n > 0:
        solver.parameters.max_time_in_seconds = float(seconds_per_n)

    callback = Counter()
    t0 = time.time()
    status = solver.Solve(model, callback)
    elapsed = time.time() - t0
    name = status_name(solver, status)

    # OPTIMAL means the entire feasible assignment space was exhausted.
    complete = (name.upper() == "OPTIMAL")

    return {
        "count": callback.count,
        "complete": complete,
        "status": name,
        "seconds": elapsed,
        "geometric_lines": geometric_count,
        "singletons": len(points),
        "candidate_count": len(candidates),
        "branches": getattr(solver, "NumBranches", lambda: -1)(),
        "conflicts": getattr(solver, "NumConflicts", lambda: -1)(),
    }


def open_output(path):
    exists = os.path.exists(path) and os.path.getsize(path) > 0
    f = open(path, "a", newline="", encoding="utf-8")
    writer = csv.writer(f)

    if not exists:
        writer.writerow([
            "N", "prime", "L",
            "geometric_lines", "singletons", "candidates",
            "optimal_covers", "complete", "status",
            "seconds", "branches", "conflicts"
        ])
        f.flush()

    return f, writer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", help="N,L CSV or rich ulam_line_covers CSV")
    ap.add_argument("--start-n", type=int, default=1)
    ap.add_argument("--max-n", type=int, default=50)
    ap.add_argument(
        "--seconds-per-n", type=float, default=0.0,
        help="optional time cap for each N; 0 means unlimited"
    )
    ap.add_argument(
        "--output", default="ulam_optimal_cover_counts.csv",
        help="append results here after every completed N"
    )
    args = ap.parse_args()

    optima = read_optima(args.csv)

    available = sorted(optima)
    if not available:
        raise SystemExit("No N values found in input.")
    max_available = max(available)

    if args.max_n > max_available:
        raise SystemExit(
            "Requested --max-n %d but input only reaches N=%d."
            % (args.max_n, max_available)
        )

    primes = first_primes(args.max_n)

    # Prefer prime values from the CSV, but reconstruct them if absent.
    for n in range(1, args.max_n + 1):
        if n not in optima:
            raise SystemExit("Input is missing N=%d." % n)

    out, writer = open_output(args.output)

    print(
        "Counting canonical optimal covers for N=%d..%d"
        % (args.start_n, args.max_n)
    )
    print("Output:", args.output)
    print(
        "Convention: all distinct >=2-point geometric lines + one singleton token per point."
    )
    if args.seconds_per_n:
        print("Per-N time cap: %.1f s" % args.seconds_per_n)
    else:
        print("Per-N time cap: none")
    print()

    try:
        for n in range(args.start_n, args.max_n + 1):
            csv_prime, L = optima[n]
            prime = csv_prime if csv_prime is not None else primes[n - 1]
            points = [ulam_coordinate(p) for p in primes[:n]]

            print(
                "N=%d prime=%d L=%d ... " % (n, prime, L),
                end="",
                flush=True,
            )

            result = count_covers(
                points,
                L,
                seconds_per_n=args.seconds_per_n,
            )

            writer.writerow([
                n, prime, L,
                result["geometric_lines"],
                result["singletons"],
                result["candidate_count"],
                result["count"],
                1 if result["complete"] else 0,
                result["status"],
                "%.6f" % result["seconds"],
                result["branches"],
                result["conflicts"],
            ])
            out.flush()

            suffix = "" if result["complete"] else "  [PARTIAL COUNT]"
            print(
                "%s covers, %.3fs, %s%s"
                % (
                    f"{result['count']:,}",
                    result["seconds"],
                    result["status"],
                    suffix,
                )
            )

            # If a time limit cut off an N, continuing to larger N is usually
            # not a productive use of a finite compute window.
            if not result["complete"]:
                print(
                    "\nEnumeration did not finish at N=%d. "
                    "The recorded count is only a lower bound." % n
                )
                print(
                    "Stopping here so the machine does not silently produce "
                    "a sequence containing partial counts."
                )
                break

    except KeyboardInterrupt:
        print("\nInterrupted. Completed rows are already saved.", file=sys.stderr)
    finally:
        out.close()


if __name__ == "__main__":
    main()
