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
