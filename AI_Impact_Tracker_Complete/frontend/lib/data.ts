export function rootResult(data: any): any {
  return data?.result || data || {};
}

/* =========================================================
   GENERIC HELPERS
========================================================= */

function numberOrNull(
  value: unknown
): number | null {
  if (
    value === null ||
    value === undefined ||
    value === ""
  ) {
    return null;
  }

  const n = Number(value);

  return Number.isFinite(n)
    ? n
    : null;
}

function stringValue(
  value: unknown
): string {
  if (
    value === null ||
    value === undefined
  ) {
    return "";
  }

  return String(value).trim();
}

function normaliseText(
  value: unknown
): string {
  return stringValue(value)
    .toLowerCase()
    .replace(/\s+/g, " ");
}

function sourceUrlOf(
  row: any
): string {
  return (
    row?.source_url ||
    row?.url ||
    row?.evidence_url ||
    ""
  );
}

function productOf(
  row: any,
  fallback?: any
): string {
  return (
    row?.product ||
    row?.tool ||
    row?.tool_name ||
    fallback?.product ||
    fallback?.tool ||
    fallback?.tool_name ||
    ""
  );
}

function vendorOf(
  row: any,
  fallback?: any
): string {
  return (
    row?.vendor ||
    row?.company_vendor ||
    fallback?.vendor ||
    fallback?.company_vendor ||
    ""
  );
}

function customerOf(
  row: any
): string {
  return (
    row?.customer ||
    row?.customer_company ||
    row?.company ||
    row?.organisation ||
    row?.organization ||
    ""
  );
}

/* =========================================================
   RECOMMENDATIONS
========================================================= */

export function recommendations(
  data: any
): any[] {
  const result =
    rootResult(data);

  if (
    Array.isArray(
      result?.recommendations
    )
  ) {
    return result.recommendations;
  }

  if (
    Array.isArray(
      result?.validated_products
    )
  ) {
    return result.validated_products;
  }

  if (
    Array.isArray(
      result?.candidates
    )
  ) {
    return result.candidates;
  }

  return [];
}

export function bestRecommendation(
  data: any
): any | null {
  const result =
    rootResult(data);

  return (
    result?.recommendations?.[0] ||
    result?.validated_products?.[0] ||
    result?.candidates?.[0] ||
    result?.recommendation ||
    result?.best_recommendation ||
    result?.best ||
    null
  );
}

/* =========================================================
   DATA QUALITY
========================================================= */

export function dataQuality(
  data: any
): any {
  const result =
    rootResult(data);

  return (
    result?.data_quality ||
    {}
  );
}

export function researchComplete(
  data: any
): boolean {
  const quality =
    dataQuality(data);

  return (
    quality?.research_complete ===
    true
  );
}

/* =========================================================
   EVIDENCE
========================================================= */

export function allEvidence(
  data: any
): any[] {
  const result =
    rootResult(data);

  const direct =
    Array.isArray(
      result?.evidence
    )
      ? result.evidence
      : [];

  const nested =
    recommendations(result).flatMap(
      (recommendation: any) => {
        const rows =
          Array.isArray(
            recommendation?.evidence
          )
            ? recommendation.evidence
            : Array.isArray(
                  recommendation
                    ?.retained_source_evidence
                )
              ? recommendation
                  .retained_source_evidence
              : [];

        return rows.map(
          (evidence: any) => ({
            ...evidence,

            product:
              productOf(
                evidence,
                recommendation
              ),

            vendor:
              vendorOf(
                evidence,
                recommendation
              ),
          })
        );
      }
    );

  const combined = [
    ...direct,
    ...nested,
  ];

  const seen =
    new Set<string>();

  return combined.filter(
    (row: any) => {
      const key = [
        productOf(row),
        sourceUrlOf(row),
        row?.claim ||
          row?.supporting_text ||
          row?.title ||
          "",
      ]
        .map(normaliseText)
        .join("|");

      if (
        seen.has(key)
      ) {
        return false;
      }

      seen.add(key);

      return true;
    }
  );
}

/* =========================================================
   REVIEWS / SENTIMENT
========================================================= */

export function reviewRows(
  data: any
): any[] {
  const result =
    rootResult(data);

  const direct =
    result?.sentiment?.items ||
    result?.sentiment?.reviews ||
    result?.sentiment?.evidence ||
    result?.sentiment?.results ||
    result?.reviews ||
    null;

  const directRows =
    Array.isArray(direct)
      ? direct
      : [];

  const nested =
    recommendations(result).flatMap(
      (recommendation: any) => {
        const rows =
          recommendation
            ?.sentiment?.items ||
          recommendation
            ?.sentiment?.reviews ||
          recommendation
            ?.sentiment?.evidence ||
          recommendation
            ?.review_evidence ||
          recommendation?.reviews ||
          [];

        if (
          !Array.isArray(rows)
        ) {
          return [];
        }

        return rows.map(
          (row: any) => ({
            ...row,

            product:
              productOf(
                row,
                recommendation
              ),

            vendor:
              vendorOf(
                row,
                recommendation
              ),
          })
        );
      }
    );

  const combined = [
    ...directRows,
    ...nested,
  ];

  const seen =
    new Set<string>();

  return combined.filter(
    (row: any) => {
      const key = [
        productOf(row),
        sourceUrlOf(row),
        row?.review_text ||
          row?.text ||
          row?.claim ||
          row?.snippet ||
          row?.title ||
          "",
      ]
        .map(normaliseText)
        .join("|");

      if (
        seen.has(key)
      ) {
        return false;
      }

      seen.add(key);

      return true;
    }
  );
}

export function classifiedReviewRows(
  data: any
): any[] {
  return reviewRows(data).filter(
    (row: any) => {
      const label =
        String(
          row?.sentiment ||
            row?.label ||
            ""
        )
          .trim()
          .toLowerCase();

      return [
        "positive",
        "neutral",
        "negative",
      ].includes(label);
    }
  );
}

/* =========================================================
   CUSTOMER / ADOPTION / IMPACT
========================================================= */

export function customerRows(
  data: any
): any[] {
  const result =
    rootResult(data);

  const rows: any[] = [];

  /*
   * Top-level qualitative customer/adoption
   * evidence.
   */
  if (
    Array.isArray(
      result?.customers
    )
  ) {
    for (
      const row of
      result.customers
    ) {
      rows.push({
        ...row,

        product:
          productOf(row),

        record_type:
          row?.record_type ||
          "customer_reference",
      });
    }
  }

  /*
   * Top-level quantified customer impact.
   */
  if (
    Array.isArray(
      result?.customer_impact
    )
  ) {
    for (
      const row of
      result.customer_impact
    ) {
      rows.push({
        ...row,

        product:
          productOf(row),

        record_type:
          row?.record_type ||
          "customer_impact",
      });
    }
  }

  /*
   * Recommendation-level records.
   */
  for (
    const recommendation of
    recommendations(result)
  ) {
    const qualitative =
      Array.isArray(
        recommendation?.customers
      )
        ? recommendation.customers
        : [];

    for (
      const row of
      qualitative
    ) {
      rows.push({
        ...row,

        product:
          productOf(
            row,
            recommendation
          ),

        vendor:
          vendorOf(
            row,
            recommendation
          ),

        record_type:
          row?.record_type ||
          "customer_reference",
      });
    }

    const impacts =
      Array.isArray(
        recommendation
          ?.customer_impact
      )
        ? recommendation
            .customer_impact
        : [];

    for (
      const row of
      impacts
    ) {
      rows.push({
        ...row,

        product:
          productOf(
            row,
            recommendation
          ),

        vendor:
          vendorOf(
            row,
            recommendation
          ),

        record_type:
          row?.record_type ||
          "customer_impact",
      });
    }

    /*
     * Optional explicit adoption /
     * technographic fields.
     */
    const adoptionSources = [
      recommendation
        ?.customer_adoption,
      recommendation
        ?.adoption_evidence,
      recommendation
        ?.technographic_evidence,
      recommendation
        ?.technology_adoption,
    ];

    for (
      const source of
      adoptionSources
    ) {
      if (
        !Array.isArray(source)
      ) {
        continue;
      }

      for (
        const row of source
      ) {
        rows.push({
          ...row,

          product:
            productOf(
              row,
              recommendation
            ),

          vendor:
            vendorOf(
              row,
              recommendation
            ),

          record_type:
            row?.record_type ||
            "adoption_evidence",
        });
      }
    }
  }

  /*
   * Normalise common field aliases so pages
   * can work even if Gemini/backend emits
   * slightly different names.
   */
  const normalised =
    rows.map((row: any) => {
      const sourceUrl =
        sourceUrlOf(row);

      const impactValue =
        numberOrNull(
          row?.impact_value ??
            row?.numeric_value ??
            row?.value
        );

      const customer =
        customerOf(row);

      const sourceHost =
        (() => {
          if (!sourceUrl) {
            return "";
          }

          try {
            return new URL(
              sourceUrl
            ).hostname.replace(
              /^www\./,
              ""
            );
          } catch {
            return "";
          }
        })();

      const isTheirStack =
        sourceHost
          .toLowerCase()
          .includes(
            "theirstack.com"
          ) ||
        String(
          row?.source ||
            row?.platform ||
            ""
        )
          .toLowerCase()
          .includes(
            "theirstack"
          );

      return {
        ...row,

        product:
          productOf(row),

        customer,

        customer_company:
          row?.customer_company ||
          customer,

        source_url:
          sourceUrl,

        impact_value:
          impactValue,

        impact_unit:
          row?.impact_unit ||
          row?.unit ||
          "",

        evidence_type:
          row?.evidence_type ||
          row?.record_type ||
          (isTheirStack
            ? "technographic_adoption"
            : impactValue !== null
              ? "customer_impact"
              : "customer_reference"),

        record_type:
          row?.record_type ||
          (isTheirStack
            ? "technographic_adoption"
            : impactValue !== null
              ? "customer_impact"
              : "customer_reference"),
      };
    });

  /*
   * Deduplicate without removing a qualitative
   * adoption record simply because a separate
   * quantified outcome exists.
   */
  const seen =
    new Set<string>();

  return normalised.filter(
    (row: any) => {
      const key = [
        productOf(row),
        customerOf(row),
        row?.record_type ||
          row?.evidence_type ||
          "",
        sourceUrlOf(row),
        row?.impact_value,
        row?.claim ||
          row?.application ||
          row?.outcome ||
          row?.description ||
          row?.adoption_evidence ||
          "",
      ]
        .map(normaliseText)
        .join("|");

      if (
        seen.has(key)
      ) {
        return false;
      }

      seen.add(key);

      return true;
    }
  );
}

/* =========================================================
   FINANCIALS
========================================================= */

export function financials(
  data: any
): any {
  const result =
    rootResult(data);

  const raw =
    result
      ?.company_financial_context ||
    result?.financial_context ||
    result?.company_financials ||
    {};

  if (
    !raw ||
    typeof raw !== "object"
  ) {
    return {};
  }

  /*
   * Already flat.
   * Preserve evidence arrays too.
   */
  if (
    raw?.revenue != null ||
    raw?.operating_income != null ||
    raw?.total_assets != null ||
    raw?.company_name != null
  ) {
    return {
      ...raw,

      evidence:
        Array.isArray(
          raw?.evidence
        )
          ? raw.evidence
          : Array.isArray(
                raw?.sources
              )
            ? raw.sources
            : [],
    };
  }

  const identity =
    raw?.identity || {};

  const metrics =
    Array.isArray(
      raw?.metrics
    )
      ? raw.metrics
      : [];

  const evidence =
    Array.isArray(
      raw?.evidence
    )
      ? raw.evidence
      : Array.isArray(
            raw?.sources
          )
        ? raw.sources
        : [];

  const aliases: Record<
    string,
    string[]
  > = {
    revenue: [
      "revenue",
      "sales",
      "turnover",
      "total revenue",
    ],

    operating_costs: [
      "operating_costs",
      "operating costs",
      "operating expenses",
      "operating expense",
    ],

    operating_income: [
      "operating_income",
      "operating income",
      "operating profit",
    ],

    adjusted_operating_profit: [
      "adjusted_operating_profit",
      "adjusted operating profit",
    ],

    profit_before_tax: [
      "profit_before_tax",
      "profit before tax",
      "pbt",
    ],

    net_income: [
      "net_income",
      "net income",
      "profit after tax",
      "profit for the year",
    ],

    total_assets: [
      "total_assets",
      "total assets",
    ],

    total_liabilities: [
      "total_liabilities",
      "total liabilities",
    ],

    cash: [
      "cash",
      "cash and cash equivalents",
      "cash equivalents",
    ],

    operating_cash_flow: [
      "operating_cash_flow",
      "operating cash flow",
      "cash from operations",
      "net cash from operating activities",
    ],

    employees: [
      "employees",
      "employee count",
      "number of employees",
      "headcount",
    ],
  };

  const out: any = {
    status:
      raw?.status,

    message:
      raw?.message,

    company_name:
      identity?.company_name ||
      identity?.name ||
      raw?.company_name,

    matched_company:
      identity?.company_name ||
      identity?.name ||
      raw?.matched_company,

    company_number:
      identity?.company_number ||
      raw?.company_number,

    ticker:
      identity?.ticker ||
      raw?.ticker,

    cik:
      identity?.cik ||
      raw?.cik,

    country:
      identity?.country ||
      raw?.country,

    industry:
      identity?.industry ||
      raw?.industry,

    website:
      identity?.website ||
      raw?.website,

    match_confidence:
      identity?.match_confidence ??
      raw?.match_confidence,

    source_url:
      identity?.source_url ||
      raw?.source_url,

    sector_alignment:
      raw?.sector_alignment,

    financial_scope:
      identity?.financial_scope ||
      raw?.financial_scope,

    trading_brand:
      identity?.trading_brand ||
      raw?.trading_brand,

    parent_company:
      identity?.parent_company ||
      raw?.parent_company,

    currency:
      identity?.currency ||
      raw?.currency,

    candidates:
      Array.isArray(raw?.candidates)
        ? raw.candidates
        : Array.isArray(identity?.candidates)
          ? identity.candidates
          : [],

    fmp:
      raw?.fmp,

    evidence,
  };

  for (
    const metric of metrics
  ) {
    const rawName =
      String(
        metric?.metric ||
          metric?.name ||
          metric?.label ||
          ""
      )
        .trim()
        .toLowerCase();

    if (!rawName) {
      continue;
    }

    let matchedKey:
      | string
      | null = null;

    for (
      const [
        key,
        names,
      ] of Object.entries(
        aliases
      )
    ) {
      const matched =
        names.some(
          (alias) =>
            rawName ===
              alias ||
            rawName.includes(
              alias
            )
        );

      if (matched) {
        matchedKey =
          key;
        break;
      }
    }

    if (!matchedKey) {
      continue;
    }

    if (
      out[matchedKey] ==
        null &&
      metric?.value != null
    ) {
      out[matchedKey] =
        metric.value;
    }

    /*
     * Preserve metric-specific period and
     * source so the Financials page can show
     * the correct source per row.
     */
    const metricPeriod =
      metric
        ?.reporting_period ||
      metric?.period ||
      metric?.fiscal_year ||
      "";

    const metricSourceUrl =
      metric?.source_url ||
      metric?.url ||
      "";

    const metricSource =
      metric?.source ||
      metric?.source_title ||
      metric?.title ||
      "";

    if (
      metricPeriod &&
      !out[
        `${matchedKey}_reporting_period`
      ]
    ) {
      out[
        `${matchedKey}_reporting_period`
      ] = metricPeriod;
    }

    if (
      metricSourceUrl &&
      !out[
        `${matchedKey}_source_url`
      ]
    ) {
      out[
        `${matchedKey}_source_url`
      ] = metricSourceUrl;
    }

    if (
      metricSource &&
      !out[
        `${matchedKey}_source`
      ]
    ) {
      out[
        `${matchedKey}_source`
      ] = metricSource;
    }

    if (
      !out.currency &&
      metric?.currency
    ) {
      out.currency =
        metric.currency;
    }

    if (
      !out.reporting_period &&
      metricPeriod
    ) {
      out.reporting_period =
        metricPeriod;
    }

    if (
      !out.fiscal_year &&
      metric?.fiscal_year
    ) {
      out.fiscal_year =
        metric.fiscal_year;
    }

    if (
      !out.source &&
      metricSource
    ) {
      out.source =
        metricSource;
    }

    if (
      !out.source_url &&
      metricSourceUrl
    ) {
      out.source_url =
        metricSourceUrl;
    }
  }

  /*
   * Evidence fallback.
   */
  const firstEvidence =
    evidence.find(
      (row: any) =>
        row?.source_url ||
        row?.url
    ) ||
    evidence[0];

  if (
    !out.source_url &&
    firstEvidence
  ) {
    out.source_url =
      firstEvidence?.source_url ||
      firstEvidence?.url ||
      "";
  }

  if (
    !out.source &&
    firstEvidence
  ) {
    out.source =
      firstEvidence?.source_title ||
      firstEvidence?.title ||
      firstEvidence?.source ||
      "";
  }

  return out;
}

/* =========================================================
   RUN ID
========================================================= */

export function runId(
  data: any
): number | null {
  const result =
    rootResult(data);

  const raw =
    data?.id ??
    data?.research_run_id ??
    result?.research_run_id ??
    result?.id ??
    result?.run_id ??
    null;

  const n =
    Number(raw);

  return Number.isFinite(n) &&
    n > 0
    ? n
    : null;
}

/* =========================================================
   SCORES / CONFIDENCE
========================================================= */

export function scoreOf(
  row: any
): number {
  const n =
    numberOrNull(
      row?.final_score ??
        row?.score ??
        row?.overall_score
    );

  return n ?? 0;
}

export function confidenceOf(
  row: any
): number | null {
  const raw =
    row?.recommendation_confidence ??
    row?.confidence ??
    row?.evidence_confidence;

  const value =
    numberOrNull(raw);

  if (
    value === null ||
    value <= 0
  ) {
    return null;
  }

  return value;
}

/* =========================================================
   AVAILABILITY FLAGS
========================================================= */

export function sentimentAvailable(
  row: any
): boolean {
  const directCount =
    numberOrNull(
      row
        ?.sentiment_summary
        ?.classified_review_count
    );

  if (
    directCount !==
      null &&
    directCount > 0
  ) {
    return true;
  }

  const rows =
    row?.reviews ||
    row?.review_evidence ||
    row?.sentiment?.reviews ||
    row?.sentiment?.items ||
    [];

  if (
    !Array.isArray(rows)
  ) {
    return false;
  }

  return rows.some(
    (review: any) => {
      const label =
        String(
          review?.sentiment ||
            review?.label ||
            ""
        )
          .trim()
          .toLowerCase();

      return [
        "positive",
        "neutral",
        "negative",
      ].includes(label);
    }
  );
}

export function customerImpactAvailable(
  row: any
): boolean {
  return (
    (Array.isArray(
      row?.customer_impact
    ) &&
      row.customer_impact
        .length > 0) ||
    (Array.isArray(
      row?.customers
    ) &&
      row.customers
        .length > 0) ||
    (Array.isArray(
      row?.customer_adoption
    ) &&
      row.customer_adoption
        .length > 0) ||
    (Array.isArray(
      row
        ?.technographic_evidence
    ) &&
      row
        .technographic_evidence
        .length > 0)
  );
}

/* =========================================================
   FORMATTING
========================================================= */

export function money(
  value: any,
  currency = "GBP"
): string {
  const n =
    numberOrNull(value);

  if (n === null) {
    return "Unavailable";
  }

  try {
    return new Intl.NumberFormat(
      "en-GB",
      {
        style: "currency",
        currency,
        maximumFractionDigits: 0,

        notation:
          Math.abs(n) >=
          1_000_000
            ? "compact"
            : "standard",
      }
    ).format(n);
  } catch {
    return `${currency} ${n.toLocaleString(
      "en-GB"
    )}`;
  }
}

export function num(
  value: any,
  digits = 1
): string {
  const n =
    numberOrNull(value);

  return n === null
    ? "—"
    : n.toFixed(digits);
}
