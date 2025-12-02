# 빌드 스테이지
FROM python:3.12-alpine AS builder

# 빌드 의존성 설치 (paramiko용 cryptography 빌드에 필요)
RUN apk add --no-cache \
    gcc \
    musl-dev \
    libffi-dev \
    openssl-dev \
    cargo

WORKDIR /build

# 가상환경 생성 및 의존성 설치
COPY requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# 런타임 스테이지
FROM python:3.12-alpine

# 런타임에 필요한 라이브러리만 설치
RUN apk add --no-cache libffi openssl

WORKDIR /app

# 빌드 스테이지에서 가상환경 복사
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 애플리케이션 복사
COPY main.py .
COPY system_prompt.txt .

# 비루트 사용자 생성
RUN adduser -D -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
