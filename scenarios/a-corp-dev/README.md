# 시나리오: a-corp-dev (A사, 가상 이커머스)

2.5.4 비밀번호 관리(1단계)와 IAM 계정·권한 관리(2.2.5, 2.5.1~2.5.6), 네트워크 접근통제(2.6), 암호화(2.7), 로그·백업(2.9, 2.12)을 관통시키기 위한 **개발용 공개 시나리오**입니다.
단계별 데이터는 `python scripts/build_a_corp_dev_iam.py`, `python scripts/build_a_corp_dev_network.py`, `python scripts/build_a_corp_dev_crypto.py`, `python scripts/build_a_corp_dev_logging.py`로 (이 순서대로) 다시 만들 수 있습니다.
모든 회사·인물·계정 정보는 가상입니다 (계정 ID 111111111111 등, 도메인 .example).

| 폴더 | 내용 |
|---|---|
| docs/ | 정보보호 정책서, 접근통제 지침(v2.1), 계정관리 절차서, 암호통제 지침(v1.0), 운영보안 지침(v1.0) — 실제 규정 형식의 docx |
| evidence/ | 회원가입 화면 캡처, 인사 명부, 계정 관리대장, 특수권한자 목록, 접근권한 검토 기록, 정보자산 목록, 암호키 관리대장, 접속기록 점검 기록, 백업 복구 테스트 기록 (재해 복구 훈련 기록은 일부러 없음) |
| aws-snapshot/ | 3개 AWS 계정의 수집 결과 (live 수집기와 같은 형식) |
| terraform/ | 설정으로 재현 가능한 결함을 실제 샌드박스에 만드는 코드 |
| scope.yaml | 진단 범위 사실과 근거 |
| expected/ | 심은 결함 38개(D1~D38), 자료 미제출 1건(G1)과 함정, 기대 결과 (개발용 정답지) |
