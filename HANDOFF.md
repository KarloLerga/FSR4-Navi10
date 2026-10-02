# Handoff — what the user should do

This folder itself is the seed repository. Do not create another project around it.

1. Extract to a short Windows path, recommended `C:\Dev\FSR4-Navi10`.
2. Open that exact folder in VS Code.
3. Start **local** Codex for that workspace and choose the strongest/highest reasoning mode available.
4. Give it workspace write access, terminal access and internet access.
5. Open `CODEX_START_PROMPT.txt`, copy all of it into Codex, and send once.
6. Let Codex continue autonomously. Only intervene for unavoidable Windows UAC/elevation, authentication/licensing, or a reboot.

The Codex run should treat the repository files as durable memory. It must not ask the user to paste the whole specification again. If context is compacted, it re-reads `AGENTS.md`, `docs/MASTER_SPEC.md`, `.agent/EXEC_PLAN.md`, `PROGRESS.md`, `DECISIONS_LOG.md`, and `RESULTS.md`.

The seed repository intentionally does **not** contain AMD model/source assets or prebuilt proprietary FSR DLLs. `scripts/bootstrap.ps1` and `scripts/fetch-upstreams.ps1` acquire the required legal/public inputs on the user's machine and pin hashes/provenance.

The run is successful only when `docs/ACCEPTANCE_CRITERIA.md` is met and the local RX 5700 XT has measured results in `RESULTS.md`. A build-only scaffold is not completion.
