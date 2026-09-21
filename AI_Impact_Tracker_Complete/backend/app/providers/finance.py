import re
from difflib import SequenceMatcher
import httpx
from app.config import settings


def _norm(value: str) -> str:
    value = (value or '').lower()
    value = re.sub(r'\b(limited|ltd|plc|incorporated|inc|corp|corporation|company|co|holdings?)\b', ' ', value)
    value = re.sub(r'[^a-z0-9]+', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()


def _similarity(a: str, b: str) -> float:
    a2, b2 = _norm(a), _norm(b)
    if not a2 or not b2:
        return 0.0
    if a2 == b2:
        return 1.0
    return SequenceMatcher(None, a2, b2).ratio()


class CompaniesHouseProvider:
    BASE = 'https://api.company-information.service.gov.uk'

    async def search_candidates(self, name: str, limit: int = 8):
        if not settings.companies_house_api_key or not name:
            return []
        async with httpx.AsyncClient(timeout=25, auth=(settings.companies_house_api_key, '')) as client:
            r = await client.get(f'{self.BASE}/search/companies', params={'q': name, 'items_per_page': limit})
            if r.status_code != 200:
                return []
            rows = r.json().get('items', [])[:limit]
            out = []
            for row in rows:
                number = row.get('company_number')
                profile = {}
                if number:
                    p = await client.get(f'{self.BASE}/company/{number}')
                    if p.status_code == 200:
                        profile = p.json()
                out.append({
                    'company_name': row.get('title'),
                    'company_number': number,
                    'address': row.get('address_snippet'),
                    'company_status': profile.get('company_status') or row.get('company_status'),
                    'company_type': profile.get('type'),
                    'sic_codes': profile.get('sic_codes', []),
                    'date_of_creation': profile.get('date_of_creation'),
                    'similarity': round(_similarity(name, row.get('title', '')), 4),
                    'source_url': f'https://find-and-update.company-information.service.gov.uk/company/{number}' if number else None,
                })
            return out

    async def search_company(self, name: str):
        rows = await self.search_candidates(name, 8)
        if not rows:
            return None
        # Sort candidates: active companies first, then by similarity
        def _rank_key(row):
            sim = row.get('similarity', 0)
            is_active = 1 if str(row.get('company_status', '')).lower() == 'active' else 0
            # Prefer exact normalized brand match
            norm_name = _norm(name)
            norm_row = _norm(row.get('company_name', ''))
            exact = 1 if norm_name == norm_row else 0
            return (exact, is_active, sim)

        rows.sort(key=_rank_key, reverse=True)
        best = rows[0]
        best_sim = best.get('similarity', 0)

        # Only consider candidates with sufficient similarity
        if best_sim < 0.70:
            return {'status': 'ambiguous', 'candidates': rows[:5]}

        norm_input = _norm(name)
        # Check if other candidates are genuinely different unrelated entities
        unrelated_tied = []
        for x in rows[1:]:
            sim_diff = abs(x.get('similarity', 0) - best_sim)
            if sim_diff < 0.05:
                norm_x = _norm(x.get('company_name', ''))
                # If candidate shares core brand tokens with best, it is part of the same group/brand
                if norm_input and (norm_input in norm_x or norm_x in norm_input):
                    continue
                unrelated_tied.append(x)

        if unrelated_tied and best_sim < 0.92:
            return {'status': 'ambiguous', 'candidates': rows[:5]}

        # Compute transparent match confidence
        confidence = best_sim
        if str(best.get('company_status', '')).lower() == 'active':
            confidence = min(1.0, confidence + 0.05)
        if _norm(best.get('company_name', '')) == norm_input:
            confidence = min(1.0, confidence + 0.05)
        best['match_confidence'] = round(confidence, 2)

        return {'status': 'matched', **best, 'candidates': rows[:5]}


class SECProvider:
    TICKER_URL = 'https://www.sec.gov/files/company_tickers.json'

    @staticmethod
    def _metric(usgaap: dict, tags: list[str]):
        candidates = []
        for tag in tags:
            units = usgaap.get(tag, {}).get('units', {})
            for unit_name, facts in units.items():
                if unit_name not in ('USD', 'USD/shares'):
                    continue
                for x in facts:
                    if x.get('form') not in ('10-K', '20-F', '40-F'):
                        continue
                    if x.get('fp') not in (None, 'FY'):
                        continue
                    fy = x.get('fy')
                    end = x.get('end', '')
                    if not fy or not end:
                        continue
                    try:
                        end_year = int(end[:4])
                    except Exception:
                        continue
                    # Comparative prior-year facts appear in later 10-Ks. Prefer the fact
                    # whose period end year actually matches the fiscal year.
                    year_distance = abs(end_year - int(fy))
                    candidates.append((year_distance, int(fy), x.get('filed', ''), tag, unit_name, x))
        if not candidates:
            return None
        candidates.sort(key=lambda z: (-z[1], z[0], z[2]), reverse=False)
        latest_fy = max(z[1] for z in candidates)
        same_fy = [z for z in candidates if z[1] == latest_fy]
        same_fy.sort(key=lambda z: (z[0], z[2]), reverse=False)
        chosen = same_fy[0]
        x = chosen[-1]
        return {
            'tag': chosen[3],
            'unit': chosen[4],
            'value': x.get('val'),
            'start': x.get('start'),
            'end': x.get('end'),
            'fy': x.get('fy'),
            'form': x.get('form'),
            'filed': x.get('filed'),
            'accession': x.get('accn'),
        }

    async def company_facts(self, company_name: str):
        if not company_name:
            return None
        headers = {'User-Agent': settings.sec_user_agent, 'Accept-Encoding': 'gzip, deflate'}
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            tick = await client.get(self.TICKER_URL)
            if tick.status_code != 200:
                return None
            entries = list(tick.json().values())
            norm_requested = _norm(company_name)
            upper_req = company_name.upper().strip()
            def _sec_score(e):
                ticker = str(e.get('ticker', '')).upper()
                if ticker and ticker == upper_req:
                    return 1.0
                title = str(e.get('title', ''))
                if _norm(title) == norm_requested:
                    return 1.0
                return _similarity(company_name, title)

            scored = sorted(
                [(_sec_score(e), e) for e in entries],
                key=lambda z: z[0], reverse=True
            )
            if not scored or scored[0][0] < 0.78:
                return {'status': 'ambiguous', 'candidates': [
                    {'company_name': e.get('title'), 'ticker': e.get('ticker'), 'similarity': round(score, 4)}
                    for score, e in scored[:5]
                ]}
            top_score, m = scored[0]
            # Only declare ambiguous if there's a competing unrelated company with nearly identical score
            if len(scored) > 1 and top_score - scored[1][0] < 0.02 and top_score < 0.95:
                cand_norm = _norm(scored[1][1].get('title', ''))
                if not (norm_requested and (norm_requested in cand_norm or cand_norm in norm_requested)):
                    return {'status': 'ambiguous', 'candidates': [
                        {'company_name': e.get('title'), 'ticker': e.get('ticker'), 'similarity': round(score, 4)}
                        for score, e in scored[:5]
                    ]}

            cik = str(m['cik_str']).zfill(10)
            r = await client.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json')
            if r.status_code != 200:
                return None
            data = r.json()
            usgaap = data.get('facts', {}).get('us-gaap', {})

            metrics = {
                'Revenue': self._metric(usgaap, [
                    'RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues',
                    'SalesRevenueNet', 'SalesRevenueGoodsNet'
                ]),
                'Operating income': self._metric(usgaap, ['OperatingIncomeLoss']),
                'Net income': self._metric(usgaap, [
                    'NetIncomeLoss', 'ProfitLoss', 'NetIncomeLossAvailableToCommonStockholdersBasic'
                ]),
                'Total assets': self._metric(usgaap, ['Assets']),
                'Total liabilities': self._metric(usgaap, ['Liabilities']),
                'Cash and cash equivalents': self._metric(usgaap, [
                    'CashAndCashEquivalentsAtCarryingValue',
                    'CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents'
                ]),
                'Operating cash flow': self._metric(usgaap, [
                    'NetCashProvidedByUsedInOperatingActivities'
                ]),
            }
            return {
                'status': 'matched',
                'company_name': data.get('entityName'),
                'ticker': m.get('ticker'),
                'cik': cik,
                'similarity': round(top_score, 4),
                'metrics': metrics,
                'source_url': f'https://www.sec.gov/edgar/browse/?CIK={cik}',
            }
