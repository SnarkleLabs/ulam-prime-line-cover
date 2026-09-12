#!/usr/bin/env python3
"""
Resumable progressive runner for the Ulam prime line-cover solver.

This is the staged runner, with checkpoint/resume support built around the
combined CSV.  After every completed stage, that stage is appended to the
combined CSV.  If the run is interrupted, rerunning the same command resumes
from the highest complete N already present in the output CSV.

Python 3.7+ compatible.

Examples
--------
Start a new run to 4096 from an existing 2048 result:

    python3 run_ulam_progressive_resume.py 4096 \
        --resume-from ulam_line_covers_2048.csv

This creates ulam_line_covers_4096.csv, copies the 1..2048 data into it, then
starts at N=2049.

If that run is interrupted, simply rerun the SAME command.  Because
ulam_line_covers_4096.csv now exists, the runner validates it and resumes from
its last complete N automatically.

To deliberately throw away an existing output and start over, add --restart.

The C++ template ulam_prime_line_cover_progressive_fast.cpp should be in the
same folder as this script, or pass --source PATH.
"""
from __future__ import print_function
import argparse
import csv
import os
import re
import shutil
import subprocess
import sys


def round_up_64(n):
    return ((n + 63) // 64) * 64


def patch_capacity(text, capacity):
    text, n1 = re.subn(
        r'(constexpr\s+int\s+kBitCapacity\s*=\s*)\d+(\s*;)',
        r'\g<1>%d\2' % capacity, text, count=1)
    text, n2 = re.subn(
        r'(constexpr\s+int\s+kExecutionLimit\s*=\s*)\d+(\s*;)',
        r'\g<1>%d\2' % capacity, text, count=1)
    if n1 != 1 or n2 != 1:
        raise RuntimeError("Could not patch capacity constants in C++ source")
    return text


def inspect_cover_csv(csv_path):
    """Validate a combined/stage cover CSV and return (max_n, L(max_n)).

    A complete frame at N should contain exactly L(N) line rows.  We also
    require N=1..max_n with no gaps, and consistent prime/L values within each
    N.  This makes it unlikely that a partially-written final frame will be
    mistaken for a checkpoint.
    """
    required = set(["N", "new_prime", "total_lines", "line_id"])
    counts = {}
    line_counts = {}
    primes = {}
    line_ids = {}

    with open(csv_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise RuntimeError("CSV has no header: %s" % csv_path)
        missing = required.difference(reader.fieldnames)
        if missing:
            raise RuntimeError("CSV is missing columns %s: %s" %
                               (", ".join(sorted(missing)), csv_path))

        for row_no, row in enumerate(reader, start=2):
            try:
                n = int(row["N"])
                p = int(row["new_prime"])
                l = int(row["total_lines"])
                line_id = int(row["line_id"])
            except Exception:
                raise RuntimeError("Bad numeric data at CSV row %d in %s" %
                                   (row_no, csv_path))

            if n < 1 or l < 1:
                raise RuntimeError("Invalid N/L at CSV row %d in %s" %
                                   (row_no, csv_path))

            counts[n] = counts.get(n, 0) + 1
            if n in line_counts and line_counts[n] != l:
                raise RuntimeError("Inconsistent total_lines for N=%d in %s" %
                                   (n, csv_path))
            if n in primes and primes[n] != p:
                raise RuntimeError("Inconsistent new_prime for N=%d in %s" %
                                   (n, csv_path))
            line_counts[n] = l
            primes[n] = p
            line_ids.setdefault(n, set()).add(line_id)

    if not counts:
        raise RuntimeError("CSV contains no data rows: %s" % csv_path)

    max_n = max(counts)
    missing_n = [n for n in range(1, max_n + 1) if n not in counts]
    if missing_n:
        preview = ", ".join(str(x) for x in missing_n[:10])
        if len(missing_n) > 10:
            preview += ", ..."
        raise RuntimeError("CSV has missing N values (%s): %s" %
                           (preview, csv_path))

    for n in range(1, max_n + 1):
        expected = line_counts[n]
        if counts[n] != expected:
            raise RuntimeError(
                "Incomplete frame at N=%d: found %d line rows, expected %d in %s" %
                (n, counts[n], expected, csv_path))
        if len(line_ids[n]) != expected:
            raise RuntimeError(
                "Duplicate/missing line_id values at N=%d in %s" % (n, csv_path))

    return max_n, line_counts[max_n]


def last_line_count(csv_path, end_n):
    last = None
    rows = 0
    ids = set()
    with open(csv_path, "r", newline="") as f:
        for row in csv.DictReader(f):
            try:
                n = int(row["N"])
            except Exception:
                continue
            if n == end_n:
                last = int(row["total_lines"])
                rows += 1
                ids.add(int(row["line_id"]))
    if last is None:
        raise RuntimeError("Could not find N=%d in %s" % (end_n, csv_path))
    if rows != last or len(ids) != last:
        raise RuntimeError(
            "Stage CSV appears incomplete at N=%d: found %d rows, expected %d" %
            (end_n, rows, last))
    return last


def append_csv(src, dst, write_header):
    with open(src, "r", newline="") as fi, open(dst, "a", newline="") as fo:
        reader = csv.reader(fi)
        writer = csv.writer(fo)
        header = next(reader)
        if write_header:
            writer.writerow(header)
        for row in reader:
            writer.writerow(row)


def next_stage_end(start, target, stage_size):
    # Preserve the original 512-style boundaries even when resuming from a
    # non-boundary N.  Example: resume at 2300 -> finish that block at 2560.
    boundary = ((start - 1) // stage_size + 1) * stage_size
    return min(target, boundary)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", type=int, help="largest N to solve")
    ap.add_argument("--stage-size", type=int, default=512,
                    help="N values per checkpoint stage (default: 512)")
    ap.add_argument("--output", default=None,
                    help="combined cover CSV (default: ulam_line_covers_TARGET.csv)")
    ap.add_argument("--resume-from", default=None,
                    help="seed a new output from an earlier combined cover CSV")
    ap.add_argument("--source", default=None,
                    help="path to ulam_prime_line_cover_progressive_fast.cpp")
    ap.add_argument("--compiler", default="clang++")
    ap.add_argument("--restart", action="store_true",
                    help="ignore/delete an existing output and start from N=1")
    ap.add_argument("--keep-build", action="store_true",
                    help="keep generated per-stage source, executables, and CSVs")
    ap.add_argument("--plan-only", action="store_true",
                    help="show resume point/stages without compiling or solving")
    args = ap.parse_args()

    if args.target < 1:
        ap.error("target must be positive")
    if args.target > 4096:
        ap.error("this template is intended for targets up to 4096")
    if args.stage_size < 64:
        ap.error("stage-size should be at least 64")

    here = os.path.dirname(os.path.abspath(__file__))
    source = args.source or os.path.join(here, "ulam_prime_line_cover_progressive_fast.cpp")
    if not os.path.exists(source):
        raise SystemExit("C++ template not found: %s" % source)

    output = os.path.abspath(args.output or ("ulam_line_covers_%d.csv" % args.target))
    resume_from = os.path.abspath(args.resume_from) if args.resume_from else None

    start = 1
    prev_lines = 0
    wrote_header = False

    if args.restart:
        if os.path.exists(output):
            os.remove(output)
        print("Restart requested: beginning at N=1", flush=True)
    elif os.path.exists(output):
        # Most convenient recovery path: rerun the same command after an
        # interruption and use the already-assembled output as the checkpoint.
        max_n, prev_lines = inspect_cover_csv(output)
        if max_n > args.target:
            raise SystemExit("Existing output already extends past target: N=%d" % max_n)
        start = max_n + 1
        wrote_header = True
        print("Resuming from existing output: %s" % output, flush=True)
        print("Validated complete through N=%d; L(%d)=%d" %
              (max_n, max_n, prev_lines), flush=True)
    elif resume_from:
        if not os.path.exists(resume_from):
            raise SystemExit("Resume CSV not found: %s" % resume_from)
        max_n, prev_lines = inspect_cover_csv(resume_from)
        if max_n > args.target:
            raise SystemExit("Resume CSV already extends past target: N=%d" % max_n)
        if os.path.abspath(resume_from) != output:
            shutil.copyfile(resume_from, output)
        start = max_n + 1
        wrote_header = True
        print("Seeded output from: %s" % resume_from, flush=True)
        print("Validated complete through N=%d; L(%d)=%d" %
              (max_n, max_n, prev_lines), flush=True)

    if start > args.target:
        print("Already complete through target N=%d." % args.target)
        print("Combined CSV: %s" % output)
        return

    # Show exactly what remains before doing any expensive work.
    print("Next N        : %d" % start, flush=True)
    print("Target        : %d" % args.target, flush=True)
    print("Previous L    : %d" % prev_lines, flush=True)
    print("Combined CSV  : %s" % output, flush=True)
    print("Remaining stages:", flush=True)
    s = start
    while s <= args.target:
        e = next_stage_end(s, args.target, args.stage_size)
        print("  N=%d..%d  capacity=%d bits" % (s, e, round_up_64(e)), flush=True)
        s = e + 1

    if args.plan_only:
        print("Plan only: no compilation or solving performed.")
        return

    compiler = shutil.which(args.compiler)
    if not compiler:
        raise SystemExit("Compiler not found: %s" % args.compiler)

    build_dir = os.path.abspath(".ulam_progressive_build")
    if not os.path.isdir(build_dir):
        os.makedirs(build_dir)

    with open(source, "r") as f:
        template = f.read()

    stage_no = (start - 1) // args.stage_size + 1

    while start <= args.target:
        end = next_stage_end(start, args.target, args.stage_size)
        capacity = round_up_64(end)

        stage_cpp = os.path.join(build_dir, "ulam_stage_%04d.cpp" % capacity)
        stage_exe = os.path.join(build_dir, "ulam_stage_%04d" % capacity)
        stage_csv = os.path.join(build_dir, "ulam_stage_%04d_%04d.csv" % (start, end))

        print("\n=== Stage %d: N=%d..%d, capacity=%d bits ===" %
              (stage_no, start, end, capacity), flush=True)

        patched = patch_capacity(template, capacity)
        with open(stage_cpp, "w") as f:
            f.write(patched)

        compile_cmd = [compiler, "-std=c++20", "-O3", "-march=native", "-pthread",
                       stage_cpp, "-o", stage_exe]
        print("Compiling capacity-%d solver..." % capacity, flush=True)
        subprocess.check_call(compile_cmd)

        # Remove any stale partial stage CSV left by an interrupted attempt.
        if os.path.exists(stage_csv):
            os.remove(stage_csv)

        run_cmd = [stage_exe, str(end), stage_csv, str(start), str(prev_lines)]
        subprocess.check_call(run_cmd)

        # Only append after the stage's final frame has been verified complete.
        prev_lines = last_line_count(stage_csv, end)
        append_csv(stage_csv, output, not wrote_header)
        wrote_header = True

        print("Checkpoint saved: complete through N=%d, L=%d" %
              (end, prev_lines), flush=True)
        print("Combined CSV: %s" % output, flush=True)

        start = end + 1
        stage_no += 1

    print("\nFinished N=1..%d" % args.target)
    print("Final line count: %d" % prev_lines)
    print("Combined CSV: %s" % output)

    if not args.keep_build:
        shutil.rmtree(build_dir, ignore_errors=True)
    else:
        print("Build files kept in: %s" % build_dir)


if __name__ == "__main__":
    main()
