#!/usr/bin/env python3
# Exact brute-force / branch-and-bound verifier for small-N Ulam prime line cover.
# Python 3.7 compatible.

from __future__ import print_function
import math
import sys
from fractions import Fraction


def primes_first(n):
    out=[]
    x=2
    while len(out)<n:
        isprime=True
        r=int(math.sqrt(x))
        for p in out:
            if p>r:
                break
            if x%p==0:
                isprime=False
                break
        if isprime:
            out.append(x)
        x += 1
    return out


def ulam_coordinate(value):
    if value <= 1:
        return (0,0)
    k = int(math.ceil((math.sqrt(float(value)) - 1.0)/2.0))
    side = 2*k
    max_value = (2*k+1)*(2*k+1)
    d = max_value - value
    if d < side:
        return (k-d, -k)
    elif d < 2*side:
        return (-k, -k + (d-side))
    elif d < 3*side:
        return (-k + (d-2*side), k)
    else:
        return (k, k-(d-3*side))


def canonical_line(a,b):
    x1,y1=a; x2,y2=b
    A=y1-y2
    B=x2-x1
    C=-(A*x1+B*y1)
    g=math.gcd(math.gcd(abs(A),abs(B)),abs(C))
    if g:
        A//=g; B//=g; C//=g
    if A<0 or (A==0 and B<0):
        A=-A; B=-B; C=-C
    return (A,B,C)


def popcount(x):
    try:
        return x.bit_count()
    except AttributeError:
        return bin(x).count('1')


def build_line_masks(points):
    n=len(points)
    by_line={}
    for i in range(n):
        for j in range(i+1,n):
            key=canonical_line(points[i], points[j])
            m=by_line.get(key,0)
            m |= (1<<i) | (1<<j)
            by_line[key]=m
    # Only heavy lines matter explicitly. Any 0/1/2 residual points can be paired arbitrarily.
    heavy=[]
    for key,m in by_line.items():
        if popcount(m)>=3:
            heavy.append((key,m))
    return heavy


def exact_min_cover(points, verbose=False):
    n=len(points)
    heavy=build_line_masks(points)
    full=(1<<n)-1

    # Incidence for branch choice.
    inc=[[] for _ in range(n)]
    for idx,(key,m) in enumerate(heavy):
        mm=m
        while mm:
            lsb=mm & -mm
            p=lsb.bit_length()-1
            inc[p].append(idx)
            mm -= lsb

    best=[(n+1)//2]
    best_sel=[[]]

    # Greedy quick UB.
    uncovered=full
    sel=[]
    while True:
        best_i=-1; best_c=2
        for i,(k,m) in enumerate(heavy):
            c=popcount(m & uncovered)
            if c>best_c:
                best_c=c; best_i=i
        if best_i<0:
            break
        uncovered &= ~heavy[best_i][1]
        sel.append(best_i)
    ub=len(sel)+(popcount(uncovered)+1)//2
    if ub<best[0]:
        best[0]=ub; best_sel[0]=sel[:]

    seen={}

    def dfs(uncovered, chosen):
        if not uncovered:
            if len(chosen)<best[0]:
                best[0]=len(chosen); best_sel[0]=chosen[:]
            return

        rem=popcount(uncovered)
        # Simple absolute lower bound: one line can cover at most max current heavy coverage, otherwise 2.
        maxcov=2
        for _,m in heavy:
            c=popcount(m & uncovered)
            if c>maxcov:
                maxcov=c
        lb=(rem + maxcov - 1)//maxcov
        if len(chosen)+lb >= best[0]:
            return

        prev=seen.get(uncovered)
        if prev is not None and prev <= len(chosen):
            return
        seen[uncovered]=len(chosen)

        # Baseline: finish with arbitrary light lines.
        light_cost=(rem+1)//2
        if len(chosen)+light_cost < best[0]:
            best[0]=len(chosen)+light_cost
            best_sel[0]=chosen[:]

        # Pick an uncovered point with fewest productive heavy options.
        upts=[]
        mm=uncovered
        while mm:
            lsb=mm & -mm
            p=lsb.bit_length()-1
            opts=[]
            for li in inc[p]:
                c=popcount(heavy[li][1] & uncovered)
                if c>=3:
                    opts.append(( -c, li))
            upts.append((len(opts), p, opts))
            mm -= lsb
        upts.sort(key=lambda t:(t[0],t[1]))
        _, p, opts = upts[0]

        # If no productive heavy line through p, we don't need to branch on a light line explicitly;
        # baseline pairing handles it. Instead branch on any productive heavy line elsewhere.
        if not opts:
            best_global=[]
            for li,(k,m) in enumerate(heavy):
                c=popcount(m & uncovered)
                if c>=3:
                    best_global.append((-c,li))
            opts=best_global
            if not opts:
                return

        opts.sort()
        for negc,li in opts:
            m=heavy[li][1] & uncovered
            c=-negc
            if c<3:
                continue
            dfs(uncovered & ~m, chosen+[li])

    dfs(full,[])
    return best[0], heavy, best_sel[0]


def main():
    maxn=int(sys.argv[1]) if len(sys.argv)>1 else 30
    ps=primes_first(maxn)
    pts=[ulam_coordinate(p) for p in ps]
    print('N,prime,exact_lines')
    vals=[]
    for n in range(1,maxn+1):
        v,heavy,sel=exact_min_cover(pts[:n])
        vals.append(v)
        print('%d,%d,%d' % (n, ps[n-1], v))
    print('\nsequence=' + ','.join(str(v) for v in vals))
    print('awkward=' + ','.join(str(ps[i]) for i in range(1,maxn) if vals[i]>vals[i-1]))

if __name__=='__main__':
    main()
