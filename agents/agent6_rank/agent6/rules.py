"""Patient-briefing rules (draft, team to confirm). Fixed sentences carry a `rule:<id>` ref instead of a graph node.

KGCP = 「의약품 등의 안전에 관한 규칙」 [별표 4] 의약품 임상시험 관리기준 (2022-12-07). 제7호 아목:
research_not_treatment 10) 가), randomized 10) 다), no_benefit_promise 10) 아), voluntary 10) 자)·파),
withdraw 10) 파), BANNED 3) (강요·부당한 영향 금지), plain language 6). IRB review of written material and recruitment
ads in 라목 1)·3). placebo is not a KGCP item: it is there for comprehension (Tam et al. 2015, DESIGN_BASIS 3장).
ask_alternatives points the reader to 10) 자) (다른 치료방법), which the graph does not hold, so it is a question to ask,
not a statement. phase_*, active_comparator, no_intervention_arm, blinded describe the trial design from the ⓪ record
(team idea doc 9장 "이 시험은 무엇을 하는가"); guardian is used when the patient is under 19 (age_at_as_of). clinician_explains_first replaces the "what it studies"
sentence when the trial is a cancer trial but the patient's record has no confirmed malignancy (keyinfo.cancer_hidden):
a cancer diagnosis is the clinician's to give, not the briefing's.
no_kr_site (a6-0.4.13) is said when no Korean site recruits (kr_sites 0), followed by the recruiting countries, so a
trial abroad is not read as one the patient can join here.
The mapping below is the team's reading of those items for a pre-consent briefing, not a legal review.
"""

FIXED = {
    "rule:research_not_treatment": "이 안내는 치료 추천이 아니라, 연구(임상시험) 참여를 검토하실 때 참고하실 정보입니다.",
    "rule:voluntary": "참여는 자유이며, 참여하지 않아도 지금 받고 계신 치료는 그대로 받으실 수 있습니다.",
    "rule:withdraw": "참여하더라도 언제든 그만두실 수 있습니다.",
    "rule:no_benefit_promise": "시험약이 효과가 있을지는 아직 모르기 때문에 연구를 하는 것입니다.",
    "rule:ask_clinician": "최종 참여 가능 여부는 연구 담당 의료진이 직접 확인합니다.",
    "rule:randomized": "이 시험은 참여자가 어느 치료를 받을지 무작위로 정해집니다.",
    "rule:placebo": "참여자 일부는 시험약 대신 위약(효과가 없는 가짜 약)을 받을 수 있습니다.",
    # trial design (from trials.jsonl, cited together with trial:<id>)
    "rule:phase_EARLY_PHASE1": "아주 초기 단계(초기 1상) 연구로, 적은 수의 사람에게 처음 시험하는 단계입니다.",
    "rule:phase_PHASE1": "1상 연구로, 주로 안전성과 알맞은 용량을 처음 확인하는 단계입니다.",
    "rule:phase_PHASE1_PHASE2": "1·2상 연구로, 안전성과 용량을 확인하면서 효과 가능성도 함께 살펴보는 단계입니다.",
    "rule:phase_PHASE2": "2상 연구로, 효과가 있을 가능성과 안전성을 비교적 적은 수의 환자에게서 살펴보는 단계입니다.",
    "rule:phase_PHASE2_PHASE3": "2·3상 연구로, 효과 가능성을 살펴본 뒤 더 많은 환자에게서 확인하는 단계입니다.",
    "rule:phase_PHASE3": "3상 연구로, 많은 환자에게서 효과와 안전성을 기존 치료 등과 비교해 확인하는 단계입니다.",
    "rule:phase_PHASE4": "4상 연구로, 이미 허가된 치료를 실제 진료에 가까운 상황에서 더 살펴보는 단계입니다.",
    "rule:active_comparator": "시험 치료를 이미 쓰이고 있는 다른 치료와 비교합니다.",
    "rule:no_intervention_arm": "참여자 일부는 시험 치료 없이 경과를 지켜보는 그룹에 배정될 수 있습니다.",
    "rule:blinded": "참여자나 의료진이 누가 어떤 치료를 받는지 모르게 진행됩니다.",
    # questions to bring to the research team (not statements of fact)
    "rule:ask_alternatives": "지금 받으실 수 있는 다른 치료 방법이 무엇인지도 의료진에게 물어보실 수 있습니다.",
    "rule:ask_burden": "참여하면 방문 횟수, 검사, 기간처럼 해야 하는 일이 무엇인지도 미리 물어보실 수 있습니다.",
    "rule:dropped_stale": "모집 상태가 24개월 넘게 확인되지 않아 추천에서 제외했습니다 (공통 형식 6.4).",
    "rule:clinician_explains_first": "이 시험이 지금 상황과 맞는 연구인지는 담당 의료진이 먼저 설명드립니다.",
    "rule:no_kr_site": "현재 국내에는 이 시험의 참여자를 모집하는 기관이 없습니다.",
    "rule:guardian": "이 안내는 환자와 보호자께 드리는 것이며, 참여 여부는 보호자와 의료진이 함께 상의해 결정합니다.",
}
PHASE_RULE = {"EARLY_PHASE1": "rule:phase_EARLY_PHASE1", "PHASE1": "rule:phase_PHASE1", "PHASE2": "rule:phase_PHASE2",
              "PHASE3": "rule:phase_PHASE3", "PHASE4": "rule:phase_PHASE4", "PHASE1+PHASE2": "rule:phase_PHASE1_PHASE2",
              "PHASE2+PHASE3": "rule:phase_PHASE2_PHASE3"}
REQUIRED = ["rule:research_not_treatment", "rule:voluntary", "rule:ask_clinician"]

# Phrases that promise benefit, pressure, or state eligibility as settled. Draft list: extend, do not shrink silently.
BANNED = ["추천합니다", "권합니다", "꼭 참여", "반드시 참여", "놓치지", "효과가 있습니다", "효과를 볼", "나을 수", "완치",
          "치료됩니다", "무료로 치료", "최신 치료", "확정", "참여 가능합니다", "자격이 있습니다", "적합합니다", "안전합니다",
          # promised effect on the patient's own symptoms (idea doc 9장 "표현의 선") and treatment advice (topic adherence)
          "줄여줄", "줄여 줄", "줄여 드", "개선해줄", "개선해 줄", "좋아질", "좋아지실", "도움이 될 것", "도움이 됩니다",
          "복용하세요", "중단하세요", "끊으세요", "바꾸세요", "드세요"]
