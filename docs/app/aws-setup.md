# AWS Setup: The Full Build

[← Hub](README.md) · [Phase 1 setup](phase-1-setup.md) · [Technical: Hosting](technical.md#hosting) · [Database](database.md)

[Phase 1 setup](phase-1-setup.md) is the short to-do list. This page has everything behind it: every AWS piece, why it's there, who sets it up, and what it costs. The agents use it as their work order.

## The short version

- **There are 13 parts.** Accounts, guardrails, logins, security alarms, network, domain, front door, apps, data, backups, monitoring, the deploy pipeline, and limits. Skipping one is how money apps get broken into or lose data.
- **You click; the agents build.** Your part is about an hour of sign-ups and settings only the account owner can do ([Part 1](#part-1-your-part-about-an-hour-once)). Everything else is code the agents write and GitHub deploys. Nobody clicks around in the AWS console.
- **Dev first.** Dev runs on testnet with no real money. Staging and production use the same code and are built right before the closed beta.
- **Cost:** dev alone is about $200–250 a month, inside the original $100–300 target. Production, with a standby database and two copies of every service, is about $550–700 on its own. See [What it costs](#what-it-costs).

---

## Decisions for you

Each has a default. Tell the agents "go with the defaults" and they use them.

| Decision | Default | Why |
|---|---|---|
| AWS region | **us-east-2 (Ohio)** | Same prices as us-east-1 (Virginia), which is AWS's busiest region and where its biggest outages have hit. A few global pieces (CloudFront certificates, billing) live in us-east-1 regardless |
| Infrastructure code | **Terraform** | The most common choice; also manages non-AWS pieces (GitHub settings, DNS). AWS CDK is the AWS-only alternative |
| Account setup | **Plain AWS Organizations, written in Terraform** | AWS Control Tower automates the same thing, but adds cost and console-only steps. Revisit at the SOC 2 audit |
| How long the tamper-proof archive keeps files | **7 years** (confirm with your accountant) | Locked files can't be deleted early by anyone, you included. Set it once, carefully |
| Recovery targets | Lose at most **5 minutes** of data; back up within **1 hour** | Point-in-time restore gives the 5 minutes. Balances live on the blockchain, so the ledger can be rebuilt from it |
| Extra network locks in production | **Yes** (about $30–40 a month) | Private links to the key and secret services, plus an outbound allowlist ([Part 5](#part-5-network)) |
| Monthly budget alerts | Dev $300, staging $300, production $900 | Email and text at 50%, 80% and 100%, plus a forecast warning |

---

## The account map

Separate accounts mean a mistake or break-in in dev can't touch production, and the audit logs live where even someone with production access can't erase them. Accounts are free.

| Account | What it holds | Who gets in | When |
|---|---|---|---|
| **Management** | Billing, the organization, logins. Nothing runs here | You only | Now |
| **Security** | The security alarm services for every account | You | Now |
| **Log archive** | Every account's audit logs, locked so they can't be changed or deleted | Read-only, you | Now |
| **Dev** | Testnet, fake data | You; the GitHub deploy role | Now |
| **Staging** | Production's twin on testnet, for TestFlight and Play testing | You; the GitHub deploy role | Step 3 |
| **Production** | Real money | You; the GitHub deploy role, only after you approve | Step 3 |
| **Backup** | Locked copies of production backups | Nobody, except to restore | Step 3 |

Groups: **Security** (security, log archive, backup), **Non-production** (dev, staging), **Production**.

---

## Part 1: Your part (about an hour, once)

| # | Step | Notes |
|---|---|---|
| 1 | **Company email on your domain** (Google Workspace or Microsoft 365) | Every AWS account needs its own address. Use aliases: aws-management@, aws-security@, aws-logs@, aws-dev@, aws-staging@, aws-prod@, aws-backup@. AWS Activate also wants a company address |
| 2 | **Create the management account and choose the Paid plan at sign-up** | New accounts get $100–200 in credits. If you start on the Free plan and then turn on Organizations, the credits disappear on the spot. Choosing Paid at sign-up keeps them |
| 3 | **Lock the root login** | Two hardware security keys (or passkeys) as MFA, stored in two different places. Then stop using root |
| 4 | **Company details** | Legal name and address, tax ID (EIN) in Tax settings, the company card for payment |
| 5 | **Alternate contacts** | Billing, operations and security. AWS emails the security contact when it sees something wrong, so use an address you actually read |
| 6 | **Turn on billing access and Cost Explorer** | "IAM user and role access to billing information" lets your daily login see the bill. Add a starter budget alert while you're there |
| 7 | **Apply for AWS Activate (Founders tier)** | $1,000 in credits for self-funded startups, and some get up to $5,000. Needs the Paid plan, a company email and a website |
| 8 | **Turn on AWS Organizations and IAM Identity Center**, then create your own Identity Center user with a passkey or security key | This is your daily login. Root stays locked away |
| 9 | **Launch the bootstrap stack** the agent gives you (one link, one click, in the management account) | Creates the GitHub deploy role so GitHub Actions can build everything else. No access keys are created |
| 10 | **Approve the agent's first pull request** | It creates the security, log archive and dev accounts, the guardrails, logins and budget alerts. Each new account shows up in your access portal |

After that: paste secrets into the empty slots the agents create. **Never paste keys into chat, code or GitHub.**

---

## Part 2: Guardrails across every account

Organization-wide rules that nobody can override from inside an account, not even an admin:

- **Can't leave the organization**, and can't turn off the audit log, the security alarms or the settings recorder
- **Only our regions:** ours, plus us-east-1 for global pieces. Everything else is blocked
- **No root logins in member accounts:** centralized root access is turned on and root passwords are removed (accounts created through Organizations start without them)
- **No permanent passwords or access keys:** no IAM users. People log in through Identity Center; machines use short-lived roles
- **Nothing shared outside the organization:** resource control policies stop buckets, keys, secrets and queues from being opened to outside accounts, even by mistake
- **Production protection:** nobody can delete the database, its backups or the encryption keys, or turn off deletion protection, except a break-glass role that alerts you when used
- **Public buckets blocked** at the account level, everywhere
- **Required tags** (`env`, `component`) so the bill shows what costs what

---

## Part 3: Logins and access

| Who | How they get in | What they can do |
|---|---|---|
| **You** | Identity Center with your passkey | Admin (1-hour sessions), read-only, billing |
| **GitHub Actions** | Short-lived role per account through OIDC, locked to the `unconstructed/osprey` repo | A `plan` role (read-only) on every pull request. An `apply` role only from `main`; production also waits for your approval in GitHub |
| **Coding agents** | **No AWS access at all** | They write code; GitHub deploys it. Every infrastructure plan shows up on the pull request for review |
| **Each service** | Its own task role | Only what it needs. Only the trade router can sign with the auto-trading key; only the workers send email |
| **Emergencies** | A break-glass admin role in production | Every use alerts you |

No SSH and no jump servers. Getting into a running container (ECS Exec) or the database (Session Manager) is logged, and off by default in production.

---

## Part 4: Security alarms

All run across every account and report to the Security account.

| Service | What it does |
|---|---|
| **CloudTrail** (organization trail) | Records every action in every account to the log archive, locked with Object Lock, with tamper checks on the log files |
| **GuardDuty** | Watches for break-ins: stolen credentials, crypto-mining, odd network traffic, attacks on the database and containers (runtime monitoring on) |
| **Security Hub** | Checks every account against AWS's security best practices and the CIS benchmark, and lists what's wrong |
| **AWS Config** | Keeps a history of every setting so Security Hub can check it. Records only what's needed, to keep the cost down |
| **IAM Access Analyzer** | Flags anything reachable from outside the organization, and permissions nobody uses |
| **Inspector** | Scans container images for known security holes (staging and production) |

High and critical findings page you. Specific alarms also go to you for: a root login anywhere, any change to the guardrails, CloudTrail stopping, and **any use of the auto-trading key by anything other than the trade router**.

---

## Part 5: Network

Each environment gets its own private network (VPC), spread across two availability zones (separate data centers).

| Layer | What's in it | Reachable from the internet? |
|---|---|---|
| Public | Only the load balancer | Yes, HTTPS only |
| Private, apps | All the containers | No. They reach out through the NAT gateway |
| Private, data | Postgres and Valkey | No, and no way out either |

- **NAT gateway** (regional mode, no public subnet needed): lets containers call Privy, the RPC provider, 0x, the exchanges and Expo without being reachable themselves. Its fixed outbound addresses go on **each provider's IP allowlist** where offered, so a stolen API key doesn't work from anywhere else
- **Firewall rules** (security groups): the load balancer talks only to the API and the price gateway; only app containers reach the database and Valkey; outbound is HTTPS only
- **Outbound allowlist** (Route 53 Resolver DNS Firewall): containers can only look up approved addresses (Privy, our RPC provider, 0x, Coinbase, Kraken, MoonPay, Expo, Apple and Google push). A hacked container can't call an unknown server by name
- **Private links** (VPC endpoints): S3 traffic stays inside AWS (free). In production, KMS and Secrets Manager get private endpoints too, so the signing path never crosses the internet
- **Flow logs** in production: a record of network connections, for investigations
- **Separate address ranges** per environment (for example 10.10.0.0/16 dev, 10.20.0.0/16 staging, 10.30.0.0/16 production), so they can be connected later without renumbering

Phase 2: a full network firewall (AWS Network Firewall) for strict outbound control by IP, when its cost (hundreds of dollars a month) is worth it.

---

## Part 6: Domain, certificates and email

| Piece | Setup |
|---|---|
| **DNS** (Route 53) | The main domain lives in the production account; `dev.` and `staging.` subdomains are handed to their own accounts |
| **Certificate lock** (CAA record) | Only Amazon's certificate service may issue certificates for our domain |
| **Certificates** (ACM) | Free and auto-renewing; one set in our region for the load balancer, one in us-east-1 for CloudFront |
| **Email sending** (SES) | Domain verified with DKIM, SPF and DMARC so statements don't land in spam; bounces and complaints handled automatically; production sending access requested in step 3 |
| **Company email** | Stays with Google Workspace or Microsoft 365; its DNS records go in the same zone |

Login codes and passkey emails come from Privy, not SES.

---

## Part 7: Front door

| Piece | Setup |
|---|---|
| **Load balancer** (ALB) | HTTPS only with modern TLS; HTTP redirects to HTTPS; access logs on; deletion protection in production; long idle timeout plus pings so live price connections stay open |
| **WAF** | AWS managed rules (common attacks, known bad inputs, bad IP reputation); rate limits per IP, tighter on login, quotes and trades; request size limits; logs with auth headers removed |
| **CloudFront** | Caches public chart history and serves the marketing site from a private bucket. The agent may also put the API behind CloudFront so the load balancer has no public address at all |
| **DDoS protection** | Shield Standard is automatic and free. Shield Advanced costs thousands a month; only if we're ever targeted |

---

## Part 8: Apps

| Piece | Setup |
|---|---|
| **Container registry** (ECR) | One repository per service; image tags can't be overwritten; images scanned on push; old images cleaned up |
| **Images** | Built once per change and promoted unchanged from dev to staging to production. Run as a non-root user on a read-only file system. Built for Graviton (ARM) chips, about 20% cheaper on Fargate, if NautilusTrader and every library run on ARM; the agent checks, otherwise x86 |
| **ECS cluster** on Fargate | One per environment |
| **Services** | One per component, each with its own task role, health check and automatic rollback if a deploy fails. Two copies of each in production, in different zones |
| **Secrets in containers** | Pulled from Secrets Manager when the container starts; never in images, code or plain settings |
| **Strategy nodes** | **Never two copies at once.** Deploys stop the old node before starting the new one, so a signal can't go out twice. The database's unique trade key would catch a duplicate, but we don't lean on it |
| **Trade queue** | SQS FIFO with one message group per wallet (or an equivalent per-wallet lock in the trade router), so a wallet never has two swaps in flight at once; dead-letter queue for failures |
| **Scheduled jobs** | EventBridge Scheduler starts one-off tasks: reconciliation, statements, cleanup |
| **Scaling** | The API and price gateway scale on load; workers scale on queue depth in Phase 2 |

---

## Part 9: Data

### Postgres (RDS)

- PostgreSQL 16 or newer. The schema checks were run on 16; the agent re-runs them on the version it picks. An old major version later costs extra (RDS Extended Support), so upgrades get planned
- Dev: small and single-zone. Production: **Multi-AZ** with a standby; storage grows on its own up to a cap
- Encrypted with our own key; TLS required on every connection
- Point-in-time restore (14 days in production); deletion protection on
- AWS creates and rotates the master password in Secrets Manager. The app's roles (`osprey_api`, `osprey_worker`, `osprey_admin`) get their own rotated passwords or IAM login
- `pg_partman` for the price-history partitions, with `pg_cron` running its hourly upkeep (the way AWS documents it); `pg_stat_statements` to find slow queries
- Timeouts, so a stuck query or forgotten transaction can't hold locks forever
- Performance monitoring on; alarms on CPU, storage, connections and standby lag

### Valkey (ElastiCache)

- Valkey is the open-source continuation of Redis: same commands, about 20% cheaper on AWS. The agent confirms NautilusTrader runs on it in dev; if anything breaks, use the Redis engine instead
- Encrypted, password required, data subnet only; a replica in a second zone in production
- Daily snapshots, because Nautilus keeps its crash-recovery state here

### Queues (SQS)

Dead-letter queue on every queue; encrypted; long polling. Alarms when anything lands in a dead-letter queue or a message waits too long.

### Storage buckets (S3)

All private, encrypted and versioned.

| Bucket | Notes |
|---|---|
| App files | |
| **Audit archive** | Object Lock in **compliance mode**: nobody, including you and AWS support, can delete or change a file before its retention date. Dev uses the softer governance mode so tests can clean up |
| Logs | Load balancer, CloudFront and flow logs; moved to cheaper storage, then expired |
| Terraform state | One per account; uses S3's built-in state locking (the older DynamoDB lock table is deprecated) |
| Marketing site | Served only through CloudFront |

### Secrets Manager

One empty slot per key, which you fill: Privy app secret, RPC key, 0x key, Coinbase and MoonPay keys and their webhook secrets, Expo token, Apple push key, Firebase service account. Each slot is readable only by the services that need it, and rotated where the provider allows. Settings that aren't secret (URLs, feature switches) go in Parameter Store.

### Encryption keys (KMS), per environment

| Key | Used for |
|---|---|
| Data key | Database, buckets, queues, logs, backups |
| Secrets key | Secrets Manager |
| **Auto-trading key** | Signs the trade router's requests to Privy. A P-256 signing key created inside KMS that can never be exported. Only the trade router can use it, every use is logged, and any other caller sets off an alarm. The agent confirms in dev that Privy accepts KMS signatures |

---

## Part 10: Backups and recovery

- **AWS Backup** for production: daily database snapshots and file backups, copied to the **Backup account** into a locked vault nobody can empty early, plus a copy in a second region
- **Restore drills:** monthly in staging; before launch, a full "we lost the database" drill
- **Runbooks** (the agents write them, you keep a copy): restore the database, rotate secrets, rotate the auto-trading key, pause all auto-trading at once, a provider outage (Privy, RPC, 0x), a leaked key, a region outage
- **If the whole region goes down:** rebuild from code in the second region and restore the copied backups, within 24 hours. A warm standby region is a Phase 2 upgrade

---

## Part 11: Monitoring and alarms

- **Logs** (CloudWatch): every service, encrypted, kept 14 days in dev and 1 year in production. No secrets or personal data in logs; they're stripped where the log is written
- **Money metrics:** swaps succeeded and failed, signal-to-fill time, queue depth, price feed freshness, reconciliation mismatches, gas spent, Privy policy rejections
- **Outside checks** (CloudWatch Synthetics): every 5 minutes, test the API and the live price feed the way a user would
- **Alarms to you:** email and text through SNS (add Slack or an on-call app later). They cover everything in [Phase 1 setup, step 2](phase-1-setup.md#step-2-the-agents-build-the-dev-environment), plus server errors, crashing containers, database and Valkey limits, certificate expiry, budgets, security findings, and AWS problems in our region
- **Dashboards:** one for money, one for infrastructure
- **Tracing** (OpenTelemetry): follows one trade through every service. Add it when debugging needs it

---

## Part 12: Deploy pipeline

- **Rules on `main`:** pull request required, tests and checks must pass, no force pushes
- **Every pull request:** tests, `terraform plan` posted as a comment, security scans of the infrastructure code and the images
- **Merge to `main`:** deploys to dev, then staging, automatically
- **Production:** the same images and code; waits for **your approval** in GitHub
- **Database migrations** run as a one-off task before new code starts
- **Nightly drift check:** if anything in AWS differs from the code (someone clicked in the console), you get an alert
- **Dependency updates** arrive as pull requests (Dependabot or Renovate) and are tested like any change

---

## Part 13: Limits and support

- **Raise limits early.** New accounts start with low limits (Fargate capacity, public addresses, email sending). The agent requests production increases well before the beta; some take days
- **AWS Support:** the free Basic plan for dev and staging. Before public launch, **Business Support+** on the production account: from $29 a month or a share of the bill, whichever is greater. The older Business Support plan ends January 1, 2027
- **Partner paperwork:** AWS Artifact has AWS's own security reports (SOC 2, ISO) for partners' security questionnaires

---

## What it costs

US list prices, on demand, checked 2026-11-19. These are estimates; the agent re-prices with the AWS Pricing Calculator in its handoff.

### Dev: about $200–250 a month

| Item | Monthly |
|---|---|
| Containers: 8 small services on Graviton | ~$85 |
| NAT gateway (one zone) and its address | ~$37 |
| Load balancer and its addresses | ~$25 |
| Postgres, small, single-zone, with storage | ~$15–28 |
| Valkey, smallest node | ~$9 |
| WAF | ~$10 |
| Secrets, keys, DNS, queues, buckets, registry | ~$12 |
| Logs, alarms, security services | ~$20–30 |

### Production: about $550–700 a month

| Item | Monthly |
|---|---|
| Containers: two copies of each service | ~$200 |
| NAT gateway (two zones) and addresses | ~$75 |
| Load balancer | ~$30 |
| Postgres, Multi-AZ with standby, storage and backups | ~$115–125 |
| Valkey with a replica | ~$30 |
| WAF and CloudFront | ~$20 |
| Private links for KMS and Secrets Manager | ~$30 |
| Secrets, keys, DNS, queues, buckets, registry | ~$15 |
| Logs, alarms, outside checks, security services | ~$50 |
| Backup copies (Backup account, second region) | ~$10 |
| Business Support+ | from $29 |

Staging costs about what dev does while it's on. The shared accounts (management, security, log archive, backup) add about $15–30.

### Totals

| When | What's running | AWS per month |
|---|---|---|
| Now until the beta | Dev and the shared accounts | about $220–280: inside the original $100–300 target |
| Closed beta onward | Dev, staging part-time, production, shared | about $900–1,000 |

### Ways to cut it

- **Turn dev off at night and on weekends.** It rebuilds from code, so containers, the database and even the NAT gateway can go away when nobody's working: saves about $70–100
- **Staging on only during test weeks**
- **Commit once usage is steady:** a Compute Savings Plan for containers and reserved instances for the database and Valkey take roughly 20–30% off for a one-year commitment
- **Credits:** $100–200 from the sign-up credits plus $1,000 from Activate Founders cover the first several months of dev

**Not AWS (budget separately):** Privy, the RPC provider, gas sponsorship, Expo, the domain and company email.

---

## Done when

**Dev (step 2 of Phase 1 setup):**
- [ ] Management, security, log archive and dev accounts exist, built from code
- [ ] Guardrails proven: turning off CloudTrail or creating an IAM user in dev fails
- [ ] No root credentials in member accounts; no IAM users or access keys anywhere
- [ ] Security Hub reviewed; no high or critical findings open
- [ ] Everything in [Phase 1 setup, step 2](phase-1-setup.md#step-2-the-agents-build-the-dev-environment) "Done when"

**Staging and production (step 3):**
- [ ] Staging, production and backup accounts exist; production matches staging except for size
- [ ] Locked backup vault working; a restore from the copy tested
- [ ] Production limits raised; Business Support+ on
- [ ] Break-glass role used once on purpose, and its alarm reached you
- [ ] A signing call from any role but the trade router fails and sets off the alarm
- [ ] Audit archive in compliance mode with the retention you chose
- [ ] Independent security review booked

---

## Sources

- [AWS NAT Gateway now supports regional availability](https://aws.amazon.com/about-aws/whats-new/2025/11/aws-nat-gateway-regional-availability) and [VPC pricing](https://aws.amazon.com/vpc/pricing/)
- [AWS Free Tier FAQs](https://aws.amazon.com/free/faqs/) and [Free Tier terms](https://aws.amazon.com/free/terms) (credits and the Organizations upgrade)
- [Everything you need to know about AWS Activate credits](https://aws.amazon.com/aws-startups/learn/everything-you-need-to-know-about-aws-activate-credits/)
- [Centralize root access for member accounts](https://docs.aws.amazon.com/en_us/IAM/latest/UserGuide/id_root-enable-root-access.html)
- [Terraform S3 backend](https://developer.hashicorp.com/terraform/language/v1.15.x/backend/s3) (S3 state locking; DynamoDB locking deprecated)
- [AWS Support plans](https://docs.aws.amazon.com/awssupport/latest/user/aws-support-plans.md) (Business Support+; legacy plans end January 1, 2027)
- [AWS Control Tower landing zone 4.0 changes](https://docs.aws.eu/controltower/latest/userguide/key-changes-lz-v4.html)
- [Managing PostgreSQL partitions with pg_partman on RDS](https://docs.aws.eu/AmazonRDS/latest/UserGuide/PostgreSQL_Partitions.html)
- [AWS Fargate pricing](https://aws.amazon.com/fargate/pricing/), [ElastiCache pricing breakdown, 2026](https://upstash.com/blog/aws-elasticache-pricing-explained-2026-full-cost-breakdown), [RDS PostgreSQL t4g pricing, 2026](https://infratally.com/articles/aws-rds-pricing-explained-2026/)
