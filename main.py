import time
import os
import sys
from pathlib import Path
from fastapi import FastAPI
from pydantic import BaseModel
import paramiko
from openai import OpenAI
import json
import re
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# 시스템 프롬프트 파일 경로
SYSTEM_PROMPT_FILE = Path(__file__).parent / "system_prompt.txt"


def validate_env() -> tuple[str, str]:
    """환경 변수 검증 및 로드"""
    openai_api_key = os.getenv("OPENAI_API_KEY")
    ollama_base_url = os.getenv("OLLAMA_BASE_URL")

    errors = []

    if not openai_api_key:
        errors.append("OPENAI_API_KEY 환경 변수가 설정되지 않았습니다.")
    elif not openai_api_key.startswith("sk-"):
        errors.append("OPENAI_API_KEY 형식이 올바르지 않습니다. (sk-로 시작해야 함)")

    if not ollama_base_url:
        errors.append("OLLAMA_BASE_URL 환경 변수가 설정되지 않았습니다.")
    elif not ollama_base_url.startswith("http"):
        errors.append("OLLAMA_BASE_URL 형식이 올바르지 않습니다. (http:// 또는 https://로 시작해야 함)")

    if errors:
        print("=" * 50)
        print("환경 변수 검증 실패:")
        for error in errors:
            print(f"  - {error}")
        print("=" * 50)
        print("\n.env.example 파일을 참고하여 환경 변수를 설정하세요.")
        sys.exit(1)

    return openai_api_key, ollama_base_url


# 환경 변수 검증 및 로드
OPENAI_API_KEY, OLLAMA_BASE_URL = validate_env()

# OpenAI 클라이언트
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Ollama 클라이언트 (Local LLM)
ollama_client = OpenAI(
    base_url=OLLAMA_BASE_URL,
    api_key="ollama"
)

# 위험 명령어 패턴
DANGEROUS_PATTERNS = [
    r"\brm\s+(-[rf]+\s+)?/",  # rm -rf /
    r"\brm\s+-[rf]*\s+\*",    # rm -rf *
    r"\breboot\b",
    r"\bshutdown\b",
    r"\binit\s+[0-6]\b",
    r"\bmkfs\b",
    r"\bdd\s+.*of=/dev/",
    r"\b>\s*/dev/sd[a-z]",
    r"\bformat\b",
    r":(){ :|:& };:",         # fork bomb
    r"\bkill\s+-9\s+-1\b",
    r"\bpkill\s+-9\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
]


class SSHConnection(BaseModel):
    ip: str
    id: str
    password: str
    port: int = 22


class UsageTokens(BaseModel):
    input: int
    output: int
    total: int


class RequestDTO(BaseModel):
    ssh: SSHConnection
    message: str
    category: str
    user: str
    localllm: bool = False
    max_turns: int = 10


class CommandExecution(BaseModel):
    command: str
    reason: str
    output: str
    exit_code: int


class Latency(BaseModel):
    ssh: float
    openai: float
    total: float


class ResponseDTO(BaseModel):
    message: str
    executions: list[CommandExecution]
    latency: Latency
    usage_tokens: UsageTokens


# Function Calling 정의
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_ssh_command",
            "description": "SSH를 통해 Linux 서버에서 명령어를 실행하여 정보를 수집합니다. 서버 상태 확인, 로그 조회, 프로세스 확인 등에 사용합니다. 정보 수집 후에는 finish_diagnosis를 호출하여 진단 결과를 제공해야 합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "실행할 Linux 명령어 (예: 'df -h', 'free -m', 'tail -100 /var/log/syslog')"
                    },
                    "reason": {
                        "type": "string",
                        "description": "이 명령어를 실행하는 이유"
                    }
                },
                "required": ["command", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "finish_diagnosis",
            "description": "명령어 실행 결과를 분석하여 최종 진단 결과를 제공할 때 호출합니다. execute_ssh_command로 필요한 정보를 수집한 후 반드시 이 함수를 호출하여 사용자에게 진단 결과와 해결 방법을 전달해야 합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "diagnosis": {
                        "type": "string",
                        "description": "execute_ssh_command로 수집한 정보를 분석한 결과입니다. 현재 시스템 상태, 발견된 문제의 원인, 관련 로그나 프로세스 정보를 포함하여 설명합니다."
                    },
                    "solution": {
                        "type": "string",
                        "description": "문제를 해결하기 위한 구체적인 방법입니다. 실행해야 할 조치, 설정 변경 사항, 권장 명령어 등을 포함하여 설명합니다."
                    },
                    "commands_to_fix": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "문제 해결을 위해 사용자가 직접 실행해야 할 명령어 목록입니다 (선택사항)"
                    }
                },
                "required": ["diagnosis", "solution"]
            }
        }
    }
]

def load_system_prompt() -> str:
    """외부 파일에서 시스템 프롬프트를 읽어옴 (호출 시마다 새로 읽음)"""
    try:
        return SYSTEM_PROMPT_FILE.read_text(encoding='utf-8')
    except FileNotFoundError:
        return "당신은 Linux 시스템 엔지니어입니다. 서버 문제를 진단해주세요."


def is_dangerous_command(command: str) -> bool:
    """위험한 명령어인지 검사"""
    command_lower = command.lower().strip()
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command_lower):
            return True
    return False


def execute_ssh_command(ssh_client: paramiko.SSHClient, command: str) -> tuple[str, int]:
    """SSH로 명령어 실행"""
    if is_dangerous_command(command):
        return f"[BLOCKED] 위험한 명령어가 차단되었습니다: {command}", -1

    try:
        stdin, stdout, stderr = ssh_client.exec_command(command, timeout=30)
        exit_code = stdout.channel.recv_exit_status()
        output = stdout.read().decode('utf-8', errors='replace')
        error = stderr.read().decode('utf-8', errors='replace')

        if error and exit_code != 0:
            return f"{output}\n[STDERR] {error}".strip(), exit_code
        return output.strip() if output else "(명령어 출력 없음)", exit_code
    except Exception as e:
        return f"[ERROR] 명령어 실행 실패: {str(e)}", -1


def create_ssh_client(ssh: SSHConnection) -> paramiko.SSHClient:
    """SSH 클라이언트 생성"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=ssh.ip,
        port=ssh.port,
        username=ssh.id,
        password=ssh.password,
        timeout=10
    )
    return client


def run_diagnosis_loop(
    ssh_client: paramiko.SSHClient,
    trouble_description: str,
    max_turns: int,
    localllm: bool = False
) -> tuple[str, list[CommandExecution], float, dict]:
    """다중 턴 진단 루프 실행"""

    client = ollama_client if localllm else openai_client # localllm 플래그에 따라 클라이언트 선택. False면 OpenAI 사용 
    model = "gpt-oss:20b" if localllm else "gpt-5-mini"

    print(f"Using model: {model}")
    print(f"truble_description: {trouble_description}")

    messages = [
        {"role": "system", "content": load_system_prompt()},
        {"role": "user", "content": f"### 요청 사항 \n\n{trouble_description}"}
    ]

    executions: list[CommandExecution] = []
    total_usage = {"input": 0, "output": 0, "total": 0}
    total_llm_time = 0

    for turn in range(max_turns):
        start_time = time.time()

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="required", # "none", "auto", "required"
            # TEST START
            # temperature=0,
            # max_tokens=2000,
            # top_p=1,
            # seed=42,
            # reasoning_effort="minimal", # "none", "minimal", "low", "medium", "high"
            # verbosity="low" # "low", "medium", "high"
            # TEST END
        )

        total_llm_time += time.time() - start_time

        # 토큰 사용량 집계
        if response.usage:
            total_usage["input"] += response.usage.prompt_tokens
            total_usage["output"] += response.usage.completion_tokens
            total_usage["total"] += response.usage.total_tokens

        assistant_message = response.choices[0].message

        # 디버깅 로그
        if assistant_message.tool_calls:
            for tool_call in assistant_message.tool_calls:
                print(f"[TURN {turn + 1}] Function: {tool_call.function.name}")
                print(f"[TURN {turn + 1}] Arguments: {tool_call.function.arguments}")
        else:
            print(f"[TURN {turn + 1}] No Function Call")
            print(f"[TURN {turn + 1}] Content: {assistant_message.content}")

        messages.append(assistant_message.model_dump())

        # Function call이 없으면 종료
        if not assistant_message.tool_calls:
            final_message = assistant_message.content or "진단을 완료할 수 없습니다."
            return final_message, executions, total_llm_time, total_usage

        # Function call 처리
        for tool_call in assistant_message.tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)

            if function_name == "execute_ssh_command":
                command = function_args.get("command", "")
                reason = function_args.get("reason", "")
                output, exit_code = execute_ssh_command(ssh_client, command)

                executions.append(CommandExecution(
                    command=command,
                    reason=reason,
                    output=output[:2000],  # 출력 제한
                    exit_code=exit_code
                ))

                tool_response = {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": f"Exit Code: {exit_code}\n\n{output[:2000]}"
                }
                messages.append(tool_response)

            elif function_name == "finish_diagnosis":
                diagnosis = function_args.get("diagnosis", "")
                solution = function_args.get("solution", "")
                commands_to_fix = function_args.get("commands_to_fix", [])

                final_message = f"""## 진단 결과
{diagnosis}

## 해결 방법
{solution}"""

                if commands_to_fix:
                    final_message += "\n\n## 권장 명령어\n"
                    for cmd in commands_to_fix:
                        final_message += f"```\n{cmd}\n```\n"

                return final_message, executions, total_llm_time, total_usage

    return "최대 진단 횟수에 도달했습니다. 다시 시도해 주세요.", executions, total_llm_time, total_usage


app = FastAPI()


@app.post("/", response_model=ResponseDTO)
async def root(request: RequestDTO):
    total_start = time.time()
    ssh_start = time.time()

    ssh_client = create_ssh_client(request.ssh)
    ssh_connect_time = time.time() - ssh_start

    try:
        message, executions, llm_time, usage = run_diagnosis_loop(
            ssh_client,
            request.message,
            request.max_turns,
            request.localllm
        )

        # SSH 명령어 실행 시간 계산
        total_ssh_time = ssh_connect_time
        for _ in executions:
            total_ssh_time += 0.1  # 대략적인 명령어 실행 시간

        total_time = time.time() - total_start

        return ResponseDTO(
            message=message,
            executions=executions,
            latency=Latency(
                ssh=round(total_ssh_time, 2),
                openai=round(llm_time, 2),
                total=round(total_time, 2)
            ),
            usage_tokens=UsageTokens(
                input=usage["input"],
                output=usage["output"],
                total=usage["total"]
            )
        )
    finally:
        ssh_client.close()


@app.get("/health")
async def health():
    return {"status": "ok"}
