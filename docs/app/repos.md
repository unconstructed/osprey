# Repositories

*Started 2026-11-23. The owner agreed to the three-repo layout on 2026-11-23 and asked for it to be written down. The items under "Open" are not decided yet.*

The product is split across **three repositories**, with an optional fourth later. The split follows who may change what: research code, customer-facing code and production infrastructure each get their own review rules and credentials.

| # | Repo | Holds | Changed by | Status |
|---|---|---|---|---|
| 1 | `unconstructed/osprey` (this repo, the Strategy Lab) | Data, research, backtests, validation, strategy code, approved exports | Research agents; the owner approves exports | Exists |
| 2 | `osprey-platform` (monorepo) | Mobile app, admin dashboard, every backend service, the production Nautilus node, shared types | Build agents; money-path folders need the owner's review | To create |
| 3 | `osprey-infra` | Infrastructure as code for the dev, staging and production AWS accounts | Infra changes through reviewed pull requests; applying to production needs the owner | To create |
| 4 | `osprey-web` (later) | Marketing site, and web checkout if it is added ([README: Open questions](README.md#open-questions)) | Build agents | Not needed yet |

## Why separate repos

- **The lab's rules forbid production code.** [AGENTS.md](../../AGENTS.md) says the lab never touches user wallets, the app backend or production infrastructure, and nothing in it sends orders (hard rule 2). Every lab agent reads those rules, so backend or wallet code in this repo would contradict them.
- **Different review gates.** The lab is a research sandbox where agents commit often. The trade router, risk engine and auto-trading permission are money paths that the owner personally reads before launch ([Technical: Agent team rules](technical.md#agent-team-rules)). Separate repos give them separate branch protection and reviewers.
- **Secrets and blast radius.** The platform needs Privy keys, RPC endpoints and AWS credentials. The lab needs none of them and may reach only its data sources. Only `osprey-infra`'s pipeline holds credentials that can change production AWS.
- **Different stacks and pipelines.** The lab is Python 3.13 with uv and a long test tier. The platform is TypeScript, React Native/Expo builds and service deploys. The infrastructure is Terraform or CDK plans and applies.

## 1. `osprey` — the Strategy Lab

Unchanged: everything in [AGENTS.md](../../AGENTS.md). What it hands to production:

- **A tagged commit** of the approved strategy code.
- **The export** `exports/<name>/config.yaml`: each setting's default and allowed values, the risk level and its limits, the backtested drawdowns, the code commit, the data snapshot ID and the model version, if any ([AGENTS.md: Ready for production](../../AGENTS.md#validation-gates)).
- **Model artifacts** for strategies that use a model (`lab/models/artifact.py`, SHA-256 checked on load).

## 2. `osprey-platform` — the monorepo

Everything a customer or an operator touches. Proposed layout:

```
osprey-platform/
├── apps/
│   ├── mobile/            # React Native + Expo (iOS and Android)
│   └── admin/             # admin dashboard: user lookup, strategy health, halt, bulk revoke, kill switch
├── services/
│   ├── api/               # app API; verifies Privy tokens
│   ├── trade-router/      # signal fan-out, per-user sizing, 0x swap builder, SQS consumers   [owner review]
│   ├── risk-engine/       # the four risk layers, fails closed                                [owner review]
│   ├── permissions/       # auto-trading permission: grant, expiry, revoke                     [owner review]
│   ├── chain-watcher/     # swap confirmation, balance reads, reconciliation
│   ├── ramps/             # Coinbase Onramp/Offramp and MoonPay sessions and webhooks
│   ├── notifications/     # push, in-app inbox, monthly statement email
│   ├── rules/             # customer rule records and the "hold this mix" daily check
│   └── engine/            # production NautilusTrader nodes (Python): one node per strategy
├── packages/
│   └── shared/            # signal schema, API types, rule-record format, risk-level config reader
├── CODEOWNERS             # owner required on the [owner review] folders and packages/shared/signal
└── AGENTS.md              # the platform agents' rules (from Technical: Agent team rules)
```

Component descriptions are in [Technical: Components](technical.md#components).

**Why one repo for the app and the backend:** the signal, the API and the rule-record format are defined once in `packages/shared`; a change that touches the API and a screen ships as one reviewed commit; one agent team keeps one CI and one set of rules.

**Languages:** TypeScript for the app and the services (one language end to end, with the Privy, 0x and viem SDKs for Base). Python only in `services/engine`, because Nautilus strategies are Python.

**Money-path protection:** `CODEOWNERS` requires the owner's approval on `services/trade-router`, `services/risk-engine`, `services/permissions` and the signal schema. A different agent reviews those folders than the one that wrote them, and every money path carries the tests listed in [Technical: Agent team rules](technical.md#agent-team-rules).

## 3. `osprey-infra` — infrastructure as code

- Terraform or AWS CDK ([Technical: Infrastructure as code](technical.md#infrastructure-as-code)) for the three AWS accounts in [Technical: Environments](technical.md#environments): dev (Base Sepolia), staging (testnet, mirrors production) and production (Base mainnet).
- Phase 1 resources from [Technical: Phase 1](technical.md#phase-1-launch): ECS Fargate, RDS Postgres Multi-AZ, Redis, SQS with dead-letter queues, KMS, S3 with Object Lock, CloudTrail, least-privilege IAM per service.
- Every pull request runs a plan. Applying to dev and staging runs on merge; applying to production needs the owner. Only this repo's pipeline holds credentials that can change production.
- No agent changes production infrastructure without owner approval ([Technical: Agent team rules](technical.md#agent-team-rules)). Anything that costs money is approved by the owner first.

## How a strategy gets from the lab to production

The production node must run exactly the code that was audited.

1. The lab tags the approved commit and writes the export (owner approves; `risk-officer` writes `exports/<name>/config.yaml`).
2. The lab's strategy code is published as a **versioned Python package** built from that tag. It holds only `strategies/` and the parts of `lab/` that a strategy imports at run time (for example `lab/models/online.py`), never research or validation code.
3. `osprey-platform/services/engine` pins that package version, the export file and any model artifact (by SHA-256). It refuses to start a strategy whose export, commit or model hash does not match.
4. The engine sends signals to the trade router in the schema from `packages/shared` ([Technical: The signal](technical.md#the-signal)). No strategy code is copied between repos.

## Order of work

Each repo follows the roadmap in [README: Roadmap](README.md#roadmap); creating a repo does not change that order.

| Repo | First work |
|---|---|
| `osprey` | Finish TESTING.md 5.4, then milestone 2 (cost models and the Nautilus runner) |
| `osprey-platform` | Testnet-only alpha: Privy login and wallet on Base Sepolia (roadmap step 3), app skeleton, "hold this mix" screen, stubbed signals. No real money, no AWS spend |
| `osprey-infra` | Roadmap step 4, only after the owner approves AWS spend |

## Open

- [ ] Repo names (`osprey-platform` and `osprey-infra` are working names)
- [ ] Terraform or AWS CDK
- [ ] Where the lab's strategy package is published (a private package registry, or a git dependency pinned to the tag)
- [ ] Whether the lab's AGENTS.md gains a step for publishing that package (an AGENTS.md change, the owner's to approve)
- [ ] Monorepo tooling for `osprey-platform` (for example pnpm workspaces with Turborepo)
