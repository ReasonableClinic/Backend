"""Planning step of Agent 2 before ①-b exists.

1. Candidate trials: rank the reference trials by TF-IDF similarity between the patient record (summary weighted
   up) and the trial title + conditions + MeSH terms; keep the top k. This stands in for the system's
   "condition-based candidate lookup" and uses no gold information.
2. Extraction plan: the provisional concepts the candidates' criteria mention (concept triggers below) and a
   vocabulary of clinical content words from those criteria. Generic facts (findings, diagnoses, drugs,
   procedures, other labs) are kept only when they share a content word with this vocabulary.
With ①-b (criteria carrying `concept` / `term`), the trigger concepts are the concepts the candidate trials'
criteria name and the vocabulary also holds their `term`s ("AP", "PERT").
"""
import math, re, collections

STOP = set("""a an the and or of in on at to for with without by from as is are was were be been being not no nor
any all each per than then that this these those who whom which what when where while within prior previous
current currently patient patients subject subjects participant participants study trial must have has had
having history known other including include includes included exclude excluded excluding criteria criterion
inclusion exclusion following documented evidence diagnosis diagnosed confirmed defined clinically significant
screening baseline visit day days week weeks month months year years time least more less greater equal
investigator opinion judgment may might could would should will shall can able unable use used using
treatment treated therapy therapies receive received receiving dose doses agent agents drug drugs medication
medications condition conditions disease diseases disorder disorders severe moderate mild active acute chronic
new start started first second line lines also only such per eg ie etc via upon after before during since
age aged male female women men subject's patient's level levels value values normal upper lower limit uln lln
test tests result results positive negative well stable presence present absence absent other any one two three
four five six""".split())
TRIGGERS = {
    "ecog": r"ecog|performance status|karnofsky", "pregnancy": r"pregnan|lactat|breast.?feed|childbearing",
    "contraception": r"contracep", "smoking": r"smok|tobacco|pack.?year", "alcohol": r"alcohol",
    "substance_use": r"substance|illicit|drug abuse", "allergy": r"allerg|hypersensitiv",
    "hepatitis_b": r"hepatitis b|hbv|hbsag", "hepatitis_c": r"hepatitis c|hcv", "hiv": r"\bhiv\b",
    "hcg": r"pregnan", "lvef": r"ejection fraction|lvef", "qtc": r"\bqtc?\b",
    "cancer_stage": r"\bstage\b|tnm|metasta", "metastasis": r"metasta", "tumor_marker": r"her2|er\b|pd-?l1|egfr|alk|kras|braf|mutation|express",
    "body_weight": r"weight|bmi|body mass", "bmi": r"bmi|body mass|weight", "blood_pressure": r"blood pressure|hypertension|mmhg",
}


def words(text):
    return [w[:7] for w in re.findall(r"[a-z][a-z0-9\-]{2,}", text.lower()) if w not in STOP and not w.isdigit()]


class Planner:
    def __init__(self, trials, criteria):
        self.trials = trials
        self.crit_by_trial = collections.defaultdict(list)
        self.concepts_by_trial = collections.defaultdict(set)     # ①-b: what each trial's criteria ask about
        self.terms_by_trial = collections.defaultdict(list)
        for c in criteria:
            if not c.get("administrative"):
                self.crit_by_trial[c["trial_id"]].append(c["original_text"])
                if c.get("concept"):
                    self.concepts_by_trial[c["trial_id"]].add(c["concept"])
                    self.terms_by_trial[c["trial_id"]] += [t for t in (c.get("term") or []) if isinstance(t, str)]
        self.structured = any(self.concepts_by_trial.values())
        docs = {t["trial_id"]: words(" ".join([t.get("title") or ""] + (t.get("conditions") or []) * 2
                                              + (t.get("condition_mesh") or []) * 2)) for t in trials}
        df = collections.Counter(w for ws in docs.values() for w in set(ws))
        n = len(docs)
        self.idf = {w: math.log((n + 1) / (c + 1)) + 1 for w, c in df.items()}
        self.vecs = {tid: self._vec(ws) for tid, ws in docs.items()}

    def _vec(self, ws):
        tf = collections.Counter(w for w in ws if w in self.idf)
        v = {w: c * self.idf[w] for w, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1
        return {w: x / norm for w, x in v.items()}

    def candidates(self, patient, k=15):
        text = " ".join([patient.get("summary") or ""] * 3 + [d["text"] for d in patient["documents"]])
        pv = self._vec(words(text))
        scores = sorted(((sum(pv.get(w, 0) * x for w, x in tv.items()), tid) for tid, tv in self.vecs.items()), reverse=True)
        return [(tid, round(s, 3)) for s, tid in scores[:k] if s > 0]

    def plan(self, patient, k=15):
        cands = self.candidates(patient, k)
        crit_text = " ".join(t for tid, _ in cands for t in self.crit_by_trial[tid])
        trial_text = " ".join(" ".join([t.get("title") or ""] + (t.get("conditions") or []))
                              for t in self.trials if t["trial_id"] in {c for c, _ in cands})
        terms = " ".join(t for tid, _ in cands for t in self.terms_by_trial[tid])
        vocab = set(words(crit_text + " " + trial_text + " " + terms))
        if self.structured:          # ①-b: the concepts the candidates' criteria name
            concepts = sorted({k_ for tid, _ in cands for k_ in self.concepts_by_trial[tid]})
        else:
            concepts = sorted(k_ for k_, rx in TRIGGERS.items() if re.search(rx, crit_text, re.I))
        return {"candidate_trials": cands, "trigger_concepts": concepts, "vocab": vocab,
                "n_criteria": sum(len(self.crit_by_trial[tid]) for tid, _ in cands)}


def relevant(unit_text, vocab):
    """Content words of the unit that also appear in the candidate trials' criteria."""
    return sorted({w for w in words(unit_text) if w in vocab})
