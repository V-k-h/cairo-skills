#!/usr/bin/env python3
"""Compute Cairo BoundedInt result bounds for add / sub / mul / div.

The skill `cairo-coding` instructs the agent to use this tool instead of
guessing bounds by hand. Output bounds feed directly into BoundedInt type
declarations and AddHelper / SubHelper / MulHelper / DivRemHelper impls.

Usage:
    bounded_int_calc.py add <a_lo> <a_hi> <b_lo> <b_hi>
    bounded_int_calc.py sub <a_lo> <a_hi> <b_lo> <b_hi>
    bounded_int_calc.py mul <a_lo> <a_hi> <b_lo> <b_hi>
    bounded_int_calc.py div <a_lo> <a_hi> <b_lo> <b_hi>

Notes:
  * Multiplication handles signed / mixed-sign ranges by taking the min/max
    over all four endpoint products (the unsigned shortcut is wrong for
    mixed signs).
  * Division reports both the quotient bound and the remainder bound.
    Cairo's bounded_int_div_rem floors toward zero and requires a
    non-negative dividend (see the SHIFT pattern in the skill).
  * BoundedInt bounds are hard-capped at 2**128; results outside that range
    are flagged because they can crash the Sierra specializer.
"""

import sys

CAP = 1 << 128  # BoundedInt magnitude cap (2**128)


def _endpoints(a_lo, a_hi, b_lo, b_hi):
    return a_lo, a_hi, b_lo, b_hi


def bounds_add(a_lo, a_hi, b_lo, b_hi):
    return a_lo + b_lo, a_hi + b_hi


def bounds_sub(a_lo, a_hi, b_lo, b_hi):
    # [a_lo - b_hi, a_hi - b_lo]
    return a_lo - b_hi, a_hi - b_lo


def bounds_mul(a_lo, a_hi, b_lo, b_hi):
    products = [a_lo * b_lo, a_lo * b_hi, a_hi * b_lo, a_hi * b_hi]
    return min(products), max(products)


def bounds_div(a_lo, a_hi, b_lo, b_hi):
    if b_lo <= 0 <= b_hi:
        raise ValueError("divisor range includes 0; division is undefined")
    if a_lo < 0:
        raise ValueError(
            "negative dividend: bounded_int_div_rem requires a non-negative "
            "lower bound. Apply the SHIFT pattern first."
        )
    # quotient floors: [a_lo // b_hi, a_hi // b_lo]
    q_lo = a_lo // b_hi
    q_hi = a_hi // b_lo
    # remainder: [0, max_divisor_magnitude - 1]
    r_hi = max(abs(b_lo), abs(b_hi)) - 1
    return (q_lo, q_hi), (0, r_hi)


def _warn_cap(lo, hi):
    if abs(lo) >= CAP or abs(hi) >= CAP:
        print(
            "WARNING: bound magnitude >= 2**128. BoundedInt is hard-capped at "
            "2**128 and this may crash the Sierra specializer.",
            file=sys.stderr,
        )


def main(argv):
    if len(argv) != 6:
        print(__doc__)
        return 1

    op = argv[1].lower()
    try:
        a_lo, a_hi, b_lo, b_hi = (int(x) for x in argv[2:6])
    except ValueError:
        print("error: arguments must be integers\n", file=sys.stderr)
        print(__doc__)
        return 1

    if a_lo > a_hi or b_lo > b_hi:
        print("error: each range must have lo <= hi", file=sys.stderr)
        return 1

    if op == "add":
        lo, hi = bounds_add(a_lo, a_hi, b_lo, b_hi)
        _warn_cap(lo, hi)
        print(f"BoundedInt<{lo}, {hi}>")
    elif op == "sub":
        lo, hi = bounds_sub(a_lo, a_hi, b_lo, b_hi)
        _warn_cap(lo, hi)
        print(f"BoundedInt<{lo}, {hi}>")
    elif op == "mul":
        lo, hi = bounds_mul(a_lo, a_hi, b_lo, b_hi)
        _warn_cap(lo, hi)
        print(f"BoundedInt<{lo}, {hi}>")
    elif op == "div":
        (q_lo, q_hi), (r_lo, r_hi) = bounds_div(a_lo, a_hi, b_lo, b_hi)
        _warn_cap(q_lo, q_hi)
        print(f"DivT: BoundedInt<{q_lo}, {q_hi}>, RemT: BoundedInt<{r_lo}, {r_hi}>")
    else:
        print(f"error: unknown op {op!r} (use add|sub|mul|div)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
