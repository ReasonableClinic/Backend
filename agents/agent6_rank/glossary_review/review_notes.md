# 환자 표시용 용어집 검토 기록

## 결과와 검토 범위

- 전체 235행 검토. 모든 status를 reviewed로 변경.
- ko·abbr·kind 중 실제 변경: 21행, 23개 셀(ko 19, abbr 3, kind 1). status 변경은 이 집계에서 제외.
- en, source, dev_used, note 및 행 순서·열 순서는 모두 원본 그대로 보존.
- 원 note를 덮어쓰지 않았으므로 원래의 검토 요청 문구가 결과 CSV에도 남아 있음. 그에 대한 판단은 아래 30행 검토 기록을 참조.
- reviewed는 언어·의미·분류 검토를 수행했다는 작업 상태이며, 모든 임상 문맥이나 공식 허가 명칭을 외부 자료로 검증했다는 뜻이 아님.
- 이번 검토에는 원 시험 문서, SYN-0019의 모집 기준, 최신 MeSH·식약처 데이터베이스의 직접 대조가 포함되지 않음. 외부 문헌을 확인했다고 주장하지 않으며, 원문만으로 불명확한 항목은 유지 후 확인 대상으로 구분.
- 행 번호는 헤더를 제외한 데이터 행 기준. 일반적인 CSV 텍스트 줄 번호는 +1.

## 핵심 결정

1. **종양과 암 구분**: Urinary Bladder Neoplasms → 방광 종양 유지. Breast Neoplasms·Colorectal Neoplasms도 각각 유방 종양·대장 종양 유지. Ureteral Neoplasms·Liver Neoplasm도 기존 종양 표현 유지. MeSH 표제어만으로 악성 진단을 확정하지 않음.
2. **SYN-0019**: 첫 시험의 원문이 이 파일에는 없으므로 그 시험에서 방광암으로 표현해도 되는지는 별도 확인 필요. 전역 용어집을 특정 시험에 맞춰 좁히지 않음.
3. **pMN**: 통상 primary membranous nephropathy를 뜻하므로 원발성 막성 신병증 유지. 해당 시험의 약어 해석은 문맥 확인 필요.
4. **환자용 표현**: 전조가 있는 편두통 유지. 조짐편두통은 전문 용어 대응으로 원 note에 보존. 환자용 표현을 쓰더라도 임상적 제한·침범 범위·원인 정보는 삭제하지 않음.
5. **약물 한글명**: 리퍼타맙·텔리타시셉트는 임의로 다른 표기로 바꾸지 않고 유지. 국내 공식 표기는 확인 보류이며 공개 전 별도 대조 필요. 터제파타이드도 유지.
6. **기타 중요한 수정**: EBV는 감염이 아니라 바이러스 자체로 바로잡아 other로 변경. non-diabetic CKD는 비당뇨병성 만성 콩팥병으로 수정. 망막박리 진단에서 빠진 superior bullous를 복원.
7. **solid tumor 표기**: 암으로 확정하지 않은 원문의 범위를 보존하기 위해 고형 종양으로 통일. malignant가 명시된 Advanced Solid Malignancies는 진행성 고형암 유지. 전이성이라는 수식어는 악성 맥락을 담고 있으므로 그대로 보존했으며 이를 양성 종양으로 해석하라는 뜻은 아님.

## 적용 기준

- 기존 kind 값(disease, state, biomarker, procedure, drug, other)을 유지하는 체계로 검토. 새로운 분류 값은 만들지 않음.
- 건강인·해부학적 부위·측정 대상·치료 목적·광범위 치료 방식·병원체는 이 체계에서 other로 처리. 실제 검토에서 kind 변경은 EBV 한 행만 해당.
- 약어는 ko에 중복해 넣지 않고 abbr에서 관리. 유전자·표지자 명칭(HER2, KRAS 등)은 이름에 필요한 요소이므로 ko에 유지.
- 약어는 전체 구문의 완전한 두문자어가 아니라 그 안의 핵심 개념 약어일 수도 있음(예: ILM은 내경계막, EEG는 뇌파). '전체 구문 = 약어'라는 등치가 필요한 화면이라면 병기 위치를 별도로 조정해야 함.
- 원문에 명시된 약어는 보존하는 방향으로 검토하되 모든 질환에 새 약어를 일괄 생성하지 않음. T2D와 T2DM 등 원문의 서로 다른 약어도 임의 통일하지 않음.
- 절차·약물·건강인 등은 질병 문장 템플릿에 무조건 넣지 않음. 이는 해당 시험이나 행을 삭제하라는 의미가 아님.

## note가 있는 30행의 판단

### 데이터 4행 — Diabete Type 2

유지. '제2형 당뇨병'으로 해석할 수 있는 철자 오류이며, 검색 키인 en의 Diabete는 수정하지 않음.

### 데이터 22행 — Urinary Bladder Neoplasms

'방광 종양' 유지. MeSH 표제어의 neoplasms는 양성·악성을 포괄하므로 '방광암'으로 일괄 치환하지 않음. SYN-0019에서 악성 방광암만 모집하는지는 이 CSV만으로 확인할 수 없음. 시험별 환자 안내에는 원 시험의 진단·선정 기준을 확인한 뒤 '방광암'을 쓸 수 있으나 전역 용어집은 넓은 뜻을 보존.

### 데이터 33행 — high-grade invasive urothelial carcinoma invading muscularis propria

'근육층까지 침범한 고등급 침윤성 요로상피암' 유지. muscularis propria는 고유근층이며 여기서는 환자용으로 '근육층'이라고 풀어 쓴 표현을 허용. 고등급·침윤성·근육층 침범을 모두 보존. 원문에 없는 '방광'은 추가하지 않음.

### 데이터 37행 — Migraine With Aura

'전조가 있는 편두통' 유지. 환자에게 보여 주는 ko에는 이해하기 쉬운 표현을 우선하고, 공식 용어 '조짐편두통'은 원 note에 보존. 두 용어를 다른 질환으로 취급하지 않음.

### 데이터 40행 — rhegmatogenous retinal detachment superior bullous involving macula OD

수정. superior bullous의 정보가 빠져 있어 '위쪽 망막이 물집처럼 부푼'으로 복원. OD는 오른쪽 눈, involving macula는 황반 침범으로 보존. 침범을 macula-off로 임의 확정하지 않음.

### 데이터 51행 — Advance Solid Tumors

ko를 '진행성 고형 종양'으로 변경. Advance는 Advanced의 오기로 보이지만 en은 그대로 보존. 암임이 명시되지 않은 solid tumor의 범위를 보존.

### 데이터 60행 — Alzheimer&#39; Disease

ko 유지, en 유지. &#39;는 HTML 문자 참조로 아포스트로피에 해당하며, 원문 표현의 오류·서식 문제가 한국어 진단명에 영향을 주지 않음.

### 데이터 62행 — Alzheimers Disease

유지. 아포스트로피 누락은 검색 키에서 보존하고 ko는 '알츠하이머병'으로 유지.

### 데이터 72행 — Breast Neoplasms

'유방 종양' 유지. 유방암으로 한정하지 않음. 암 진단이 확인된 개별 시험의 환자 문구는 별도 맥락에서 처리.

### 데이터 76행 — Chronic Kidney Diseases

'만성 콩팥병', CKD 유지. 환자용으로 콩팥을 사용하며 '만성 신장병'과 혼용하지 않도록 동일 개념의 표기를 통일.

### 데이터 85행 — Colorectal Neoplasms

'대장 종양' 유지. colorectal neoplasms는 대장암보다 넓으며, 양성 병변을 일괄 배제하지 않음.

### 데이터 91행 — Diabete Mellitus

유지. '당뇨병'으로 해석하고 en의 Diabete는 수정하지 않음.

### 데이터 103행 — EEG Brain Oscillations

ko를 '뇌파 진동'으로 정리하고 EEG는 abbr로 이동. kind=other 유지. 질병이 아닌 측정 대상이므로 질병 대상 문장에 자동 삽입하지 않음.

### 데이터 106행 — Episodic Migraine

'삽화성 편두통' 유지. '가끔 생기는 편두통'은 빈도를 지나치게 느슨하게 표현할 수 있어 대체하지 않음. 만성 편두통과 대비되는 분류이며, 구체적인 빈도 기준은 해당 시험에서 확인.

### 데이터 114행 — Graves Ophthalmopathy

'그레이브스 눈병증' 유지. 환자용으로 눈병증을 사용하고 같은 계열의 Graves Orbitopathy에도 동일 표기 유지. 전문 표현 '그레이브스안병증'은 원 note에 보존.

### 데이터 119행 — Healthy

'건강한 사람', kind=other 유지. 질병명으로 취급하지 않되, 건강인 시험 자체를 제외하라는 뜻은 아님. 건강인 연구에는 별도 대상 문장 사용.

### 데이터 127행 — Hemifacial Microsomia

'반얼굴 왜소증' 유지. 환자에게 더 이해하기 쉬운 표현을 사용하며 '반안면 왜소증'은 동일 개념의 대체 표현으로 취급.

### 데이터 128행 — Hepatecellular Carcinoma

'간세포암' 유지. Hepatecellular는 Hepatocellular의 오기로 해석하되 en은 보존.

### 데이터 135행 — Hypertensive Nephropathy

'고혈압성 콩팥병' 유지. 환자용 ko에서 콩팥 표현을 일관되게 사용하고 전문 표현 '고혈압성 신장병증'은 원 note에 보존.

### 데이터 139행 — ILM Peeling

'내경계막 박리술', kind=procedure 유지. 원문 약어 ILM은 abbr에 추가하며, ILM은 내경계막을 뜻하는 구성요소 약어임. 질병 대상으로 사용하지 않음.

### 데이터 141행 — Immunotherapy

'면역치료', kind=other 유지. 기존 분류 체계에 treatment가 없고 procedure를 개별 검사·시술에 쓰고 있어 광범위 치료 방식은 other에 둠. 원문만으로 구체적인 약물·시술을 확정하지 않음.

### 데이터 161행 — Migraine Prophylaxis

'편두통 예방', kind=other 유지. 질병 자체가 아니라 치료 목적. 대상 문장에 쓰려면 편두통의 진단·유형 및 모집 기준을 별도로 확인.

### 데이터 163행 — Minimal Change Disease

'미세변화병' 유지. Minimal Change Disease와 신증후군은 항상 동일한 개념이 아니므로 '미세변화 신증후군'으로 일괄 대체하지 않음.

### 데이터 177행 — Non-small Cell Carcinoma

'비소세포암' 유지. 원문에 Lung이 없으므로 '폐'나 NSCLC를 추가하지 않음. 폐 원발 여부는 해당 시험에서 별도 확인.

### 데이터 193행 — pMN

'원발성 막성 신병증', pMN, disease 유지. pMN은 신장학 문맥에서 통상 primary membranous nephropathy를 뜻하므로 현재 해석은 타당함. 다만 약어 단독만 주어졌으므로 해당 시험에서의 풀네임·선정 기준까지 확정한 것은 아님.

### 데이터 198행 — Pulmonary Mucormycosis

'폐 털곰팡이증' 유지. 환자용 한국어 명칭을 사용하며 '폐 뮤코르진균증'은 대체 표현으로 취급. 피부사상균 감염 등 다른 곰팡이 질환으로 바꾸지 않음.

### 데이터 207행 — Ripertamab

'리퍼타맙', kind=drug 유지(공식 표기 확인 보류). 이 검토에서는 식약처 자료·국내 시험 문서의 공식 한글 표기를 대조하지 못함. Ripertamab의 현재 한글 표기를 승인된 국내 일반명이라고 보증하지 않으며 공개 전 확인 필요. 유사한 이름의 다른 단클론항체로 임의 교체하지 않음.

### 데이터 217행 — T1D Heart Failure

'제1형 당뇨병과 심부전' 유지. T1D는 통상 제1형 당뇨병이나, 두 질환의 동시 모집·동반 여부나 인과관계는 원문만으로 확정되지 않음. '당뇨병으로 인한 심부전' 또는 '제1형 당뇨병 환자의 심부전'으로 단정하지 않고 원 시험 확인을 요청.

### 데이터 219행 — Telitacicept

'텔리타시셉트', kind=drug 유지(공식 표기 확인 보류). Telitacicept의 현재 표기를 국내 공식 한글명으로 검증하지 못했으므로 공개 전 식약처 자료·시험 의뢰자 문서와 대조 필요. 질병 대상 문장에 약물명을 넣지 않음.

### 데이터 225행 — Tirzepatide

'터제파타이드', kind=drug 유지. 성분명과 상품명을 혼동하지 않고 약물을 질병으로 분류하지 않음. 이번 작업에서 최신 국내 허가 문서를 직접 대조한 것은 아님.

## 추가로 문맥 확인이 필요한 항목

- **데이터 73행 Cardio-renal Vascular Function and Failure**: 질병 하나를 가리키는 명확한 표준 명칭이 아니며 cardio-renal과 vascular의 수식 범위도 모호함. 기존 ko·other를 유지했으나 실제 환자 문장에 자동 삽입하기 전 원 시험 목적·평가변수 확인 필요.
- **데이터 176행 Non-diabetic Chronic Kidney Disease**: 비당뇨병성 원인과 당뇨병 미동반은 동일하지 않음. 이번 ko는 원문 표현의 범위를 보존하기 위한 것으로, 당뇨병 환자 참여 가능 여부는 선정·제외 기준에서 확인해야 함.
- **데이터 193·217행**: 각각 pMN의 시험별 풀네임, T1D Heart Failure의 두 개념 간 관계 확인 필요.
- **데이터 207·219행**: 약물의 공식 국내 한글 표기 확인이 필요하며, 현 표기는 잠정 유지.

## 변경 상세

동봉 changes.csv에는 ko·abbr·kind의 셀별 이전값·이후값·사유가 수록되어 있음. 아래는 행별 요약이며, status만 변경한 나머지 행은 이 목록에서 제외.

| 데이터 행 | en | 변경 필드 | 사유 |
|---:|---|---|---|
| 40 | rhegmatogenous retinal detachment superior bullous involving macula OD | ko | 원문에서 빠진 superior bullous(상부 수포성)를 환자용 설명으로 복원하고 OD(오른쪽 눈)·황반 침범도 보존. |
| 49 | Acute Pancreatitis (AP) | abbr | 원문에 명시된 AP를 약어 열에 분리. |
| 51 | Advance Solid Tumors | ko | solid tumor만으로 악성임을 확정하지 않도록 '고형암'을 '고형 종양'으로 변경. 진행성·전이성·유전자 변이·절제 불가 등 원문 수식어는 유지. |
| 54 | Advanced Solid Tumor | ko | solid tumor만으로 악성임을 확정하지 않도록 '고형암'을 '고형 종양'으로 변경. 진행성·전이성·유전자 변이·절제 불가 등 원문 수식어는 유지. |
| 55 | Advanced Solid Tumors | ko | solid tumor만으로 악성임을 확정하지 않도록 '고형암'을 '고형 종양'으로 변경. 진행성·전이성·유전자 변이·절제 불가 등 원문 수식어는 유지. |
| 56 | Advanced Solid Tumors With KRAS G12C Mutations | ko | solid tumor만으로 악성임을 확정하지 않도록 '고형암'을 '고형 종양'으로 변경. 진행성·전이성·유전자 변이·절제 불가 등 원문 수식어는 유지. |
| 67 | Biliary Pancreatitis | ko | biliary는 담도 관련 원인을 뜻하며 담석으로만 한정되지 않으므로 원인 범위를 보존. |
| 68 | Bladder (Urothelial, Transitional Cell) Cancer | ko | 원문에 병기된 transitional cell(이행세포)도 보존. |
| 74 | Cardiovascular Risk | ko | 환자에게 위험의 대상을 더 명확히 표현. |
| 102 | EBV | ko, kind | EBV 단독은 바이러스명이며 감염 진단이 아님. 원문에 없는 감염을 제거하고 병원체는 기존 kind 중 other로 분류. |
| 103 | EEG Brain Oscillations | ko, abbr | 약어를 ko에 중복 포함하지 않고 abbr로 분리. |
| 139 | ILM Peeling | abbr | 원문에 명시된 ILM을 약어 열에 보존. |
| 145 | KRAS Altered Advanced or Metastatic Solid Tumors | ko | solid tumor만으로 악성임을 확정하지 않도록 '고형암'을 '고형 종양'으로 변경. 진행성·전이성·유전자 변이·절제 불가 등 원문 수식어는 유지. |
| 150 | Localized Muscle Invasive Bladder Urothelial Carcinoma | ko | localized와 locally advanced를 구별하도록 '국소'를 '국한성'으로 구체화. |
| 152 | Locally Advanced Solid Tumor | ko | solid tumor만으로 악성임을 확정하지 않도록 '고형암'을 '고형 종양'으로 변경. 진행성·전이성·유전자 변이·절제 불가 등 원문 수식어는 유지. |
| 158 | Metastatic Solid Tumor | ko | solid tumor만으로 악성임을 확정하지 않도록 '고형암'을 '고형 종양'으로 변경. 진행성·전이성·유전자 변이·절제 불가 등 원문 수식어는 유지. |
| 159 | Metastatic Solid Tumors | ko | solid tumor만으로 악성임을 확정하지 않도록 '고형암'을 '고형 종양'으로 변경. 진행성·전이성·유전자 변이·절제 불가 등 원문 수식어는 유지. |
| 176 | Non-diabetic Chronic Kidney Disease | ko | non-diabetic CKD는 비당뇨병성 원인을 뜻할 수 있어 '당뇨병이 없는'으로 단정하지 않음. 실제 당뇨병 동반 허용 여부는 선정·제외 기준에서 확인. |
| 210 | Solid Tumor | ko | solid tumor만으로 악성임을 확정하지 않도록 '고형암'을 '고형 종양'으로 변경. 진행성·전이성·유전자 변이·절제 불가 등 원문 수식어는 유지. |
| 211 | Solid Tumor, Adult | ko | solid tumor만으로 악성임을 확정하지 않도록 '고형암'을 '고형 종양'으로 변경. 진행성·전이성·유전자 변이·절제 불가 등 원문 수식어는 유지. |
| 233 | Unresectable Solid Tumor | ko | solid tumor만으로 악성임을 확정하지 않도록 '고형암'을 '고형 종양'으로 변경. 진행성·전이성·유전자 변이·절제 불가 등 원문 수식어는 유지. |
