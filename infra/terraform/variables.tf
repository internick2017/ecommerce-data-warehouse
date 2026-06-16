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
  description = "SSM Parameter Store path prefix for this project's secrets (must start with /)."
  default     = "/ecommerce-dw"

  validation {
    condition     = startswith(var.ssm_prefix, "/")
    error_message = "ssm_prefix must start with a leading slash, e.g. /ecommerce-dw."
  }
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
