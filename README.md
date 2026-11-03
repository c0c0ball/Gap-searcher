# ISMS-P 갭분석 자동화 (isms-gap)

정책·증적·클라우드 설정을 ISMS-P 요구사항과 대조해 **결함 후보와 미확인 항목**을 찾아 주는 웹서비스입니다.
인증 적합 여부를 대신 판정하지 않으며, 모든 결과는 사람이 검토·승인한 뒤에만 외부에 표기합니다.

현재 단계: **1~4단계 완료 — 2.5.4 비밀번호 관리를 입력부터 보고서까지 관통** (자세한 내용: [docs/진행기록.md](docs/진행기록.md))

## 구성

| 서비스 | 역할 | 포트 |
|---|---|---|
| web | Next.js 화면 | 3000 |
| api | FastAPI | 8000 |
| worker | Celery — 관측·판정 작업 실행 | – |
| postgres | PostgreSQL 16 + pgvector | 5432 |
| redis | 작업 큐 | – |
| minio | 원본·파생본 저장 (콘솔 9001) | 9000, 9001 |
| clamav | 업로드 검역 (clamd) | – |
| Ollama | 로컬 LLM — **Mac에 직접 설치** (Docker는 Metal GPU를 못 씀) | 11434 |

## 실행 (Mac, Apple Silicon)

```bash
# 1) Ollama 설치 후 모델 받기
brew install ollama          # 또는 https://ollama.com 에서 앱 설치
ollama serve &               # 앱으로 설치했다면 생략
ollama pull qwen3:8b
ollama pull bge-m3

# 2) 환경 변수
cp .env.example .env         # 비밀번호 값은 바꿔도 되고 로컬 전용이면 그대로 둬도 됨

# 3) 기동
docker compose up --build
```

브라우저에서 http://localhost:3000 을 엽니다.

| 화면 | 하는 일 |
|---|---|
| `/` 대시보드 | 최근 점검의 항목별 상태 띠, 담당자별 남은 일, 최근 실행 |
| `/checklist` 전체 점검표 | ISMS-P 인증기준 101개·확인사항 328개 전체. 자동 점검 결과를 보여 주고, 나머지는 담당자가 결함/결함 없음/해당 없음으로 판단·증적 첨부, xlsx 내려받기 |
| `/tasks` 할 일 | 고칠 부분을 담당자별로 모아 보고 완료를 표시 |
| `/upload` 자료 올리기 | 작업공간 만들기, 규정 문서·증적 업로드 → 검역·조항 읽기·규칙 추출 미리보기 → 바로 진단 |
| `/runs` 진단 실행 | 예제나 작업공간을 골라 실행, 실행 기록 |
| `/runs/<id>` 결과 | 쉬운 보기(직원용) / 담당자 보기(근거·승인·반려), 보고서 다운로드 |
| `/system` 시스템 상태 | 구성요소 연결, worker 왕복, 규칙 검사 |

화면 테마는 사이드바 아래에서 시스템 따라감 / 어둡게 / 밝게로 바꿀 수 있습니다.

- **ClamAV**는 첫 기동 때 시그니처를 받느라 몇 분 동안 빨간색일 수 있습니다.
- **worker 왕복**은 "확인" 버튼을 눌러야 검사합니다 (api → redis → worker → api).
- **요구사항 lint**는 `오류 0건 · 경고 29건`이 정상입니다. 경고는 자동 점검 없이 사람이 확인하도록 남겨 둔 확인사항입니다 (YAML의 note에 이유).

## 명령줄

```bash
cd backend && pip install -e '.[dev]'
gapcheck run ../scenarios/a-corp-dev            # 실행 → runs/<id>/result.json, report.xlsx, summary.md
gapcheck check ../scenarios/a-corp-dev          # 개발용 정답지와 비교
gapcheck run ../scenarios/a-corp-dev --llm      # Ollama 문서 추출 함께 사용
gapcheck collect --targets targets.yaml --out ../scenarios/my-live/aws-snapshot   # live AWS 수집
pytest                                          # 테스트 155개
```

`targets.yaml` 예시 (커밋하지 말 것):

```yaml
targets:
  - {account_id: "123456789012", alias: sandbox, role_arn: "arn:aws:iam::123456789012:role/gapcheck-collector", external_id: "임의-문자열"}
```

## 요구사항(AR) lint

```bash
cd backend && pip install -e '.[dev]'
cd .. && python -m gapcheck.compiler requirements sources   # 또는 gapcheck-lint
cd backend && pytest
```

| 규칙 | 막는 것 |
|---|---|
| RC-000 | 스키마 위반, 정의되지 않은 필드 (원문 복제용 필드 차단) |
| RC-001 | AR id 형식·중복 |
| RC-002 | Registry에 없는 원천 / 미검증 원천을 쓰는 active AR |
| RC-003 | 관측 축이 하나뿐인 적합 경로 (사유 없이) |
| RC-004 | 비활성 법정 파라미터를 기준값으로 사용 / 상수를 관측값으로 사용 |
| RC-005 | 존재하지 않는 테스트·산출값 참조 |
| RC-006 | 모집단 없이 주기·범위 검사 |
| RC-007 | 질의 답변만으로 적합 |
| RC-008 | 질의 답변을 결함 근거로 사용 |
| RC-009 | 확인사항 커버리지 누락 |
| RC-010 | 근거 없는 적용/제외 기본값 |

## 폴더

```
requirements/      AR YAML (공개) — 원문 대신 위치와 자체 요약만
scenarios/         가상기업 시나리오 (공개, 개발용) — a-corp-dev
runs/              실행 결과·검토 기록 (gitignore)
assessments/       전체 점검표 판단·증적 (gitignore)
docs/              진행 기록
sources/           Source Registry, 법정 파라미터 overlay (공개, 메타데이터만)
data/              원문 사본·코퍼스·가상기업 자료 (비공개, gitignore)
backend/gapcheck/  api, worker, compiler, ingest, normalize, observe, rules, adjudicate, attribution, report
web/               Next.js
db/init.sql        pgvector 활성화
```

## 자동 점검 범위

| 기준 | 자동 점검 | 쓰는 자료 |
|---|---|---|
| 1.1.2 최고책임자 지정 | 정책에 CISO 지정 조항 | 정보보호 정책서 |
| 1.1.3 조직 구성 | 정보보호위원회 개최 주기 | 정책서, 위원회 회의록 목록 |
| 1.1.5 정책 수립 | 정책·지침의 승인권자, 정기 검토(개정 이력) | 정책서, 각 문서의 표지·개정 이력 표 |
| 1.2.1 정보자산 식별 | 실제 RDS·S3가 정보자산 목록에 있는지 | 정책서, 정보자산 목록, AWS |
| 1.2.3 위험 평가 | 위험평가 주기 | 정책서, 위험평가 기록 |
| 1.4.1 법적 요구사항 | 규정이 인용한 안전성 확보조치 기준이 현행 고시인지 | 규정 문서, Source Registry |
| 1.4.2 관리체계 점검 | 내부 감사 주기 | 정책서, 내부 감사 기록 |
| 1.4.3 관리체계 개선 | 기한 지난 미완료 개선 조치 | 정책서, 개선조치 관리대장 |
| 2.2.5 퇴직 및 직무변경 | 퇴직자 계정 회수 기한(영업일) | 절차서, 인사 명부, 계정 관리대장, IAM |
| 2.5.1 사용자 계정 | 신청·승인 절차, 직무 그룹으로만 권한 부여 | 절차서·지침, IAM 권한 상세 |
| 2.5.2 사용자 식별 | 추측하기 쉬운 계정 이름, 공용 계정 승인 | 지침, 계정 관리대장, IAM |
| 2.5.3 사용자 인증 | 콘솔 사용자 MFA, 루트 MFA | 지침, credential report |
| 2.5.4 비밀번호 | 작성규칙·임시 비밀번호·변경 주기·회원 비밀번호 | 지침, IAM·Cognito |
| 2.5.5 특수 계정·권한 | 관리자 권한 ↔ 특수권한자 목록, 유지보수 계정 기한 | 지침, IAM 권한 상세, 목록·관리대장 |
| 2.5.6 접근권한 검토 | 검토 주기 이행, 장기 미사용 계정, 계정·권한 변경 이력(감사 로그) | 지침, 검토 기록, credential report, CloudTrail |
| 2.6.1 네트워크 접근 | DB 공인 접근 차단, 기본 보안그룹 규칙 없음 | 지침, RDS, 보안그룹 |
| 2.6.2 정보시스템 접근 | telnet·FTP 등 평문 프로토콜 포트 차단 | 지침, 보안그룹 |
| 2.6.4 데이터베이스 접근 | DB 보안그룹은 애플리케이션 보안그룹에서만 | 지침, 보안그룹, RDS |
| 2.6.6 원격접근 통제 | SSH·RDP는 지정 관리망에서만 | 지침(관리망 대역), 보안그룹 |
| 2.6.7 인터넷 접속 통제 | DB 서브넷에 인터넷 기본 경로 없음 | 지침, 서브넷·라우팅, RDS |
| 2.7.1 암호정책 적용 | DB·디스크 저장 암호화, 개인정보 S3 KMS 암호화, 공개 HTTP 평문 리스너, 최소 TLS | 암호통제 지침, RDS·EBS·S3·ALB, 정보자산 목록 |
| 2.7.2 암호키 관리 | KMS 자동 교체, 다른 계정 키 사용, 암호키 관리대장 등록 | 암호통제 지침, KMS·RDS·EBS·S3, 암호키 관리대장 |
| 2.9.3 백업 및 복구관리 | 중요 DB 백업 보관기간, 다른 리전 복사, 복구 테스트 주기 | 운영보안 지침, RDS·AWS Backup, 정보자산 목록, 복구 테스트 기록 |
| 2.9.4 로그 및 접속기록 관리 | 감사 로그 기록, 무결성 검증, 로그 보관기간 | 운영보안 지침, CloudTrail, S3 수명주기 |
| 2.9.5 로그 및 접속기록 점검 | 이상 행위 탐지(GuardDuty), 접속기록 점검 주기 | 운영보안 지침, GuardDuty, 접속기록 점검 기록 |
| 2.12.2 재해 복구 시험 | 재해 복구 훈련 주기 | 운영보안 지침, 재해 복구 훈련 기록 |

증적 엑셀은 파일 이름이 아니라 첫 줄 제목 칸으로 종류를 알아냅니다 (계정 관리대장, 인사 명부, 특수권한자 목록, 접근권한 검토 기록, 정보자산 목록, 암호키 관리대장, 접속기록 점검 기록, 백업 복구 테스트 기록, 재해 복구 훈련 기록, 정보보호위원회 회의록 목록, 위험평가 기록, 내부 감사 기록, 개선조치 관리대장).
규정 문서(docx)는 조항뿐 아니라 표지(승인자·시행일)와 개정 이력 표, 법령 인용(고시 번호)도 관측으로 씁니다.
규칙은 YAML만으로 씁니다. 대상별 검사(`SUBJECT_CHECK`)로 모집단 거르기, 다른 자료와 대조, 영업일 유예를 표현합니다.

## 안내서 정리본 (비공개 파일)

전체 점검표에 인증기준·확인사항·결함사례 문장을 보여 주려면 `data/sources/ISMS-P_인증기준_2023-11.json`이 있어야 합니다.
이 파일은 KISA 안내서를 정리한 것이라 저장소에 올리지 않습니다. 없으면 번호·이름·쪽수만 보이고 판단 기록은 그대로 됩니다.
저장소에는 문장 없는 뼈대(`sources/ismsp_catalog_skeleton.json`)만 있습니다.

## 데이터·라이선스 원칙

- 코드만 공개하고 데이터는 공개하지 않습니다 (`data/`는 gitignore).
- KISA 자료는 공공누리 제4유형(변경금지)이므로 원문을 저장소에 복제하지 않습니다.
- 비교 기준값은 조직 자체 정책 문서에서 뽑은 값이 기본입니다. 법정 수치는 원문 대조 후 `active: true`인 것만 씁니다.

## 다음 할 일

[docs/진행기록.md](docs/진행기록.md)의 "다음 할 일"을 참고하세요.
