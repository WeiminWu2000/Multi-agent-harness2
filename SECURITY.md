# Credentials and generated programs

Keep provider keys in environment variables or private files referenced by `OPENROUTER_API_KEY_FILE`. The CLI does not load `.env` automatically. Codex authentication remains local and is never bundled. If a real credential enters a commit, revoke it and remove it from history before publishing; deleting the current file alone is insufficient.

Run generated scientific code on an isolated Linux worker using bubblewrap and explicit CPU/memory limits. The runtime fails when bubblewrap is unavailable; do not add an automatic unsandboxed fallback. Kernel sandboxing is not a guarantee against every host vulnerability. Mount only the intended public files and a trusted scientific environment.

Do not put keys, gold targets, graders or unrelated private files in the public data directory. Full run logs and API traces remain private by default. When reporting a defect, provide a minimal synthetic reproduction and redact credentials and private data. This repository does not advertise an unconfigured private vulnerability-reporting address.
