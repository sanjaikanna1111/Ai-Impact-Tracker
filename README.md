AI Impact Tracker
AI Impact Tracker is an evidence-first AI strategy intelligence and post-implementation impact measurement application.

It helps an organisation answer two questions:

Before adoption: Which AI/software solution is best supported by evidence for this business problem?
After adoption: Did the implementation actually deliver measurable operational and financial value?
What this build includes
Next.js 16 frontend with separate workspace views for Overview, Recommendations, Evidence, Sentiment, Financials, Value and Impact.
FastAPI backend with SQLite persistence.
Gemini for business-problem interpretation and structured evidence extraction.
Serper for live web discovery with rate limiting, retry/backoff and deduplication.
Jina Reader for page extraction.
Product discovery and validation before final ranking.
Deep research for the top five validated products.
Up to ~30 retained evidence records per shortlisted product when genuine public evidence exists.
Up to ~25 review/reputation sources per shortlisted product when genuine public review evidence exists.
Evidence coverage reporting so missing evidence is visible rather than fabricated.
Customer-impact extraction with traceable source links.
Pricing and implementation-cost research.
Deterministic Python recommendation scoring.
Company identity validation before financial data is attached.
UK company matching through Companies House when configured.
US public-company financial extraction through SEC EDGAR/XBRL.
Financial context displayed as a table rather than raw JSON.
ROI and payback only when baseline process cost and credible investment data exist.
Separate post-implementation KPI / realised-benefit measurement.
Optional Random Forest layer after sufficient real measurements are collected.
Research flow
Business input
    ↓
Gemini problem interpretation
    ↓
Serper broad product discovery
    ↓
Vendor-domain resolution + validation
    ↓
Preliminary deterministic scoring
    ↓
Top-five deep research
    ├─ product/vendor evidence
    ├─ independent evidence
    ├─ review/reputation evidence
    ├─ customer case studies
    ├─ quantified impact
    └─ pricing / implementation
    ↓
Jina extraction
    ↓
Gemini structured extraction
    ↓
Python evidence scoring + final ranking
    ↓
Company financial context
    ↓
Value / ROI scenario when inputs support it
    ↓
Post-implementation actual impact tracking
Evidence policy
The evidence targets are research-depth targets, not fabrication quotas. If only 11 legitimate review sources exist, the app reports 11/25 rather than inventing another 14. Search hits, readable pages, retained evidence and validated claims are kept conceptually separate.

Backend setup — Windows PowerShell
From the project root:

cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
Edit backend/.env and add your keys:

GEMINI_API_KEY=your_key
GEMINI_MODEL=gemini-3.5-flash
SERPER_API_KEY=your_key
JINA_API_KEY=your_key
COMPANIES_HOUSE_API_KEY=your_key_if_used
SEC_USER_AGENT=AIImpactTracker your-email@example.com
Start the API:

python -m uvicorn app.main:app --reload --port 8000
Health endpoint:

http://localhost:8000/api/health
FastAPI docs:

http://localhost:8000/docs
Frontend setup — Windows PowerShell
Open a second terminal:

cd frontend
npm.cmd install
Copy-Item .env.local.example .env.local
npm.cmd run dev
Open:

http://localhost:3000/research
If PowerShell says next is not recognized, npm.cmd install did not complete successfully. Do not install Next globally; fix the local dependency installation first.

Optional ML dependencies
The core app does not require scikit-learn. When you have enough genuine post-implementation observations and want to enable the ML layer:

python -m pip install -r requirements-ml.txt
Tests
cd backend
pytest -q
Important methodological rules
A search result is not automatically an evidence claim.
Vendor claims are labelled as vendor evidence.
Missing pricing remains missing.
Missing public reviews remain missing.
A company-name match must be sufficiently confident before financials are attached.
Company revenue is context, not the financial benefit of AI.
Estimated ROI and realised ROI are separate.
Post-implementation actual KPI impact is only calculated after real measurements are entered.
Project structure
AI_Impact_Tracker_Complete/
├─ backend/
│  ├─ app/
│  │  ├─ api/
│  │  ├─ providers/
│  │  ├─ services/
│  │  ├─ config.py
│  │  ├─ db.py
│  │  ├─ main.py
│  │  ├─ models.py
│  │  └─ schemas.py
│  ├─ tests/
│  ├─ requirements.txt
│  ├─ requirements-ml.txt
│  └─ .env.example
├─ frontend/
│  ├─ app/
│  ├─ lib/
│  ├─ package.json
│  └─ .env.local.example
├─ docker-compose.yml
└─ README.md
