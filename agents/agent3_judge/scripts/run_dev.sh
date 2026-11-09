#!/usr/bin/env bash
# dev 확인 (a3-0.3.1, 근거 v14.12): 기본 20명(54쌍) + 변형 36명(100쌍)을 한 번에 실행하고 정답으로 채점.
#   bash scripts/run_dev.sh          Claude API로 실행 (키를 물어봄)
#   bash scripts/run_dev.sh --dry    API 없이 코드 규칙만
source "$(dirname "$0")/_common.sh"

check_inputs
get_key

run_one dev_$DEV_TAG 54 --split dev \
    --evidence agent3_kit/evidence_dev_haiku_v14_12.jsonl
run_one dev_variants_$DEV_TAG 100 --split dev \
    --patients data/dev/input/patients_variants.jsonl \
    --pairs data/dev/gold/gold_variants.jsonl \
    --evidence agent3_kit/evidence_dev_variants_haiku_v14_12.jsonl
failed_ok || exit 1

# 채점 (API 없음)
python3 eval/score_dev.py runs/dev_$DEV_TAG$SUFFIX/agent3_out.jsonl \
    --evidence agent3_kit/evidence_dev_haiku_v14_12.jsonl \
    --md runs/dev_$DEV_TAG$SUFFIX/score_gold.md > /dev/null
python3 eval/score_dev.py runs/dev_variants_$DEV_TAG$SUFFIX/agent3_out.jsonl \
    --gold data/dev/gold/gold_variants.jsonl \
    --evidence agent3_kit/evidence_dev_variants_haiku_v14_12.jsonl \
    --md runs/dev_variants_$DEV_TAG$SUFFIX/score_gold.md > /dev/null

echo
echo "== dev 채점 요약 (전체: runs/*/score_gold.md)"
for n in dev_$DEV_TAG$SUFFIX dev_variants_$DEV_TAG$SUFFIX; do
    echo "[$n]"
    grep -E "^\| .*(기준 상태 일치 \(엄격\)|반대 방향 오류|시험 판정 일치|정답 eligible/potential → ineligible|eligible 재현율)" \
        runs/$n/score_gold.md
done
