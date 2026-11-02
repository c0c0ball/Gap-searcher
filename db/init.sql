-- pgvector 활성화. 스키마 마이그레이션은 이후 단계에서 Alembic으로 관리한다.
CREATE EXTENSION IF NOT EXISTS vector;
