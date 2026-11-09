# run_dev.sh·run_test.sh 공통 부분. 직접 실행하지 않음.
#   --dry  API 없이 코드 규칙만(--llm none)으로 경로·파일 연결만 확인. 결과는 runs/*_dry/ (제출용 아님)
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL=claude-sonnet-5-5      # FREEZE_a3-0.3.1.json과 같은 고정 설정 (a3-0.3.1 + p07)
FREEZE=FREEZE_a3-0.3.1.json
DEV_TAG=a031_v10_kit1412_p07   # dev: 근거 키트 v14.12
TAG=a031_v10_kit149_p07        # test: 근거 v14.9 고정
WORKERS=${WORKERS:-8}
if [[ "${1:-}" == "--dry" ]]; then LLM=none; SUFFIX=_dry; else LLM=anthropic; SUFFIX=; fi

check_inputs() {
    echo "== 받은 파일 4개와 같은지 확인"
    python3 scripts/check_inputs.py || { echo "파일이 받은 zip과 다릅니다. 먼저 교체하세요."; exit 1; }
}

# 키는 이 스크립트 프로세스 안에서만 씀 (셸에 export하지 않으니 Claude Code 과금 방식에 영향 없음)
get_key() {
    [[ "$LLM" == none ]] && return
    if [[ -z "${ANTHROPIC_API_KEY:-}" && -f .env ]]; then          # a3-0.3.1: .env (cp .env.example .env)
        ANTHROPIC_API_KEY=$(python3 -c "from agent3.env_setup import load_env; import os; load_env(); print(os.environ.get('ANTHROPIC_API_KEY', ''))")
        [[ -n "$ANTHROPIC_API_KEY" ]] && { export ANTHROPIC_API_KEY; echo "== 키: .env에서 읽음"; }
    fi
    if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
        read -rsp "Anthropic API key (붙여넣기: 오른쪽 클릭 또는 Ctrl+Shift+V): " ANTHROPIC_API_KEY; echo
        ANTHROPIC_API_KEY=$(printf '%s' "$ANTHROPIC_API_KEY" | tr -d '[:space:]')
        export ANTHROPIC_API_KEY
    fi
    echo "== 키 확인 (모델 목록 조회, 과금 없음)"
    local r
    r=$(curl -s https://api.anthropic.com/v1/models -H "anthropic-version: 2023-06-01" \
        -H @<(printf 'x-api-key: %s\n' "$ANTHROPIC_API_KEY")) \
        || { echo "api.anthropic.com에 연결하지 못했습니다 (인터넷 확인)"; exit 1; }
    if [[ "$r" != *'"data"'* ]]; then
        echo "키가 거부됐습니다: $(printf '%s' "$r" | cut -c1-200)"; exit 1
    fi
    echo "키 OK"
}

# run_one 이름 쌍수 [agent3.run 추가 인자...]  -> runs/이름/, runs/이름.err
run_one() {
    local name=$1$SUFFIX want=$2; shift 2
    local out=runs/$name
    echo "== $name 실행 (예상 $want쌍, --llm $LLM). 환자 하나 끝날 때마다 한 줄씩 나옵니다"
    python3 -m agent3.run --llm "$LLM" --model "$MODEL" --workers "$WORKERS" --out "$out" "$@" 2>&1 | tee "$out.err"
    local got fail
    got=$(wc -l < "$out/agent3_out.jsonl")
    fail=$(grep -cF "  ! " "$out.err" || true)
    echo "-- $name: $got쌍, 실패한 호출 $fail건"
    [[ "$got" -eq "$want" ]] || { echo "쌍 수가 $want이 아닙니다"; exit 1; }
    FAILS=$(( ${FAILS:-0} + fail ))
}

failed_ok() {
    if (( ${FAILS:-0} > 0 )); then
        echo "실패한 호출 ${FAILS}건 (위 '!' 줄). 같은 명령을 그대로 다시 실행하세요. 받은 답은 캐시에서 비용 없이 읽고 실패분만 다시 부릅니다."
        return 1
    fi
}
