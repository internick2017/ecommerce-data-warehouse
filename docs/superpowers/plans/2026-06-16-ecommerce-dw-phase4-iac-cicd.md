# Phase 4 — IaC + CI/CD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the scheduled-run infrastructure (AWS Lambda + EventBridge), Terraform that codifies it, and GitHub Actions CI/CD — all as validated artifacts (no live `apply`).

**Architecture:** A thin `lambda_app/handler.py` wraps the existing `pipeline.run_pipeline`. A build script vendors Linux wheels into a deployment zip. A Terraform module (in `infra/terraform/`) declares the Lambda, its least-privilege IAM role, a CloudWatch log group, and an EventBridge schedule — referencing the bucket/RDS already created by `infra/aws_bootstrap.py` (Terraform *complements*, never *replaces*, the boto3 bootstrap). GitHub Actions runs pytest (against a Postgres service container) plus `terraform validate` on every push, and a manual deploy workflow builds the zip with the apply gated/dormant.

**Tech Stack:** Python 3.12, AWS Lambda, Amazon EventBridge, AWS IAM, SSM Parameter Store, Terraform (`hashicorp/aws` provider), GitHub Actions, pytest.

**Spec:** `docs/superpowers/specs/2026-06-16-ecommerce-dw-phase4-iac-cicd-design.md`

**Branch:** `feat/phase4-iac-cicd` (already created; spec already committed).

---

## File Structure

| File | Responsibility |
|------|----------------|
| `lambda_app/__init__.py` | Package marker (new). |
| `lambda_app/handler.py` | Lambda entrypoint: builds client + connection, calls `run_pipeline`, returns status. (new) |
| `tests/test_lambda_handler.py` | Unit tests for the handler (mocked deps, no DB). (new) |
| `infra/build_lambda.py` | Builds `dist/pipeline_lambda.zip` (vendored Linux wheels + source). (new) |
| `infra/terraform/versions.tf` | Terraform + provider version pins, provider block. (new) |
| `infra/terraform/variables.tf` | Input variables (non-secret config). (new) |
| `infra/terraform/main.tf` | Lambda, IAM role/policy, log group, EventBridge, SSM data sources. (new) |
| `infra/terraform/outputs.tf` | Useful outputs (ARN, log group, schedule). (new) |
| `infra/terraform/README.md` | How to validate/plan/apply. (new) |
| `.github/workflows/ci.yml` | CI: pytest (Postgres service) + terraform validate. (new) |
| `.github/workflows/deploy.yml` | CD: build zip (green) + gated/dormant plan+apply. (new) |
| `infra/aws_setup.md` | Pointer to the Terraform module. (modify) |
| `README.md` | Phase 4 section + diagram update. (modify) |
| `.env.example` | Document Lambda env vars. (modify) |
| `.gitignore` | Ignore `dist/`, `build/`, `.terraform/`, tfstate. (modify) |

---

## Task 1: Lambda handler (TDD)

**Files:**
- Create: `lambda_app/__init__.py`
- Create: `lambda_app/handler.py`
- Test: `tests/test_lambda_handler.py`

- [ ] **Step 1: Create the package marker**

Create `lambda_app/__init__.py` (empty file):

```python
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_lambda_handler.py`:

```python
from unittest import mock

import lambda_app.handler as h


def _patch_deps(monkeypatch, run_result=None, run_side_effect=None):
    """Patch the handler's collaborators; return (recorded_calls, fake_conn)."""
    monkeypatch.setenv("SHOPIFY_SHOP_DOMAIN", "store.myshopify.com")
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_test")
    fake_client = object()
    monkeypatch.setattr(h, "ShopifyClient", lambda **kwargs: fake_client)
    fake_conn = mock.Mock(name="conn")
    monkeypatch.setattr(h.pg_loader, "connect", lambda: fake_conn)

    calls = {}

    def fake_run(conn, client, full=False):
        calls["conn"] = conn
        calls["client"] = client
        calls["full"] = full
        if run_side_effect is not None:
            raise run_side_effect
        return run_result

    monkeypatch.setattr(h, "run_pipeline", fake_run)
    return calls, fake_conn, fake_client


def test_handler_returns_pipeline_status(monkeypatch):
    calls, fake_conn, fake_client = _patch_deps(
        monkeypatch, run_result={"status": "SUCCESS", "load_id": 7}
    )
    result = h.handler({}, None)
    assert result == {"status": "SUCCESS", "load_id": 7}
    assert calls["client"] is fake_client
    assert calls["full"] is False
    fake_conn.close.assert_called_once()


def test_handler_threads_full_flag(monkeypatch):
    calls, _, _ = _patch_deps(monkeypatch, run_result={"status": "SUCCESS"})
    h.handler({"full": True}, None)
    assert calls["full"] is True


def test_handler_handles_non_dict_event(monkeypatch):
    calls, _, _ = _patch_deps(monkeypatch, run_result={"status": "SUCCESS"})
    h.handler(None, None)
    assert calls["full"] is False


def test_handler_closes_connection_on_error(monkeypatch):
    calls, fake_conn, _ = _patch_deps(
        monkeypatch, run_side_effect=RuntimeError("boom")
    )
    import pytest
    with pytest.raises(RuntimeError):
        h.handler({}, None)
    fake_conn.close.assert_called_once()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/test_lambda_handler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lambda_app.handler'` (handler not written yet).

- [ ] **Step 4: Write the handler**

Create `lambda_app/handler.py`:

```python
"""AWS Lambda entrypoint for the batch ELT pipeline.

Triggered on a schedule by EventBridge. Reuses pipeline.run_pipeline unchanged;
this module only wires environment config to a client + connection and returns
the run's status dict. An optional ``{"full": true}`` event forces a full
re-extract (ignores watermarks).
"""
import logging
import os

from extract.shopify_client import ShopifyClient
from load import pg_loader
from pipeline import run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("lambda")


def handler(event, context):
    full = bool(event.get("full", False)) if isinstance(event, dict) else False
    client = ShopifyClient(
        shop_domain=os.environ["SHOPIFY_SHOP_DOMAIN"],
        access_token=os.environ["SHOPIFY_ACCESS_TOKEN"],
    )
    conn = pg_loader.connect()
    try:
        result = run_pipeline(conn, client, full=full)
        log.info("pipeline run complete: %s", result)
        return result
    finally:
        conn.close()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_lambda_handler.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add lambda_app/ tests/test_lambda_handler.py
git commit -m "feat(lambda): handler wrapping run_pipeline for scheduled runs"
```

---

## Task 2: Lambda packaging script

**Files:**
- Create: `infra/build_lambda.py`
- Modify: `.gitignore`

- [ ] **Step 1: Update `.gitignore`**

Append these lines to `.gitignore`:

```
dist/
build/
.terraform/
*.tfstate
*.tfstate.*
```

- [ ] **Step 2: Write the build script**

Create `infra/build_lambda.py`:

```python
"""Builds dist/pipeline_lambda.zip — the AWS Lambda deployment package.

Vendors Linux-platform wheels (so the compiled psycopg wheel matches Lambda's
runtime, not the host's), copies the runtime source packages, and zips them.
Run on any OS:

    python infra/build_lambda.py

Excludes dev/test-only deps (pytest, fastapi, uvicorn, pyodbc): the scheduled
batch Lambda needs none of them.
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "lambda"
DIST = ROOT / "dist"
ZIP_PATH = DIST / "pipeline_lambda.zip"

# Source packages/modules the handler imports at runtime.
SOURCE_ITEMS = ["lambda_app", "extract", "load", "transform", "pipeline.py"]

# Runtime deps only.
RUNTIME_DEPS = [
    "requests>=2.31",
    "pydantic>=2.5",
    "psycopg[binary]>=3.1",
    "python-dotenv>=1.0",
]
PLATFORM = "manylinux2014_x86_64"
PY_VERSION = "312"


def clean():
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)
    DIST.mkdir(exist_ok=True)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()


def vendor_deps():
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--platform", PLATFORM,
            "--python-version", PY_VERSION,
            "--implementation", "cp",
            "--only-binary=:all:",
            "--target", str(BUILD),
            *RUNTIME_DEPS,
        ],
        check=True,
    )


def copy_sources():
    for item in SOURCE_ITEMS:
        src = ROOT / item
        dest = BUILD / item
        if src.is_dir():
            shutil.copytree(
                src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
            )
        else:
            shutil.copy2(src, dest)


def make_zip():
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in BUILD.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(BUILD))


def main():
    clean()
    vendor_deps()
    copy_sources()
    make_zip()
    size_kb = ZIP_PATH.stat().st_size // 1024
    print(f"built {ZIP_PATH} ({size_kb} KB)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the build to verify it works**

Run: `python infra/build_lambda.py`
Expected: prints `built .../dist/pipeline_lambda.zip (NNNN KB)` (needs network to download wheels).

- [ ] **Step 4: Verify the zip contains the handler and a vendored dep**

Run:
```bash
python -c "import zipfile; n=zipfile.ZipFile('dist/pipeline_lambda.zip').namelist(); assert 'lambda_app/handler.py' in n; assert any(x.startswith('psycopg/') for x in n); print('OK', len(n), 'entries')"
```
Expected: `OK <N> entries`.

- [ ] **Step 5: Commit**

```bash
git add infra/build_lambda.py .gitignore
git commit -m "feat(infra): build script for the Lambda deployment package"
```

---

## Task 3: Terraform module

**Files:**
- Create: `infra/terraform/versions.tf`
- Create: `infra/terraform/variables.tf`
- Create: `infra/terraform/main.tf`
- Create: `infra/terraform/outputs.tf`
- Create: `infra/terraform/README.md`

- [ ] **Step 1: Write `versions.tf`**

```hcl
terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }
}

provider "aws" {
  region = var.aws_region
}
```

- [ ] **Step 2: Write `variables.tf`**

```hcl
variable "aws_region" {
  type        = string
  description = "AWS region for the Phase 4 resources (matches the bootstrap account)."
  default     = "us-east-2"
}

variable "raw_bucket_name" {
  type        = string
  description = "Existing S3 raw bucket from infra/aws_bootstrap.py (ecommerce-dw-raw-<acct>)."
}

variable "shop_domain" {
  type        = string
  description = "Shopify store domain, e.g. your-store.myshopify.com (non-secret)."
}

variable "schedule_expression" {
  type        = string
  description = "EventBridge schedule for the pipeline run."
  default     = "cron(0 6 * * ? *)"
}

variable "lambda_zip_path" {
  type        = string
  description = "Path to the built deployment package (see infra/build_lambda.py)."
  default     = "../../dist/pipeline_lambda.zip"
}

variable "ssm_prefix" {
  type        = string
  description = "SSM Parameter Store path prefix for this project's secrets."
  default     = "/ecommerce-dw"
}

variable "enable_vpc" {
  type        = bool
  description = "Attach the Lambda to a VPC. Needs subnets+SG and (for internet egress) a NAT gateway, which is NOT free tier. Off by default."
  default     = false
}

variable "subnet_ids" {
  type        = list(string)
  description = "Private subnet IDs for the Lambda when enable_vpc is true."
  default     = []
}

variable "security_group_ids" {
  type        = list(string)
  description = "Security group IDs for the Lambda when enable_vpc is true."
  default     = []
}
```

- [ ] **Step 3: Write `main.tf`**

```hcl
data "aws_caller_identity" "current" {}

# --- Secrets pulled from SSM Parameter Store (never stored in .tf) ---
data "aws_ssm_parameter" "shopify_access_token" {
  name = "${var.ssm_prefix}/SHOPIFY_ACCESS_TOKEN"
}

data "aws_ssm_parameter" "database_url" {
  name = "${var.ssm_prefix}/DATABASE_URL"
}

# --- IAM execution role (least privilege) ---
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "pipeline" {
  name               = "ecommerce-dw-pipeline-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "pipeline_permissions" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.pipeline.arn}:*"]
  }

  statement {
    sid     = "RawBucket"
    actions = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
    resources = [
      "arn:aws:s3:::${var.raw_bucket_name}",
      "arn:aws:s3:::${var.raw_bucket_name}/*",
    ]
  }

  statement {
    sid       = "ReadSecrets"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.ssm_prefix}/*"]
  }
}

resource "aws_iam_role_policy" "pipeline" {
  name   = "ecommerce-dw-pipeline-policy"
  role   = aws_iam_role.pipeline.id
  policy = data.aws_iam_policy_document.pipeline_permissions.json
}

# AWS-managed policy for VPC networking, only attached when enable_vpc is true.
resource "aws_iam_role_policy_attachment" "vpc_access" {
  count      = var.enable_vpc ? 1 : 0
  role       = aws_iam_role.pipeline.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# --- Log group ---
resource "aws_cloudwatch_log_group" "pipeline" {
  name              = "/aws/lambda/ecommerce-dw-pipeline"
  retention_in_days = 14
}

# --- Lambda function ---
# AWS_REGION is reserved and injected by the Lambda runtime, so boto3 finds the
# region automatically — we do not set it here. source_code_hash is intentionally
# omitted so `terraform validate` works without a built zip; the CD workflow
# builds the zip before plan/apply.
resource "aws_lambda_function" "pipeline" {
  function_name = "ecommerce-dw-pipeline"
  role          = aws_iam_role.pipeline.arn
  runtime       = "python3.12"
  handler       = "lambda_app.handler.handler"
  filename      = var.lambda_zip_path
  timeout       = 300
  memory_size   = 512

  environment {
    variables = {
      SHOPIFY_SHOP_DOMAIN  = var.shop_domain
      SHOPIFY_ACCESS_TOKEN = data.aws_ssm_parameter.shopify_access_token.value
      DATABASE_URL         = data.aws_ssm_parameter.database_url.value
      S3_BUCKET            = var.raw_bucket_name
    }
  }

  dynamic "vpc_config" {
    for_each = var.enable_vpc ? [1] : []
    content {
      subnet_ids         = var.subnet_ids
      security_group_ids = var.security_group_ids
    }
  }

  depends_on = [aws_cloudwatch_log_group.pipeline]
}

# --- EventBridge schedule ---
resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "ecommerce-dw-pipeline-schedule"
  description         = "Triggers the ELT pipeline Lambda on a schedule"
  schedule_expression = var.schedule_expression
}

resource "aws_cloudwatch_event_target" "pipeline" {
  rule      = aws_cloudwatch_event_rule.schedule.name
  target_id = "ecommerce-dw-pipeline"
  arn       = aws_lambda_function.pipeline.arn
  input     = jsonencode({ full = false })
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.pipeline.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule.arn
}
```

- [ ] **Step 4: Write `outputs.tf`**

```hcl
output "lambda_function_arn" {
  value       = aws_lambda_function.pipeline.arn
  description = "ARN of the ELT pipeline Lambda."
}

output "log_group_name" {
  value       = aws_cloudwatch_log_group.pipeline.name
  description = "CloudWatch log group for the Lambda."
}

output "schedule_expression" {
  value       = aws_cloudwatch_event_rule.schedule.schedule_expression
  description = "Effective EventBridge schedule."
}
```

- [ ] **Step 5: Write `infra/terraform/README.md`**

```markdown
# Terraform — scheduled pipeline (Phase 4)

This module declares the resources that run the batch ELT pipeline on a schedule:
an **AWS Lambda** (the pipeline), a least-privilege **IAM role**, a **CloudWatch
log group**, and an **EventBridge** schedule rule.

It **complements** `infra/aws_bootstrap.py` (which owns the S3 bucket, RDS, and the
`dw-pipeline` IAM user). This module *references* the bucket by name and reads
secrets from SSM Parameter Store — it does not manage the bucket or the database.

## Validate (no AWS credentials needed)

```bash
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform init -backend=false
terraform -chdir=infra/terraform validate
```

This is what CI runs. It checks the configuration is well-formed without touching AWS.

## Plan / apply (needs credentials — not done in this portfolio case)

To actually deploy you would:

1. Build the package: `python infra/build_lambda.py`.
2. Store secrets in SSM (once):
   ```bash
   aws ssm put-parameter --name /ecommerce-dw/SHOPIFY_ACCESS_TOKEN --type SecureString --value '...'
   aws ssm put-parameter --name /ecommerce-dw/DATABASE_URL        --type SecureString --value '...'
   ```
3. `terraform -chdir=infra/terraform plan -var raw_bucket_name=... -var shop_domain=...`
4. `terraform -chdir=infra/terraform apply` (review the plan first).

**Networking note:** by default the Lambda is *not* in a VPC, so it has free internet
egress (Shopify) but cannot reach an RDS instance locked to a single IP. Production
options: make RDS reachable, or set `enable_vpc=true` with private subnets — the
latter needs a NAT gateway for Shopify egress (~$32/mo, not free tier). This case
stays at validate/plan to avoid that cost.
```

- [ ] **Step 6: Validate the module**

Run:
```bash
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform init -backend=false
terraform -chdir=infra/terraform validate
```
Expected: `Success! The configuration is valid.`

> If `terraform` is not installed locally, install it (`choco install terraform` on
> Windows) or skip this step — CI (Task 4) runs the same commands. If `fmt -check`
> reports files, run `terraform -chdir=infra/terraform fmt -recursive` to fix.

- [ ] **Step 7: Commit**

```bash
git add infra/terraform/
git commit -m "feat(infra): Terraform module for scheduled Lambda + EventBridge"
```

---

## Task 4: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write the CI workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [master]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: dw
          POSTGRES_PASSWORD: dw
          POSTGRES_DB: ecommerce_dw
        ports:
          - 5433:5432
        options: >-
          --health-cmd "pg_isready -U dw"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    env:
      DATABASE_URL: postgresql://dw:dw@localhost:5433/ecommerce_dw
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install ODBC headers (for pyodbc)
        run: sudo apt-get update && sudo apt-get install -y unixodbc-dev
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run tests
        run: pytest -v

  terraform:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
      - name: Terraform fmt
        run: terraform -chdir=infra/terraform fmt -check -recursive
      - name: Terraform init
        run: terraform -chdir=infra/terraform init -backend=false
      - name: Terraform validate
        run: terraform -chdir=infra/terraform validate
```

- [ ] **Step 2: Validate the YAML locally**

Run:
```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('valid yaml')"
```
Expected: `valid yaml`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: pytest (Postgres service) + terraform validate on push/PR"
```

---

## Task 5: GitHub Actions CD

**Files:**
- Create: `.github/workflows/deploy.yml`

- [ ] **Step 1: Write the deploy workflow**

Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy

# Manual only. The `package` job always runs green (proves packaging). The
# `deploy` job (terraform plan + apply) is dormant: it needs AWS credentials and
# populated SSM parameters, and is gated behind the `production` environment's
# manual approval. Enable it by setting the repo variable ENABLE_DEPLOY=true and
# configuring the `production` environment with an OIDC role.
on:
  workflow_dispatch:

jobs:
  package:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Build Lambda package
        run: python infra/build_lambda.py
      - name: Upload package artifact
        uses: actions/upload-artifact@v4
        with:
          name: pipeline_lambda
          path: dist/pipeline_lambda.zip

  deploy:
    needs: package
    if: ${{ vars.ENABLE_DEPLOY == 'true' }}
    runs-on: ubuntu-latest
    environment: production
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: actions/checkout@v4
      - name: Download package artifact
        uses: actions/download-artifact@v4
        with:
          name: pipeline_lambda
          path: dist
      - name: Configure AWS credentials (OIDC)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
          aws-region: us-east-2
      - uses: hashicorp/setup-terraform@v3
      - name: Terraform init
        run: terraform -chdir=infra/terraform init
      - name: Terraform plan
        run: terraform -chdir=infra/terraform plan -input=false -var raw_bucket_name=${{ vars.RAW_BUCKET_NAME }} -var shop_domain=${{ vars.SHOP_DOMAIN }}
      - name: Terraform apply
        run: terraform -chdir=infra/terraform apply -auto-approve -input=false -var raw_bucket_name=${{ vars.RAW_BUCKET_NAME }} -var shop_domain=${{ vars.SHOP_DOMAIN }}
```

- [ ] **Step 2: Validate the YAML locally**

Run:
```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml')); print('valid yaml')"
```
Expected: `valid yaml`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: manual deploy workflow (build zip; plan/apply gated + dormant)"
```

---

## Task 6: Docs

**Files:**
- Modify: `README.md`
- Modify: `infra/aws_setup.md`
- Modify: `.env.example`

- [ ] **Step 1: Add the Phase 4 section to `README.md`**

Append after the Phase 3 section in `README.md`:

```markdown
## Phase 4 — Scheduled runs (IaC + CI/CD)

The batch pipeline runs on a schedule as an **AWS Lambda** triggered by
**EventBridge**, all declared as code with **Terraform** (`infra/terraform/`):

- **`lambda_app/handler.py`** wraps `pipeline.run_pipeline` — no logic duplicated.
- **`infra/build_lambda.py`** builds the deployment zip with Linux-platform wheels.
- **Terraform** declares the Lambda, a least-privilege IAM role, a CloudWatch log
  group, and the EventBridge schedule. It *complements* `infra/aws_bootstrap.py`:
  it references the existing S3 bucket and reads secrets from **SSM Parameter
  Store**, and does not manage the bucket or RDS.
- **GitHub Actions** — `ci.yml` runs the test suite against a Postgres service
  container and `terraform validate` on every push; `deploy.yml` builds the package
  and (gated behind a manual-approval `production` environment) can `terraform apply`.

These are validated artifacts: `terraform validate` and CI are green, but no live
`apply` is performed (a VPC-attached Lambda reaching the internet needs a NAT
gateway, outside the free tier). See `infra/terraform/README.md`.
```

- [ ] **Step 2: Extend the mermaid diagram in `README.md`**

In the `flowchart LR` block under "## Architecture", add these lines just before the closing ` ``` ` of the diagram (after the existing `ES --> D` line):

```
    SCHED["EventBridge<br/>(schedule)"] -->|"triggers"| LAM["Lambda<br/>(handler)"]
    LAM -->|"run_pipeline"| B
```

- [ ] **Step 3: Add a pointer in `infra/aws_setup.md`**

Append to `infra/aws_setup.md`:

```markdown
## 6. Scheduled runs (Phase 4)

The Lambda + EventBridge schedule that runs this pipeline automatically is defined
as code in `infra/terraform/` (see its README). It references the bucket and RDS
created above; secrets go in SSM Parameter Store, not in `.tf` files.
```

- [ ] **Step 4: Document the Lambda env vars in `.env.example`**

Append to `.env.example`:

```
# Phase 4 (Lambda): the scheduled function reads the same vars above. In AWS they
# are sourced from SSM Parameter Store (SHOPIFY_ACCESS_TOKEN, DATABASE_URL) and
# Terraform variables (SHOPIFY_SHOP_DOMAIN, S3_BUCKET); AWS_REGION is provided by
# the Lambda runtime. See infra/terraform/README.md.
```

- [ ] **Step 5: Verify the diagram still parses (visual check)**

Run: `python -c "print(open('README.md').read().count('```'))"`
Expected: an even number (all fenced/mermaid blocks balanced).

- [ ] **Step 6: Commit**

```bash
git add README.md infra/aws_setup.md .env.example
git commit -m "docs: document Phase 4 (scheduled runs, IaC, CI/CD)"
```

---

## Task 7: Final verification

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: all tests pass (the previous ~30 plus the 4 new handler tests).

- [ ] **Step 2: Re-validate Terraform (if installed)**

Run: `terraform -chdir=infra/terraform validate`
Expected: `Success! The configuration is valid.` (skip if terraform not installed; CI covers it.)

- [ ] **Step 3: Confirm no secrets staged**

Run: `git grep -nE "shpat_|postgresql://[^ ]*:[^ ]*@" -- ':!*.example' ':!docs/**' || echo "no secrets found"`
Expected: `no secrets found`.

- [ ] **Step 4: Finish the branch**

Use the `superpowers:finishing-a-development-branch` skill to merge `feat/phase4-iac-cicd`
into `master` (fast-forward, matching how Phases 1–3 landed) and update the case memory.

---

## Self-Review notes

- **Spec coverage:** handler (Task 1), packaging (Task 2), Terraform module incl. SSM
  secrets + complement-not-replace (Task 3), CI pytest+validate (Task 4), CD build+gated
  apply (Task 5), docs+diagram (Task 6), regression check (Task 7). All spec sections mapped.
- **CD honesty:** the spec said "build zip + terraform plan"; the plan refines this —
  `plan`/`apply` need credentials, so only the `package` job is green; `plan`+`apply` are
  gated/dormant behind the `production` environment. This is the truthful realization of
  the spec's "apply gated/dormant" intent.
- **Type/name consistency:** handler path `lambda_app.handler.handler` is identical in the
  handler module, the Terraform `handler` attribute, and the build script's `SOURCE_ITEMS`.
  Env var names (`SHOPIFY_SHOP_DOMAIN`, `SHOPIFY_ACCESS_TOKEN`, `DATABASE_URL`, `S3_BUCKET`)
  match `pipeline.main`, `.env.example`, and the Terraform `environment` block.
```
