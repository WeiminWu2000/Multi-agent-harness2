"""Generic public-output policy; no benchmark answers or private conventions."""

PUBLIC_OUTPUT_CONTRACT = '''PUBLIC OUTPUT CONTRACT
First establish the requested scientific computation from the task and public
sources. Keep target construction, units, independent validation split and metric
fixed when comparing programs. Check numerical behavior, not just file existence.
For filtering or extraction, compute with normalized copies if necessary but
return original source values, identifiers and representations unless the task
explicitly requests transformation. Check both soundness (every returned item
qualifies) and completeness (every qualifying item is returned); an empty or tiny
subset is not a successful filter. Preserve multiplicity when the task requires it.
Preserve source target/identifier column names and library-produced schemas unless
the task specifies a different output schema. Check serialized columns separately
from an in-memory dataframe index. Do not guess hidden grader conventions.
For arrays, verify dimension meanings and units from public data and source code.

Selection must test the most consequential differences among ALL available
programs, including archived alternatives. A prior selection is not proof of
correctness. Prefer one executable comparison table over testing only an obviously
bad alternative. Inspect exact snapshot filenames first. When public scientific
checks tie, source-value preservation is an explicit harness policy for choosing
between equivalent filtering/extraction outputs. This is output fidelity, not a
claim of better scientific prediction. A replacement on that basis must use
comparison.basis="public_output_contract", direction="min", and measured counts
of changed source representations as incumbent_value/candidate_value; additionally
include source_paths (nonempty list of public relative paths), scientific_equivalence
(true only after an executed check), and equal positive incumbent_rows/candidate_rows.
Do not use this basis when scientific content differs or a transformation is requested.
Other replacements still require measured held-out-public-data improvement or an
explicit public task requirement. Retain uncertainty when neither is established.
'''
