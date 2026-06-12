"""Bootstraps the AWS resources from infra/aws_setup.md via boto3 (idempotent).

Order matters: cost guard first, then resources.

    python infra/aws_bootstrap.py            # creates budget, S3, IAM user, RDS
    python infra/aws_bootstrap.py --wait-rds # polls until RDS is available, prints endpoint

Reads admin credentials from .env (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY/AWS_REGION).
Writes the dw-pipeline user's new access key and the generated RDS master password
to OUT_FILE (outside the repo) — never to stdout, never to git.
"""
import argparse
import json
import secrets
import sys
import time
import urllib.request

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

REGION = "us-east-2"
BUDGET_NAME = "zero-spend"
BUDGET_EMAIL = "internick2017@gmail.com"
PIPELINE_USER = "dw-pipeline"
SG_NAME = "dw-my-ip"
DB_ID = "ecommerce-dw"
DB_USER = "dw"
OUT_FILE = "f:/tmp/ecommerce-dw-aws-secrets.json"


def account_id():
    return boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]


def my_public_ip():
    with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=10) as r:
        return r.read().decode().strip()


def ensure_budget(acct):
    budgets = boto3.client("budgets", region_name="us-east-1")
    try:
        budgets.create_budget(
            AccountId=acct,
            Budget={
                "BudgetName": BUDGET_NAME,
                "BudgetLimit": {"Amount": "1.0", "Unit": "USD"},
                "TimeUnit": "MONTHLY",
                "BudgetType": "COST",
            },
            NotificationsWithSubscribers=[{
                "Notification": {
                    "NotificationType": "ACTUAL",
                    "ComparisonOperator": "GREATER_THAN",
                    "Threshold": 0.01,
                    "ThresholdType": "ABSOLUTE_VALUE",
                },
                "Subscribers": [{"SubscriptionType": "EMAIL", "Address": BUDGET_EMAIL}],
            }],
        )
        print(f"budget: created '{BUDGET_NAME}' (alerts {BUDGET_EMAIL} above $0.01)")
    except ClientError as e:
        if e.response["Error"]["Code"] == "DuplicateRecordException":
            print(f"budget: '{BUDGET_NAME}' already exists")
        else:
            raise


def ensure_bucket(acct):
    bucket = f"ecommerce-dw-raw-{acct}"
    s3 = boto3.client("s3", region_name=REGION)
    try:
        s3.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
        print(f"s3: created bucket {bucket}")
    except ClientError as e:
        if e.response["Error"]["Code"] in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            print(f"s3: bucket {bucket} already exists")
        else:
            raise
    s3.put_bucket_lifecycle_configuration(
        Bucket=bucket,
        LifecycleConfiguration={"Rules": [{
            "ID": "expire-raw-30d",
            "Status": "Enabled",
            "Filter": {"Prefix": "raw/"},
            "Expiration": {"Days": 30},
        }]},
    )
    print("s3: lifecycle expire-raw-30d applied (raw/, 30 days)")
    return bucket


def ensure_pipeline_user(bucket):
    iam = boto3.client("iam", region_name=REGION)
    try:
        iam.create_user(UserName=PIPELINE_USER)
        print(f"iam: created user {PIPELINE_USER}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            print(f"iam: user {PIPELINE_USER} already exists")
        else:
            raise
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": ["s3:PutObject", "s3:GetObject", "s3:ListBucket"],
            "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"],
        }],
    }
    iam.put_user_policy(UserName=PIPELINE_USER, PolicyName="dw-raw-bucket",
                        PolicyDocument=json.dumps(policy))
    print("iam: least-privilege bucket policy attached")
    existing = iam.list_access_keys(UserName=PIPELINE_USER)["AccessKeyMetadata"]
    if existing:
        print("iam: access key already exists (not rotating)")
        return None
    key = iam.create_access_key(UserName=PIPELINE_USER)["AccessKey"]
    print("iam: access key created (saved to OUT_FILE, not printed)")
    return {"AccessKeyId": key["AccessKeyId"], "SecretAccessKey": key["SecretAccessKey"]}


def ensure_security_group(ip):
    ec2 = boto3.client("ec2", region_name=REGION)
    vpc_id = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])["Vpcs"][0]["VpcId"]
    try:
        sg_id = ec2.create_security_group(
            GroupName=SG_NAME, Description="Postgres from my IP only", VpcId=vpc_id
        )["GroupId"]
        print(f"ec2: created security group {SG_NAME} ({sg_id})")
    except ClientError as e:
        if e.response["Error"]["Code"] == "InvalidGroup.Duplicate":
            sg_id = ec2.describe_security_groups(
                Filters=[{"Name": "group-name", "Values": [SG_NAME]}]
            )["SecurityGroups"][0]["GroupId"]
            print(f"ec2: security group {SG_NAME} already exists ({sg_id})")
        else:
            raise
    try:
        ec2.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[{
                "IpProtocol": "tcp", "FromPort": 5432, "ToPort": 5432,
                "IpRanges": [{"CidrIp": f"{ip}/32", "Description": "nick current IP"}],
            }],
        )
        print(f"ec2: ingress 5432 allowed from {ip}/32")
    except ClientError as e:
        if e.response["Error"]["Code"] == "InvalidPermission.Duplicate":
            print(f"ec2: ingress rule for {ip}/32 already present")
        else:
            raise
    return sg_id


def latest_pg16(rds):
    versions = rds.describe_db_engine_versions(Engine="postgres")["DBEngineVersions"]
    v16 = sorted(v["EngineVersion"] for v in versions if v["EngineVersion"].startswith("16."))
    return v16[-1] if v16 else None


def ensure_rds(sg_id):
    rds = boto3.client("rds", region_name=REGION)
    try:
        rds.describe_db_instances(DBInstanceIdentifier=DB_ID)
        print(f"rds: instance {DB_ID} already exists")
        return None
    except ClientError as e:
        if e.response["Error"]["Code"] != "DBInstanceNotFound":
            raise
    password = secrets.token_urlsafe(24)
    version = latest_pg16(rds)
    kwargs = dict(
        DBInstanceIdentifier=DB_ID,
        Engine="postgres",
        DBInstanceClass="db.t4g.micro",
        AllocatedStorage=20,
        StorageType="gp3",
        MasterUsername=DB_USER,
        MasterUserPassword=password,
        PubliclyAccessible=True,
        VpcSecurityGroupIds=[sg_id],
        BackupRetentionPeriod=1,
        MultiAZ=False,
        DeletionProtection=False,
    )
    if version:
        kwargs["EngineVersion"] = version
    rds.create_db_instance(**kwargs)
    print(f"rds: creating {DB_ID} (postgres {version or 'default'}, db.t4g.micro, 20GB gp3) — ~10 min")
    return password


def wait_rds():
    rds = boto3.client("rds", region_name=REGION)
    while True:
        db = rds.describe_db_instances(DBInstanceIdentifier=DB_ID)["DBInstances"][0]
        status = db["DBInstanceStatus"]
        endpoint = db.get("Endpoint", {}).get("Address")
        print(f"rds: status={status} endpoint={endpoint or '-'}")
        if status == "available" and endpoint:
            print(f"RDS_ENDPOINT={endpoint}")
            return endpoint
        time.sleep(30)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait-rds", action="store_true")
    args = parser.parse_args()
    if args.wait_rds:
        wait_rds()
        return 0

    acct = account_id()
    print(f"sts: authenticated as account {acct}")
    ensure_budget(acct)
    bucket = ensure_bucket(acct)
    pipeline_key = ensure_pipeline_user(bucket)
    ip = my_public_ip()
    sg_id = ensure_security_group(ip)
    db_password = ensure_rds(sg_id)

    out = {"bucket": bucket, "region": REGION}
    if pipeline_key:
        out["dw_pipeline_key"] = pipeline_key
    if db_password:
        out["rds_master_password"] = db_password
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"secrets written to {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
