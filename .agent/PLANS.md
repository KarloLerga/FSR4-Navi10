# ExecPlan contract

For this repository, create `.agent/EXEC_PLAN.md` before major implementation and keep it current. The plan is working state, not a substitute for implementation.

The ExecPlan must contain:
1. Current objective.
2. Concrete milestones with files/modules affected.
3. Validation command for each milestone.
4. Current blockers and how they will be resolved.
5. Architectural decisions already fixed by `docs/DECISIONS.md` (do not reopen them without evidence).
6. A decision log for new choices.
7. A progress checklist with timestamps or commits.
8. Measured results where available.

Rules:
- Continue working after updating the plan.
- Stop-and-fix: do not move past a milestone when its build/correctness gate fails unless the later milestone is required to unblock it; document that dependency.
- When a hypothesis fails, record it and revert/disable the losing change rather than accumulating dead optimization code.
- The final ExecPlan should read as a truthful record of what was implemented and validated.
