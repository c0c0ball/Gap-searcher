# b-corp-eval 채점 보고서 — v0

- 결과 파일: `/tmp/b_eval/result_v0.json` (코드 커밋 414f5f6, result_hash `84bda214…`)
- 정답지: `/home/claude/hidden_eval/b_corp_answer_key.yaml` (sha256 `cac654d64f177353d866bba52d6ad65fa93265e18ed83d11c2f3a5b0a0c3f1c7`, 채점 전 해시 일치 확인, 변경 없음)
- 채점 대상: 2.x AR 40개 (1.x AR 9개는 정답지에 없어 제외)

## 점수 요약

| 지표 | 값 |
|---|---|
| AR 상태 일치 | **12 / 40** (30.0%) |
| AR 엄격 일치 (상태 + fix subject 집합 동일) | **8 / 40** (20.0%) |
| 결함 대상 TP / FN / FP | 7 / 18 / 7 (정답 fix subject 25개) |
| 정밀도 | **0.50** |
| 재현율 | **0.28** |
| 위험 오류 ① 정답 fix → 결과 ok (결함을 적합이라 함) | 0건 |
| 위험 오류 ② 정답 ok/unknown → 결과 fix (없는 결함 지적) | 2건: AR-2.5.1-01, AR-2.5.3-02 |

### 혼동 행렬 (행: 정답, 열: 결과)

| 정답 \ 결과 | fix | ok | unknown | 합 |
|---|---|---|---|---|
| fix | 7 | 0 | 16 | 23 |
| ok | 2 | 2 | 10 | 14 |
| unknown | 0 | 0 | 3 | 3 |
| 합 | 9 | 2 | 29 | 40 |

### 주요 원인 (추정)

1. **B사 문체에서 문서 기준값 추출 실패 (가장 큰 원인).** 정보보안지침·절차·암호화·로그 지침 4종에서 doc_param이 13개만 추출됨. 기준값이 없으면 T1이 실패함. 정답 fix→결과 unknown 16건과 ok→unknown 10건 가운데 AR-2.5.2-02를 뺀 25건이 이 때문이고, AR-2.5.1-01은 조항이 없다고 보고 결함으로 오판함. 특히 암호화 지침은 `transport.tls_min_version` 하나만, 로그 지침은 `backup.retention_days`·`log.review_cycle_days` 둘만 추출됨. 놓친 표현: '패스워드', '최대 사용기간', '유추하기 쉬운 ID', '특수권한자 현황', '반기마다', '분기별', '매년', 'SSE-KMS', '멀티 리전', 호(1.) 아래에 둔 관리망 CIDR, 일반 문단으로 쓴 '제N조(…)'.
2. **범위 밖 계정 포함.** scope.yaml에서 `in_scope: false`인 777777777777(b-sandbox)을 모집단에 넣어 과탐 7건(FP 전부)이 나옴. 이 중 AR-2.5.3-02는 이것 때문에 '없는 결함'을 지적함.
3. **부분 수집 전파가 너무 넓음.** 666666666666은 `s3_buckets.json`만 수집하지 못했는데 S3를 쓰지 않는 IAM·네트워크·KMS·CloudTrail AR까지 모두 PARTIAL_COLLECTION이 됨. 결함은 직접 위반이 있으면 그대로 fix가 나오지만, 적합은 막힘 (예: AR-2.5.2-02는 T1~T4 모두 통과했는데 unknown).
4. 참고: `password.complexity_classes`를 4로 읽음(문서는 '4종 중 3종 이상'). `customer_password.min_length`=10, `complexity_classes`=3은 조건부 규칙(2종 10자/3종 8자)을 하나로 합친 값임. 이번 판정에는 영향이 없었음.

## AR별 결과

일치: ◎ 엄격 일치, ○ 상태만 일치(subject 다름), ✕ 불일치

| AR | 정답 | 결과 (verdict) | 일치 | 놓친 subject | 과탐 subject | 정답지 why | 틀린 이유(추정) |
|---|---|---|---|---|---|---|---|
| AR-2.2.5-01 | fix | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | B2041 신○○ 10-26 퇴직, 3영업일 기한(10-29) 경과(5영업일)인데 콘솔·액세스 키 활성 | - |
| AR-2.5.1-01 | ok | fix (CANDIDATE_NONCONFORMITY) | ✕ | - | 정책 문서 | 절차 제3조에 전자결재 신청·팀장 승인 후 발급 절차가 있음 | T1 문서 추출 실패: `account.request_approval` 못 찾음 (절차 제3조, 조문이 Heading이 아닌 일반 문단 + "전자결재로 신청서… 팀장의 승인" 표현) → 조항 부재로 오판해 결함 지적 |
| AR-2.5.1-02 | fix | unknown (INSUFFICIENT_EVIDENCE) | ✕ | 444444444444/data-oh | - | data-oh 에게 인라인 정책(athena-adhoc-results)이 직접 붙어 있음 — 지침 제9조① 그룹으로만 부여 | T1 문서 추출 실패: `access.group_based` 못 찾음 (지침 제9조① "역할 그룹(IAM 그룹)에 부여… 정책을 직접 연결하지 않는다"); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.5.2-01 | fix | unknown (INSUFFICIENT_EVIDENCE) | ✕ | 555555555555/test | - | b-dev 콘솔 사용자 이름 'test' — 지침 제8조②가 test 를 유추 가능 ID로 명시 금지 | T1 문서 추출 실패: `account.no_guessable_id` 못 찾음 (지침 제8조② "유추하기 쉬운 ID"); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.5.2-02 | ok | unknown (INSUFFICIENT_EVIDENCE) | ✕ | - | - | 콘솔을 쓰는 공용 계정 test 는 정보보안팀장 승인 기재. demo-shared 는 승인자 없지만 IAM에 존재하지 않음 | T1~T4 모두 통과(2건 이상 없음)인데 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 → 적합을 내지 못함 |
| AR-2.5.3-01 | fix | fix (CANDIDATE_NONCONFORMITY) | ○ | - | 777777777777/admin, 777777777777/trainee01 | dev-moon 콘솔 비밀번호 사용, MFA 미등록 — 지침 제7조 | 결함 dev-moon은 맞힘. 과탐: 범위 밖 b-sandbox(777777777777, scope in_scope:false)를 모집단에 넣음 |
| AR-2.5.3-02 | ok | fix (CANDIDATE_NONCONFORMITY) | ✕ | - | 777777777777/root | 범위 내 3개 계정 루트 모두 MFA 등록 (MFA 없는 루트는 범위 밖 샌드박스뿐) | 과탐: 범위 밖 b-sandbox(777777777777, scope in_scope:false)를 모집단에 넣음 → 범위 내 3개 계정 루트는 모두 MFA라 '없는 결함' 지적 |
| AR-2.5.4-01 | ok | ok (CANDIDATE_CONFORMING) | ◎ | - | - | 정보보안지침 제4·5조에 길이·조합·변경주기·재사용·초기 패스워드 변경 규정 | - |
| AR-2.5.4-02 | fix | fix (CANDIDATE_NONCONFORMITY) | ○ | - | 777777777777 | b-dev IAM 최소 길이 8 < 지침 9. b-prod 는 RequireSymbols=false 지만 지침은 4종 중 3종 조합이라 개별 필수 아님 → 충족. b-seclog 는 더 엄격 | b-dev 길이 8은 맞힘. 과탐: 범위 밖 b-sandbox(777777777777, scope in_scope:false)를 모집단에 넣음 (NoSuchEntity). 참고: T1이 min_length만 추출(max_age 120, reuse 5 누락), complexity_classes를 4로 읽음(문서는 4종 중 3종) |
| AR-2.5.4-03 | fix | unknown (INSUFFICIENT_EVIDENCE) | ✕ | 444444444444/ops-yoo | - | ops-yoo 로그인 프로필 발급 시각과 비밀번호 변경 시각이 같고 이후 로그인, PasswordResetRequired=false — 초기 패스워드 미변경 사용 | T1 문서 추출 실패: `password.temp_force_change` 못 찾음 (지침 제5조② "초기 패스워드는 최초 로그인 시… 즉시 변경", 절차 제4조③); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.5.4-04 | fix | unknown (INSUFFICIENT_EVIDENCE) | ✕ | 444444444444/dev-kang | - | b-prod dev-kang 비밀번호 2026-05-20 변경 후 166일 > 120일. sec-hwang 115일은 기한 안 | T1 문서 추출 실패: `password.max_age_days` 못 찾음 (지침 제5조① "최대 사용기간은 120일"); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.5.4-05 | unknown | unknown (CANDIDATE_PARTIAL) | ◎ | - | - | 회원 로그인 있으나 Cognito 미사용, 가입·변경 화면 캡처 증적 미제출 → 적용 여부 확인 불가 | 정답(unknown)과 일치 — 화면 캡처 사람 검토 대기, Cognito 미사용 |
| AR-2.5.5-01 | fix | unknown (INSUFFICIENT_EVIDENCE) | ✕ | 444444444444/svc-deploy | - | svc-deploy 가 CICD 그룹의 사용자 정의 정책 DeployPipeline(Action *, Resource *)으로 관리자 권한 보유, 특수권한자 현황에 없음 | T1이 approval_required만 추출, `privileged.list_required` 못 찾음 (지침 제9조② "특수권한자 현황을 별도로 작성·관리") → T4 게이트 미충족; 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.5.5-02 | ok | unknown (INSUFFICIENT_EVIDENCE) | ✕ | - | - | 활성 유지보수 계정 vendor-lms 사용기한 2026-12-31. vendor-old 는 기한 지났지만 비활성 | T1 문서 추출 실패: `account.vendor_expiry_required` 못 찾음 (지침 제9조③ "사용기한을 정하여 발급", 절차 제7조); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.5.6-01 | ok | unknown (CANDIDATE_PARTIAL) | ✕ | - | - | 최근 검토 2026-05-15, 171일 ≤ 반기(184일) | T1 문서 추출 실패: `access_review.cycle_days` 못 찾음 (지침 제10조 "반기마다 1회 이상") |
| AR-2.5.6-02 | fix | fix (CANDIDATE_NONCONFORMITY) | ○ | - | 777777777777/trainee01 | svc-ci 액세스 키 2026-08-15 이후 79일 미사용인데 활성 — 지침 제8조④ 60일 | svc-ci는 맞힘. 과탐: 범위 밖 b-sandbox(777777777777, scope in_scope:false)를 모집단에 넣음 (trainee01) |
| AR-2.5.6-03 | fix | unknown (INSUFFICIENT_EVIDENCE) | ✕ | 555555555555/cloudtrail | - | b-dev 유일한 trail(b-dev-trail)이 IncludeManagementEvents=false(S3 데이터 이벤트만) → IAM 변경 미기록 | T1 문서 추출 실패: `log.audit_trail_required` 못 찾음 (로그 지침 제3조① "CloudTrail을 전체 리전(멀티 리전)으로", 조문이 일반 문단); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.6.1-01 | fix | unknown (INSUFFICIENT_EVIDENCE) | ✕ | 444444444444/lms-prod-report | - | RDS lms-prod-report PubliclyAccessible=true — 지침 제11조② | T1 문서 추출 실패: `network.db_private` 못 찾음 (지침 제11조② "공인 IP를 할당하지 않으며… 퍼블릭 액세스를 허용하지 않는다"); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.6.1-02 | ok | unknown (INSUFFICIENT_EVIDENCE) | ✕ | - | - | 범위 내 모든 기본 보안그룹 규칙 0개 (규칙 남은 기본 SG는 샌드박스뿐) | T1 문서 추출 실패: `network.default_sg_unused` 못 찾음 (지침 제11조⑤ "VPC 기본 보안그룹(default)은 모든… 규칙을 삭제"); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.6.2-01 | fix | fix (CANDIDATE_NONCONFORMITY) | ○ | - | 777777777777/sg-0a7lab00000001 | dev-encoder-legacy 가 Telnet(23)을 10.50.0.0/16 에서 허용 — 지침 제12조② | Telnet은 맞힘. 과탐: 범위 밖 b-sandbox(777777777777, scope in_scope:false)를 모집단에 넣음 (FTP 0.0.0.0/0) |
| AR-2.6.4-01 | fix | unknown (INSUFFICIENT_EVIDENCE) | ✕ | 444444444444/sg-0d4db0000000001, 444444444444/sg-0d4report000001 | - | DB SG가 VPN 대역 10.250.0.0/24 에서 3306 허용, 리포트 DB SG가 203.0.113.77/32 에서 5432 허용 — 지침 제11조③ | T1 문서 추출 실패: `network.db_from_app_only` 못 찾음 (지침 제11조③ "애플리케이션 영역 보안그룹을 출발지로 하는 규칙만… IP 주소 대역… 등록하지 않는다"); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.6.6-01 | fix | unknown (INSUFFICIENT_EVIDENCE) | ✕ | 444444444444/sg-0d4bastion00001, 555555555555/sg-0e5app000000001 | - | 배스천 RDP 3389를 192.0.2.0/24(관리망 /28보다 넓음)에서 허용, 개발 앱 SSH 22를 0.0.0.0/0 에서 허용 | T1 문서 추출 실패: `network.admin_source_cidrs` 못 찾음 (지침 제12조① 항 아래 호 "1. 본사 IT 관리망: 192.0.2.32/28", "2. …SSL-VPN 대역: 10.250.0.0/24"); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.6.7-01 | ok | unknown (INSUFFICIENT_EVIDENCE) | ✕ | - | - | RDS 서브넷(b-prod data-a/c 명시 연결 rtb local만, b-dev data-a/c 메인 rtb local만)에 인터넷 기본 경로 없음 | T1 문서 추출 실패: `network.db_no_internet` 못 찾음 (지침 제11조④ "인터넷 게이트웨이 또는 NAT 게이트웨이로 향하는 경로를 두지 않는다"); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.7.1-01 | fix | unknown (INSUFFICIENT_EVIDENCE) | ✕ | 555555555555/lms-dev-db | - | 개발 DB(개인정보 포함, 운영 데이터 복제) StorageEncrypted=false | T1 문서 추출 실패: `crypto.db_at_rest` 못 찾음 (암호화 지침 제4조① "스토리지 암호화를 적용"); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.7.1-02 | ok | unknown (INSUFFICIENT_EVIDENCE) | ✕ | - | - | 범위 내 모든 EBS 암호화 (aws/ebs 키 포함). 미암호화 볼륨은 샌드박스뿐 | T1 문서 추출 실패: `crypto.disk_at_rest` 못 찾음 (암호화 지침 제4조② "블록 스토리지(EBS)는… 모두 암호화"); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.7.1-03 | fix | unknown (INSUFFICIENT_EVIDENCE) | ✕ | 444444444444/b-prod-certificates | - | 개인정보 포함 수료증 버킷이 AES256(SSE-S3) — 지침 제4조③ SSE-KMS | T1 문서 추출 실패: `crypto.personal_object_kms` 못 찾음 (암호화 지침 제4조③ "SSE-KMS… SSE-S3만 적용하는 것은 허용하지 않는다"); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.7.1-04 | ok | unknown (INSUFFICIENT_EVIDENCE) | ✕ | - | - | 공개 HTTP 리스너(lms-web:80, dev-web:80)는 HTTPS 리다이렉트. lms-admin-internal:80 은 내부 전용 | T1 문서 추출 실패: `transport.https_only` 못 찾음 (암호화 지침 제5조② "HTTPS로만 제공… HTTPS로 리다이렉트"); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.7.1-05 | fix | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | 공개 lms-api 443 보안정책 ELBSecurityPolicy-TLS-1-1-2017-01 이 TLS 1.1 허용 — 기준 TLS 1.2 이상 | - |
| AR-2.7.2-01 | fix | unknown (INSUFFICIENT_EVIDENCE) | ✕ | 444444444444/4d4d4d4d-1111-4a00-9000-00000000a002 | - | 활성 고객 관리형 키 alias/pay-prod 자동 교체 꺼짐 — 지침 제7조 | T1 문서 추출 실패: `key.rotation_required` 못 찾음 (암호화 지침 제7조 "KMS 자동 키 교체를 활성화"); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.7.2-02 | unknown | unknown (INSUFFICIENT_EVIDENCE) | ◎ | - | - | B사 문서에 환경별 암호키 분리 조항이 없음 (b-dev 볼륨이 b-prod 키 사용하나 판단 기준 부재) | 정답(unknown)과 일치 — `key.env_separation` 조항 부재를 맞게 인식 (partial 전파도 겹침) |
| AR-2.7.2-03 | fix | unknown (INSUFFICIENT_EVIDENCE) | ✕ | 555555555555/5e5e5e5e-2222-4b00-9000-00000000b001 | - | 고객 관리형 키 alias/dev-app 이 암호키 관리대장에 없음 — 지침 제6조② | T1 문서 추출 실패: `key.ledger_required` 못 찾음 (암호화 지침 제6조② "암호키 관리대장에… 기록"); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.9.3-01 | fix | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | 중요도 상 lms-prod-db 자동 백업 보관 7일 < 14일 (pay-prod-db 35일 충족) | - |
| AR-2.9.3-02 | ok | unknown (INSUFFICIENT_EVIDENCE) | ✕ | - | - | 중요도 상 자원 있는 b-prod(lms-prod-monthly), b-seclog(seclog-weekly) 모두 다른 리전 복사 계획 보유 | T1 문서 추출 실패: `backup.cross_region_required` 못 찾음 (로그 지침 제6조② "다른 리전에 복제하여 보관"); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.9.3-03 | fix | unknown (CANDIDATE_PARTIAL) | ✕ | 백업 복구 테스트 기록 | - | 최근 복구 테스트 2026-07-15, 110일 > 분기(92일) | T1 문서 추출 실패: `backup.restore_test_cycle_days` 못 찾음 (로그 지침 제7조 "분기별 1회 이상") |
| AR-2.9.4-01 | ok | unknown (INSUFFICIENT_EVIDENCE) | ✕ | - | - | 범위 내 3개 계정 모두 기록 중인 trail 보유 (b-prod-trail-old 중지는 다른 활성 trail 있어 무관) | T1 문서 추출 실패: `log.audit_trail_required` 못 찾음 (로그 지침 제3조①); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.9.4-02 | fix | unknown (INSUFFICIENT_EVIDENCE) | ✕ | 555555555555/b-dev-trail | - | 기록 중인 b-dev-trail 로그 파일 검증 꺼짐 — 지침 제3조② | T1 문서 추출 실패: `log.integrity_required` 못 찾음 (로그 지침 제3조② "로그 파일 무결성 검증을 활성화"); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.9.4-03 | unknown | unknown (INSUFFICIENT_EVIDENCE) | ◎ | - | - | 기록 중인 trail 3개 모두 b-seclog 의 b-seclog-ct-archive 에 저장, b-seclog S3 수집 실패(partial)로 수명주기 확인 불가 | 정답(unknown)과 일치. 다만 원인이 둘 겹침: 의도한 원인(중앙 로그 버킷 수집 실패) 외에 `log.retention_days`("3년간 보관")도 추출 실패 |
| AR-2.9.5-01 | fix | unknown (INSUFFICIENT_EVIDENCE) | ✕ | 555555555555/guardduty | - | b-dev GuardDuty 탐지기 존재하나 Status DISABLED | T1 문서 추출 실패: `monitor.threat_detection_required` 못 찾음 (로그 지침 제5조② "GuardDuty를 활성화"); 666666666666 partial(S3만 미수집)을 IAM·네트워크 등 무관한 AR에도 PARTIAL_COLLECTION으로 전파 |
| AR-2.9.5-02 | ok | ok (CANDIDATE_CONFORMING) | ◎ | - | - | 최근 접속기록 점검 2026-10-12, 21일 ≤ 31일 | - |
| AR-2.12.2-01 | ok | unknown (CANDIDATE_PARTIAL) | ✕ | - | - | 최근 DR 훈련 2025-12-04, 333일 ≤ 366일 | T1 문서 추출 실패: `dr.drill_cycle_days` 못 찾음 (로그 지침 제8조 "매년 1회 이상") |

## 틀린 AR 목록

- 상태 불일치 (28): AR-2.5.1-01, AR-2.5.1-02, AR-2.5.2-01, AR-2.5.2-02, AR-2.5.3-02, AR-2.5.4-03, AR-2.5.4-04, AR-2.5.5-01, AR-2.5.5-02, AR-2.5.6-01, AR-2.5.6-03, AR-2.6.1-01, AR-2.6.1-02, AR-2.6.4-01, AR-2.6.6-01, AR-2.6.7-01, AR-2.7.1-01, AR-2.7.1-02, AR-2.7.1-03, AR-2.7.1-04, AR-2.7.2-01, AR-2.7.2-03, AR-2.9.3-02, AR-2.9.3-03, AR-2.9.4-01, AR-2.9.4-02, AR-2.9.5-01, AR-2.12.2-01
- 상태는 맞지만 subject 불일치 (4): AR-2.5.3-01, AR-2.5.4-02, AR-2.5.6-02, AR-2.6.2-01
