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
