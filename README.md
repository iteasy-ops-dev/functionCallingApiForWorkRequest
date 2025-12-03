# Function Calling API for Work Request

SSH 서버에 접속하여 LLM이 직접 명령어를 생성하고 실행하여 서버 문제를 진단하는 API

## 개요

이 API는 OpenAI의 Function Calling 기능을 활용하여 Linux 서버 문제를 자동으로 진단합니다.
사용자가 문제 상황을 설명하면, LLM이 SSH로 서버에 접속하여 필요한 명령어를 실행하고 결과를 분석합니다.

## 주요 기능

| 기능 | 설명 |
|------|------|
| **다중 턴 진단** | LLM이 명령어 실행 → 결과 분석 → 추가 명령어 생성 반복 |
| **Function Calling** | OpenAI Function Calling을 활용한 구조화된 명령어 생성 |
| **위험 명령어 차단** | `rm -rf`, `reboot`, `shutdown` 등 위험 명령어 자동 차단 |
| **외부 시스템 프롬프트** | 서버 재시작 없이 프롬프트 수정 가능 |
| **Local LLM 지원** | Ollama를 통한 로컬 LLM 사용 가능 |

## 아키텍처

```
┌─────────────┐     POST /      ┌─────────────┐
│   Client    │ ───────────────>│   FastAPI   │
└─────────────┘                 └──────┬──────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    │                  │                  │
                    ▼                  ▼                  ▼
             ┌───────────┐      ┌───────────┐      ┌───────────┐
             │  OpenAI   │      │   SSH     │      │  Ollama   │
             │   API     │      │  Server   │      │  (Local)  │
             └───────────┘      └───────────┘      └───────────┘
```

## 진단 흐름

```
1. 사용자 요청 수신
         ↓
2. SSH 연결 수립
         ↓
3. LLM에 문제 설명 전달
         ↓
4. LLM이 execute_ssh_command 호출
         ↓
5. SSH로 명령어 실행 & 결과 반환
         ↓
6. LLM이 결과 분석
         ↓
   ├─ 추가 조사 필요 → 4번으로
   └─ 진단 완료 → finish_diagnosis 호출
         ↓
7. 진단 결과 및 해결책 반환
```

## 설치

### 요구 사항

- Python 3.10+
- OpenAI API Key 또는 Ollama

### 설치 방법

```bash
# 저장소 클론
git clone <repository-url>
cd iteasy.functionCallingApiForWorkRequest

# 가상환경 생성 및 활성화
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

필수 환경 변수:

| 변수명 | 설명 | 예시 |
|--------|------|------|
| `OPENAI_API_KEY` | OpenAI API 키 | `sk-...` |
| `OLLAMA_BASE_URL` | Ollama 서버 URL | `http://localhost:11434/v1` |

```env
# OpenAI API 설정
OPENAI_API_KEY=sk-your-openai-api-key-here

# Ollama (Local LLM) 설정
OLLAMA_BASE_URL=http://localhost:11434/v1
```

## 실행

### 개발 서버

```bash
uvicorn main:app --reload
```

### 프로덕션 서버

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

## API 사용법

### POST / - 서버 진단 요청

#### 요청

```json
{
  "ssh": {
    "ip": "192.168.1.100",
    "id": "root",
    "password": "password",
    "port": 22
  },
  "message": "서버가 느려졌습니다. 원인을 분석해주세요.",
  "category": "performance",
  "user": "admin",
  "localllm": false,
  "max_turns": 10
}
```

#### 요청 파라미터

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `ssh.ip` | string | O | SSH 접속 IP |
| `ssh.id` | string | O | SSH 사용자 ID |
| `ssh.password` | string | O | SSH 비밀번호 |
| `ssh.port` | int | X | SSH 포트 (기본값: 22) |
| `message` | string | O | 문제 상황 설명 |
| `category` | string | O | 문제 카테고리 |
| `user` | string | O | 요청 사용자 |
| `localllm` | bool | X | Local LLM 사용 여부 (기본값: false) |
| `max_turns` | int | X | 최대 진단 횟수 (기본값: 10) |

#### 응답

```json
{
  "message": "## 진단 결과\n메모리 사용률이 95%로 높습니다...\n\n## 해결 방법\n...",
  "executions": [
    {
      "command": "free -m",
      "reason": "현재 메모리 사용량 확인",
      "output": "              total        used        free\nMem:          16384       15565         819",
      "exit_code": 0
    },
    {
      "command": "ps aux --sort=-%mem | head -10",
      "reason": "메모리 사용량이 높은 프로세스 확인",
      "output": "USER       PID %CPU %MEM ...",
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

#### 응답 필드

| 필드 | 설명 |
|------|------|
| `message` | 최종 진단 결과 및 해결 방법 |
| `executions` | 실행된 명령어 목록 및 결과 |
| `executions[].reason` | 해당 명령어를 실행한 이유 |
| `latency.ssh` | SSH 연결 및 명령어 실행 시간 (초) |
| `latency.openai` | LLM API 호출 시간 (초) |
| `latency.total` | 전체 처리 시간 (초) |
| `usage_tokens` | LLM 토큰 사용량 |

### GET /health - 헬스체크

```bash
curl http://localhost:8000/health
```

응답:
```json
{"status": "ok"}
```

## 보안

### 위험 명령어 차단

다음 명령어들은 자동으로 차단됩니다:

| 패턴 | 설명 |
|------|------|
| `rm -rf /` | 루트 삭제 |
| `reboot`, `shutdown`, `halt`, `poweroff` | 시스템 종료/재시작 |
| `mkfs`, `dd of=/dev/` | 디스크 포맷 |
| `init 0-6` | 런레벨 변경 |
| `kill -9 -1`, `pkill -9` | 모든 프로세스 종료 |
| `:(){ :\|:& };:` | Fork bomb |

### 주의사항

- SSH 비밀번호가 요청 본문에 포함되므로 **HTTPS 사용 필수**
- 프로덕션 환경에서는 SSH 키 인증 방식 권장
- 진단 대상 서버에 대한 적절한 접근 권한 관리 필요

## 시스템 프롬프트 커스터마이징

`system_prompt.txt` 파일을 수정하면 LLM의 동작을 변경할 수 있습니다.
**서버 재시작 없이** 즉시 적용됩니다.

기본 프롬프트:
```
당신은 선임 Linux 시스템 엔지니어입니다.
사용자가 요청을 수행하기 위해 SSH 명령어를 실행할 수 있습니다.

## 규칙
1. 한 번에 하나의 명령어만 실행하세요.
2. 명령어 결과를 분석한 후 추가 조사가 필요하면 다른 명령어를 실행하세요.
3. 충분한 정보를 수집했으면 finish_diagnosis를 호출하여 최종 진단을 제공하세요.
...
```

## 파일 구조

```
.
├── main.py              # FastAPI 메인 애플리케이션
├── system_prompt.txt    # LLM 시스템 프롬프트 (수정 가능)
├── requirements.txt     # Python 의존성
├── .env                 # 환경 변수 (gitignore)
├── .env.example         # 환경 변수 예시
└── README.md            # 프로젝트 문서
```

## 의존성

| 패키지 | 용도 |
|--------|------|
| `fastapi` | 웹 프레임워크 |
| `uvicorn` | ASGI 서버 |
| `openai` | OpenAI/Ollama API 클라이언트 |
| `paramiko` | SSH 클라이언트 |
| `python-dotenv` | 환경 변수 관리 |

## 사용 예시

### cURL

```bash
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{
    "ssh": {
      "ip": "192.168.1.100",
      "id": "admin",
      "password": "secret",
      "port": 22
    },
    "message": "디스크 용량이 부족합니다",
    "category": "disk",
    "user": "operator"
  }'
```

### Python

```python
import requests

response = requests.post("http://localhost:8000/", json={
    "ssh": {
        "ip": "192.168.1.100",
        "id": "admin",
        "password": "secret"
    },
    "message": "Apache 서비스가 응답하지 않습니다",
    "category": "service",
    "user": "operator"
})

print(response.json()["message"])
```

## 문제 해결

### 환경 변수 오류

```
환경 변수 검증 실패:
  - OPENAI_API_KEY 환경 변수가 설정되지 않았습니다.
```

→ `.env` 파일에 `OPENAI_API_KEY`가 올바르게 설정되어 있는지 확인하세요.

### SSH 연결 실패

```
[ERROR] 명령어 실행 실패: Authentication failed
```

→ SSH 인증 정보(IP, 사용자, 비밀번호, 포트)가 올바른지 확인하세요.

### 명령어 차단됨

```
[BLOCKED] 위험한 명령어가 차단되었습니다: rm -rf /
```

→ 보안상 위험한 명령어는 자동으로 차단됩니다.

## 라이선스

MIT License
