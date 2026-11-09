"""Rule layer of Agent 2: concept matching, numeric values, negation / family / certainty / plan cues, dates.

Everything here works on one fact unit (a sentence, line or list item from segment.py) plus its context
(document, section heading). The LLM layer (later) is meant to handle what these rules cannot: unusual wording,
conditions outside the lexicons, and fine-grained plan vs received distinctions.
"""
import re
from datetime import date, timedelta

# ------------------------------------------------------------------ sections

SECTION_RE = re.compile(r"^\s*(?P<h>[A-Z][A-Za-z /&()\-]{1,40}?)\s*:", re.M)
SECTION_MAP = [
    (r"past surgical|surgical history|PSH", "psh"),
    (r"past medical|medical history|PMH|problem list|diagnos", "pmh"),
    (r"allerg", "allergy"),
    (r"medication|meds|current therapy|treatment history|prior therapy|oncologic history|treatment to date", "meds"),
    (r"social", "social"),
    (r"family", "family"),
    (r"review of systems|ROS", "ros"),
    (r"vital", "vitals"),
    (r"physical exam|exam\b|examination|Gen\b|HEENT|CV\b|Resp|Abd|Neuro|Ext|Skin|Eyes|Psych|GI\b|GU\b|Const", "exam"),
    (r"assessment|impression|imp\b|a/p|plan|recommendation|discussion|summary", "plan"),
    (r"HPI|history of present|CC\b|chief complaint|reason for visit|interval history|course", "narrative"),
    (r"lab|result|panel|serology|urinalysis|CBC|chemistry|coagulation|lipid|glycemia|other", "labs"),
    (r"imaging|radiology|CT\b|MRI|echo|ECG|EKG|PFT|pulmonary function", "imaging"),
    (r"patholog|biopsy|histolog", "pathology"),
]


HEAD_RE = re.compile(r"^\s*(?P<h>[A-Z][A-Z /&\-]{2,40}(?:\s*\([^)\n]{0,40}\))?|HPI|CC|Imp|Impression|Assessment|Plan|A/P|Assessment and plan|"
                     r"Assessment/Plan|Course|Hospital course|Staging|Treatment to date)\s*:", re.M)


def section_name(heading):
    for pat, name in SECTION_MAP:
        if re.search(pat, heading, re.I):
            return name
    return "other"


def sections(text):
    """[(start_offset, section)] in order: a line starting with an ALL-CAPS heading (or HPI/CC/Imp/Plan) and a
    colon opens a section that runs to the next one. Inline labels such as 'Eyes:' inside ROS do not."""
    out = [(0, "")]
    for m in HEAD_RE.finditer(text):
        out.append((m.start("h"), section_name(m.group("h"))))
    return out


def section_at(secs, pos):
    cur = ""
    for s, name in secs:
        if s <= pos:
            cur = name
        else:
            break
    return cur


# ------------------------------------------------------------------ cues

NEG_RE = re.compile(r"(?:^|[,;(]\s*|\b)(?:no|not|denies|denied|never|without|negative for|none|non-?|nil|NKDA|ruled out|absent|free of)\b", re.I)
NEG_START = re.compile(r"^\s*(?:no|not|denies|denied|never|without|negative for|none|nil|NKDA)\b", re.I)
FAMILY_RE = re.compile(r"\b(?:mother|father|sister|brother|sibling|aunt|uncle|grand(?:mother|father|parent)s?|cousin|"
                       r"family history|FHx|FH|relative's|relatives|parents?)\b", re.I)
# a spouse whose own history is told ("Her husband was diagnosed with colon cancer"); "Lives with spouse" is the
# patient's living situation, not someone else's history
OTHER_PERSON_RE = re.compile(r"\b(?:husband|wife|spouse|partner)(?:'s)?\s+(?:was|is|has|had|died|passed|developed|"
                             r"underwent|diagnosed|suffers|with\s+(?:a\s+)?(?:history|hx))\b", re.I)
SUSPECT_RE = re.compile(r"\b(?:suspect(?:ed)?|possible|possibly|probable|presumed|presumptive|likely|features of|"
                        r"rule out|r/o|concern(?:ing)? for|cannot exclude|can't exclude|not excluded|under work-?up|"
                        r"query|questionable|suggestive of|differential)\b|\?", re.I)
REPORTED_RE = re.compile(r"\b(?:reports?|reported|states?|per patient|patient notes|mother notes|father notes|"
                         r"by history|self-reported|c/o|complains?|admits?|endorses?)\b", re.I)
# advice about a behavior is a plan, not the patient's habit (review of v13.3.1: "Mild eye symptoms: lubricating
# drops, no smoking, reassess at each visit" was read as a current smoker)
_BEHAV = r"(?:smok\w*|tobacco|cigarettes?|vap(?:e|ing)|alcohol|EtOH|drink(?:ing)?|(?:recreational |illicit )?drugs?|substances?)"
BEHAV_SERVICE_RE = re.compile(r"\b(?:smoking|tobacco|alcohol|substance(?: use)?|drug)\s+(?:cessation|abstinence|program(?:me)?s?|"
                              r"clinics?|services?|counsel\w*|reduction|rehab\w*|treatment|education)\b", re.I)
BEHAV_ADVICE_RE = re.compile(r"\b(?:no|avoid(?:ance of)?|avoiding|stop(?:ping)?|cease|abstain(?:ing)? from|abstinence from|"
                             r"refrain(?:ing)? from|limit(?:ing)?|minimi[sz]e|reduce|cut(?:ting)? down(?: on)?|quit(?:ting)?)\s+"
                             r"(?:\w+\s+){0,2}?" + _BEHAV + r"\b", re.I)
ADVICE_RE = re.compile(r"\b(?:advised?|advice|counsel(?:l?ed|l?ing)?|encourag(?:ed|e)|recommend(?:ed|ation)?|instructed|"
                       r"educat(?:ed|ion)|reassess|continue|monitor)\b", re.I)
PLAN_RE = re.compile(r"\b(?:plan(?:ned|s)?|to start|will start|will begin|start(?:ing)? on|consider(?:ing|ed)?|"
                     r"discuss(?:ed|ion)?|options?|recommend(?:ed)?|candidate for|referr(?:al|ed)|scheduled|"
                     r"awaiting|pending|not yet started|step-down|if (?:relapse|needed|progression)|eligible for|"
                     r"would|could|may)\b", re.I)
DECLINED_RE = re.compile(r"\b(?:declined|refused)\b", re.I)

# ------------------------------------------------------------------ lexicons (general clinical vocabulary)

DIAG_RE = re.compile(
    r"\b(?:\w*carcinoma|cancer|tumou?r|malignan\w*|lymphoma|leuka?emia|myeloma|sarcoma|melanoma|neoplasm|"
    r"glioma|mass|lesion|nodules?|metasta\w*|"
    r"diabetes|T[12]DM|DM[12]?|DKA|hypertension|HTN|dyslipid\w*|hyperlipid\w*|hypercholesterol\w*|"
    r"hypertriglycerid\w*|obes\w*|overweight|cirrhosis|hepatitis|steatosis|fatty liver|NAFLD|NASH|MASLD|"
    r"HBV|HCV|HIV|CKD|ESRD|AKI|nephrotic|nephritis|nephropathy|proteinuria|"
    r"syndrome|disease|disorder|failure|insufficiency|infarction|MI|stroke|TIA|angina|CAD|CVD|CHF|HFrEF|HFpEF|"
    r"arrhythmi\w*|fibrillation|AF|AFib|flutter|cardiomyopathy|valv\w+|"
    r"asthma|COPD|emphysema|fibrosis|ILD|IPF|UIP|pneumonitis|pneumonia|bronchiectasis|"
    r"infection|infected|sepsis|tubercul\w*|TB|abscess|cellulitis|mucormycosis|fungal|"
    r"arthritis|RA|lupus|SLE|psoriasis|psoriatic|dermatitis|eczema|vasculitis|colitis|Crohn\w*|IBD|"
    r"pancreatitis|gallstones?|cholelithiasis|thyroid\w*|Graves|hashimoto|hypothyroid\w*|hyperthyroid\w*|"
    r"thyrotoxicosis|orbitopathy|ophthalmopathy|"
    r"an(?:a)?emia|thrombo\w*|embol\w*|DVT|PE|bleed\w*|hemorrhage|coagulopathy|"
    r"depress\w*|anxiety|psychiatric|psychosis|bipolar|schizophren\w*|dementia|cognitive|seizures?|epilep\w*|"
    r"migraines?|headaches?|neuropathy|retinopathy|NPDR|PDR|maculopathy|detachment|glaucoma|cataract|"
    r"uveitis|retinal|"
    r"fractures?|osteopor\w*|osteopenia|gout|"
    r"pregnan\w*|immunodeficien\w*|immunosuppress\w*|transplant\w*|"
    r"remission|relapse|recurren\w*|progression|progressive|refractory|"
    r"\w+itis|\w+osis|\w+oma|\w+pathy|\w+emia|\w+algia)\b", re.I)

DRUG_WORDS = (
    r"metformin|insulin\w*|glimepiride|gliclazide|glipizide|sulfonylurea|GLP-1(?: RA)?|SGLT2(?: inhibitor)?|DPP-4|"
    r"semaglutide|liraglutide|dulaglutide|tirzepatide|empagliflozin|dapagliflozin|pioglitazone|"
    r"methotrexate|hydroxychloroquine|sulfasalazine|leflunomide|azathioprine|mycophenolate|cyclosporine|"
    r"tacrolimus|cyclophosphamide|rituximab|tocilizumab|adalimumab|infliximab|etanercept|abatacept|"
    r"prednisolone|prednisone|methylprednisolone|dexamethasone|hydrocortisone|budesonide|steroids?|corticosteroids?|"
    r"methimazole|carbimazole|propylthiouracil|PTU|levothyroxine|beta-?blocker|propranolol|"
    r"amphotericin\w*|posaconazole|isavuconazole|voriconazole|fluconazole|antibiotics?|antifungals?|antivirals?|"
    r"entecavir|tenofovir|"
    r"chemotherapy|chemo|immunotherapy|platinum(?: doublet)?|carboplatin|cisplatin|oxaliplatin|pemetrexed|"
    r"docetaxel|paclitaxel|gemcitabine|etoposide|pembrolizumab|nivolumab|atezolizumab|durvalumab|ipilimumab|"
    r"osimertinib|alectinib|trastuzumab|pertuzumab|tamoxifen|letrozole|anastrozole|exemestane|fulvestrant|"
    r"palbociclib|ribociclib|abemaciclib|capecitabine|sorafenib|lenvatinib|atezolizumab|bevacizumab|"
    r"aspirin|clopidogrel|warfarin|heparin|enoxaparin|apixaban|rivaroxaban|dabigatran|anticoagula\w*|"
    r"statins?|atorvastatin|rosuvastatin|simvastatin|fenofibrate|ezetimibe|omega-3|icosapent\w*|"
    r"ACE inhibitor|ARB|lisinopril|enalapril|ramipril|losartan|valsartan|amlodipine|nifedipine|"
    r"hydrochlorothiazide|furosemide|spironolactone|metoprolol|bisoprolol|carvedilol|"
    r"ibuprofen|naproxen|NSAIDs?|acetaminophen|paracetamol|opioids?|triptans?|sumatriptan|rizatriptan|"
    r"topiramate|propranolol|amitriptyline|valproate|erenumab|galcanezumab|fremanezumab|botulinum|CGRP\w*|"
    r"oral contraceptive|contraceptive|OCP|estrogen|progestin|"
    r"omeprazole|pantoprazole|PPI|antidepressants?|SSRIs?|sertraline|escitalopram|fluoxetine|"
    r"potassium chloride|magnesium sulfate|iron|vitamin \w+|supplements?|vaccin\w*|"
    r"radioactive iodine|RAI|radiotherapy|radiation|"
    r"\w+mab|\w+tinib|\w+ciclib|\w+platin|\w+taxel|\w+statin|\w+pril|\w+sartan|\w+olol|\w+dipine|"
    r"\w+conazole|\w+cycline|\w+mycin|\w+cillin|\w+floxacin|\w+parin|\w+xaban|\w+gliptin|\w+gliflozin|"
    r"\w+glutide|\w+prazole|\w+triptan")
DRUG_RE = re.compile(r"\b(?:" + DRUG_WORDS + r")\b", re.I)
DOSE_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|ug|g|units|IU|mg/kg|mg/m2|AUC\s*\d)\b", re.I)

PROC_RE = re.compile(
    r"\b(?:\w+ectomy|\w+otomy|\w+ostomy|\w+plasty|\w+scopy|\w+pexy|surgery|surgical|operation|resection|"
    r"excision|debridement|biopsy|transplant\w*|TURBT|TACE|RFA|ablation|radiation|radiotherapy|SBRT|"
    r"irradiation|chemoembolization|stent\w*|PCI|CABG|bypass|dialysis|hemodialysis|vitrectomy|"
    r"buckle|laser|photocoagulation|injection|infusion|catheter\w*|amputation|repair|implant\w*)\b", re.I)

STAGE_RE = re.compile(r"\b(?:stage\s+[0IV]+[ABC]?\d?|[cpy]?T[0-4x][a-c]?\s*N[0-3x][a-c]?\s*M[01x][a-c]?|"
                      r"Gleason|BCLC\s*\w|Child-Pugh\s*\w*|ISS\s*\w+)\b", re.I)
MARKER_RE = re.compile(r"\b(?:ER|PR|HER2|PD-?L1|TPS|CPS|EGFR(?! \()|ALK|ROS1|KRAS|BRAF|NTRK|RET|MET|BRCA[12]?|"
                       r"MSI(?:-H)?|dMMR|TMB|Ki-?67|TTF-1|p16|HPV|IDH\w*|MGMT)\b(?!\s*\d+\s*mL)")
METS_RE = re.compile(r"\bmetasta\w*|\bM1[abc]?\b", re.I)

ECOG_RE = re.compile(r"\b(?:ECOG(?:\s+PS)?|performance status|WHO PS)\s*(?:of|:|=)?\s*([0-4])\b", re.I)
# named scales whose value is not a plain number after the name (①-b concepts)
NYHA_RE = re.compile(r"\bNYHA(?:\s+(?:functional\s+)?class)?\s*(?:of|:|=)?\s*(IV|III|II|I|[1-4])\b(?!\s*[-/]\s*(?:IV|III|II|[1-4]))")
CHILD_PUGH_RE = re.compile(r"\bChild[- ]Pugh(?:\s+(?:class|score))?\s*(?:of|:|=)?\s*([ABC])\s*-?\s*(\d{1,2})?\b", re.I)
HERTEL_RE = re.compile(r"\b(?:Hertel|exophthalmometry)\s*(?:of|:|=)?\s*(\d{1,2}(?:\.\d)?)\s*(?:/\s*(\d{1,2}(?:\.\d)?))?\s*mm", re.I)
CTSI_RE = re.compile(r"\b(?:modified\s+)?(?:CT\s+severity\s+index|CTSI)\s*(?:of|:|=)?\s*(\d{1,2})\b", re.I)
VIRAL_UNDETECTED_RE = re.compile(r"\b(HBV\s*DNA|HCV\s*RNA|HIV(?:-1)?\s*(?:RNA|viral load))\s+(?:not\s+detected|undetectable)"
                                 r"(?:\s*\(\s*<\s*(\d+(?:\.\d+)?)\s*(IU/mL|copies/mL)\s*\))?", re.I)
MENOPAUSE_RE = re.compile(r"\b(post-?menopausal|menopause(?:\s+since)?|pre-?menopausal|peri-?menopausal)\b", re.I)
KPS_RE = re.compile(r"\b(?:Karnofsky|KPS)\s*(?:of|:|=)?\s*(\d{2,3})", re.I)

SMOKE_RE = re.compile(r"\b(?:smok\w*|tobacco|cigarettes?|pack-?years?|vap\w+)\b", re.I)
ALC_RE = re.compile(r"\b(?:alcohol|EtOH|beers?|wine|soju|drinker)\b|\b(?:\d+(?:\s*[-\u2013]\s*\d+)?|one|two|few|several)\s+drinks?\b|"
                    r"\bdrinks?\s*(?:~|about|approx\w*\s*)?(?:\d|per\b|/|a (?:day|week|month)|daily|weekly|socially|heavily|occasionally)|"
                    r"\bdrinking\s+(?:alcohol|heavily|socially|daily)", re.I)   # not "able to eat and drink normally"
SUBST_RE = re.compile(r"\b(?:substance use|illicit|recreational drugs?|drug use|cannabis|marijuana|IVDU)\b", re.I)
ALLERGY_RE = re.compile(r"\b(?:NKDA|NKA|allerg\w*|anaphyla\w*)\b", re.I)
PREG_RE = re.compile(r"\b(?:pregnan\w*|lactat\w*|breast-?feed\w*|postpartum|LMP|gravida|G\dP\d)\b", re.I)
CONTRA_RE = re.compile(r"\b(?:contracep\w*|condoms?|IUD|IUS|tubal ligation|vasectomy|abstinen\w*)\b", re.I)

SEROLOGY_RE = re.compile(
    r"\b(?P<name>HBsAg|hepatitis B (?:s|surface) ?(?:Ag|antigen)|hepatitis C (?:Ab|antibody)|anti-?HBc(?: total| IgM)?|anti-?HBs|HBV DNA|HBeAg|anti-?HCV|HCV (?:antibody|Ab|RNA)|"
    r"HIV(?:-1/2)?(?: Ag/Ab| antibody| RNA)?|hCG|beta-?hCG|pregnancy test|QuantiFERON|IGRA|TB test|ANA|"
    r"anti-?dsDNA|RF|anti-?CCP|TRAb|TSI|TPO|ANCA|C3|C4|culture|PCR|antigen|IgG|IgM|ketones|nitrite|"
    r"leukocyte esterase|blood|protein|glucose)\b(?P<rest>[^.;,\n]{0,40}?)\b(?P<res>non-?reactive|reactive|"
    r"negative|positive|detected|not detected|undetectable|indeterminate|trace|\d\+)\b", re.I)

# ------------------------------------------------------------------ numeric labs / vitals

NUM = r"(?P<op><=|>=|<|>|≤|≥)?\s*(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?:\s*/\s*(?P<num2>\d+(?:\.\d+)?))?"
UNIT = r"(?:\s*(?P<unit>%|(?:x\s?)?10\^?\d+/(?:L|uL|µL)|[a-zA-Zµ]+(?:/[a-zA-Z0-9.^µ]+)*(?:/1\.73\s?m2)?|°C))?"


def alias_regex(alias):
    """Short all-caps aliases (T, K, HR, Hb) are case-sensitive and need a number right after; others ignore case."""
    esc = re.escape(alias).replace(r"\ ", r"\s+")
    if len(alias) <= 3:
        return re.compile(r"(?<![\w/-])" + esc + r"(?![\w/-])\s*(?:\([^)]{0,20}\))?\s*(?:[:=]|\b(?:was|is|of|at)\b)?\s*"
                          r"(?=[<>≤≥]?\s*\d)")
    # not part of an "X/Y" expression ("protein/creatinine", "FEV1/FVC"): those are ratios, not the analyte
    return re.compile(r"(?<![\w/-])(?<!/ )" + esc + r"(?![\w-])(?!\s*/\s*[A-Za-z])", re.I)


def build_numeric_matchers(concepts):
    """Longest aliases first across all concepts, so 'urine protein/creatinine ratio' claims its text before
    'creatinine' can."""
    out = []
    for c in concepts:
        if c.get("type") in ("lab", "vital", "measurement") and c.get("aliases"):
            for a in c["aliases"]:
                out.append((len(a), c["key"], alias_regex(a), c))
    return [(k, rx, c) for _, k, rx, c in sorted(out, key=lambda x: -x[0])]


TREND_KEYS = {"mmse", "moca", "cdr", "cat_score", "das28", "egfr", "creatinine", "hba1c", "body_weight", "bmi", "nt_probnp",
              "six_minute_walk_distance", "lvef", "fev1", "fvc", "dlco", "urine_protein_creatinine_ratio",
              "urine_albumin_creatinine_ratio", "triglycerides", "alt", "ast", "hemoglobin", "platelet_count"}
COUNT_UNIT = r"((?:x\s?)?10\^?\d/(?:L|uL|µL))"
ABS_LABELED = re.compile(r"\babs(?:olute)?\.?\s*:?\s*(\d+(?:\.\d+)?)\s*" + COUNT_UNIT + r"?", re.I)
ABS_LEADING = re.compile(r"^\s*\(\s*(\d+(?:\.\d+)?)\s*" + COUNT_UNIT + r"\s*(?=[);,]|$)")


def abs_count(text, pos):
    """Absolute count written after a percentage: '(abs 6.0 x10^9/L)' first, else '(4.0 x10^9/L)' when that
    number is not the start of a reference range ('1.9 x10^9/L ... 5.9'). Returns (raw, unit, end) or None."""
    seg_end = min(len(text), pos + 80)
    nxt = re.search(r"[;,]\s*(?!abs)[A-Z][a-z]+\s+\d", text[pos:seg_end])   # stop at the next analyte
    if nxt:
        seg_end = pos + nxt.start()
    m = ABS_LABELED.search(text, pos, seg_end)
    if m:
        unit = m.group(2)
        if not unit:      # 'abs 0.5' with the unit given earlier in the parenthesis
            u = re.search(COUNT_UNIT, text[pos:seg_end])
            unit = u.group(1) if u else None
        return m.group(1), unit, m.end()
    m = ABS_LEADING.match(text[pos:pos + 60])
    return (m.group(1), m.group(2), pos + m.end()) if m else None
RATIO_GAP = re.compile(r"\bratio\b|/|\bindex\b", re.I)


VALUE_AFTER = re.compile(r"(?:\s*\([^)]{0,30}\))?(?:,\s*(?:fasting|random|serum|plasma|whole blood|venous|arterial))?"
                         r"\s*(?:[:=]|of|was|is|at|peaked)?\s*(?:\w+\s+){0,2}?" + NUM + UNIT)


def numeric_values(unit_text, matchers):
    """[(concept, value, unit_written, extra)] for 'alias ... number unit' patterns inside one unit."""
    out, taken, found = [], [], set()
    for key, rx, c in matchers:
        if key in found:
            continue
        for m in rx.finditer(unit_text):
            if any(m.start() < b and m.end() > a for a, b in taken):
                continue
            v = VALUE_AFTER.match(unit_text, m.end())
            if not v or v.start("num") - m.end() > 25:
                continue
            if re.match(r"[A-Za-z]\d", unit_text[v.end("num"):v.end("num") + 2]):
                continue                                  # "PD-L1 22C3 TPS 70%": 22C3 is an antibody clone, not a value
            if RATIO_GAP.search(unit_text[m.end():v.start("num")]):     # "creatinine ratio 0.4": not the analyte
                continue
            raw = v.group("num").replace(",", "")
            unit = (v.group("unit") or "").strip().rstrip(".") or None
            end = v.end()
            if unit == "%" and c.get("unit") != "%" and "%" not in (c.get("alt_units") or {}):
                # a percentage is not this analyte ("Neutrophils 62 %" is not an ANC); for counts take the
                # absolute value written right after it ("(abs 3.9 x10^3/uL", "(1.9 x10^9/L"), else skip
                got = abs_count(unit_text, v.end()) if c.get("unit") == "10^9/L" else None
                if not got:
                    continue
                raw, unit, end = got
            if c.get("unit") == "%" and unit and unit.upper() == "L":
                pp = re.match(r"[^%;]{0,20}?\(?\s*(\d+(?:\.\d+)?)\s*%\s*(?:of\s+)?pred", unit_text[end:end + 40], re.I)
                if not pp:
                    continue                              # "FVC 2.56 L" alone: litres are not % predicted
                raw, unit, end = pp.group(1), "%", end + pp.end()   # "FEV1 1.12 L (38% predicted)" -> 38 %
            if key in TREND_KEYS and not v.group("num2"):
                pos, nxt_num = v.end("num"), None            # "MoCA 20 to 19", "UACR 980 -> 1,120 -> 1,150 mg/g"
                while (later := re.match(r"\s*(?:%\s*)?(?:\([^)]{0,20}\)\s*)?(?:->|→|to|then)\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\b"
                                         r"(?!\s*(?:years?|months?|weeks?|days?|times))", unit_text[pos:pos + 44])):
                    nxt_num, pos = later.group(1).replace(",", ""), pos + later.end()
                if nxt_num is not None and not re.match(r"\s*\S{0,8}\s*(?:range|ref)", unit_text[pos:pos + 24], re.I):
                    raw = nxt_num
                    u2 = UNIT and re.match(r"\s*(%|[a-zA-Zµ]+(?:/[a-zA-Z0-9.^µ]+)*(?:/1\.73\s?m2)?)", unit_text[pos:pos + 20])
                    if unit and unit.lower() in ("to", "then", "->"):
                        unit = u2.group(1) if u2 else None
                    end = pos + (u2.end() if u2 else 0)
            found.add(key)
            val = float(raw)
            val = int(val) if val.is_integer() and "." not in raw else val
            if unit and unit.lower() in ("on", "and", "with", "in", "since", "at", "after", "the", "of", "to", "from"):
                unit = None
            extra = {}
            if v.group("num2") and key == "blood_pressure":
                extra = {"systolic": val, "diastolic": float(v.group("num2"))}
                val = f"{v.group('num')}/{v.group('num2')}"
            if v.group("op"):
                extra["comparator"] = v.group("op").replace("≤", "<=").replace("≥", ">=")
            # the lab's reference range right after the value ("ALT 74 U/L (ref 10-40)", "(<1.75)"): ①-b has 41
            # criteria written in x ULN that need the upper limit
            rr = re.match(r"\s*(?:\w{1,3}\s*)?[(\[]\s*(?:ref(?:erence)?(?:\s+range)?\s*:?\s*|normal\s*:?\s*)?"
                          r"(?:(?P<lo>\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(?P<hi>\d+(?:\.\d+)?)|(?P<op><|>|<=|>=)\s*(?P<lim>\d+(?:\.\d+)?))",
                          unit_text[end:end + 40], re.I)
            if rr and not v.group("num2"):
                if rr.group("hi"):
                    extra["ref_low"], extra["ref_high"] = float(rr.group("lo")), float(rr.group("hi"))
                elif rr.group("op").startswith("<"):
                    extra["ref_high"] = float(rr.group("lim"))
                else:
                    extra["ref_low"] = float(rr.group("lim"))
            out.append((key, val, unit, extra))
            taken.append((m.start(), end))
            break
    return out


def convert(value, unit, concept):
    """Convert to the concept's default unit with alt_units. Returns (value, unit, ok)."""
    base = concept.get("unit")
    if (concept.get("ratio_below") and isinstance(value, (int, float)) and not isinstance(value, bool)
            and value < concept["ratio_below"] and (not unit or unit.lower() == "ratio")):
        return round(value * 100, 4), base, True          # "FEV1/FVC 0.44" -> 44 %
    if not isinstance(value, (int, float)) or not unit or not base:
        return value, (base or unit), True
    norm = lambda u: u.replace(" ", "").replace("µ", "u").lower()  # noqa: E731
    if norm(unit) == norm(base) or norm(unit).lstrip("x") == norm(base).lstrip("x"):
        return value, base, True
    for u, f in (concept.get("alt_units") or {}).items():
        if norm(u) == norm(unit) or norm(u).lstrip("x") == norm(unit).lstrip("x"):
            return round(value * f, 6), base, True
    if re.fullmatch(r"[a-z]+", unit) and len(unit) > 3:      # a following word ("HR 72 sinus"), not a unit
        return value, base, True
    return value, unit, False


# ------------------------------------------------------------------ dates

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
D_FULL = re.compile(r"\b(20\d{2}|19\d{2})-(\d{1,2})-(\d{1,2})\b")
D_YM = re.compile(r"\b(20\d{2}|19\d{2})-(\d{1,2})\b(?!-\d)")
D_MY_SLASH = re.compile(r"\b(\d{1,2})/(20\d{2}|19\d{2})\b")
D_MD = re.compile(r"(?<![\d-])(\d{2})-(\d{2})(?![\d-])(?!\s*(?:years?|yrs?|months?|weeks?|days?|hours?|times|mg|%|/))")
# full month names or exact abbreviations only ("Marfan" is not March); bare "May" needs a day or a year after it
D_MONTH = re.compile(r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May(?=\s+\d)|June?|July?|Aug(?:ust)?|"
                     r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b\.?"
                     r"(?:\s+(\d{1,2})(?:st|nd|rd|th)?,?)?(?:\s+(20\d{2}|19\d{2}))?\b")
D_YEAR = re.compile(r"(?<![\d./-])((?:19|20)\d{2})\b(?![-/]\d)")
D_SINCE = re.compile(r"\b(?:since|started|start|on since)\s+~?(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+)?((?:19|20)\d{2})(?:-(\d{1,2})(?:-(\d{1,2}))?)?", re.I)
# "3 days ago"; a range "10-15 years ago" counts back the larger number (the earliest possible day)
D_REL = re.compile(r"\b(?:\d+\s*(?:-|to)\s*)?(\d+|a|one|two|three|four|five|six)\s+(day|week|wk|month|mo|year|yr)s?\s+ago\b", re.I)
D_LAST = re.compile(r"\b(yesterday|last night|last week|last month|last year|today|this morning|this week)\b", re.I)
D_RANGE_END = re.compile(r"\bto\s+(20\d{2}-\d{1,2}-\d{1,2})\b")
D_MASKED = re.compile(r"\[\*\*[^\]]*\*\*\]")
WORDNUM = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def _safe(y, m, d=1):
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def resolve_date(unit_text, doc_date, as_of):
    """observed_date for a fact unit. Returns (iso or None, how). Partial dates resolve to the first day of the
    month/year (the earliest possible day, conservative for 'within N days' windows)."""
    if D_MASKED.search(unit_text):
        return None, "masked"
    # ongoing facts ("since 2019", "start 2026-09-19"): observed at the document date, start date kept apart
    if D_SINCE.search(unit_text) and not D_RANGE_END.search(unit_text) and not re.search(
            r"\b(?:stopped|discontinued|until|completed|ended)\b", unit_text, re.I):
        if doc_date and doc_date <= as_of:
            return doc_date, "ongoing"
    dd = date.fromisoformat(doc_date) if doc_date else None
    ref = date.fromisoformat(as_of)
    cand, how = None, "document"
    m = D_RANGE_END.search(unit_text)
    if m:
        cand, how = _safe(*m.group(1).split("-")), "range_end"
    if not cand and (m := D_FULL.search(unit_text)):
        cand, how = _safe(m.group(1), m.group(2), m.group(3)), "explicit"
    if not cand and (m := D_YM.search(unit_text)):
        cand, how = _safe(m.group(1), m.group(2)), "year_month"
    if not cand and (m := D_MY_SLASH.search(unit_text)):
        cand, how = _safe(m.group(2), m.group(1)), "year_month"
    if not cand and dd and (m := D_MD.search(unit_text)) and 1 <= int(m.group(1)) <= 12:
        c = _safe(dd.year, m.group(1), m.group(2))
        if c and c > dd:
            c = _safe(dd.year - 1, m.group(1), m.group(2))
        cand, how = c, "month_day"
    if not cand and (m := D_MONTH.search(unit_text)):
        mon = MONTHS[m.group(1)[:3].lower()]
        if m.group(3):
            cand, how = _safe(m.group(3), mon, m.group(2) or 1), "month_name"
        elif dd:
            y = dd.year if mon <= dd.month else dd.year - 1
            cand, how = _safe(y, mon, m.group(2) or 1), "month_name"
    if not cand and dd and (m := D_REL.search(unit_text)):
        n = WORDNUM.get(m.group(1).lower()) or int(m.group(1))
        u = m.group(2).lower()
        days = n * {"day": 1, "week": 7, "wk": 7, "month": 30, "mo": 30, "year": 365, "yr": 365}[u]
        cand, how = dd - timedelta(days=days), "relative"
    if not cand and dd and (m := D_LAST.search(unit_text)):
        w = m.group(1).lower()
        days = {"yesterday": 1, "last night": 1, "last week": 7, "last month": 30, "last year": 365}.get(w, 0)
        cand, how = dd - timedelta(days=days), "relative"
    if not cand and (m := D_YEAR.search(unit_text)):
        cand, how = _safe(m.group(1), 1), "year"
    if cand is None:
        return (doc_date, "document") if dd and dd <= ref else (None, "no_date")
    if cand > ref or cand.year < 1900:
        return None, "implausible"
    return cand.isoformat(), how


# ------------------------------------------------------------------ negation scope (per term / per clause)

LABEL_RE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9 /&()\-]{0,30}:\s*")
NEG_CUE = re.compile(r"\b(?:no|not|denies|denied|deny|never|without|negative for|no evidence of|free of|absence of|"
                     r"ruled out|nil)\b|\bnon-(?=\w)", re.I)
# the scope also stops at a time anchor or an indication: "no alcohol since the cirrhosis diagnosis", "denies prior
# therapy for liver cancer", "no new flashes since surgery" deny the alcohol / therapy / flashes, not what follows;
# "with" after "diagnosed / treated / been" stays inside: "never been diagnosed with HIV or hepatitis"
NEG_RESET = re.compile(r"\b(?:but|however|although|except|apart from|other than|since|after|before|until|following|"
                       r"for)\b|(?<!diagnosed\s)(?<!treated\s)(?<!been\s)\bwith\b|[;.:(]|"
                       r",\s*(?:mild|moderate|severe|normal|intact|attached|healed|palpable|small|large|warm|soft|"
                       r"regular|clear|stable|positive|reduced|increased|decreased|elevated|low|high|present|"
                       r"\w+\s+(?:normal|intact|present|attached|symmetric))\b", re.I)
POS_LEAD = re.compile(r"^\s*(?:but|however|although|positive for|has|with|shows?)\b", re.I)


def term_negated(text, start):
    """Is the term starting at `start` inside the scope of a negation? The scope runs from the last negation cue
    before the term, and is reset by ';', '.', ':', '(' or 'but / however / with ...' between cue and term.
    'No fever, vomiting or rash' -> all three negated; 'Psoriasis, no arthritis' -> only arthritis;
    'LVEF 60%, no evidence of pulmonary hypertension' -> hypertension negated."""
    window = text[:start]
    cues = list(NEG_CUE.finditer(window))
    if not cues:
        return False
    if cues[-1].group(0).lower().startswith("non-") and start - cues[-1].end() > 0:
        return False                              # "non-" negates only its own word ("Non-smoker, alcohol ...")
    after = window[cues[-1].end():]
    if re.search(r",\s*$", window) and POS_HEAD.match(text, start):   # "no fever or chills, mild fatigue"
        return False
    return not NEG_RESET.search(after)


POS_HEAD = re.compile(r"\s*(?:mild|moderate|severe|normal|intact|attached|healed|palpable|small|large|warm|soft|"
                      r"regular|clear|stable|positive|reduced|increased|decreased|elevated|low|high|present|"
                      r"\w+\s+(?:\d\+\s+)?(?:normal|intact|present|attached|symmetric))\b", re.I)


def clause_polarity(text):
    """Split a finding sentence into its positive and its denied parts (label like 'Resp:' removed).
    Returns (positive_text, negated_text); either may be ''. A clause continues the negation of the clause before
    it ('No fever, vomiting, abdominal pain') unless it starts with a positive lead word."""
    body = LABEL_RE.sub("", text, count=1)
    pos, neg, in_neg = [], [], False
    for cl in re.split(r"\s*[,;]\s*", body):
        if not cl.strip():
            continue
        if re.match(r"\s*non-\w+\s+(?!(?:with|and|or|on|in|at|to|but|of|for)\b)[a-z]", cl, re.I) and not NEG_CUE.search(cl, re.match(r"\s*non-\w+", cl, re.I).end()):
            pos.append(cl.strip())               # "non-bilious vomiting": a kind of vomiting, not a denial
            in_neg = False
            continue
        if NEG_CUE.match(cl.strip()) or re.match(r"^\s*(?:in|with|and|or)\s+no\b", cl, re.I):
            in_neg = True
        elif POS_LEAD.match(cl) or not in_neg:
            in_neg = False
        elif re.match(r"\s*(?:and|but|while)\s+(?:her|his|their|the|she|he|it|they)\b", cl, re.I) or re.search(
                r"\b(?:has|have|shows?|noted|present|seen)\b", cl, re.I):
            in_neg = False                       # a new clause ("and her menses are regular"), not a listed item
        if re.fullmatch(r"\s*(?:negative|unremarkable|none|nil|normal)\.?\s*", cl, re.I):
            neg.append(cl.strip())               # "Psych: negative." = nothing found
            continue
        m = NEG_CUE.search(cl)
        while m and m.group(0).lower().startswith("non-") and re.match(r"non-\w+\s+(?!(?:with|and|or|on|in|at|to|but|of|for)\b)[a-z]", cl[m.start():], re.I):
            m = NEG_CUE.search(cl, m.end())      # "projectile non-bilious vomiting": a qualifier, look further
        if m and m.start() > 0 and not in_neg and re.match(r"(?:without|no|negative for|free of|absence of)\b|non-",
                                                           m.group(0), re.I):
            # a prepositional denial after a positive head ("Mild eye involvement without active orbitopathy");
            # a verb denial ("liver edge not palpable") negates the whole clause instead
            head, tail = cl[:m.start()].strip(" ,"), cl[m.start():].strip()
            if re.search(r"[a-z]{3}", head):
                pos.append(head)
            neg.append(tail)
            in_neg = True
            continue
        (neg if in_neg or m else pos).append(cl.strip())
    return ", ".join(pos), ", ".join(neg)
