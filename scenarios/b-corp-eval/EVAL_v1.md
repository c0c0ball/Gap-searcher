# b-corp-eval 채점 보고서 — v1

> **v1 은 비블라인드(참고용)입니다.** v0 채점 보고서(AR별 정답·원인 공개)를 본 뒤 고친 버전이라, 이 점수는 일반화 성능을 보여 주지 않습니다. 블라인드 성능은 v0 또는 새 숨김 시나리오로 판단해야 합니다.

- 결과 파일: `/tmp/b_eval/result_v1.json` (변경 내용: 범위 밖 계정 제외, 부분 수집 전파 수정, 조 제목·본문 한 줄 형식과 호 해석, 규정 어휘 확장)
- 정답지: `/home/claude/hidden_eval/b_corp_answer_key.yaml` (sha256 `cac654d64f177353d866bba52d6ad65fa93265e18ed83d11c2f3a5b0a0c3f1c7`, 채점 전 해시 일치 확인, 변경 없음)
- 채점 대상: 2.x AR 40개 (1.x AR 9개 제외). 채점 규칙은 v0과 같음

## 점수 요약

| 지표 | v1 |
|---|---|
| AR 상태 일치 | **39 / 40** (97.5%) |
| AR 엄격 일치 | **39 / 40** (97.5%) |
| 결함 대상 TP / FN / FP | 25 / 0 / 0 (정답 fix subject 25개) |
| 정밀도 / 재현율 | **1.00 / 1.00** |
| 위험 오류 ① 정답 fix → 결과 ok | 0건 |
| 위험 오류 ② 정답 ok/unknown → 결과 fix | 0건 |

## v0 대비 변화

| 지표 | v0 | v1 | 변화 |
|---|---|---|---|
| AR 상태 일치 (/40) | 12 | 39 | +27 |
| AR 엄격 일치 (/40) | 8 | 39 | +31 |
| TP | 7 | 25 | +18 |
| FN (놓침) | 18 | 0 | -18 |
| FP (과탐) | 7 | 0 | -7 |
| 정밀도 | 0.50 | 1.00 | +0.50 |
| 재현율 | 0.28 | 1.00 | +0.72 |
| 위험 오류 ① (fix→ok) | 0 | 0 | 0 |
| 위험 오류 ② (ok/unknown→fix) | 2 | 0 | -2 |

### 혼동 행렬 (행: 정답, 열: 결과, 괄호는 v0)

| 정답 \ 결과 | fix | ok | unknown |
|---|---|---|---|
| fix | 23 (7) | 0 (0) | 0 (16) |
| ok | 0 (2) | 13 (2) | 1 (10) |
| unknown | 0 (0) | 0 (0) | 3 (3) |

### 해석

1. **문서 기준값 추출:** v0 13개 → v1 39개. 정답지 policy_values와 비교하면 `password.complexity_classes`(4번 참고)를 빼고 모두 맞습니다(관리망 CIDR 2개, 120일, 184일, 92일, 1095일 등). 아직 못 찾은 값은 `dr.drill_cycle_days`('매년 1회') 하나이고, `key.env_separation`은 문서에 없어 못 찾는 것이 정상입니다.
2. **범위 밖 계정 제외:** 777777777777 관련 과탐 7건이 모두 사라졌고, AR-2.5.3-02도 적합으로 바뀌었습니다.
3. **부분 수집 전파:** 666666666666의 미수집이 이제 S3를 쓰는 AR(2.7.1-03, 2.7.2-02, 2.9.4-03 등)에만 걸립니다. 그 결과 IAM·네트워크 AR의 적합 판정이 나옵니다(예: AR-2.5.2-02).
4. **남은 잔여 오류(판정에는 영향 없음):** `password.complexity_classes`를 여전히 4로 읽습니다(문서는 '4종 중 3종 이상'). `customer_password`는 조건부 규칙(2종 10자/3종 8자)을 10자/3종 하나로 합쳐 읽습니다. 이번 시나리오에서는 판정에 쓰이지 않았지만, Cognito를 쓰는 회사라면 결과가 달라질 수 있습니다.

## AR별 결과

일치: ◎ 엄격 일치, ○ 상태만 일치(subject 다름), ✕ 불일치. 'v0'은 v0 결과 분류

| AR | 정답 | v0 | 결과 (verdict) | 일치 | 놓친 subject | 과탐 subject | 정답지 why | 틀린 이유(추정) |
|---|---|---|---|---|---|---|---|---|
| AR-2.2.5-01 | fix | fix ◎ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | B2041 신○○ 10-26 퇴직, 3영업일 기한(10-29) 경과(5영업일)인데 콘솔·액세스 키 활성 | - |
| AR-2.5.1-01 | ok | fix ✕ | ok (CANDIDATE_CONFORMING) | ◎ | - | - | 절차 제3조에 전자결재 신청·팀장 승인 후 발급 절차가 있음 | - |
| AR-2.5.1-02 | fix | unknown ✕ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | data-oh 에게 인라인 정책(athena-adhoc-results)이 직접 붙어 있음 — 지침 제9조① 그룹으로만 부여 | - |
| AR-2.5.2-01 | fix | unknown ✕ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | b-dev 콘솔 사용자 이름 'test' — 지침 제8조②가 test 를 유추 가능 ID로 명시 금지 | - |
| AR-2.5.2-02 | ok | unknown ✕ | ok (CANDIDATE_CONFORMING) | ◎ | - | - | 콘솔을 쓰는 공용 계정 test 는 정보보안팀장 승인 기재. demo-shared 는 승인자 없지만 IAM에 존재하지 않음 | - |
| AR-2.5.3-01 | fix | fix ○ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | dev-moon 콘솔 비밀번호 사용, MFA 미등록 — 지침 제7조 | - |
| AR-2.5.3-02 | ok | fix ✕ | ok (CANDIDATE_CONFORMING) | ◎ | - | - | 범위 내 3개 계정 루트 모두 MFA 등록 (MFA 없는 루트는 범위 밖 샌드박스뿐) | - |
| AR-2.5.4-01 | ok | ok ◎ | ok (CANDIDATE_CONFORMING) | ◎ | - | - | 정보보안지침 제4·5조에 길이·조합·변경주기·재사용·초기 패스워드 변경 규정 | - |
| AR-2.5.4-02 | fix | fix ○ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | b-dev IAM 최소 길이 8 < 지침 9. b-prod 는 RequireSymbols=false 지만 지침은 4종 중 3종 조합이라 개별 필수 아님 → 충족. b-seclog 는 더 엄격 | - |
| AR-2.5.4-03 | fix | unknown ✕ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | ops-yoo 로그인 프로필 발급 시각과 비밀번호 변경 시각이 같고 이후 로그인, PasswordResetRequired=false — 초기 패스워드 미변경 사용 | - |
| AR-2.5.4-04 | fix | unknown ✕ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | b-prod dev-kang 비밀번호 2026-05-20 변경 후 166일 > 120일. sec-hwang 115일은 기한 안 | - |
| AR-2.5.4-05 | unknown | unknown ◎ | unknown (CANDIDATE_PARTIAL) | ◎ | - | - | 회원 로그인 있으나 Cognito 미사용, 가입·변경 화면 캡처 증적 미제출 → 적용 여부 확인 불가 | 정답과 일치 — 화면 캡처 사람 검토 대기, Cognito 미사용 |
| AR-2.5.5-01 | fix | unknown ✕ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | svc-deploy 가 CICD 그룹의 사용자 정의 정책 DeployPipeline(Action *, Resource *)으로 관리자 권한 보유, 특수권한자 현황에 없음 | - |
| AR-2.5.5-02 | ok | unknown ✕ | ok (CANDIDATE_CONFORMING) | ◎ | - | - | 활성 유지보수 계정 vendor-lms 사용기한 2026-12-31. vendor-old 는 기한 지났지만 비활성 | - |
| AR-2.5.6-01 | ok | unknown ✕ | ok (CANDIDATE_CONFORMING) | ◎ | - | - | 최근 검토 2026-05-15, 171일 ≤ 반기(184일) | - |
| AR-2.5.6-02 | fix | fix ○ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | svc-ci 액세스 키 2026-08-15 이후 79일 미사용인데 활성 — 지침 제8조④ 60일 | - |
| AR-2.5.6-03 | fix | unknown ✕ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | b-dev 유일한 trail(b-dev-trail)이 IncludeManagementEvents=false(S3 데이터 이벤트만) → IAM 변경 미기록 | - |
| AR-2.6.1-01 | fix | unknown ✕ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | RDS lms-prod-report PubliclyAccessible=true — 지침 제11조② | - |
| AR-2.6.1-02 | ok | unknown ✕ | ok (CANDIDATE_CONFORMING) | ◎ | - | - | 범위 내 모든 기본 보안그룹 규칙 0개 (규칙 남은 기본 SG는 샌드박스뿐) | - |
| AR-2.6.2-01 | fix | fix ○ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | dev-encoder-legacy 가 Telnet(23)을 10.50.0.0/16 에서 허용 — 지침 제12조② | - |
| AR-2.6.4-01 | fix | unknown ✕ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | DB SG가 VPN 대역 10.250.0.0/24 에서 3306 허용, 리포트 DB SG가 203.0.113.77/32 에서 5432 허용 — 지침 제11조③ | - |
| AR-2.6.6-01 | fix | unknown ✕ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | 배스천 RDP 3389를 192.0.2.0/24(관리망 /28보다 넓음)에서 허용, 개발 앱 SSH 22를 0.0.0.0/0 에서 허용 | - |
| AR-2.6.7-01 | ok | unknown ✕ | ok (CANDIDATE_CONFORMING) | ◎ | - | - | RDS 서브넷(b-prod data-a/c 명시 연결 rtb local만, b-dev data-a/c 메인 rtb local만)에 인터넷 기본 경로 없음 | - |
| AR-2.7.1-01 | fix | unknown ✕ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | 개발 DB(개인정보 포함, 운영 데이터 복제) StorageEncrypted=false | - |
| AR-2.7.1-02 | ok | unknown ✕ | ok (CANDIDATE_CONFORMING) | ◎ | - | - | 범위 내 모든 EBS 암호화 (aws/ebs 키 포함). 미암호화 볼륨은 샌드박스뿐 | - |
| AR-2.7.1-03 | fix | unknown ✕ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | 개인정보 포함 수료증 버킷이 AES256(SSE-S3) — 지침 제4조③ SSE-KMS | - |
| AR-2.7.1-04 | ok | unknown ✕ | ok (CANDIDATE_CONFORMING) | ◎ | - | - | 공개 HTTP 리스너(lms-web:80, dev-web:80)는 HTTPS 리다이렉트. lms-admin-internal:80 은 내부 전용 | - |
| AR-2.7.1-05 | fix | fix ◎ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | 공개 lms-api 443 보안정책 ELBSecurityPolicy-TLS-1-1-2017-01 이 TLS 1.1 허용 — 기준 TLS 1.2 이상 | - |
| AR-2.7.2-01 | fix | unknown ✕ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | 활성 고객 관리형 키 alias/pay-prod 자동 교체 꺼짐 — 지침 제7조 | - |
| AR-2.7.2-02 | unknown | unknown ◎ | unknown (INSUFFICIENT_EVIDENCE) | ◎ | - | - | B사 문서에 환경별 암호키 분리 조항이 없음 (b-dev 볼륨이 b-prod 키 사용하나 판단 기준 부재) | 정답과 일치. T1 `key.env_separation` 조항 부재를 맞게 인식. 결정 사유에는 666666666666 s3 미수집(T2)이 표시됨 — 결과는 같음 |
| AR-2.7.2-03 | fix | unknown ✕ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | 고객 관리형 키 alias/dev-app 이 암호키 관리대장에 없음 — 지침 제6조② | - |
| AR-2.9.3-01 | fix | fix ◎ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | 중요도 상 lms-prod-db 자동 백업 보관 7일 < 14일 (pay-prod-db 35일 충족) | - |
| AR-2.9.3-02 | ok | unknown ✕ | ok (CANDIDATE_CONFORMING) | ◎ | - | - | 중요도 상 자원 있는 b-prod(lms-prod-monthly), b-seclog(seclog-weekly) 모두 다른 리전 복사 계획 보유 | - |
| AR-2.9.3-03 | fix | unknown ✕ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | 최근 복구 테스트 2026-07-15, 110일 > 분기(92일) | - |
| AR-2.9.4-01 | ok | unknown ✕ | ok (CANDIDATE_CONFORMING) | ◎ | - | - | 범위 내 3개 계정 모두 기록 중인 trail 보유 (b-prod-trail-old 중지는 다른 활성 trail 있어 무관) | - |
| AR-2.9.4-02 | fix | unknown ✕ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | 기록 중인 b-dev-trail 로그 파일 검증 꺼짐 — 지침 제3조② | - |
| AR-2.9.4-03 | unknown | unknown ◎ | unknown (INSUFFICIENT_EVIDENCE) | ◎ | - | - | 기록 중인 trail 3개 모두 b-seclog 의 b-seclog-ct-archive 에 저장, b-seclog S3 수집 실패(partial)로 수명주기 확인 불가 | 정답과 일치. 이번에는 의도한 원인과 같음: `log.retention_days`=1095는 추출했고, T4 '판단 불가 3건'(중앙 로그 버킷 미수집) |
| AR-2.9.5-01 | fix | unknown ✕ | fix (CANDIDATE_NONCONFORMITY) | ◎ | - | - | b-dev GuardDuty 탐지기 존재하나 Status DISABLED | - |
| AR-2.9.5-02 | ok | ok ◎ | ok (CANDIDATE_CONFORMING) | ◎ | - | - | 최근 접속기록 점검 2026-10-12, 21일 ≤ 31일 | - |
| AR-2.12.2-01 | ok | unknown ✕ | unknown (CANDIDATE_PARTIAL) | ✕ | - | - | 최근 DR 훈련 2025-12-04, 333일 ≤ 366일 | T1 문서 추출 실패: `dr.drill_cycle_days` 못 찾음 (로그 지침 제8조 "매년 1회 이상 재해복구(DR) 모의훈련"). '매년'이 주기 어휘에 없거나, 조문이 일반 문단으로 쓰여 있어 놓친 것으로 추정. 기준값이 없어 T3 주기 검사를 하지 못하고 CANDIDATE_PARTIAL로 끝남 |

## 틀린 AR 목록

- 상태 불일치 (1): AR-2.12.2-01
- 상태는 맞지만 subject 불일치 (0): 없음
