# Phase 1 Setup: Who Does What, in Order

[← Hub](README.md) · [AWS setup](aws-setup.md) · [Technical: Hosting](technical.md#hosting) · [Database](database.md)

The hosting plan is in [Technical: Hosting](technical.md#hosting). This page turns it into a to-do list. **[AWS setup](aws-setup.md)** has the full build behind it: every AWS piece, the guardrails, security alarms, network, backups and costs.

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
| 0.1 | **Register the company**, if it isn't already (an LLC is the usual choice; ask an accountant which fits), and get its **EIN** (tax ID) | State filing | Everything below is in the company's name |
| 0.2 | **Get a D-U-N-S number** for the company (free from Dun & Bradstreet) | Can take days to weeks | Apple and Google require it for organization developer accounts |
| 0.3 | **Apple Developer Program, as an organization** | Apple verifies the company | TestFlight, App Store |
| 0.4 | **Google Play Console, as an organization** | Google verifies the company | Play internal testing, Play Store |
| 0.5 | **Apply to the ramp partners:** Coinbase Developer Platform (Onramp and Offramp) and MoonPay | Business verification (KYB) and review | Add cash and Cash out |
| 0.6 | **Buy the domain** (for example osprey + a domain you like) | Quick, but DNS takes time to settle | API address, website, email |
| 0.7 | **Company email on the domain** (Google Workspace or Microsoft 365) | Quick once the domain works | Every AWS account needs its own address; AWS Activate and the ramp partners want a company email |
| 0.8 | **Two hardware security keys** (for example YubiKeys) | Shipping | Locking the AWS root login, and your other money accounts |

---

## Step 1: Your part for the dev environment (about 2–3 hours)

Do these in order. Use a company email address for every account, and turn on two-factor login (MFA) everywhere. Full detail for the AWS steps: [AWS setup, Part 1](aws-setup.md#part-1-your-part-about-an-hour-once).

| # | Task | Notes |
|---|---|---|
| 1.0 | **Answer the AWS decisions**, or tell the agents "use the defaults" | Region, Terraform, archive retention, recovery targets, budget amounts: [AWS setup: Decisions](aws-setup.md#decisions-for-you) |
| 1.1 | **Create the AWS account and choose the Paid plan at sign-up** | This becomes the "management" account: billing and logins only, nothing runs in it. Choosing Paid keeps the $100–200 sign-up credits; starting on Free and then turning on Organizations wipes them. Lock root with both hardware keys, then stop using it |
| 1.2 | **Fill in the account basics** | Company name, address and EIN; company card; billing, operations and security contacts; billing access for your daily login; Cost Explorer; a starter budget alert |
| 1.3 | **Apply for AWS Activate (Founders tier)** | $1,000 in credits for self-funded startups |
| 1.4 | **Turn on AWS Organizations and IAM Identity Center**, and create your own Identity Center user with a passkey or security key | Your daily login, never root |
| 1.5 | **Launch the bootstrap stack** the agent gives you (one click), then **approve its first pull request** | The bootstrap creates the GitHub deploy role (short-lived access through OIDC; no permanent keys anywhere). The pull request creates the security, log archive and dev accounts, the guardrails, logins and budget alerts |
| 1.6 | **Privy:** create an account and a **dev app** | Gives the app ID and secret; turn on smart wallets and testnet gas sponsorship |
| 1.7 | **RPC provider** (for example Alchemy): create an account and keys for **Base Sepolia** | How the backend reads and writes on the blockchain |
| 1.8 | **0x:** create an account and an API key | Swap quotes |
| 1.9 | **Expo:** create the organization account | Mobile builds and push notifications |
| 1.10 | **Paste every secret into AWS Secrets Manager** (dev account) | The agent creates empty, named slots; you fill them in. **Never paste keys into chat, code or GitHub** |

---

## Step 2: The agents build the dev environment

Hand this section to the coding agent as its work order, together with [AWS setup](aws-setup.md) Parts 2–12, which say exactly how each piece is set up. Everything is defined in Terraform and deployed through GitHub Actions, never by clicking in the AWS console. The agents themselves get no AWS access.

**Build, in this order:**
0. **Accounts, guardrails and security alarms:** the security, log archive and dev accounts; organization guardrails; Identity Center permissions; the organization audit trail, GuardDuty, Security Hub, Config and Access Analyzer; budget alerts ([AWS setup, Parts 2–4](aws-setup.md#part-2-guardrails-across-every-account))
1. **Network:** a private network (VPC) across two zones with private subnets; regional NAT gateway; outbound DNS allowlist; databases never reachable from the internet ([Part 5](aws-setup.md#part-5-network))
2. **Container registry and ECS cluster**, with a placeholder service for each Phase 1 component:
   - App API
   - trade router, rules service and chain watcher
   - workers
   - market data service and live price gateway
   - one Nautilus strategy node
3. **Postgres (RDS):** single-AZ and small for dev. Then run [schema.sql](schema.sql) as migration 0001, set up `pg_partman`, and run [schema_checks.sql](schema_checks.sql) on a scratch copy
4. **Valkey (ElastiCache, the Redis-compatible engine)**, **SQS queues with dead-letter queues**, **KMS keys** (data, secrets, auto-trading), **Secrets Manager slots** (empty; the owner fills them)
5. **S3 buckets:** files, logs, Terraform state, and one with **Object Lock** for ledger and audit archives
6. **Front door:** DNS, TLS certificates, load balancer and WAF for the dev API address; SES domain set up for email
7. **CloudFront** for chart caching and the marketing site
8. **Monitoring:** CloudWatch dashboards, outside health checks, and alarms (failed swaps, queue backlog, price feed down, reconciliation mismatch, spend, security findings), sent to the owner's phone and email
9. **Pipeline:** GitHub Actions plans on every pull request and deploys to dev automatically on every merge; nightly drift check

**Keep dev cheap:**
- the smallest instance sizes
- single-AZ databases
- the fewest always-on services possible
- note anything with a fixed monthly cost (for example NAT gateways) in the handoff

**Done when:**
- [ ] Guardrails proven: turning off CloudTrail or creating an IAM user in dev fails
- [ ] Security Hub reviewed; no high or critical findings open
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
- [ ] Approve the pull request that creates the **staging**, **production** and **backup** accounts
- [ ] Confirm the **audit archive retention** before production's archive is locked (it can't be shortened later)
- [ ] Turn on **Business Support+** for the production account
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
- [ ] The auto-trading signing key goes in KMS, usable only by the trade router; a call from any other role fails and alarms
- [ ] Production network locks: private links to KMS and Secrets Manager; providers' IP allowlists set to our NAT addresses
- [ ] Backups copied to the backup account's locked vault and a second region; restore from the copy tested
- [ ] Production limits raised (Fargate capacity, addresses, email sending) well before the beta
- [ ] Break-glass role tested once; its alarm reached you
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
- [ ] 0.7 Company email
- [ ] 0.8 Two hardware security keys
- [ ] 1.0 AWS decisions answered (or "use the defaults")
- [ ] 1.1 AWS account on the Paid plan; root locked with both keys
- [ ] 1.2 Account basics: company details, contacts, billing access, starter budget alert
- [ ] 1.3 AWS Activate application
- [ ] 1.4 Organizations and your Identity Center login
- [ ] 1.5 Bootstrap stack launched; first pull request approved
- [ ] 1.6 Privy dev app
- [ ] 1.7 RPC provider, Base Sepolia keys
- [ ] 1.8 0x API key
- [ ] 1.9 Expo account
- [ ] 1.10 Secrets pasted into Secrets Manager
- [ ] Step 2 handed to the agent; review its handoff
- [ ] Step 3 when the app works on testnet
