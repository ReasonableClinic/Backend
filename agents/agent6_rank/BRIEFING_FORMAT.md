# 브리핑 출력 형식 (초안 v1)

환자 한 명, 읽는 사람 한 종류마다 JSON 파일 하나: `<patient_id>.clinician.json`, `<patient_id>.patient.json`.

```json
{
  "patient_id": "SYN-0019",
  "as_of": "2026-10-01",
  "audience": "patient",
  "graph_file": "SYN-0019.json",
  "ranking": ["NCT05614739", "NCT07566156"],
  "sentences": [
    {"text": "이 안내는 치료 추천이 아니라 ...", "refs": ["rule:research_not_treatment"], "kind": "rule"},
    {"text": "1. FORAGER-1 ... 아직 확인이 필요한 조건이 있습니다.", "refs": ["trial:NCT05614739", "label:NCT05614739"], "kind": "fact"},
    {"text": "참여 전에 의료진이 확인할 항목이 5개 남아 있습니다.", "refs": ["dec:NCT05614739:NCT05614739-E02:r1", "..."], "kind": "fact"}
  ]
}
```

| 필드 | 뜻 |
| --- | --- |
| `audience` | `clinician` 또는 `patient`. `patient`이면 금지 표현과 필수 문구를 검사 |
| `graph_file` | 근거로 쓴 그래프 파일 이름 (`--graphs` 폴더에서 찾음) |
| `ranking` | 이 브리핑이 다루는 시험. 문장에 이 밖의 NCT 번호가 나오면 경고 |
| `also_mentioned` | (의료진용, 선택) 순위 밖이지만 언급하는 시험: 24개월 넘게 모집 미확인으로 빠진 시험, FAIL 1개로 제외된 시험(near-miss) |
| `sentences[].text` | 화면에 보일 문장 하나. 문장 단위로 나눠야 연결 검사가 의미 있음 |
| `sentences[].refs` | 그 문장의 근거: 그래프 노드 ID(`trial:` `crit:` `dec:` `label:` `ev:` `src:` `calc:` `concept:`), `rules.py`의 `rule:` ID, 용어 사전의 `gloss:` ID, 또는 `--evidence`로 읽은 에이전트 2 근거의 `ev:` ID(그래프 밖, 같은 버전만) |
| `glossary` | 사용한 용어 사전: `{mode, sha256, rows_used, draft}` (사전 없음 조건은 `mode: none`) |
| `evidence` | `--evidence`로 읽은 에이전트 2 근거: `{files, sha256, id_series, graph_ev_nodes_checked}` (`id_series`는 run_meta가 있을 때 haiku/rules) (그래프와 버전 대조를 통과한 경우만, 없으면 null) |
| `agent6` | 브리핑을 만든 코드 버전 (예: `a6-0.4.0`). LLM 브리핑은 `generator.agent6` |
| `sentences[].kind` | `fact`(사실, refs 필수), `heading`(제목, refs 필수), `rule`(고정 문구), `meta`(환자 ID·날짜, refs 없어도 됨) |

규칙:

- 한 문장이 여러 기준을 묶으면 그 기준들의 판정 ID를 모두 넣습니다.
- 환자 이야기는 판정(`dec:`)이나 근거(`ev:`, `src:`) ID로, 시험 이야기는 `trial:` ID로 참조합니다. `trial:`은 그 시험의 ⓪ 기록(`trials.jsonl`) 전체를 대신합니다.
- 고정 문구를 고쳐 쓰면 `rules.py`에 새 `rule:` ID로 추가합니다. 문장 안에서 즉석으로 만들지 않습니다.
- 화면(frontend)은 `refs`로 문장을 눌렀을 때 근거를 펼칠 수 있습니다. 그래서 ID는 그래프의 것을 그대로 씁니다.
- **에이전트 5 카드와 연결 (a6-0.4.8):** `dec:<trial_id>:<criterion_id>:r<n>`의 시험·기준 ID가 카드 항목의 `trial_id`·`criterion_id`와 같습니다. 화면은 카드를 (`patient_id`, `trial_id`, `criterion_id`)로 색인해 문장의 `dec:` ref로 찾습니다(`scripts/link_cards.py`).
- 그래프에 없는 에이전트 2 근거로 내용을 정한 문장(지금은 암 진단 확인으로 환자용에 질환명을 쓴 경우)은 그 근거의 `ev:` ID를 refs에 넣습니다. 이 ID는 그래프 노드가 아니므로, 화면은 에이전트 2 근거 파일(같은 버전)에서 찾아 펼쳐야 합니다.
