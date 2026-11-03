# C사(c-corp-eval) 평가 결과 — result_v2

> **블라인드 평가**: 규칙 작성 측은 시나리오를 열어 보지 않고 실행(코드 커밋 `d9e22c2`). 결과 파일 `/tmp/c_eval/result_v2.json`(result_hash `dc4305a6…`), 정답지 `c_corp_answer_key.yaml`(sha256 `b72cca36…387eb`, 채점 전 해시 일치 확인, 수정 없음).

## 점수 요약

| 지표 | 값 |
|---|---|
| AR 상태 일치 | **36/49 (73.5%)** |
| AR 엄격 일치 (상태 + fix subject 집합 동일) | **34/49 (69.4%)** — AR-2.5.1-01의 문서 수준 subject('정책 문서' vs 정답 빈 집합) 형식 차이를 인정하면 35/49 |
| 결함 대상(subject) TP / FN / FP | 23 / 14 / 2 |
| 정밀도 | 92.0% (23/25) |
| 재현율 | 62.2% (23/37) |
| 위험 오류: 정답 fix → 결과 ok | **0건** |
| 위험 오류: 정답 ok/unknown → 결과 fix | **1건** (AR-1.1.2-01) |
| 1.x 관리체계 (9개) 상태 일치 | 5/9 |
| 2.x 보호대책 (40개) 상태 일치 | 31/40 |

FP 2건: `정책 문서`(AR-1.1.2-01, 실제 과탐), `정책 문서`(AR-2.5.1-01, 상태는 맞고 정답지 subject 형식 차이). 범위 제외 계정(801000000009) subject는 0건 — 범위 함정 통과.

### 혼동 행렬 (행 = 정답, 열 = 결과)

| 정답 \ 결과 | fix | ok | unknown | 합계 |
|---|---|---|---|---|
| fix | 22 | 0 | 10 | 32 |
| ok | 1 | 10 | 2 | 13 |
| unknown | 0 | 0 | 4 | 4 |

### 틀린 원인 요약

- 상태 불일치 13건은 모두 원인이 같다: **정책 문서에서 기준값·근거 조항을 추출하지 못함(T1 fail)**. 12건은 비교 테스트가 gap이 되어 CANDIDATE_PARTIAL로 끝났다. 기술 관측·증적 판독은 모두 통과했다. 놓친 표현: '임명', '반기마다', '…가 승인하고 …는 CISO가 승인', '180일을 넘기지 않고', '60일 … 잠금 처리', '3영업일 이내'(조 없는 절차서 형식), 'CloudTrail을 전 리전 대상으로 활성화', '보안그룹을 출발지로 지정하는 방식으로만', '라우팅 테이블에는 … 경로를 두지 않는다', '백업 보관기간을 14일 이상', '일반 명칭은 계정 ID로 쓰지 않는다', '개선조치 관리대장에 기록'.
- 나머지 1건인 AR-1.1.2-01은 '조항 부재 = 결함'형 AR이라 추출 실패가 **과탐(위험 오류)** 으로 이어졌다.
- 엄격 일치에서만 틀린 2건: AR-2.5.4-02(비밀번호 주기·재사용 미추출로 c-sec 놓침), AR-2.5.1-01(subject 형식).

## AR별 결과

| AR | 정답 | 결과 | 일치 | 놓침 subject | 과탐 subject | 정답지 why | 틀린 이유(추정) / 참고 |
|---|---|---|---|---|---|---|---|
| AR-1.1.2-01 | ok | fix (CANDIDATE_NONCONFORMITY) | X |  | 정책 문서 | 정책 C-POL-01 제3조①이 정보보호 최고책임자(CISO) 임명을 정함 | 정책 C-POL-01 제3조①이 '정보보호 최고책임자(CISO)로 **임명**한다'로 표현됨. 추출기가 '지정' 계열 표현만 찾은 것으로 보임 → ciso_designated 미추출 → 조항 부재로 오판(과탐) |
| AR-1.1.3-01 | fix | unknown (CANDIDATE_PARTIAL) | X | 정보보호위원회 회의록 |  | 정책 제4조② 반기(184일). 위원회 마지막 개최 2026-03-27(임시) → 220일. 2026-06·09 행은 실무협의회로 위원회가 아님(제5조) | 정책 제4조② '반기마다 정기회의를 개최'에서 committee.cycle_days 미추출 → T3 gap. (회의 목록 5행은 판독됨. 실무협의회 행 구분 함정은 시험되지 않음) |
| AR-1.1.5-01 | fix | unknown (CANDIDATE_PARTIAL) | X | C-PRC-03 |  | 정책 제6조② 승인권자 대표이사·CISO. 계정관리 절차 승인자가 정보보호파트장. 내부관리계획의 'CISO'는 승인권자와 같음 | 정책 제6조② '정책은 대표이사가 승인하고, 규정·지침·절차 및 계획은 CISO가 승인'에서 policy.approvers 미추출 → T3 gap. 문서별 승인자(T2)는 5건 모두 판독됨 |
| AR-1.1.5-02 | fix | fix (CANDIDATE_NONCONFORMITY) | O |  |  | 정책 제7조 매년 검토. 로그 및 백업 관리지침 마지막 이력 2025-06-30 → 490일. 통합규정은 2026-07-14 검토 이력(변경 없음)이 있어 충족 |  |
| AR-1.2.1-01 | fix | fix (CANDIDATE_NONCONFORMITY) | O |  |  | 정책 제9조. c-prod 급여 이관 버킷과 c-dev 급여 복제 DB가 정보자산 목록에 없음 (c-sec S3는 수집 실패라 판단 대상 아님) | 참고: c-sec s3 미수집이 있어도 확인된 위반 2건으로 fix — 정답과 같음 |
| AR-1.2.3-01 | unknown | unknown (INSUFFICIENT_EVIDENCE) | O |  |  | 정책 제10조 매년 위험평가. 위험평가 기록이 제출되지 않음 (위원회 안건에 '위험평가 결과' 언급뿐, 평가일 기록 없음) | 참고: 위험평가 기록 미제출로 판단 보류 — 정답 근거와 같음 |
| AR-1.4.1-01 | fix | fix (CANDIDATE_NONCONFORMITY) | O |  |  | 로그 및 백업 관리지침 제1조가 고시 제2023-6호 인용 (현행 제2026-9호). 내부관리계획 제1조는 현행 번호, 통합규정 제1조는 법률만 인용 |  |
| AR-1.4.2-01 | ok | ok (CANDIDATE_CONFORMING) | O |  |  | 정책 제11조 연 1회. 마지막 점검 2026-06-17 → 138일 |  |
| AR-1.4.3-01 | fix | unknown (CANDIDATE_PARTIAL) | X | 조치 CA-26-05, 조치 CA-26-07 |  | 정책 제12조. CA-26-05 기한 2026-10-15 지남·조치중, CA-26-07 완료예정일 없음·검토중. CA-26-03은 '조치완료'(완료), CA-26-04·06은 기한 전 | 정책 제12조 '조치 담당자와 완료 기한을 정하여 개선조치 관리대장에 기록'에서 improve.tracking_required 미추출 → T3 gap. 관리대장 7행은 판독됨 |
| AR-2.2.5-01 | fix | unknown (CANDIDATE_PARTIAL) | X | 801000000001/jhkim, 801000000002/sypark |  | 절차 5.나 퇴직 후 3영업일. jhkim(E2041) 10-08 퇴직, 콘솔 활성. sypark(E2019) 09-18 퇴직, 콘솔은 지웠으나 액세스 키 활성. hwang.yr(E2077) 10-29 퇴직은 2영업일로 기한 안, lim.ga는 휴직, oh.ks는 회수 완료 | 기한이 계정관리 절차(C-PRC-03) '5. 퇴직자 계정 회수 — 나. 퇴직일로부터 3영업일 이내'에 있음. 이 문서는 조(제N조) 없이 '1.~6.' 장과 '가.~라.' 목으로 되어 있어 offboarding_business_days 미추출로 보임 → T5 gap |
| AR-2.5.1-01 | fix | fix (CANDIDATE_NONCONFORMITY) | 상태만 O |  | 정책 문서 | 계정관리 절차 3항은 메신저·이메일 요청 후 담당자 확인만으로 계정 생성 — 발급 전 승인(신청서·결재) 절차가 어느 문서에도 없음 (특수권한·공용계정 승인만 있음). 문서 수준 결함 | 상태는 일치(조항 부재 → fix). 결과 subject '정책 문서'는 정답지가 문서 수준 결함 subjects를 비워 둔 것과 형식만 달라 엄격 기준에서 불일치로 셈(실질 일치) |
| AR-2.5.1-02 | fix | fix (CANDIDATE_NONCONFORMITY) | O |  |  | 규정 제9조 그룹으로만 부여. dev-cho에 인라인 정책 EmergencyFullAccess 직접 부여 |  |
| AR-2.5.2-01 | ok | unknown (CANDIDATE_PARTIAL) | X |  |  | 규정 제4조①. 범위 내 콘솔 사용자 중 admin·test·guest 같은 일반 명칭 없음. sysadmin-hong은 개인 식별 가능, *-shared는 공용 계정 문제(2.5.2-02)로 별도. 샌드박스 'test'는 범위 제외 | 규정 제4조① '…일반 명칭은 계정 ID로 쓰지 않는다'에서 no_guessable_id 미추출 → T3 gap → 판단 보류. 정답은 대상 위반 0건이라 ok |
| AR-2.5.2-02 | fix | fix (CANDIDATE_NONCONFORMITY) | O |  |  | 규정 제4조② 정보보호파트장 승인. qa-shared는 사번 없이 콘솔 사용, 승인자 없음. ops-shared는 승인 기록 있음, batch-shared는 콘솔 미사용 |  |
| AR-2.5.3-01 | fix | fix (CANDIDATE_NONCONFORMITY) | O |  |  | 규정 제7조 콘솔 2단계 인증. choi.mr 콘솔 비밀번호 사용·MFA 없음. 서비스 계정은 콘솔 없음, 샌드박스는 범위 제외 |  |
| AR-2.5.3-02 | ok | ok (CANDIDATE_CONFORMING) | O |  |  | 범위 내 3개 계정 루트 모두 MFA. 샌드박스 루트 MFA 없음은 범위 제외 |  |
| AR-2.5.4-01 | ok | ok (CANDIDATE_CONFORMING) | O |  |  | 규정 제6조에 길이·조합·주기·재사용·임시 비밀번호 규칙 모두 있음 |  |
| AR-2.5.4-02 | fix | fix (CANDIDATE_NONCONFORMITY) | 상태만 O | 801000000003 |  | 규정 제6조 12자·3종 이상·180일·5회. c-dev 최소 10자. c-sec 만료 없음(ExpirePasswords false)이고 소문자·숫자 2종만 요구. c-prod는 12자·4종·180일·5회로 충족. 샌드박스(정책 없음)는 범위 제외 | T1이 password.min_length만 추출. 제6조② '180일을 넘기지 않고 변경'(max_age_days), ③ '최근 사용한 5개…다시 쓸 수 없다'(reuse_prevention) 미추출, '3종류 이상'(complexity_classes)은 계정의 require_* 비교에 쓰이지 않음 → c-sec(만료 없음·2종만 요구) 놓침. c-dev(10자)만 검출 |
| AR-2.5.4-03 | fix | fix (CANDIDATE_NONCONFORMITY) | O |  |  | 규정 제6조④. yoon.hj 발급 시각(10-20 01:00:02)과 마지막 변경이 같고 이후 로그인, 재설정 요구 없음. lee.jw는 발급 2시간 뒤 변경 |  |
| AR-2.5.4-04 | fix | unknown (CANDIDATE_PARTIAL) | X | 801000000003/sec.kang |  | 규정 제6조② 180일. sec.kang 2026-03-15 변경 → 232일. sysadmin-hong 176일은 기간 안 | 제6조② '180일을 넘기지 않고 변경'에서 password.max_age_days 미추출 → T3 gap |
| AR-2.5.4-05 | fix | fix (CANDIDATE_NONCONFORMITY) | O |  |  | 규정 제8조 이용자 10자 이상. 직원 로그인 사용자 풀 최소 8자 (화면 안내 문구는 10자라 화면만 보면 놓침). 고객사 관리자 풀은 12자로 충족 |  |
| AR-2.5.5-01 | fix | fix (CANDIDATE_NONCONFORMITY) | O |  |  | 규정 제10조①. kim.dh는 PlatformAdmins 그룹(AdministratorAccess), dev-cho는 인라인 '*:*' — 둘 다 특수권한자 현황에 없음. sec.kang(IAMFullAccess)·park.sj는 등재. PowerUserAccess·PayrollBatch(s3:* 특정 버킷)는 관리자 권한 아님 |  |
| AR-2.5.5-02 | fix | fix (CANDIDATE_NONCONFORMITY) | O |  |  | 규정 제10조②. 사용기한 2026-09-30 지났는데 활성. vendor-qa는 기한 지났지만 비활성, vendor-soc는 2027-03-31 |  |
| AR-2.5.6-01 | ok | ok (CANDIDATE_CONFORMING) | O |  |  | 규정 제11조 반기(184일). 마지막 검토 2026-05-20 → 166일 |  |
| AR-2.5.6-02 | fix | unknown (CANDIDATE_PARTIAL) | X | 801000000001/svc-report-export |  | 규정 제12조 60일. 액세스 키 마지막 사용 2026-07-01 → 124일인데 활성. 나머지 활성 사용자는 60일 안 | 제12조 '60일 이상 사용 기록이 없는 계정(액세스 키 포함)은 잠금 처리'에서 account.inactive_days 미추출('비활성화' 대신 '잠금' 표현) → T3 gap |
| AR-2.5.6-03 | fix | unknown (CANDIDATE_PARTIAL) | X | 801000000002/cloudtrail |  | 지침 C-GDL-07 제3조① 전 리전·읽기쓰기 기록. c-dev-audit는 기록 중이지만 ReadWriteType=ReadOnly라 IAM 변경(쓰기)이 남지 않음 | 지침 C-GDL-07 제3조① 'CloudTrail을 전 리전 대상으로 활성화하여 관리 이벤트(읽기·쓰기)를 빠짐없이 기록'에서 log.audit_trail_required 미추출 → T3 gap. ReadOnly trail 수집(T2)은 정상 |
| AR-2.6.1-01 | fix | fix (CANDIDATE_NONCONFORMITY) | O |  |  | 규정 제13조②. 스테이징 급여 DB 퍼블릭 액세스 켜짐. 샌드박스는 범위 제외 |  |
| AR-2.6.1-02 | ok | ok (CANDIDATE_CONFORMING) | O |  |  | 규정 제13조⑤. 범위 내 기본 보안그룹 3개 모두 규칙 0개. 'dev-default-app'은 기본 보안그룹이 아님. 샌드박스는 범위 제외 |  |
| AR-2.6.2-01 | fix | fix (CANDIDATE_NONCONFORMITY) | O |  |  | 규정 제15조. dev-legacy-batch 보안그룹이 Telnet(23)을 10.20.0.0/16에서 허용. 샌드박스 FTP는 범위 제외 |  |
| AR-2.6.4-01 | fix | unknown (CANDIDATE_PARTIAL) | X | 801000000001/sg-0c1db0000000001 |  | 규정 제13조③. prod-db 보안그룹에 앱 SG 규칙과 함께 5432를 IP 대역 10.250.0.0/24(DBA VPN)에서 허용. prod-cache는 Role=database 태그가 있지만 RDS에 붙지 않음 | 규정 제13조③ '애플리케이션 영역 보안그룹을 출발지로 지정하는 방식으로만…IP 대역을 출발지로 지정하지 않는다'에서 network.db_from_app_only 미추출 → T3 gap |
| AR-2.6.6-01 | fix | fix (CANDIDATE_NONCONFORMITY) | O |  |  | 규정 제14조 관리망 192.0.2.32/27·10.250.0.0/24. soc-tools RDP 3389를 192.0.2.0/24(관리망보다 넓음)에서 허용. 배스천 192.0.2.40/32와 dev 10.250.0.0/24는 관리망 안 |  |
| AR-2.6.7-01 | fix | unknown (CANDIDATE_PARTIAL) | X | 801000000002/subnet-0c2pub00000000a, 801000000002/subnet-0c2pub00000000c |  | 규정 제13조④. stg-payroll 서브넷 그룹이 퍼블릭 서브넷(IGW 기본 경로)을 씀. c-prod 데이터 서브넷은 피어링 경로만, 앱 서브넷 NAT는 DB 영역 아님 | 규정 제13조④ '데이터 영역 서브넷의 라우팅 테이블에는 인터넷 게이트웨이나 NAT 게이트웨이로 향하는 경로를 두지 않는다'에서 network.db_no_internet 미추출 → T3 gap |
| AR-2.7.1-01 | fix | fix (CANDIDATE_NONCONFORMITY) | O |  |  | 규정 제16조①. dev-payroll-clone 저장 암호화 꺼짐 (자산 목록에도 없는 DB) |  |
| AR-2.7.1-02 | ok | ok (CANDIDATE_CONFORMING) | O |  |  | 규정 제16조②. 범위 내 EBS 모두 암호화 (분리된 볼륨·aws/ebs 키 포함). 샌드박스는 범위 제외 |  |
| AR-2.7.1-03 | fix | fix (CANDIDATE_NONCONFORMITY) | O |  |  | 규정 제16조③. 개인정보(Y) 급여명세서 버킷이 SSE-S3(AES256). tenant-uploads는 KMS. 목록에 없는 이관 버킷은 이 AR 모집단 밖(1.2.1에서 지적) |  |
| AR-2.7.1-04 | ok | ok (CANDIDATE_CONFORMING) | O |  |  | 규정 제17조. 공개 리스너는 HTTPS이거나 80→HTTPS 전환. prod-internal-admin HTTP:8080은 내부 전용. 샌드박스 poc-web HTTP는 범위 제외 |  |
| AR-2.7.1-05 | fix | fix (CANDIDATE_NONCONFORMITY) | O |  |  | 규정 제17조 TLS 1.2 이상. prod-api 443 보안정책 ELBSecurityPolicy-TLS-1-1-2017-01이 TLS 1.1 허용. 내부 ALB의 2016-08 정책은 인터넷 구간 아님 |  |
| AR-2.7.2-01 | fix | fix (CANDIDATE_NONCONFORMITY) | O |  |  | 규정 제18조②. c-dev 고객 관리형 키 alias/dev-app 자동 교체 꺼짐. c-prod alias/prod-legacy-2024는 비활성 키라 대상 아님 |  |
| AR-2.7.2-02 | unknown | unknown (INSUFFICIENT_EVIDENCE) | O |  |  | 환경별 암호키 분리 조항이 어느 문서에도 없음 → AR 전제 미충족(판단 보류). stg-payroll이 c-prod 키를 쓰지만 이 AR로 결함 단정 불가 | 참고: key.env_separation 미추출(정답 근거와 같음)과 c-sec s3 미수집이 함께 판단 보류 사유 |
| AR-2.7.2-03 | fix | fix (CANDIDATE_NONCONFORMITY) | O |  |  | 규정 제18조①. c-sec alias/soc-forensics가 암호키 관리대장에 없음. 비활성 legacy 키는 대장에 등재 |  |
| AR-2.9.3-01 | fix | unknown (CANDIDATE_PARTIAL) | X | 801000000001/prod-payroll |  | 지침 제5조① 중요도 상 DB 14일 이상. prod-payroll 7일. prod-tenant-core 35일. stg-payroll(중)·dev-payroll-clone(목록 없음)은 대상 아님 | 지침 제5조① '백업 보관기간을 14일 이상으로 설정'에서 backup.retention_days 미추출 → T4 gap |
| AR-2.9.3-02 | fix | fix (CANDIDATE_NONCONFORMITY) | O |  |  | 지침 제5조②. c-sec는 중요도 상 자원(SIEM 서버) 보유, 백업 계획 자체가 없음. c-prod는 prod-weekly-dr에 오사카 복사 있음, c-dev는 상 자원 없음 |  |
| AR-2.9.3-03 | ok | ok (CANDIDATE_CONFORMING) | O |  |  | 지침 제5조③ 분기(92일). 마지막 복구 시험 2026-09-10 → 53일 |  |
| AR-2.9.4-01 | ok | unknown (CANDIDATE_PARTIAL) | X |  |  | 지침 제3조①. 범위 내 3개 계정 모두 기록 중인 trail 있음 (c-prod 구 trail 중지는 무관). 샌드박스는 범위 제외 | log.audit_trail_required 미추출(2.5.6-03과 같은 원인) → T3 gap → 판단 보류. 정답은 범위 내 3개 계정 모두 기록 중이라 ok |
| AR-2.9.4-02 | fix | fix (CANDIDATE_NONCONFORMITY) | O |  |  | 지침 제3조②. c-sec-audit 무결성 검증 꺼짐. 중지된 c-prod-legacy-trail은 기록 중이 아니라 대상 아님 |  |
| AR-2.9.4-03 | unknown | unknown (INSUFFICIENT_EVIDENCE) | O |  |  | 지침 제3조③ 3년. c-prod·c-sec trail 저장 버킷(c-sec-central-audit-logs)이 c-sec S3 수집 실패로 보관기간 확인 불가. c-dev 버킷은 1500일로 충족 | 참고: 결과는 맞지만 이유가 둘 겹침 — log.retention_days 후보 [1095(C-GDL-07 감사 로그 3년), 730(C-PIP-01 접속기록 2년)] 충돌로 T1 품질 실패, 그리고 c-sec s3 미수집. 정답 근거는 후자 |
| AR-2.9.5-01 | unknown | unknown (INSUFFICIENT_EVIDENCE) | O |  |  | 지침 제4조. c-prod·c-sec는 GuardDuty ENABLED, c-dev는 수집 권한 거부로 확인 불가. 샌드박스는 범위 제외 | 참고: c-dev guardduty.json 미수집으로 판단 보류 — 정답 근거와 같음 |
| AR-2.9.5-02 | ok | ok (CANDIDATE_CONFORMING) | O |  |  | 내부관리계획 제4조② 분기(92일). 마지막 점검 2026-09-29 → 34일 (월 단위로 보면 오판) |  |
| AR-2.12.2-01 | ok | ok (CANDIDATE_CONFORMING) | O |  |  | 지침 제6조 연 1회. 마지막 훈련 2026-04-23 → 193일 |  |
