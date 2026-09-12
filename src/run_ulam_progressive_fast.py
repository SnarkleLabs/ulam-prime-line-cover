#!/usr/bin/env python3
"""
Progressive runner for the Ulam prime line-cover solver.

Instead of asking a 4096-capacity solver to carry every future heavy line while
solving tiny N, this runner rebuilds the exact solver in stages.  Each stage is
compiled with only enough bit capacity for that horizon, and solves only the
new N values.

Python 3.7+ compatible.

Examples:
    python3 run_ulam_progressive.py 2048
    python3 run_ulam_progressive.py 4096 --stage-size 512 --output ulam_4096.csv

The C++ template ulam_prime_line_cover_progressive_fast.cpp should be in the same folder
as this script, or pass --source PATH.
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


def last_line_count(csv_path, end_n):
    last = None
    with open(csv_path, "r", newline="") as f:
        for row in csv.DictReader(f):
            try:
                n = int(row["N"])
            except Exception:
                continue
            if n == end_n:
                last = int(row["total_lines"])
    if last is None:
        raise RuntimeError("Could not find N=%d in %s" % (end_n, csv_path))
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", type=int, help="largest N to solve")
    ap.add_argument("--stage-size", type=int, default=512,
                    help="N values per stage (default: 512)")
    ap.add_argument("--output", default=None,
                    help="combined cover CSV (default: ulam_line_covers_TARGET.csv)")
    ap.add_argument("--source", default=None,
                    help="path to ulam_prime_line_cover_progressive_fast.cpp")
    ap.add_argument("--compiler", default="clang++")
    ap.add_argument("--keep-build", action="store_true",
                    help="keep generated per-stage source, executables, and CSVs")
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

    compiler = shutil.which(args.compiler)
    if not compiler:
        raise SystemExit("Compiler not found: %s" % args.compiler)

    output = args.output or ("ulam_line_covers_%d.csv" % args.target)
    output = os.path.abspath(output)
    if os.path.exists(output):
        os.remove(output)

    build_dir = os.path.abspath(".ulam_progressive_build")
    if not os.path.isdir(build_dir):
        os.makedirs(build_dir)

    with open(source, "r") as f:
        template = f.read()

    start = 1
    prev_lines = 0
    stage_no = 0
    wrote_header = False

    while start <= args.target:
        stage_no += 1
        end = min(args.target, start + args.stage_size - 1)
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

        run_cmd = [stage_exe, str(end), stage_csv, str(start), str(prev_lines)]
        subprocess.check_call(run_cmd)

        prev_lines = last_line_count(stage_csv, end)
        append_csv(stage_csv, output, not wrote_header)
        wrote_header = True

        print("Stage complete: L(%d)=%d" % (end, prev_lines), flush=True)
        start = end + 1

    print("\nFinished N=1..%d" % args.target)
    print("Final line count: %d" % prev_lines)
    print("Combined CSV: %s" % output)

    if not args.keep_build:
        shutil.rmtree(build_dir, ignore_errors=True)
    else:
        print("Build files kept in: %s" % build_dir)


if __name__ == "__main__":
    main()
