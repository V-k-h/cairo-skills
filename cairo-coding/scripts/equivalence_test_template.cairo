// Equivalence-test template for the `cairo-coding` skill.
//
// Purpose: discharge the gate-G3 proof obligation for a `[C]` (proof-required)
// optimization by showing the optimized implementation is observationally equal
// to the implementation it replaces.
//
// How to use:
//   1. Copy this file into your crate's `tests/` (or a `#[cfg(test)]` module).
//   2. Replace `old_impl` with the EXACT pre-optimization code, frozen and renamed.
//      Do not delete it until the differential test passes and is committed.
//   3. Point `new_impl` at the optimized code.
//   4. Fill INPUTS with a representative set PLUS every boundary value that
//      matters for the invariant you are protecting:
//        - numeric result:   0, 1, MODULUS - 1, MODULUS, MAX, MAX - 1
//        - overflow:          values straddling each type boundary
//        - limbs/packing:     all-zero limbs, all-max limbs, single-bit-set
//   5. For small domains, prefer the exhaustive variant below over a sample.
//
// A `[C]` rewrite is NOT done until the matching test here passes.

// ----- Replace these two with your real implementations -------------------

// The pre-optimization implementation, frozen. Trusted reference.
fn old_impl(x: felt252) -> felt252 {
    // ... original code ...
    x
}

// The optimized implementation under test.
fn new_impl(x: felt252) -> felt252 {
    // ... optimized code ...
    x
}

// --------------------------------------------------------------------------

#[cfg(test)]
mod equivalence {
    use super::{new_impl, old_impl};

    /// Differential test over an explicit input set (representative + edges).
    #[test]
    fn new_matches_old_on_input_set() {
        let inputs: Array<felt252> = array![
            0,
            1,
            // MODULUS - 1, MODULUS, MAX - 1, MAX, ...   // <-- add real edges
        ];
        let mut span = inputs.span();
        while let Option::Some(x) = span.pop_front() {
            assert!(new_impl(*x) == old_impl(*x), "divergence at input {}", *x);
        }
    }

    /// Exhaustive variant — use when the domain is small (e.g. mod q for small q).
    /// Delete if not applicable. Replace `Q` with your modulus / domain size.
    #[test]
    fn new_matches_old_exhaustive() {
        let q: u32 = 12289; // <-- domain size
        let mut a: u32 = 0;
        while a != q {
            // For binary ops, nest a second loop over `b` here.
            assert!(
                new_impl(a.into()) == old_impl(a.into()),
                "divergence at {}",
                a,
            );
            a += 1;
        }
    }
}
