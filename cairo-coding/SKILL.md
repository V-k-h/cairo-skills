---
name: cairo-coding
description: Use when writing, reviewing, or optimizing Cairo code — loops, modular arithmetic, integer splitting, limb assembly, modular reduction, storage slot packing, Poseidon hashing, felt252/u128/u256 conversions, and BoundedInt bounds. Every optimization is gated behind an explicit invariant set and a verification workflow; a rewrite ships only when equivalence is demonstrable, not merely plausible.
---

# Coding Cairo

Rules and patterns for writing efficient **and** safe Cairo. The goal is to reduce
gas/step cost **without changing observable behavior**. The skill's core claim is
simple: *an optimization you cannot prove equivalent is a bug you have not found
yet.* Treat every rewrite as guilty until proven equivalent.

For profiling, gas snapshots, and before/after measurements, use the Cairo
benchmarking skill — this skill is not a substitute for measurement.

---

## When to Use

Use when working on Cairo involving:

- Modular arithmetic; quotient/remainder; parity checks and halving
- Loop and array/span iteration optimization
- Limb splitting or assembly; byte decomposition; selector construction
- `felt252`, `u128`, `u256`, and bounded-integer conversions
- Storage packing
- Poseidon hashing
- `BoundedInt` arithmetic
- Cairo cleanup before commit or audit

**Do not use** as a replacement for benchmarking.

---

## Workflow — the optimization gate

Every rewrite passes through these gates **in order**. A failed gate is a STOP, not
a warning. Do not advance to the next gate until the current one is cleared.

```
G0 worth it? ─▶ G1 classify risk ─▶ G2 name invariants ─▶ G3 establish proof
                                                                  │
   G6 report ◀── G5 verify (fmt + test + bench) ◀── G4 minimal rewrite
```

**G0 — Is it worth it?** Confirm the code is on a hot path (runs often or dominates
steps/gas). Cold code is never worth a semantics risk. If you cannot point at the
hot path, STOP.

**G1 — Classify the risk tier.** Map the rewrite to exactly one tier (every rule in
this skill is tagged `[A]`, `[B]`, or `[C]`):

- **`[A]` Safe by construction** — produces identical values/behavior by the
  language's own rules (e.g. `DivRem::div_rem` vs separate `/` and `%`). No
  precondition, no proof. Still run `scarb fmt`.
- **`[B]` Safe under a named precondition** — equivalent *only if* a specific fact
  about the surrounding code holds (e.g. "the array is not reused", "the loop
  length is fixed"). You must state the precondition and verify it by reading the
  code.
- **`[C]` Proof required** — semantics may genuinely differ; the win is real but so
  is the risk (e.g. low-level Poseidon, `felt252` truncation, storage packing).
  Equivalence must be demonstrated with a test vector or differential/property test
  *before* the rewrite ships.

**G2 — Name the invariants touched.** Pull them from the *Invariant Set* below. If
you cannot name which invariant the rewrite touches, you do not yet understand the
rewrite. STOP.

**G3 — Establish the proof obligation.**
- `[A]`: none.
- `[B]`: state the precondition and confirm it by reading the actual surrounding
  code — never assume.
- `[C]`: write the equivalence proof first (see *Verification* below). The proof
  must exist and pass before the rewrite is applied.

**G4 — Apply the minimal rewrite.** Change the least code that captures the win.
Large rewrites smuggle in unrelated semantic drift.

**G5 — Verify.** Run `scarb fmt`. Run the test from G3. If you claimed a gas/step
win, measure it (benchmarking skill). A `[C]` rewrite with no passing equivalence
test is not done — revert it.

**G6 — Report** per *Agent Output Requirements*.

---

## The Invariant Set

These are the observable behaviors a rewrite must preserve. For each invariant:
*what breaks it*, *how to detect the risk*, and *how to prove it preserved*. Check
every invariant a rewrite could touch — not just the obvious one.

| Invariant | Breaks when | Detect by | Prove preserved by |
| --------- | ----------- | --------- | ------------------ |
| **Numeric result** | floor-division rounding, wrong modular shift, silent truncation, off-by-one quotient | compare outputs on edge inputs (`0`, `MAX`, `modulus ± 1`) | property/fuzz test of old vs new over the full domain + edge set |
| **Ownership / consumption** | `pop_front`/`multi_pop_front`/`slice`-then-mutate consumes data reused later | trace every later use of the array/span | rely on the move checker; ensure no read after consume |
| **Panic behavior** | `unwrap` added/removed, panic felt changed, `assert` dropped, range check elided | diff every panic site and its felt | `#[should_panic(expected: ...)]` on each path |
| **Overflow / underflow** | switching checked ↔ wrapping ↔ type-bounded arithmetic | identify the arithmetic mode of each op | test at type boundaries (`MAX`, `MAX+1`, `0-1`) |
| **Public API / ABI** | external signature, parameter type, or selector changes | diff external `fn` signatures and the interface trait | confirm ABI unchanged, or that the change is explicitly intended |
| **Storage layout** | packing, field reorder, slot-count change | diff the storage struct and any `StorePacking` impl | layout test + a migration for any deployed contract |
| **Domain separation** | hash domain tag/separator removed or altered | inspect hash construction inputs | test vector against the reference implementation |
| **Hash preimage format** | input order, padding, or length encoding changes | compare preimage assembly step by step | pinned test vector (known input → known output) |
| **Bounds checks** | a checked conversion is swapped for an unchecked/truncating one | identify which conversions are checked vs truncating | test that out-of-range input is still rejected |
| **Serialization (`Serde`)** | byte/felt layout of (de)serialization changes | diff `serialize`/`deserialize` | round-trip test + cross-version fixture |
| **Upgrade compatibility** | storage layout or selectors shift across versions | compare against the deployed layout | upgrade test starting from the prior layout |

**Default to unsafe.** If a rewrite is not *obviously* invariant-preserving, treat
it as `[C]` and produce a proof before applying.

---

## Verification — how to actually prove equivalence

The proof obligation from gate G3 is discharged with one of three techniques.
Match the technique to the invariant.

### Differential test (the default for `[C]` rewrites)

Keep the old implementation under a frozen name; run both over identical inputs and
assert equality. A bundled template lives at
[`scripts/equivalence_test_template.cairo`](scripts/equivalence_test_template.cairo)
— copy it, rename `old_impl`/`new_impl`, and supply your input set.

```cairo
// Prove new_impl == old_impl across a representative + edge input set.
#[test]
fn opt_preserves_result() {
    let inputs = array![0, 1, MODULUS - 1, MODULUS, MAX, /* representative */];
    for x in inputs {
        assert!(new_impl(x) == old_impl(x), "divergence at {}", x);
    }
}
```

### Property / fuzz test (for the numeric-result and overflow invariants)

Assert an algebraic property that pins the result, plus the boundary set. For
modular arithmetic, test against a `felt252`/`u256` reference computed the slow,
obviously-correct way.

```cairo
#[test]
fn add_mod_matches_reference() {
    // exhaustive for small domains; sampled + boundaries for large ones
    let q = 12289;
    for a in 0..q { for b in 0..q {
        let reference = ((a + b) % q);          // slow, trusted
        assert!(add_mod(a, b) == reference);    // fast, under test
    }}
}
```

### Test vector (mandatory for hashing, domain separation, serialization)

Pin a known input → known output produced by the *reference* (the wrapper you are
replacing, or an external spec). The low-level rewrite must reproduce it bit for
bit. Never replace a Poseidon/`Serde` path without this.

```cairo
#[test]
fn poseidon_lowlevel_matches_wrapper() {
    let x = 0x123; let y = 0x456;
    let expected = poseidon_hash_span(array![x, y].span()); // reference
    assert!(lowlevel_hash(x, y) == expected);               // optimized
}
```

**Rule:** a `[C]` rewrite ships only with a passing test of the matching kind.
For protocol-critical code, the test must be committed alongside the change.

---

## Quick Reference

`[A]` safe by construction · `[B]` safe under a named precondition · `[C]` proof required

| #  | Risk | Pattern | Avoid | Prefer |
| -- | ---- | ------- | ----- | ------ |
| 1  | `[A]` | Quotient + remainder | `x / m` and `x % m` separately | `DivRem::div_rem(x, m)` |
| 2  | `[B]` | Loop condition | `while i < n` | `while i != n`, only when exact termination is proven |
| 3  | `[B]` | Powers of 2 | `2_u32.pow(k)` | `match` lookup table (range known) |
| 4  | `[B]` | Array iteration | `*data.at(i)` in index loop | `pop_front`/`for`/`multi_pop_front` when data isn't reused |
| 5  | `[B]` | Length in loop | `data.len()` every iteration | Cache `let n = data.len();` |
| 6  | `[B]` | Slicing | Manual extraction loop | `span.slice(start, length)` |
| 7  | `[A]` | Parity + halving | Bitwise `index & 1` plus `/ 2` | `DivRem::div_rem(index, 2)` |
| 8  | `[B]`/`[C]` | Integer width | `u256` for values `< 2^128` | `u128`/tighter (`[C]` if public API) |
| 9  | `[C]` | Storage layout | One slot per small field | `StorePacking` with migration proof |
| 10 | `[B]` | Limb arithmetic | Bitwise/raw arithmetic in hot path | `BoundedInt` helpers (bounds proven) |
| 11 | `[C]` | Poseidon 2-input hash | Generic span hash | Low-level permutation after test-vector equivalence |
| 12 | `[C]` | Bulk `felt252` conversion | `try_into().unwrap()` in hot path | `u128s_from_felt252` when truncation invariant is valid |

---

## Rules

### 1. `[A]` Use `DivRem::div_rem` when both quotient and remainder are needed

```cairo
// BAD
let q = x / m;
let r = x % m;

// GOOD
let (q, r) = DivRem::div_rem(x, m);
```

For parity plus halving:

```cairo
// BAD
let is_odd = (index & 1) == 1;
index = index / 2;

// GOOD
let (q, r) = DivRem::div_rem(index, 2);
if r == 1 { /* odd branch */ }
index = q;
```

### 2. `[B]` Use `while i != n` only when termination is guaranteed

Equality is cheaper than comparison, but `!=` can loop forever. **Precondition:**
`i` starts known (usually `0`), `n` is fixed, `i` increments by exactly `1`, and
`i` cannot skip `n`. Touches the *numeric-result* invariant (via termination).

```cairo
// BAD if used blindly
while i < n { ...; i += 1; }

// GOOD only when the precondition holds
while i != n { ...; i += 1; }
```

Do not rewrite loops with variable steps, decreasing counters, mutation of `n`,
early jumps, or uncertain bounds.

### 3. `[B]` Avoid `pow()` for small constant powers of 2

**Precondition:** exponent range is small and known; the panic for out-of-range is
preserved (panic-behavior invariant).

```cairo
// BAD
let p = 2_u32.pow(depth.into());

// GOOD
fn pow2(n: u32) -> u32 {
    match n {
        0 => 1, 1 => 2, 2 => 4, 3 => 8, 4 => 16, 5 => 32,
        6 => 64, 7 => 128, 8 => 256, 9 => 512, 10 => 1024,
        _ => core::panic_with_felt252('pow2 out of range'),
    }
}
```

### 4. `[B]` Prefer pointer-style iteration over index loops

**Precondition:** the data is not reused after the loop (ownership invariant).

```cairo
// BAD
let mut i = 0;
let n = data.len();
while i != n { let val = *data.at(i); ...; i += 1; }

// GOOD when consuming the data is acceptable
while let Option::Some(val) = data.pop_front() { ... }

// GOOD
for val in data { ... }

// GOOD for batch processing
while let Option::Some(chunk) = data.multi_pop_front::<4>() { ... }
```

`pop_front` **consumes** the array/span. Do not use it if the original data must be
reused later.

### 5. `[B]` Cache `.len()` before loops

**Precondition:** the collection length does not change inside the loop.

```cairo
// BAD
let mut i = 0;
while i != data.len() { ...; i += 1; }

// GOOD
let mut i = 0;
let n = data.len();
while i != n { ...; i += 1; }
```

### 6. `[B]` Prefer `span.slice()` over manual extraction

**Precondition:** a view suffices; the code does not need an owned copy.

```cairo
// BAD
let mut result: Array<felt252> = array![];
let mut i = 0;
while i != length { result.append(*data.at(start + i)); i += 1; }

// GOOD
let result = data.slice(start, length);
```

### 7. `[B]`/`[C]` Use the smallest integer type that safely represents the value

`[B]` for internal helpers; `[C]` when it changes an external signature (public
API / ABI invariant — requires intent).

```cairo
// BAD
fn deposit(value: u256) { assert(value < MAX_U128, 'too large'); ... }

// GOOD
fn deposit(value: u128) { ... }
```

### 8. `[C]` Use `StorePacking` only with a layout/migration proof

Touches storage-layout and upgrade-compatibility invariants.

```cairo
use starknet::storage_access::StorePacking;

const POW_2_128: felt252 = 0x100000000000000000000000000000000;

struct MyStruct { amount: u128, fee_bps: u128 }

impl MyStorePacking of StorePacking<MyStruct, felt252> {
    fn pack(value: MyStruct) -> felt252 {
        value.amount.into() + value.fee_bps.into() * POW_2_128
    }
    fn unpack(value: felt252) -> MyStruct {
        let u256 { low, high } = value.into();
        MyStruct { amount: low, fee_bps: high.try_into().unwrap() }
    }
}
```

Do not introduce packing into a deployed layout without a handled migration.
Check: existing layout, upgrade safety, backward compat, field bounds, unpack
failure behavior.

### 9. `[C]` Do not replace Poseidon wrappers with low-level permutations without a test vector

`poseidon_hash_span([x, y])` may include padding, length encoding, or domain
separation. Replace with a lower-level permutation **only** after a test vector
proves equivalence (hash-preimage + domain-separation invariants).

```cairo
// Safe baseline
let h = poseidon_hash_span(array![x, y].span());

// May NOT be semantically identical — prove with a test vector first
let h = hades_permutation(x, y, 2);
```

Verify same: input order, padding, domain separation, length treatment, output
element. In protocol-critical code, commit the test vector with the change.

---

## BoundedInt Optimization `[B]`

`BoundedInt<MIN, MAX>` encodes value constraints in the type system and can remove
runtime overflow checks. Use for modular arithmetic, limb splitting/assembly, byte
decomposition, selector construction, and repeated hot-path arithmetic. Do not use
if conversion overhead dominates the saving. **Precondition: bounds are computed
correctly** (use the bundled calculator) — wrong bounds silently violate the
numeric-result invariant.

### Critical rule: avoid repeated downcasts

The biggest pitfall is converting between native ints and `BoundedInt` at every
boundary.

```cairo
// BAD: repeated downcasts
pub fn add_mod(a: u16, b: u16) -> u16 {
    let a: Zq = downcast(a).expect('overflow');
    let b: Zq = downcast(b).expect('overflow');
    let sum: ZqSum = add(a, b);
    let (_q, rem) = bounded_int_div_rem(sum, nz_q());
    upcast(rem)
}

// GOOD: BoundedInt throughout the hot path
pub fn add_mod(a: Zq, b: Zq) -> Zq {
    let sum: ZqSum = add(a, b);
    let (_q, rem) = bounded_int_div_rem(sum, nz_q());
    rem
}
```

Convert only at system boundaries: deserialization, calldata parsing, external API
entry points.

### Refactoring strategy

1. Identify the hot path.
2. Change internal arithmetic types to `BoundedInt`.
3. Propagate `BoundedInt` through helper signatures.
4. Avoid repeated `downcast`.
5. Convert back to native types only at boundaries.
6. Add a differential test proving the optimized version matches the original.

### Type conversion rules

| From                   | To                                       | Operation  | Cost                  |
| ---------------------- | ---------------------------------------- | ---------- | --------------------- |
| `u16`                  | `BoundedInt<0, 65535>`                   | `upcast`   | Cheap/free            |
| `u16`                  | `BoundedInt<0, 12288>`                   | `downcast` | Expensive range check |
| `BoundedInt<0, 12288>` | `u16`                                    | `upcast`   | Cheap/free            |
| `BoundedInt<A, B>`     | `BoundedInt<C, D>` where `[A,B] ⊆ [C,D]` | `upcast`   | Cheap/free            |
| `BoundedInt<A, B>`     | `BoundedInt<C, D>` where `[A,B] ⊄ [C,D]` | `downcast` | Expensive             |

Key rule: `upcast` works only when the target range is a **superset** of the
source. You cannot upcast `u32` to `BoundedInt<0, 150994944>` because `u32::MAX`
exceeds `150994944`.

### Required imports

```cairo
use corelib_imports::bounded_int::{
    BoundedInt, upcast, downcast, bounded_int_div_rem,
    AddHelper, MulHelper, DivRemHelper, UnitInt,
};
use corelib_imports::bounded_int::bounded_int::{ SubHelper, add, sub, mul };
```

```toml
[dependencies]
corelib_imports = "0.1.2"
```

Check the project version before copying imports — Cairo libraries evolve.

### Template: modular addition (mod 100)

```cairo
type Val = BoundedInt<0, 99>;
type ValSum = BoundedInt<0, 198>;
type ValConst = UnitInt<100>;

impl AddValImpl of AddHelper<Val, Val> { type Result = ValSum; }
impl DivRemValImpl of DivRemHelper<ValSum, ValConst> {
    type DivT = BoundedInt<0, 1>;
    type RemT = Val;
}

fn add_mod_100(a: Val, b: Val) -> Val {
    let sum: ValSum = add(a, b);
    let nz_100: NonZero<ValConst> = 100;
    let (_q, rem) = bounded_int_div_rem(sum, nz_100);
    rem
}
```

### Compute bounds with the bundled tool, not by hand

Use [`scripts/bounded_int_calc.py`](scripts/bounded_int_calc.py):

```bash
python3 scripts/bounded_int_calc.py add 0 12288 0 12288   # -> BoundedInt<0, 24576>
python3 scripts/bounded_int_calc.py sub 0 12288 0 12288   # -> BoundedInt<-12288, 12288>
python3 scripts/bounded_int_calc.py mul 0 12288 0 12288   # -> BoundedInt<0, 150994944>
python3 scripts/bounded_int_calc.py div 0 24576 12289 12289  # DivT<0,1>, RemT<0,12288>
```

Do not manually guess bounds in audit or production code.

### Bounds formulas

| Operation     | Bounds                       |
| ------------- | ---------------------------- |
| Add           | `[a_lo + b_lo, a_hi + b_hi]` |
| Sub           | `[a_lo - b_hi, a_hi - b_lo]` |
| Mul, unsigned | `[a_lo * b_lo, a_hi * b_hi]` |
| Div quotient  | `[a_lo / b_hi, a_hi / b_lo]` |
| Div remainder | `[0, b_hi - 1]`              |

For signed/mixed-sign multiplication, compute all four endpoint products and take
min/max — do not use the unsigned formula.

### Negative dividends: the SHIFT pattern

`bounded_int_div_rem` does not support negative lower bounds. When reducing a
possibly-negative value mod `Q`, add a multiple of `Q` first.

```cairo
// (a - b) mod Q
pub fn sub_mod(a: Zq, b: Zq) -> Zq {
    let a_plus_q: BoundedInt<12289, 24577> = add(a, Q_CONST);
    let diff: BoundedInt<1, 24577> = sub(a_plus_q, b);
    let (_q, rem) = bounded_int_div_rem(diff, nz_q());
    rem
}

// a - (b * c) mod Q
pub fn fused_sub_mul_mod(a: Zq, b: Zq, c: Zq) -> Zq {
    let prod: ZqProd = mul(b, c);
    // OFFSET = multiple of Q large enough to make the diff non-negative.
    let a_offset: BoundedInt<151007232, 151019520> = add(a, OFFSET_CONST);
    let diff: BoundedInt<12288, 151019520> = sub(a_offset, prod);
    let (_q, rem) = bounded_int_div_rem(diff, nz_q());
    rem
}
```

```text
SHIFT = ceil(abs(min_possible_value) / modulus) * modulus
```

The shift must be a multiple of the modulus so it preserves the value mod `Q`.

---

## felt252 → u128 / BoundedInt conversions `[C]`

`felt252` → `u128` can mean **checked conversion** or **low-limb extraction** —
different semantics. Choosing wrong violates the numeric-result and bounds-checks
invariants.

### Checked conversion — when the value must fit in `u128`

```cairo
let x_u128: u128 = x.try_into().unwrap();
```

Preserves `x < 2^128` but costs a range check and may panic. Use at boundaries or
when correctness requires rejecting wide values.

### Low-limb extraction — only when truncation is intended

```cairo
use corelib_imports::integer::{ U128sFromFelt252Result, u128s_from_felt252 };

fn felt252_low_u128(x: felt252) -> u128 {
    match u128s_from_felt252(x) {
        U128sFromFelt252Result::Narrow(low) => low,
        U128sFromFelt252Result::Wide((_high, low)) => low,
    }
}
```

Do not replace checked conversion with low-limb extraction unless truncation is
part of the algorithm or a prior invariant proves the high limb is zero.

### Bulk conversions

For generated/unrolled code with many conversions, prefer `u128s_from_felt252 +
upcast` **only when the precondition is valid**. Avoid `try_into().unwrap()` inside
large unrolled hot paths — panic paths cause Sierra bloat and repeated range
checks.

---

## Limb assembly and splitting `[B]`

Prefer `BoundedInt` helpers in hot paths; bounds must be proven first.

### Assembling limbs (four `u32` → one `u128`)

```cairo
// BAD: raw arithmetic in hot path
fn u32s_to_u128(d0: u32, d1: u32, d2: u32, d3: u32) -> u128 {
    d0.into() + d1.into() * POW_2_32 + d2.into() * POW_2_64 + d3.into() * POW_2_96
}

// GOOD: BoundedInt helpers after establishing proper bounds
fn u32s_to_u128(d0: u32, d1: u32, d2: u32, d3: u32) -> u128 {
    let d0_bi: u32_bi = upcast(d0);
    let d1_bi: u32_bi = upcast(d1);
    let d2_bi: u32_bi = upcast(d2);
    let d3_bi: u32_bi = upcast(d3);
    let r: u128_bi = add(
        add(add(d0_bi, mul(d1_bi, POW_32_UI)), mul(d2_bi, POW_64_UI)),
        mul(d3_bi, POW_96_UI),
    );
    upcast(r)
}
```

### Extracting bits

```cairo
let (qu1, bit0) = bounded_int_div_rem(u1, TWO_NZ);
let (qu2, bit1) = bounded_int_div_rem(u2, TWO_NZ);
let selector = add(bit0, mul(bit1, TWO_UI));
```

---

## Common Mistakes

- **Unsafe loop condition** — `while i < n` → `while i != n` when `i` is not
  guaranteed to hit `n` exactly.
- **Consuming data with `pop_front`** when the array/span must remain available.
- **Truncation for checked conversion** — `try_into().unwrap()` → `felt252_low_u128`
  without truncation intent or a proven-zero high limb.
- **Packing a deployed storage layout** without a migration.
- **Replacing a Poseidon wrapper** with a low-level permutation without a test vector.
- **Downcast at every call** — use bounded types throughout hot paths.
- **Wrong subtraction bounds** — correct is `[a_lo - b_hi, a_hi - b_lo]`, **not**
  `[a_lo - b_lo, a_hi - b_hi]`.
- **Negative dividend** in `bounded_int_div_rem` — shift by a multiple of the
  modulus first.
- **Quotient off-by-one** — integer division floors: `24576 / 12289 = 1`, not `2`.
- **BoundedInt beyond supported bounds** — bounds are hard-capped at `2^128`;
  larger bounds can crash the Sierra specializer.

---

## Code Quality

Before finalizing Cairo code:

- Run `scarb fmt`.
- Keep repeated validation in helper functions; avoid duplicated
  validate-then-write logic.
- Pin Scarb and Starknet Foundry versions in `.tool-versions` (or project
  equivalent).
- Prefer project-local idioms over generic rewrites.
- Preserve public interfaces unless the change is explicitly intended.
- Add tests for optimized paths; include before/after gas or step measurements
  when possible.

---

## Agent Output Requirements

When applying this skill, report:

1. **Optimization** — what was changed.
2. **Risk tier** — `[A]`/`[B]`/`[C]`.
3. **Invariants** — which from the Invariant Set it touches, and why each is preserved.
4. **Precondition / proof** — the `[B]` precondition you verified, or the `[C]` test you wrote.
5. **Tests** — what covers the change.
6. **Measurement** — gas/step before/after, or "unmeasured".
7. **Skipped** — optimizations intentionally not applied because they were unsafe.

```text
Applied:
- [A] Replaced separate division/remainder with DivRem::div_rem.
- [B] Cached array length before loop.

Invariants:
- Numeric result: div_rem returns the same q and r as / and % (construction).
- Termination: loop length is read once and not mutated (verified in source).
- Ownership: array is not consumed or mutated inside the loop (verified).

Proof:
- [A] none required. [B] precondition confirmed by reading the loop body.

Skipped:
- [C] Did not replace `while i < n` with `while i != n` — `i` increments by a
  variable step, so exact termination is not guaranteed; no proof available.
```

---

## Review Checklist

- [ ] Each rewrite is tagged `[A]`/`[B]`/`[C]` and cleared its gate
- [ ] No semantic change from loop rewrites
- [ ] No accidental array/span consumption
- [ ] No unchecked truncation from `felt252`
- [ ] No storage layout break
- [ ] No Poseidon/domain-separation change without a test vector
- [ ] No repeated `downcast` in hot paths
- [ ] BoundedInt bounds computed via the bundled calculator
- [ ] Negative modular reductions use a valid shift
- [ ] Public APIs changed only intentionally
- [ ] Every `[C]` rewrite ships with a passing equivalence test (differential / property / vector)
- [ ] `scarb fmt` has been run
- [ ] Gas/step improvement is measured or clearly marked as unmeasured
