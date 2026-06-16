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
