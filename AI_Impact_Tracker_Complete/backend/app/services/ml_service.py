import pandas as pd  # type: ignore[import-not-found] # pyright: ignore[reportMissingImports]
from sklearn.compose import ColumnTransformer  # type: ignore[import-not-found] # pyright: ignore[reportMissingImports]
from sklearn.pipeline import Pipeline  # type: ignore[import-not-found] # pyright: ignore[reportMissingImports]
from sklearn.preprocessing import OneHotEncoder  # type: ignore[import-not-found] # pyright: ignore[reportMissingImports]
from sklearn.ensemble import RandomForestRegressor  # type: ignore[import-not-found] # pyright: ignore[reportMissingImports]
from sklearn.impute import SimpleImputer  # type: ignore[import-not-found] # pyright: ignore[reportMissingImports]

MIN_OBSERVATIONS = 20
FEATURES = ['sector','business_goal','company_size','employees','budget','annual_software_cost','implementation_cost','evidence_score','sentiment_score','impact_score','implementation_score']
TARGETS = ['actual_impact_percent','actual_roi_percent','actual_payback_months']

def train_if_ready(rows: list[dict]):
    if len(rows) < MIN_OBSERVATIONS:
        return {'ready': False, 'observations': len(rows), 'minimum': MIN_OBSERVATIONS}
    df = pd.DataFrame(rows)
    cat = ['sector','business_goal','company_size']; num = [x for x in FEATURES if x not in cat]
    prep = ColumnTransformer([
        ('cat', Pipeline([('imp',SimpleImputer(strategy='most_frequent')),('ohe',OneHotEncoder(handle_unknown='ignore'))]), cat),
        ('num', Pipeline([('imp',SimpleImputer(strategy='median'))]), num),
    ])
    models = {}
    for target in TARGETS:
        usable = df[df[target].notna()]
        if len(usable) < MIN_OBSERVATIONS: continue
        pipe = Pipeline([('prep',prep),('model',RandomForestRegressor(n_estimators=300, random_state=42, min_samples_leaf=2))])
        pipe.fit(usable[FEATURES], usable[target]); models[target] = pipe
    return {'ready': bool(models), 'observations': len(rows), 'models': models}
