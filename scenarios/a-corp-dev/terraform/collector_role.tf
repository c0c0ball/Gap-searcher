# 진단 서비스(collector)가 이 계정을 읽을 때 쓰는 읽기 전용 역할.
# 서비스 쪽 주체만 AssumeRole 할 수 있고, ExternalId가 일치해야 한다.

resource "aws_iam_role" "gapcheck_collector" {
  name                 = "gapcheck-collector"
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = var.collector_principal_arn }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "sts:ExternalId" = var.external_id } }
    }]
  })
}

# 2.5.4 수집에 필요한 API만 허용한다. 항목이 늘면 여기에 추가하고 승인 기록을 남긴다.
resource "aws_iam_role_policy" "gapcheck_collector_read" {
  name = "gapcheck-2-5-4-read"
  role = aws_iam_role.gapcheck_collector.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "IamPasswordReads"
        Effect = "Allow"
        Action = [
          "iam:GetAccountPasswordPolicy",
          "iam:GenerateCredentialReport",
          "iam:GetCredentialReport",
          "iam:GetLoginProfile",
          "iam:GetAccountAuthorizationDetails",
          "iam:ListUsers",
        ]
        Resource = "*"
      },
      {
        Sid      = "CognitoPoolReads"
        Effect   = "Allow"
        Action   = ["cognito-idp:ListUserPools", "cognito-idp:DescribeUserPool"]
        Resource = "*"
      },
    ]
  })
}
