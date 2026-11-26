# Owner's answers to the milestone 2 review (2026-11-25)

The owner's words: "go with your recommendations on all of them" (on the seven questions of
[2026-11-25-milestone2.md](2026-11-25-milestone2.md), as put to the owner in the session's report).

| # | Question | Answer | Where it is recorded |
|---|---|---|---|
| 1 | Apply the director's patch? | Yes, as written | The patch applied; this commit |
| 2 | May counted luck controls run on a reference engine with a parity test? | No: NautilusTrader only | AGENTS.md "Running many simulations", rule 6 |
| 3 | Does milestone 3 start with the multi-asset Nautilus runner and its parity test? | Yes | AGENTS.md "Milestones", row 3 |
| 4 | May the lab read 0x price quotes and a public Base RPC to measure costs? | Yes, read only; the 0x key in the environment's secure store, never in code or chat | AGENTS.md "Data" |
| 5 | A `lab-engineer` role for the engines? | Yes | AGENTS.md "Desk roles"; `.claude/agents/lab-engineer.md` |
| 6 | Keep `BacktestEngine` rather than `BacktestNode`? | Yes | AGENTS.md "What's left to build" item 1 and "Running many simulations" rule 1 |
| 7 | The app's rules service: Python on the lab's decision code, or a TypeScript port? | Python, importing the lab's published decision functions | `docs/app/repos.md` "Languages"; `docs/app/technical.md` "Strategy settings" |

Also added on the director's question 7 (AGENTS.md section for self-directed tool studies): yes, AGENTS.md
"Self-directed tool studies".

Still open from the director's report: how far apart neighbouring drawdown budgets must be (risk-officer proposal,
question 3), and the other open questions of `reports/risk-officer/2026-11-25-new-risk-levels.md`.
