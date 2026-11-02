# A사 AWS 샌드박스 (개발용 결함)

| 결함 | 심는 방법 | 대상 AR |
|---|---|---|
| D1 IAM 최소 길이 8 (정책 10) | `aws_iam_account_password_policy` | AR-2.5.4-02 |
| D3 ops-kim 임시 비밀번호 변경 강제 안 함 | `password_reset_required = false` | AR-2.5.4-03 |
| D5 Cognito 최소 길이 6 (정책 8) | `aws_cognito_user_pool` | AR-2.5.4-05 |
| D2 stg 계정 비밀번호 정책 없음 | 계정이 하나라 스냅샷으로만 재현 | AR-2.5.4-02 |
| D4 dev-lee 185일 미변경 | 시간이 필요해 스냅샷으로만 재현 | AR-2.5.4-04 |

```bash
terraform init
terraform validate
terraform apply -var collector_principal_arn=<본인 IAM ARN> -var external_id=<임의 문자열>
```

이 Terraform 코드는 작성 환경에 Terraform이 없어 `validate`를 돌리지 못했습니다. 처음 실행할 때 `terraform validate`부터 확인하세요.
D3을 실제로 재현하려면 apply 후 ops-kim으로 콘솔에 한 번 로그인해야 합니다 (발급 비밀번호 그대로 사용).
끝나면 `terraform destroy` 로 정리합니다.
