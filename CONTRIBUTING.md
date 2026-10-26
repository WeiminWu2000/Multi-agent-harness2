# Contributing

Use the single `mah2.cli` entry point and canonical configuration. Add a separate setting only when it represents a scientific condition that needs its own reporting; avoid parallel copies of the optimizer.

For changes, explain the problem, changed behavior, and validation. Run the regression suite and release audit described in README. New tests should cover a meaningful failure or contract, such as preserving scope ownership, preventing public-data leakage, retaining an incumbent, or accounting for paid calls.

Do not commit credentials, vendor checkouts, datasets, model outputs, or complete API traces. Keep historical measured results immutable. A change to model, prompts, input boundary, resource policy, or selection logic requires a new experimental label and fresh provenance. Preserve unsuccessful outcomes and distinguish interrupted runs from completed failures.

MASS-specific source must not be copied into this repository. Preserve all applicable attribution and notices when adding a dependency.
