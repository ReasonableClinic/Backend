"""도구: ClinicalTrials.gov API v2 조회. (collect_ctgov.py 의 검색 규칙 그대로)

- fetch_study(nct_id)                      한 시험
- search_studies(condition, term, ...)     질환 검색 (모집 중, 중재 연구)
네트워크가 막힌 환경에서는 saved= 로 저장된 응답 JSON 을 넘기면 같은 경로로 처리된다.
"""
import json, time
from pathlib import Path

API = "https://clinicaltrials.gov/api/v2/studies"
ACTIVE = ("RECRUITING", "NOT_YET_RECRUITING")


def _get(url, params=None, timeout=60):
    import requests
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_study(nct_id: str) -> dict:
    """NCT 번호 하나 → API 응답 (protocolSection 포함)."""
    return _get(f"{API}/{nct_id}", {"format": "json"})


def search_studies(condition: str, term: str = "", statuses=ACTIVE, page_size=50, max_pages=2, pause=0.4) -> list[dict]:
    """질환(+세부어) 검색. 모집 중인 중재 연구만. 페이지를 max_pages 까지 넘긴다."""
    studies, token, pages = [], None, 0
    while pages < max_pages:
        params = {"query.cond": condition, "filter.overallStatus": ",".join(statuses),
                  "filter.advanced": "AREA[StudyType]INTERVENTIONAL", "pageSize": page_size, "format": "json"}
        if term:
            params["query.term"] = term
        if token:
            params["pageToken"] = token
        body = _get(API, params)
        studies.extend(body.get("studies", []))
        pages += 1
        token = body.get("nextPageToken")
        if not token:
            break
        time.sleep(pause)
    return studies


def load_saved(path) -> list[dict]:
    """저장된 응답 파일(검색 결과 {"studies": [...]} 또는 단일 시험)을 읽는다."""
    d = json.load(open(path, encoding="utf-8"))
    return d["studies"] if "studies" in d else [d]
