# Function Calling API for Work Request

SSH 서버에 접속하여 LLM이 직접 명령어를 생성하고 실행하여 서버 문제를 진단하는 API

## 주요 기능

- **다중 턴 진단**: LLM이 명령어 실행 → 결과 분석 → 추가 명령어 생성 반복
- **Function Calling**: OpenAI Function Calling을 활용한 구조화된 명령어 생성
- **위험 명령어 차단**: `rm -rf`, `reboot`, `shutdown` 등 위험 명령어 자동 차단
- **외부 시스템 프롬프트**: 서버 재시작 없이 프롬프트 수정 가능

## 설치

```bash
# 가상환경 생성
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt
```

## 환경 변수 설정

`.env.example`을 참고하여 `.env` 파일 생성:

```bash
cp .env.example .env
```

```env
OPENAI_API_KEY=sk-your-openai-api-key
OLLAMA_BASE_URL=http://localhost:11434/v1
```

## 실행

```bash
uvicorn main:app --reload
```

## API 사용법

### POST /

서버 진단 요청

```json
{
  "ssh": {
    "ip": "192.168.1.100",
    "id": "root",
    "password": "password",
    "port": 22
  },
  "message": "서버가 느려졌습니다",
  "category": "performance",
  "user": "admin",
  "localllm": false,
  "max_turns": 10
}
```

### 응답 예시

```json
{
  "message": "## 진단 결과\n...",
  "executions": [
    {
      "command": "uptime",
      "output": "10:00:00 up 30 days...",
      "exit_code": 0
    }
  ],
  "latency": {
    "ssh": 0.5,
    "openai": 2.3,
    "total": 2.8
  },
  "usage_tokens": {
    "input": 500,
    "output": 200,
    "total": 700
  }
}
```

### GET /health

헬스체크

## 시스템 프롬프트 수정

`system_prompt.txt` 파일을 수정하면 서버 재시작 없이 즉시 적용됩니다.

## 파일 구조

```
.
├── main.py              # 메인 애플리케이션
├── system_prompt.txt    # 시스템 프롬프트 (수정 가능)
├── requirements.txt     # 의존성
├── .env                 # 환경 변수 (gitignore)
└── .env.example         # 환경 변수 예시
```
