# Phase 4 — Infrastructure as Code + CI/CD (validated artifacts)

- **Date:** 2026-06-16
- **Status:** Approved (design)
- **Repo:** `e:\dev\08-data\ecommerce-data-warehouse`
- **Predecessors:** MVP (batch ELT) + Phase 2 (webhooks) + Phase 3 (ODBC ERP), all on `master`, ~30 tests green.

## Goal

Close the roadmap by adding the **Infrastructure-as-Code** and **CI/CD** story the
Genius Lab "Data Integration Developer" JD asks for. The existing pipeline is a CLI you run
by hand; Phase 4 makes it *scheduled, codified, and continuously tested*:

- **Terraform** describes the cloud resources that would run the pipeline on a schedule.
- **AWS Lambda + EventBridge** are those resources: a serverless function triggered on a cron.
- **GitHub Actions** runs the test suite on every push (CI) and packages + plans the deploy (CD).

**Depth decision (locked):** these are **validated artifacts**, not a live deployment. Terraform
must `validate` and `plan` cleanly and CI must go green, but we do **not** `apply` to the live AWS
account. This proves competence without the cost (a VPC-attached Lambda reaching the public
internet needs a NAT Gateway, ~$32/mo — not free tier) and without risking the live RDS/data.

## Concepts (plain-language primer)

This phase introduces cloud/DevOps tooling. Definitions, tied to how we use each one:

- **IaC (Infrastructure as Code):** describe cloud resources in text files instead of clicking in
  the AWS console. Repeatable, version-controlled, reviewable. *(A JD bullet.)*
- **Terraform:** the IaC tool. `.tf` files declare desired resources; `terraform plan` shows what
  *would* change; `terraform apply` makes it real. We stop at `plan`/`validate`.
- **AWS Lambda:** a serverless function. Upload a zip; AWS runs it on demand when triggered — no
  server to manage. Here it runs `pipeline.run_pipeline`.
- **EventBridge:** the "cloud cron." A schedule rule triggers the Lambda (e.g. daily at 06:00 UTC).
- **IAM role:** least-privilege permissions. The Lambda's role allows exactly: write logs,
  read/write the S3 raw bucket, read its SSM parameters — nothing else.
- **SSM Parameter Store:** AWS's secure store for config/secrets (Shopify token, DB URL) so they
  are never hardcoded.
- **CI (Continuous Integration):** on every push, a runner executes the test suite automatically.
- **CD (Continuous Deployment):** the same runner packages and (optionally) deploys. We build the
  zip and run `terraform plan`; `apply` is gated behind a manual approval and stays dormant.
- **GitHub Actions:** GitHub's built-in CI/CD. Jobs are declared in `.github/workflows/*.yml`.

**Data flow added by Phase 4:**

```
EventBridge schedule ──triggers──▶ Lambda (handler) ──calls──▶ pipeline.run_pipeline
                                                                  │
                                              reads Shopify ◀─────┤
                                              writes S3 raw ◀─────┤
                                              writes RDS Postgres ◀┘
```

## Guiding principle: Terraform *complements*, does not *replace*, `aws_bootstrap.py`

The existing `infra/aws_bootstrap.py` (boto3) owns the S3 bucket, the `dw-pipeline` IAM user, the
security group, and the RDS instance. Terraform will manage **only the new Phase 4 resources**
(Lambda, its IAM role, EventBridge rule, log group) and will **reference** the existing bucket and
RDS by variable / data source. This keeps the Terraform module self-contained and `plan`-able in
isolation, with zero risk of importing or destroying the live database.

*Rejected alternative:* having Terraform take ownership of everything via `terraform import` — a
"fuller" IaC story but heavyweight and risky, and pointless when we are not applying.

## Components

### 1. Lambda entrypoint — `lambda_app/handler.py`
A thin adapter: `handler(event, context)` loads config from environment, builds `ShopifyClient`,
opens the Postgres connection, calls `pipeline.run_pipeline(...)`, and returns the status dict.
`event.get("full", False)` maps to the pipeline's full re-extract. **No business logic is
duplicated** — it reuses the existing `run_pipeline`. Connection is closed in a `finally`.

### 2. Packaging — `infra/build_lambda.py`
A real, runnable script that produces `dist/pipeline_lambda.zip`: `pip install --target` with the
Linux platform tag (so `psycopg`'s compiled wheel matches Lambda's runtime), plus a copy of the
source packages (`extract/`, `load/`, `transform/`, `pipeline.py`, `lambda_app/`). Terraform
references the zip via `archive_file` / `filename`. (The zip itself is gitignored; the script is
the artifact.)

### 3. Terraform module — `infra/terraform/`
- `versions.tf` — pin `terraform` and the `aws` provider versions.
- `variables.tf` — non-secret config as variables: `aws_region`, `raw_bucket_name`,
  `shop_domain`, `schedule_expression` (default `cron(0 6 * * ? *)`), `lambda_zip_path`,
  `enable_vpc` (default `false`), `ssm_prefix`.
- `main.tf`:
  - `aws_iam_role` + `aws_iam_role_policy` — Lambda execution role: CloudWatch Logs, S3
    read/write scoped to the existing bucket ARN, `ssm:GetParameter` on the project prefix.
  - `aws_cloudwatch_log_group` — `/aws/lambda/ecommerce-dw-pipeline`, 14-day retention.
  - `aws_lambda_function` — runtime `python3.12`, handler `lambda_app.handler.handler`,
    env vars sourced from SSM, timeout/memory sized for the batch run. VPC config behind
    `enable_vpc` (off by default to avoid NAT cost; the block documents the production setup).
  - `aws_cloudwatch_event_rule` (the schedule) + `aws_cloudwatch_event_target`
    + `aws_lambda_permission` (allow EventBridge to invoke the Lambda).
  - `data "aws_ssm_parameter"` references for the **secrets only** — `SHOPIFY_ACCESS_TOKEN`
    and `DATABASE_URL` (live in SSM, never in `.tf` files). Non-secret config
    (`SHOPIFY_SHOP_DOMAIN`, `S3_BUCKET`, `AWS_REGION`) is passed from the Terraform variables
    above. All become the Lambda's environment variables.
- `outputs.tf` — Lambda ARN, log group name, schedule expression.
- `README.md` (in the terraform dir) — how to `init -backend=false`, `validate`, `plan`, and what
  it would take to actually `apply` (set creds, populate SSM, optionally `enable_vpc=true` + NAT).

### 4. CI — `.github/workflows/ci.yml`
Triggers on pull requests and pushes to `master`.
- **Job `test`:** a `postgres:16` service container; export `DATABASE_URL`; `pip install -r
  requirements.txt`; run `pytest`. The full ~30-test suite runs in-process (pyodbc is mocked,
  webhook tests use FastAPI/httpx) — only Postgres is needed.
- **Job `terraform`:** `terraform fmt -check`, `terraform init -backend=false`,
  `terraform validate` against `infra/terraform/`.

### 5. CD — `.github/workflows/deploy.yml`
Triggers on `workflow_dispatch` (manual). Steps: run `infra/build_lambda.py` to build the zip,
`terraform init`, `terraform plan`. An `apply` step exists but is **gated behind a GitHub
Environment named `production`** that requires manual approval and AWS credentials via OIDC. Since
no credentials are wired into the repo, `apply` is dormant and documented as "ready to enable."
This demonstrates the full CD shape with zero live risk.

### 6. Tests (TDD) — `tests/test_lambda_handler.py`
- handler parses the event and invokes `run_pipeline` (mocked) with the right args;
- the `full` flag is threaded through;
- a successful run returns the status dict;
- the error path closes the connection and re-raises / returns a failure shape.
Terraform correctness is verified by CI (`validate`), not by pytest.

### 7. Docs
- README: new "Phase 4 — Scheduled runs (IaC + CI/CD)" section + extend the mermaid diagram with
  the EventBridge → Lambda → pipeline path.
- `infra/aws_setup.md`: a note pointing at the Terraform module for the scheduled-run resources.
- `.env.example`: document the new env vars the Lambda reads (same names, sourced from SSM in prod).

## Out of scope (YAGNI)

- No live `terraform apply`; no NAT Gateway / VPC-attached Lambda by default.
- No Secrets Manager (SSM Parameter Store is sufficient and free).
- No multi-environment (dev/stage/prod) layout — one set of resources.
- The Phase 2 FastAPI webhook receiver is **not** Lambda-ified: it is a long-running service, a
  poor fit for a scheduled batch function. (A future API-Gateway-fronted Lambda could host it; not
  now.)
- No extra CloudWatch alarms / dashboards beyond the Lambda log group.

## Acceptance criteria

1. `pytest` passes locally and in CI, including the new `test_lambda_handler.py`.
2. `terraform fmt -check`, `terraform init -backend=false`, and `terraform validate` all pass in
   `infra/terraform/`.
3. `python infra/build_lambda.py` produces a `dist/pipeline_lambda.zip` containing the source and
   Linux-tagged dependencies.
4. CI (`ci.yml`) and the manual CD (`deploy.yml` up to `plan`) run green in GitHub Actions.
5. README documents Phase 4 and the diagram includes the scheduled path.
6. No secrets in git; the existing batch / webhook / ERP paths are unchanged (regression-free).

## File layout (new/changed)

```
lambda_app/
  __init__.py
  handler.py                 # NEW — Lambda entrypoint wrapping run_pipeline
infra/
  build_lambda.py            # NEW — builds dist/pipeline_lambda.zip
  terraform/
    versions.tf              # NEW
    variables.tf             # NEW
    main.tf                  # NEW — Lambda, IAM role, EventBridge, log group, SSM refs
    outputs.tf               # NEW
    README.md                # NEW — how to validate/plan/apply
  aws_setup.md               # CHANGED — pointer to terraform module
.github/workflows/
  ci.yml                     # NEW — pytest (Postgres service) + terraform validate
  deploy.yml                 # NEW — build zip + terraform plan (apply gated/dormant)
tests/
  test_lambda_handler.py     # NEW
README.md                    # CHANGED — Phase 4 section + diagram
.env.example                 # CHANGED — document Lambda env vars
.gitignore                   # CHANGED — ignore dist/ and .terraform/
```
