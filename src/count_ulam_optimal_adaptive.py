#!/usr/bin/env python3
import argparse, csv, math, multiprocessing as mp, os, queue, time
from collections import deque

import count_ulam_optimal_covers as base
from ortools.sat.python import cp_model


class Counter(cp_model.CpSolverSolutionCallback):
    def __init__(self):
        super().__init__()
        self.count = 0
    def on_solution_callback(self):
        self.count += 1


def build_model(candidate_count, incidence, optimum, fixed):
    model = cp_model.CpModel()
    x = [model.NewBoolVar(f"c{j}") for j in range(candidate_count)]
    for inc in incidence:
        model.Add(sum(x[j] for j in inc) >= 1)
    model.Add(sum(x) == optimum)
    for j, v in fixed:
        model.Add(x[j] == v)
    return model


def persistent_worker(job_q, result_q, points, optimum):
    # Expensive candidate geometry is built ONCE per persistent worker.
    candidates, geometric_count, incidence = base.build_candidates(points)
    candidate_count = len(candidates)
    pid = os.getpid()

    while True:
        job = job_q.get()
        if job is None:
            return
        cid, fixed = job
        result_q.put({"kind": "started", "cid": cid, "pid": pid})
        try:
            model = build_model(candidate_count, incidence, optimum, fixed)
            solver = cp_model.CpSolver()
            solver.parameters.enumerate_all_solutions = True
            solver.parameters.num_search_workers = 1
            cb = Counter()
            t0 = time.time()
            status = solver.Solve(model, cb)
            result_q.put({
                "kind": "done", "cid": cid, "pid": pid,
                "count": cb.count, "status": solver.StatusName(status),
                "seconds": time.time() - t0,
                "branches": solver.NumBranches(),
                "conflicts": solver.NumConflicts()
            })
        except BaseException as e:
            result_q.put({"kind": "error", "cid": cid, "pid": pid, "error": repr(e)})


def make_chunks(vars_):
    chunks = [tuple()]
    for var in vars_:
        chunks = [c + ((var, b),) for c in chunks for b in (0, 1)]
    return chunks


def next_split_var(fixed, geometric_count):
    used = {j for j, _ in fixed}
    for j in range(geometric_count):
        if j not in used:
            return j
    return None


def fmt_fixed(fixed):
    return ",".join(f"{j}={v}" for j, v in fixed) or "root"


def log_comb(n, k):
    if k < 0 or k > n:
        return float("-inf")
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def chunk_size_ratio(fixed, total_candidates, optimum, baseline_log_size):
    """
    Compare a chunk's crude combinatorial completion count against a FIXED
    baseline: the mean chunk size at --initial-depth.

    Using the mean at the chunk's *current* depth moves the goalposts downward
    every time we split and can force nearly every feasible low-1 branch all
    the way to --max-depth.  The fixed baseline avoids that runaway behavior.
    """
    d = len(fixed)
    ones = sum(v for _, v in fixed)
    lc = log_comb(total_candidates - d, optimum - ones)
    if lc == float("-inf"):
        return 0.0
    diff = lc - baseline_log_size
    return float("inf") if diff > 700 else math.exp(diff)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--initial-depth", type=int, default=6)
    ap.add_argument("--max-depth", type=int, default=30)
    ap.add_argument("--status-every", type=float, default=30)
    ap.add_argument("--fill-split-after", type=float, default=15,
                    help="if queue empties with idle slots, split youngest eligible running chunk; 0 disables")
    ap.add_argument("--presplit-factor", type=float, default=16.0,
                    help="pre-launch split if combinatorial proxy exceeds this multiple of depth mean; 0 disables")
    ap.add_argument("--verbose-events", action="store_true")
    ap.add_argument("--output", default=None)
    a = ap.parse_args()

    opt = base.read_optima(a.csv)
    csv_prime, L = opt[a.n]
    primes = base.first_primes(a.n)
    prime = csv_prime if csv_prime is not None else primes[-1]
    points = [base.ulam_coordinate(p) for p in primes]
    candidates, geometric_count, _ = base.build_candidates(points)
    split_vars = list(range(min(a.initial_depth, geometric_count)))
    initial = make_chunks(split_vars)

    # Fixed presplit target: mean combinatorial size of an initial-depth chunk.
    # This stays constant as descendants are subdivided.
    baseline_log_size = (
        log_comb(len(candidates), L) - len(split_vars) * math.log(2.0)
    )

    if a.output is None:
        a.output = f"ulam_optimal_N{a.n}_chunks.csv"

    print(f"N={a.n} prime={prime} L={L}", flush=True)
    print(f"{geometric_count} geometric lines, {len(candidates)} total candidates", flush=True)
    print(f"Initial depth {len(split_vars)} -> {len(initial)} chunks", flush=True)
    print(f"{a.jobs} PERSISTENT workers; heartbeat every {a.status_every:.0f}s", flush=True)
    if a.presplit_factor > 0:
        print(f"Pre-launch size guard: > {a.presplit_factor:g}x initial-depth mean", flush=True)
    if not a.verbose_events:
        print("Console: heartbeat only", flush=True)

    ctx = mp.get_context("spawn")
    job_q = ctx.Queue(maxsize=max(2 * a.jobs, 16))
    result_q = ctx.Queue()

    workers = {}
    def spawn_worker():
        p = ctx.Process(target=persistent_worker, args=(job_q, result_q, points, L))
        p.start()
        workers[p.pid] = p

    for _ in range(a.jobs):
        spawn_worker()

    pending = deque((i, fixed, "") for i, fixed in enumerate(initial))
    next_id = len(initial)
    dispatched = {}   # cid -> fixed,parent,dispatch,start,pid
    exact_total = completed = splits = 0
    failed = False
    max_depth_seen = len(split_vars)
    free_slots = a.jobs

    exists = os.path.exists(a.output) and os.path.getsize(a.output) > 0
    outf = open(a.output, "a", newline="")
    w = csv.writer(outf)
    if not exists:
        w.writerow(["event","chunk_id","parent_id","depth","fixed","count",
                    "status","seconds","branches","conflicts"])
        outf.flush()

    def report():
        now = time.time()
        # Use dispatch time rather than the worker's "started" acknowledgement.
        # Very fast chunks can finish/reload so quickly that the coordinator has
        # several dispatched jobs whose started messages have not yet been handled.
        ages = sorted((now - r["dispatch"] for r in dispatched.values()), reverse=True)
        age_list = ", ".join(f"{x:.0f}" for x in ages) if ages else "-"
        print(f"heartbeat: running={len(dispatched)} queued={len(pending)} completed={completed} "
              f"splits={splits} maxdepth={max_depth_seen} total_so_far={exact_total:,} "
              f"ages=[{age_list}]", flush=True)

    def prepare_one(cid, fixed, parent):
        nonlocal next_id, splits, max_depth_seen
        while a.presplit_factor > 0 and len(fixed) < a.max_depth:
            ratio = chunk_size_ratio(fixed, len(candidates), L, baseline_log_size)
            if ratio <= a.presplit_factor:
                break
            var = next_split_var(fixed, geometric_count)
            if var is None:
                break
            c0, c1 = fixed + ((var,0),), fixed + ((var,1),)
            id0, id1 = next_id, next_id + 1
            next_id += 2
            pending.appendleft((id1, c1, cid))
            w.writerow(["split",cid,parent,len(fixed),fmt_fixed(fixed),"",
                        f"prelaunch-size-{ratio:.6g}x","","",""])
            splits += 1
            max_depth_seen = max(max_depth_seen, len(c0))
            cid, fixed, parent = id0, c0, cid
        return cid, fixed, parent

    def dispatch_available():
        nonlocal free_slots
        while free_slots > 0 and pending:
            cid, fixed, parent = pending.popleft()
            cid, fixed, parent = prepare_one(cid, fixed, parent)
            dispatched[cid] = {"fixed":fixed, "parent":parent,
                               "dispatch":time.time(), "start":None, "pid":None}
            job_q.put((cid, fixed))
            free_slots -= 1

    last_heartbeat = time.time()
    dispatch_available()

    try:
        while pending or dispatched:
            timeout = max(0.05, min(1.0, a.status_every - (time.time() - last_heartbeat)))
            try:
                msg = result_q.get(timeout=timeout)
            except queue.Empty:
                msg = None

            if msg:
                cid = msg["cid"]
                info = dispatched.get(cid)
                if msg["kind"] == "started":
                    if info:
                        info["start"] = time.time()
                        info["pid"] = msg["pid"]
                else:
                    info = dispatched.pop(cid, None)
                    free_slots += 1
                    if msg["kind"] == "error":
                        failed = True
                        print(f"Chunk {cid} ERROR: {msg['error']}", flush=True)
                        if info:
                            w.writerow(["error",cid,info["parent"],len(info["fixed"]),
                                        fmt_fixed(info["fixed"]),"",msg["error"],"","",""])
                    else:
                        completed += 1
                        exact_total += msg["count"]
                        if msg["status"].upper() not in ("OPTIMAL","INFEASIBLE"):
                            failed = True
                        if a.verbose_events:
                            print(f"Chunk {cid}: count={msg['count']:,} {msg['seconds']:.3f}s {msg['status']}", flush=True)
                        w.writerow(["done",cid,info["parent"],len(info["fixed"]),fmt_fixed(info["fixed"]),
                                    msg["count"],msg["status"],f"{msg['seconds']:.6f}",
                                    msg["branches"],msg["conflicts"]])
                    # Critical fast path: refill immediately after every completion.
                    dispatch_available()

            now = time.time()

            # Rare fallback: if no pending work remains but slots are idle, sacrifice
            # the YOUNGEST sufficiently-old search, split it, and replace its worker.
            if (not pending and dispatched and free_slots > 0 and a.fill_split_after > 0):
                eligible = []
                for cid, r in dispatched.items():
                    if r.get("start") is not None:
                        age = now - r["start"]
                        if age >= a.fill_split_after and len(r["fixed"]) < a.max_depth and r.get("pid"):
                            eligible.append((age,cid,r))
                if eligible:
                    age,cid,info = min(eligible, key=lambda t:t[0])
                    pid = info["pid"]
                    p = workers.pop(pid, None)
                    if p:
                        p.terminate(); p.join(timeout=2)
                    dispatched.pop(cid, None)
                    free_slots += 1
                    var = next_split_var(info["fixed"], geometric_count)
                    if var is not None:
                        c0 = info["fixed"] + ((var,0),)
                        c1 = info["fixed"] + ((var,1),)
                        id0,id1 = next_id,next_id+1
                        next_id += 2
                        pending.appendleft((id1,c1,cid)); pending.appendleft((id0,c0,cid))
                        splits += 1; max_depth_seen=max(max_depth_seen,len(c0))
                        w.writerow(["split",cid,info["parent"],len(info["fixed"]),fmt_fixed(info["fixed"]),
                                    "","idle-core-youngest",f"{age:.6f}","",""])
                    spawn_worker()
                    dispatch_available()

            if now - last_heartbeat >= a.status_every:
                outf.flush()
                report()
                last_heartbeat = now

    except KeyboardInterrupt:
        print("\nStopping persistent workers. Completed chunks are saved.", flush=True)
    finally:
        for _ in workers:
            try: job_q.put_nowait(None)
            except Exception: pass
        for p in workers.values():
            p.join(timeout=1)
            if p.is_alive():
                p.terminate(); p.join(timeout=1)
        outf.flush()
        outf.close()

    if not pending and not dispatched:
        if failed:
            print("Finished, but at least one chunk was not exact. Do not trust the total.", flush=True)
        else:
            print(f"ALL CHUNKS COMPLETE. Exact count for N={a.n}: {exact_total:,}", flush=True)


if __name__ == "__main__":
    main()
