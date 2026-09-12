# Minimum Line Covers of Primes on the Ulam Spiral

This repository contains programs, computational results, and visualizations
for a variation of the prime line-cover problem.

The positive integers are arranged on the standard Ulam spiral, and the
locations corresponding to prime numbers are selected. For the first N primes,
the problem considered here is:

> What is the minimum number of straight lines required to cover all of the
> prime locations?

The project grew out of experiments with the prime line-cover problem and the
associated "awkward primes" sequence, [OEIS A393445](https://oeis.org/A393445).
The solver used here was adapted from
[Jesper Gran Mikkelsen's exact solver](https://github.com/jespergran98/prime-line-cover).
Related theoretical background appears in
[Lines in the Prime Number Graph](https://arxiv.org/abs/2605.22752), by Scott
Duke Kominers, Rudi Mrazović, Carl Pomerance, and Patrick Solé.

The principal difference here is geometric. Rather than considering the points
(n, p_n), the primes are placed at their integer-coordinate positions on the
Ulam spiral.

This repository accompanies a video presentation of the project and is
intended to make the computations, data, and methods available for inspection
and reproduction.

An [animation of the computed covers](figures/ulam_growth.mp4) is included to
show how the selected solutions evolve as additional primes are added.


## The problem

Place the positive integers on a square Ulam spiral and select the positions
occupied by the first N primes:

    2, 3, 5, 7, 11, ...

A line cover is a collection of straight lines such that every one of these
N points lies on at least one of the lines.

The quantity L(N) is the smallest possible number of lines in such a cover.

Lines may have arbitrary slopes. A line may cover two or more prime points,
and a line covering a single otherwise-uncovered point is also permitted.

The optimization problem is therefore to find a collection of lines that
covers every point while minimizing the total number of lines. For purposes
of counting solutions, all lines that cover only the same single point are
treated as one canonical singleton choice.

Because the Ulam spiral contains many accidental and systematic collinearities,
the resulting sequence behaves quite differently from the corresponding
prime-line-cover problem on the points (n, p_n). Computed solutions make heavy
use of common diagonal clusters, and apparent changes occur in which diagonal
direction predominates. It is not yet known whether those changes reflect a
general property of optimal covers or merely the particular optimal solution
selected by the solver.



## Results

The main computed sequence is provided in:

    data/ulam_N_prime_L_2508.csv

The columns give:

    N       number of prime points included
    prime   the Nth prime
    L       minimum number of lines required

Thus each row records the exact minimum line-cover number found for the first
N primes on the Ulam spiral.

The repository contains results through N = 2508.


## Awkward primes

One useful way of looking at the sequence is to identify the primes at which
adding one additional point forces the minimum number of lines to increase.

That is, these are values of N for which

    L(N) > L(N - 1).

The corresponding primes play a role analogous to the "awkward primes" in the
ordinary prime line-cover problem.

In the accompanying data and video, these Ulam-spiral transition primes are
called "ulkward primes"—a deliberate contraction of "Ulam" and "awkward."

Computed values are provided in:

    data/ulam_awkward_primes_2508.csv

These transition points are particularly useful because most additions of a
new prime do not necessarily increase the minimum cover number.


## Counting optimal solutions

A later part of the project investigates a different question:

> How many distinct optimal line covers exist for a given N?

This is substantially more computationally expensive than merely finding the
minimum value L(N). An adaptive exhaustive-search program was developed to
divide the search space into chunks that can be evaluated in parallel.

Complete exhaustive counts have been obtained for every N through N = 30.
Calculations beyond that range are exploratory and may require substantially
more computation.

An important convention is required when counting solutions. Geometrically,
infinitely many lines pass through any single isolated point. For counting
purposes, a line covering only one point is therefore represented by one
canonical singleton candidate. This prevents infinitely many geometrically
equivalent singleton choices from being counted as distinct covers.


## Software

The `src` directory contains the programs used to compute, verify, enumerate,
and visualize line covers.

### `ulam_prime_line_cover_appleclang15.cpp`

Exact solver for finding L(N), the minimum number of straight lines required
to cover the first N prime locations on the Ulam spiral.

This program is an adaptation of Jesper Gran Mikkelsen's exact
prime-line-cover solver:

https://github.com/jespergran98/prime-line-cover

Mikkelsen's solver was modified to replace the original prime-coordinate
geometry with the integer-coordinate positions of primes on the Ulam spiral.
This version was modified for compilation with Apple Clang 15.

This solver was used during the initial development and verification of the
Ulam line-cover problem.


### `ulam_prime_line_cover_progressive_fast.cpp`

The main solver used to compute the Ulam line-cover sequence over progressively
larger values of N.

Rather than solving each value of N independently from scratch, this version
is designed for progressive computation and produces the line-cover solutions
used in the main data set.

The resulting minimum line counts form the sequence L(N).


### `run_ulam_progressive_fast.py`

Python driver for running `ulam_prime_line_cover_progressive_fast` over a
range of N values and collecting its output.

This is intended for starting a new progressive computation.


### `run_ulam_progressive_resume.py`

Companion driver for resuming an interrupted progressive computation without
discarding previously completed results.

This was particularly useful for the longer computations at larger N.


### `verify_ulam_line_cover.py`

Independent small-N implementation of the Ulam prime line-cover problem. It
recomputes the minimum line-cover number using a separate Python
branch-and-bound search and can be used for comparison with the main solver.
It does not read or validate stored cover files. Its default maximum is N = 30.


### `count_ulam_optimal_adaptive.py`

Exhaustive-search program for counting all distinct optimal covers for a
specified N after L(N) is known.

Finding L(N) and counting the solutions that attain L(N) are very different
computational problems. The latter requires exploring a potentially enormous
search tree.

The program partitions that search tree into chunks that can be processed in
parallel. Difficult chunks can be subdivided further during the calculation,
allowing unusually expensive branches to be broken into smaller pieces rather
than forcing one worker to remain trapped in a single branch for an excessive
amount of time.

Singleton-covered points are represented canonically so that the infinitely
many geometrically possible lines through a single isolated point do not
produce infinitely many equivalent covers.

This program has been used to complete exhaustive counts for every N through
N = 30.

This program uses helper functions from `count_ulam_optimal_covers.py`; both
files must remain together in the `src` directory. It also requires the
Google OR-Tools Python package.


### `render_ulam_frames.py`

Visualization program for rendering computed line covers on the Ulam spiral.

It generates graphical frames showing the prime locations and the lines used
by their covers. These frames can also be assembled into an animation showing
how the solutions evolve as additional primes are added.

The visualization is not part of the optimization calculation itself.


## Reproducing the calculations

The programs were developed and run primarily on macOS. The computational
workflow consists of three largely independent stages:

1. **Find L(N).**  
   Use one of the progressive Python drivers to calculate minimum line covers
   over a range of N. The drivers compile capacity-appropriate versions of the
   C++ solver automatically.

2. **Independently compare small-N results.**  
   `verify_ulam_line_cover.py` independently computes the minimum line-cover
   number for small values of N using a separate Python branch-and-bound
   implementation. It does not read or validate stored cover files.

3. **Count optimal covers.**  
   For selected N, use `count_ulam_optimal_adaptive.py` to exhaustively
   enumerate the optimal covers once L(N) is already known.

`render_ulam_frames.py` can optionally be used to visualize the computed
covers.

The progressive drivers require Python 3.7 or later and an available C++
compiler; they use `clang++` by default. The optimal-cover counter additionally
requires Google OR-Tools, which can be installed with:

```bash
python3 -m pip install ortools
```

## Example Commands

Run the following commands from the top-level repository directory.

To start a new progressive calculation through N = 2508:

```bash
python3 src/run_ulam_progressive_fast.py 2508 \
    --output ulam_line_covers_2508.csv \
    --source src/ulam_prime_line_cover_progressive_fast.cpp
```

To count every optimal cover for N = 30 using the stored optimum:

```bash
python3 src/count_ulam_optimal_adaptive.py \
    data/ulam_N_prime_L_2508.csv \
    --n 30 \
    --jobs 9 \
    --initial-depth 20 \
    --max-depth 100
```

If an earlier combined cover file named `ulam_line_covers_2048.csv` is
available, it can seed a run through N = 2508:

```bash
python3 src/run_ulam_progressive_resume.py 2508 \
    --output ulam_line_covers_2508.csv \
    --resume-from ulam_line_covers_2048.csv \
    --source src/ulam_prime_line_cover_progressive_fast.cpp
```

If that run is interrupted, rerun the same command. The resume driver validates
the existing `ulam_line_covers_2508.csv` and continues after its highest
complete N.

## Data files

The repository contains processed result files rather than every intermediate
file produced during computation.

Large temporary files, chunk files, rendered video frames, executables, and
other reproducible intermediate products are intentionally omitted.

In particular, exhaustive enumeration can generate very large temporary files.
These are working data rather than primary results and are not necessary for
using the main sequence.


## Background and attribution

This project was inspired by the prime line-cover problem and the work of
Jesper Gran Mikkelsen.

See:

* OEIS A393445:
  https://oeis.org/A393445

* Jesper Gran Mikkelsen's `prime-line-cover` repository:
  https://github.com/jespergran98/prime-line-cover

Parts of the solver in this repository are derived from Mikkelsen's
MIT-licensed code and have been modified for the Ulam-spiral geometry.

The original copyright and license notices for derived code are retained where
applicable.

The Ulam-spiral formulation, associated computational experiments, data
generation, analysis, and visualization in this repository were developed for
this project.


## Status

This is an ongoing computational exploration rather than a finished
mathematical classification.

The repository is being made public both to document the results and to allow
others to reproduce, check, extend, or identify connections with existing
mathematical work.

Corrections and observations are welcome.


## Citation

If you use the code or computational results from this project, please cite the
repository.

A `CITATION.cff` file is included so that GitHub can generate citation
information automatically.

If this work later results in a formal paper or archived release, the preferred
citation will be updated accordingly.


## License

Unless otherwise noted, original code in this repository is released under the
MIT License.

Portions derived from Jesper Gran Mikkelsen's `prime-line-cover` project remain
subject to its MIT license and copyright notice.

See the `LICENSE.txt` file and notices in individual source files for details.


## Contact

Questions, corrections, computational results, and related observations can be
submitted through GitHub Issues.
