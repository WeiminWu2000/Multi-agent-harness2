# Architecture

A harness contains seven role instruction strings and a coordination object. Contracts describe producer/consumer handoffs, shared fields, and versioned endpoint instructions. The role editor cannot change coordination. The coordination editor cannot change roles and can revise at most one route/contract. The composer may use base coordination or the exact tested coordination proposal.

Each outer round performs:

1. Reference execution of the current harness.
2. A role proposal and a coordination proposal, followed by separate executions.
3. Evidence-based composition and execution of the successor.
4. Public comparison of runnable candidates, including the archive.
5. Commitment of the selected program and its generating harness, then reflection.

`run_recursive` carries the selected harness, generic lessons, and runnable candidates across three rounds. If fresh work fails, prior runnable programs remain eligible. A replacement of a prior incumbent requires a recorded executed comparison supporting improvement. Invalid proposals and decisions remain visible; a fallback is not evidence that a revision helped.

All solver/editor/reflection calls use one gateway allowance per task. The GLM coordinator has a four-call limit per round. Codex uses separate account capacity and reports its usage separately; its cost is not zero merely because it is absent from the GLM ledger.

The runtime mounts only the specified public inputs and the scientific environment into the program sandbox. Public tools do not receive official graders, gold outputs, model credentials, or the host repository. Credentials stay in the host gateway; the MASS runtime receives a temporary gateway token, not the provider credential. The final program is committed before an external evaluator is invoked.

The public CLI produces `packet.json`, `config.json`, input/source hashes, API accounting, candidate traces, `commit.json`, and `result.json`. Its result explicitly says `evaluation: not_run`: replay success is not official scientific success. Scientific scoring is a separate host-side step.

The measured system is task-local. It does not train language models, rewrite the optimizer itself, add arbitrary roles, or transfer an experience library across benchmark tasks. Scientific predictor fitting is permitted when the task requires it.
