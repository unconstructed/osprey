# Phase 1 Setup: Who Does What, in Order

[← Hub](README.md) · [Technical: Hosting](technical.md#hosting) · [Database](database.md)

The hosting plan is in [Technical: Hosting](technical.md#hosting). This page turns it into a to-do list.

## The short version

- **It's less than it looks.** Almost everything in the Phase 1 table is code the agents write. Your part is sign-ups, payments and approvals: things only a person can do.
- **You don't need it all now.** Build one **dev** environment first, on testnet with no real money. Staging and production come right before the closed beta (roadmap step 9).
- **Start the slow paperwork now.** A few sign-ups take days to weeks of verification. Start them early so they're ready when the app is.

| Who | Does what |
|---|---|
| **You** | Accounts, billing, identity checks, pasting secret keys into AWS, approving production changes |
| **Agents** | All infrastructure code (Terraform or CDK), deployments, the database migration, monitoring, tests |
| **Nobody yet** | Production, until the app works end to end on testnet |

---

## Step 0: Start the slow stuff now (you)

These run in the background, so start them today.

| # | Task | Why it's slow | Needed for |
|---|---|---|---|
| 0.1 | **Register the company**, if it isn't already (an LLC is the usual choice; ask an accountant which fits) | State filing | Everything below is in the company's name |
| 0.2 | **Get a D-U-N-S number** for the company (free from Dun & Bradstreet) | Can take days to weeks | Apple and Google require it for organization developer accounts |
| 0.3 | **Apple Developer Program, as an organization** | Apple verifies the company | TestFlight, App Store |
| 0.4 | **Google Play Console, as an organization** | Google verifies the company | Play internal testing, Play Store |
| 0.5 | **Apply to the ramp partners:** Coinbase Developer Platform (Onramp and Offramp) and MoonPay | Business verification (KYB) and review | Add cash and Cash out |
| 0.6 | **Buy the domain** (for example osprey + a domain you like) | Quick, but DNS takes time to settle | API address, website, email |

---

## Step 1: Your part for the dev environment (about 2 hours)

Do these in order. Use a company email address for every account, and turn on two-factor login (MFA) everywhere.

| # | Task | Notes |
|---|---|---|
| 1.1 | **Create the AWS account** | This becomes the "management" account: billing only, nothing runs in it. Turn on MFA for the root login, then lock the root login away |
| 1.2 | **Set a budget alert** | AWS Budgets → alert to your email and phone at an amount you pick for dev |
| 1.3 | **Turn on AWS Organizations** and create a **dev** account inside it | Staging and production accounts come later (step 3) |
| 1.4 | **Turn on IAM Identity Center** and create your own user with MFA | This is how you log in day to day, never as root |
| 1.5 | **Let the agents deploy:** in the dev account, create the GitHub deploy role (the agent writes the exact steps; you click through them) | GitHub Actions gets short-lived access through OIDC; no permanent keys exist anywhere |
| 1.6 | **Privy:** create an account and a **dev app** | Gives the app ID and secret; turn on smart wallets and testnet gas sponsorship |
| 1.7 | **RPC provider** (for example Alchemy): create an account and keys for **Base Sepolia** | How the backend reads and writes on the blockchain |
| 1.8 | **0x:** create an account and an API key | Swap quotes |
| 1.9 | **Expo:** create the organization account | Mobile builds and push notifications |
| 1.10 | **Paste every secret into AWS Secrets Manager** (dev account) | The agent creates empty, named slots; you fill them in. **Never paste keys into chat, code or GitHub** |

---

## Step 2: The agents build the dev environment

Hand this section to the coding agent as its work order. Everything is defined in code and deployed through GitHub Actions, never by clicking in the AWS console.

**Build, in this order:**
1. **Network:** a private network (VPC) with private subnets; databases never reachable from the internet
2. **Container registry and ECS cluster**, with a placeholder service for each Phase 1 component:
   - App API
   - trade router, rules service and chain watcher
   - workers
   - market data service and live price gateway
   - one Nautilus strategy node
3. **Postgres (RDS):** single-AZ and small for dev. Then run [schema.sql](schema.sql) as migration 0001, set up `pg_partman`, and run [schema_checks.sql](schema_checks.sql) on a scratch copy
4. **Redis (ElastiCache)**, **SQS queues with dead-letter queues**, **KMS keys**, **Secrets Manager slots** (empty; the owner fills them)
5. **S3 buckets:** one for files, and one with **Object Lock** for ledger and audit archives; **CloudTrail** on
6. **Front door:** load balancer, WAF, TLS certificate and DNS for the dev API address
7. **CloudFront** for chart caching and the marketing site
8. **Monitoring:** CloudWatch dashboards and alarms (failed swaps, queue backlog, price feed down, reconciliation mismatch, spend), sent to the owner's phone and email
9. **Pipeline:** GitHub Actions deploys to dev automatically on every merge

**Keep dev cheap:**
- the smallest instance sizes
- single-AZ databases
- the fewest always-on services possible
- note anything with a fixed monthly cost (for example NAT gateways) in the handoff

**Done when:**
- [ ] One command (or one merge) rebuilds dev from scratch
- [ ] The migration ran, and all schema spot checks pass
- [ ] A test container answers on the dev API address over HTTPS
- [ ] A test alarm reaches the owner's phone
- [ ] A database backup was actually restored into a scratch database
- [ ] Monthly cost estimate for dev, written in the handoff
- [ ] No access keys exist anywhere; secrets are only in Secrets Manager

---

## Step 3: Before the closed beta, staging and production

When the app works end to end on testnet (roadmap steps 5 to 8).

**You:**
- [ ] Create the **staging** and **production** accounts in AWS Organizations
- [ ] Create Privy **staging** and **production** apps
- [ ] Create RPC keys for **Base mainnet**
- [ ] Set up the ramp partners' production access (from step 0.5)
- [ ] Fund gas sponsorship
- [ ] Create the Apple push notification key and the Firebase project (Android push); the agent tells you exactly where to click
- [ ] Request **email sending** for statements (Amazon SES production access)
- [ ] Paste production secrets into the production account's Secrets Manager
- [ ] Book the **independent security review** of the trade router and auto-trading permission ([Technical: Security baseline](technical.md#security-baseline))

**Agents:**
- [ ] The same code deploys staging and production; production gets the Multi-AZ database and standby
- [ ] Production deploys need **your approval** in GitHub, every time
- [ ] The auto-trading signing key goes in KMS, usable only by the trade router
- [ ] Rehearse a restore and a key rotation; write the runbooks

---

## What you approve, always

From [Technical: Agent team rules](technical.md#agent-team-rules). Agents never change these without your OK:
- Anything in **production**
- Risk limits, coin lists, wallet policies, the auto-trading signing key
- Anything that **costs money**: new paid services, bigger machines, buying data

## Your checklist

- [ ] 0.1 Company registered
- [ ] 0.2 D-U-N-S number
- [ ] 0.3 Apple Developer (organization)
- [ ] 0.4 Google Play Console (organization)
- [ ] 0.5 Coinbase Developer Platform and MoonPay applications
- [ ] 0.6 Domain
- [ ] 1.1 AWS account, root MFA
- [ ] 1.2 Budget alert
- [ ] 1.3 AWS Organizations and the dev account
- [ ] 1.4 Your Identity Center login with MFA
- [ ] 1.5 GitHub deploy role (with the agent)
- [ ] 1.6 Privy dev app
- [ ] 1.7 RPC provider, Base Sepolia keys
- [ ] 1.8 0x API key
- [ ] 1.9 Expo account
- [ ] 1.10 Secrets pasted into Secrets Manager
- [ ] Step 2 handed to the agent; review its handoff
- [ ] Step 3 when the app works on testnet
