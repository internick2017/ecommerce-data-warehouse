# AWS Setup Runbook (free tier, cost-guarded)

Do these IN ORDER. Guards first, resources second.

## 0. Account
- Sign up / log in at console.aws.amazon.com. Region: us-east-2 (matches AWS_REGION in .env and the Terraform default; AWS Budgets is global and lives in us-east-1).

## 1. Billing guard (BEFORE any resource)
- Billing → Budgets → Create budget → Zero spend budget template (alerts above $0.01),
  email = your address.
- Billing → Billing preferences → enable "Receive Billing Alerts".

## 2. S3 bucket (raw data lake)
- S3 → Create bucket: `ecommerce-dw-raw-<your-suffix>` (must be globally unique),
  us-east-2, Block ALL public access = ON (default).
- Bucket → Management → Lifecycle rule: name `expire-raw-30d`, scope = whole bucket,
  action = "Expire current versions of objects" after 30 days.
- Put the bucket name in `.env` as `S3_BUCKET=`.

## 3. IAM user for the pipeline (least privilege)
- IAM → Users → Create user `dw-pipeline` (no console access) → Create access key
  (use case: "Application running outside AWS").
- Attach this inline policy (replace BUCKET):

      {
        "Version": "2012-10-17",
        "Statement": [{
          "Effect": "Allow",
          "Action": ["s3:PutObject", "s3:GetObject", "s3:ListBucket"],
          "Resource": ["arn:aws:s3:::BUCKET", "arn:aws:s3:::BUCKET/*"]
        }]
      }

- Configure credentials locally (pick one):
  - `aws configure` (writes ~/.aws/credentials), or
  - set `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` in `.env` (gitignored).

## 4. RDS Postgres (free tier)
- RDS → Create database → Standard create → PostgreSQL 16.
- Templates: **Free tier** (forces db.t4g.micro / single-AZ / 20 GB gp3).
- DB instance id: `ecommerce-dw`. Master user: `dw`, strong password (save it).
- Connectivity: Public access = **Yes**; create new security group `dw-my-ip`
  → after creation, edit its inbound rule: PostgreSQL (5432) from **My IP** only.
- Create database. Wait ~10 min for "Available", copy the endpoint.
- Set in `.env`:
  `DATABASE_URL=postgresql://dw:<password>@<endpoint>:5432/postgres`
- Test: `python -c "from load import pg_loader; print(pg_loader.connect().execute('select version()').fetchone())"`

## 5. Cost hygiene
- STOP the RDS instance when not working on the project (RDS → Actions → Stop temporarily;
  it auto-restarts after 7 days — stop it again or set a reminder).
- The free tier covers 750 instance-hours/month of db.t4g.micro for 12 months.
- Delete everything when the portfolio case is archived: RDS instance (skip final
  snapshot), S3 bucket, IAM user.

## 6. Scheduled runs (Phase 4)

The Lambda + EventBridge schedule that runs this pipeline automatically is defined
as code in `infra/terraform/` (see its README). It references the bucket and RDS
created above; secrets go in SSM Parameter Store, not in `.tf` files.
