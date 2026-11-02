# A사(가상) AWS 샌드박스 — 2.5.4 개발용 결함을 '설정으로 만들 수 있는 것'만 심는다.
# 시간이 지나야 생기는 결함(예: 비밀번호 185일 미변경)은 Terraform으로 만들 수 없으므로
# ../aws-snapshot 의 수집 스냅샷(fixture)으로 재현한다.
#
# ⚠ 반드시 개인 샌드박스 계정에서만 apply 한다. 계정 전체의 비밀번호 정책을 바꾼다.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project  = "isms-gap"
      Scenario = "a-corp-dev"
      Purpose  = "synthetic-defects"
    }
  }
}

# ── 결함 D1: 정책(제5조 최소 10자)보다 짧은 최소 길이 8 ─────────────────
resource "aws_iam_account_password_policy" "this" {
  minimum_password_length        = 8 # 정책은 10 → AR-2.5.4-02 결함
  require_uppercase_characters   = true
  require_lowercase_characters   = true
  require_numbers                = true
  require_symbols                = true
  max_password_age               = 90
  password_reuse_prevention      = 3
  allow_users_to_change_password = true
}

# ── 콘솔 사용자 ─────────────────────────────────────────────────────────
locals {
  console_users = {
    "admin-park" = { reset_required = true }
    "dev-choi"   = { reset_required = true }
    "dev-lee"    = { reset_required = true }
    # 결함 D3: 임시 비밀번호인데 다음 로그인 시 변경을 강제하지 않음 (지침 제6조②, 절차서 제2조②)
    "ops-kim" = { reset_required = false }
  }
}

resource "aws_iam_user" "console" {
  for_each = local.console_users
  name     = each.key
  tags     = { Synthetic = "true" }
}

resource "aws_iam_user_login_profile" "console" {
  for_each                = local.console_users
  user                    = aws_iam_user.console[each.key].name
  password_reset_required = each.value.reset_required
  # pgp_key 를 지정하지 않으면 생성된 비밀번호가 state에 평문으로 남는다.
  # 샌드박스라도 state 파일을 공유하지 말 것.
  lifecycle {
    ignore_changes = [password_reset_required, password_length]
  }
}

# 콘솔 비밀번호가 없는 서비스 계정 — 모집단에서 빠져야 정상
resource "aws_iam_user" "svc_batch" {
  name = "svc-batch"
  tags = { Synthetic = "true", Type = "service" }
}

# ── 결함 D5: 이용자 비밀번호 최소 길이 6 (지침 제7조는 8자) ─────────────
resource "aws_cognito_user_pool" "members" {
  name = "a-shop-members"
  password_policy {
    minimum_length    = 6 # 정책은 8 → AR-2.5.4-05 결함
    require_lowercase = true
    require_numbers   = true
    require_symbols   = true
    require_uppercase = false
  }
}
