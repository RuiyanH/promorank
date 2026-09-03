# V2 frozen synthetic contracts

These files define the shared, synthetic-only boundary for delegated V2 slices.
The integrator owns this directory. Slice agents may read it but must not edit it.

`SHA256SUMS` records the exact accepted bytes. Any semantic or byte change requires
integrator review, a regenerated hash manifest, and confirmation that downstream
slices have not begun against the earlier contract.

The fixtures contain no raw H&M customer IDs, secrets, real customer mappings,
test/holdout outcomes, or product probability fields.
