data "aws_caller_identity" "current" {}

locals {
  function_name = "ecommerce-dw-pipeline"
}

# --- Secrets pulled from SSM Parameter Store (never stored in .tf) ---
# KNOWN TRADE-OFF: these values are injected as Lambda environment variables, so
# they are visible in the Lambda console and stored in Terraform state. Accepted
# here because this case is a validated artifact and is not deployed. A
# production version would pass only the SSM parameter NAMES and fetch them in
# code at cold start (the ReadSecrets IAM statement already allows that), or use
# the Lambda SSM/Secrets Manager extension.
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
  name               = "${local.function_name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "pipeline_permissions" {
  # CreateLogGroup is intentionally omitted: the log group is pre-created below
  # (with depends_on), so the runtime only needs to write to it.
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
    resources = ["arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${trimprefix(var.ssm_prefix, "/")}/*"]
  }
}

resource "aws_iam_role_policy" "pipeline" {
  name   = "${local.function_name}-policy"
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
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = 14
}

# --- Lambda function ---
# AWS_REGION is reserved and injected by the Lambda runtime, so boto3 finds the
# region automatically — we do not set it here. source_code_hash is intentionally
# omitted so `terraform validate` works without a built zip; the CD workflow
# builds the zip before plan/apply.
resource "aws_lambda_function" "pipeline" {
  function_name = local.function_name
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

  lifecycle {
    precondition {
      condition     = !var.enable_vpc || (length(var.subnet_ids) > 0 && length(var.security_group_ids) > 0)
      error_message = "enable_vpc requires at least one subnet_id and one security_group_id."
    }
  }

  depends_on = [aws_cloudwatch_log_group.pipeline]
}

# --- EventBridge schedule ---
resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "${local.function_name}-schedule"
  description         = "Triggers the ELT pipeline Lambda on a schedule"
  schedule_expression = var.schedule_expression
}

resource "aws_cloudwatch_event_target" "pipeline" {
  rule      = aws_cloudwatch_event_rule.schedule.name
  target_id = local.function_name
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
