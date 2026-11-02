output "collector_role_arn" {
  value = aws_iam_role.gapcheck_collector.arn
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.members.id
}
