#!/usr/bin/env bash
# test 1회 실행: 기본 30명(90쌍) + 변형 34명(102쌍)을 한 번에 실행하고 보낼 zip을 만듦. test 정답은 없어 채점하지 않음.
#   bash scripts/run_test.sh          Claude API로 실행 (키를 물어봄)
#   bash scripts/run_test.sh --dry    API 없이 코드 규칙만 (연결 확인용, 결과 보지 말 것)
source "$(dirname "$0")/_common.sh"

BASE=runs/test_$TAG$SUFFIX
VAR=runs/test_variants_$TAG$SUFFIX
PKG=runs/agent3_test_$TAG$SUFFIX.zip

# test는 한 번만: 실패 없이 끝난 결과가 있으면 다시 돌리지 않음 (실패가 남아 있을 때의 재실행은 캐시로 실패분만 채움)
if [[ -z "$SUFFIX" && -f "$PKG" ]]; then
    echo "이미 완료된 test 결과가 있습니다: $PKG  (다시 돌리지 않습니다)"; exit 1
fi

# a3-0.3.0 test가 마지막 순수 test 점수 (5차 회의). a3-0.3.1로 test를 다시 돌릴지는 팀이 정한 뒤에만
if [[ -z "$SUFFIX" && "${ALLOW_TEST:-}" != 1 ]]; then
    echo "a3-0.3.1 test 재실행은 팀 결정 후에만 합니다. 정해졌으면 ALLOW_TEST=1 bash scripts/run_test.sh"; exit 1
fi

check_inputs
get_key

run_one test_$TAG 90 --split test \
    --evidence agent3_kit/evidence_test_haiku_v14_9.jsonl
run_one test_variants_$TAG 102 --split test \
    --patients data/test/input/patients_variants.jsonl \
    --pairs data/test/input/pairs_variants.jsonl \
    --evidence agent3_kit/evidence_test_variants_haiku_v14_9.jsonl
failed_ok || exit 1

# 보낼 파일: 두 실행의 agent3_out.jsonl·run_meta.json·graph/ + 고정 기록
FREEZE=$FREEZE python3 - "$PKG" "$BASE" "$VAR" <<'EOF'
import os, sys, zipfile
pkg, dirs = sys.argv[1], sys.argv[2:]
with zipfile.ZipFile(pkg, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(os.environ["FREEZE"])
    for d in dirs:
        for root, _, files in os.walk(d):
            for f in files:
                p = os.path.join(root, f)
                z.write(p, os.path.relpath(p, "runs"))
print(f"보낼 파일: {pkg} ({os.path.getsize(pkg) // 1024} KB)")
EOF
