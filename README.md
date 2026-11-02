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
| `/tasks` 할 일 | 고칠 부분을 담당자별로 모아 보고 완료를 표시 |
| `/upload` 자료 올리기 | 작업공간 만들기, 규정 문서·증적 업로드 → 검역·조항 읽기·규칙 추출 미리보기 → 바로 진단 |
| `/runs` 진단 실행 | 예제나 작업공간을 골라 실행, 실행 기록 |
| `/runs/<id>` 결과 | 쉬운 보기(직원용) / 담당자 보기(근거·승인·반려), 보고서 다운로드 |
| `/system` 시스템 상태 | 구성요소 연결, worker 왕복, 규칙 검사 |

화면 테마는 사이드바 아래에서 시스템 따라감 / 어둡게 / 밝게로 바꿀 수 있습니다.

- **ClamAV**는 첫 기동 때 시그니처를 받느라 몇 분 동안 빨간색일 수 있습니다.
- **worker 왕복**은 "확인" 버튼을 눌러야 검사합니다 (api → redis → worker → api).
- **요구사항 lint**는 `오류 0건 · 경고 6건`이 정상입니다. 경고는 아래 "다음 할 일"이 끝나면 줄어듭니다.

## 명령줄

```bash
cd backend && pip install -e '.[dev]'
gapcheck run ../scenarios/a-corp-dev            # 실행 → runs/<id>/result.json, report.xlsx, summary.md
gapcheck check ../scenarios/a-corp-dev          # 개발용 정답지와 비교
gapcheck run ../scenarios/a-corp-dev --llm      # Ollama 문서 추출 함께 사용
gapcheck collect --targets targets.yaml --out ../scenarios/my-live/aws-snapshot   # live AWS 수집
pytest                                          # 테스트 81개
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
docs/              진행 기록
sources/           Source Registry, 법정 파라미터 overlay (공개, 메타데이터만)
data/              원문 사본·코퍼스·가상기업 자료 (비공개, gitignore)
backend/gapcheck/  api, worker, compiler, ingest, normalize, observe, rules, adjudicate, attribution, report
web/               Next.js
db/init.sql        pgvector 활성화
```

## 데이터·라이선스 원칙

- 코드만 공개하고 데이터는 공개하지 않습니다 (`data/`는 gitignore).
- KISA 자료는 공공누리 제4유형(변경금지)이므로 원문을 저장소에 복제하지 않습니다.
- 비교 기준값은 조직 자체 정책 문서에서 뽑은 값이 기본입니다. 법정 수치는 원문 대조 후 `active: true`인 것만 씁니다.

## 다음 할 일

[docs/진행기록.md](docs/진행기록.md)의 "다음 할 일"을 참고하세요.
