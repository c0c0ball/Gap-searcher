variable "region" {
  type    = string
  default = "ap-northeast-2"
}

variable "collector_principal_arn" {
  type        = string
  description = "진단 서비스가 쓰는 IAM 주체 ARN (로컬 개발 시 본인 IAM 사용자 ARN)"
}

variable "external_id" {
  type        = string
  sensitive   = true
  description = "AssumeRole ExternalId — 추측하기 어려운 임의 문자열"
}
