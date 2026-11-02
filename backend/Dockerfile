FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY gapcheck ./gapcheck
RUN pip install --no-cache-dir -e .
# api와 worker가 같은 이미지를 쓰고 command만 다르다 (docker-compose.yml 참고)
