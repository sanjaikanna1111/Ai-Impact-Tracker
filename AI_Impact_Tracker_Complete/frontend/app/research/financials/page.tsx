"use client";

import ResultGuard from "@/components/ResultGuard";
import { HorizontalBars } from "@/components/Charts";
import { financials } from "@/lib/data";
import { ExternalLink } from "lucide-react";

const metrics = [
  ["revenue", "Revenue"],
  ["operating_costs", "Operating costs"],
  ["operating_income", "Operating income"],
  ["adjusted_operating_profit", "Adjusted operating profit"],
  ["profit_before_tax", "Profit before tax"],
  ["net_income", "Net income"],
  ["total_assets", "Total assets"],
  ["total_liabilities", "Total liabilities"],
  ["cash", "Cash"],
  ["operating_cash_flow", "Operating cash flow"],
  ["employees", "Employees"],
];

function numberOrNull(value: unknown): number | null {
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

function formatMoney(
  value: unknown,
  currency = "GBP"
): string {
  const n = numberOrNull(value);

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
      }
    ).format(n);
  } catch {
    return `${currency} ${n.toLocaleString("en-GB")}`;
  }
}

function formatEmployees(
  value: unknown
): string {
  const n = numberOrNull(value);

  if (n === null) {
    return "Unavailable";
  }

  return n.toLocaleString(
    "en-GB"
  );
}

function formatConfidence(
  value: unknown
): string {
  const n = numberOrNull(value);

  if (n === null) {
    return "Unavailable";
  }

  const pct =
    n <= 1
      ? n * 100
      : n;

  return `${Math.round(pct)}%`;
}

function sourceLabel(
  value: unknown
): string {
  if (
    value === null ||
    value === undefined ||
    value === ""
  ) {
    return "—";
  }

  return String(value);
}

function isUrl(
  value: unknown
): boolean {
  return (
    typeof value === "string" &&
    /^https?:\/\//i.test(value)
  );
}

export default function FinancialsPage() {
  return (
    <ResultGuard>
      {(data) => {
        const f =
          financials(data) || {};

        const currency =
          f?.currency ||
          "GBP";

        const status =
          String(
            f?.status || ""
          ).toLowerCase();

        const message =
          f?.message || "";

        const companyName =
          f?.company_name ||
          f?.matched_company ||
          "Unavailable";

        const identifier =
          f?.company_number ||
          f?.ticker ||
          f?.cik ||
          "Unavailable";

        const period =
          f?.reporting_period ||
          f?.fiscal_year ||
          "Unavailable";

        const scopeRaw = f?.financial_scope || "";
        const formattedScope =
          scopeRaw === "legal_entity"
            ? "Legal entity"
            : scopeRaw === "parent_company"
              ? "Parent company"
              : scopeRaw === "group"
                ? "Group"
                : scopeRaw
                  ? String(scopeRaw).replace(/_/g, " ")
                  : "Unavailable";

        const legalEntityOrGroup =
          f?.parent_company ||
          (f?.trading_brand && f?.trading_brand !== companyName
            ? `${companyName} (${formattedScope})`
            : companyName);

        const fmp = f?.fmp || {};

        const graphRows =
          metrics
            .slice(0, 10)
            .map(
              ([key, label]) => ({
                label,
                value:
                  numberOrNull(
                    f?.[key]
                  ),
              })
            )
            .filter(
              (
                row
              ): row is {
                label: string;
                value: number;
              } =>
                row.value !==
                null
            );

        const availableMetrics = metrics.filter(
          ([key]) => numberOrNull(f?.[key]) !== null
        );

        return (
          <>
            <header className="page-header">
              <div>
                <span className="eyebrow">
                  07 / FINANCIALS
                </span>

                <h1>
                  Company financial
                  context.
                </h1>

                <p>
                  Verified company
                  identity and financial
                  context are shown
                  separately from
                  product recommendation
                  scoring.
                </p>
              </div>
            </header>

            {status === "identity_verified_financials_unavailable" ? (
              <div className="status amber" style={{ marginBottom: 18 }}>
                {message || "Company identity verified, but no sufficiently reliable financial metrics were found from the configured sources."}
              </div>
            ) : message ? (
              <div
                className={
                  status ===
                    "complete" ||
                  status ===
                    "verified"
                    ? "status green"
                    : status ===
                        "partial" ||
                      status ===
                        "ambiguous_company" ||
                      status ===
                        "ambiguous"
                      ? "status amber"
                      : "empty-state"
                }
                style={{
                  marginBottom: 18,
                }}
              >
                {message}
              </div>
            ) : null}

            {!message &&
              status ===
                "not_requested" && (
                <div className="empty-state">
                  Enter a company name on
                  the Research page to
                  retrieve verified
                  company financial
                  context.
                </div>
              )}

            {(status === "ambiguous_company" || status === "ambiguous") && (
              <section className="panel" style={{ borderLeft: "4px solid #f59e0b", marginBottom: 18 }}>
                <span className="eyebrow" style={{ color: "#d97706" }}>AMBIGUOUS ENTITY RESOLUTION</span>
                <h2>Company identity could not be unambiguously resolved</h2>
                <p>
                  Multiple competing entities match this name in official registries. Financial context was not attached
                  to avoid matching the wrong organisation or attributing unrelated financial figures.
                </p>
                {Array.isArray(f?.candidates) && f.candidates.length > 0 && (
                  <div className="table-wrap" style={{ marginTop: 12 }}>
                    <table>
                      <thead>
                        <tr>
                          <th>Candidate company</th>
                          <th>Company number / Ticker</th>
                          <th>Status</th>
                          <th>Match score</th>
                        </tr>
                      </thead>
                      <tbody>
                        {f.candidates.map((cand: any, idx: number) => (
                          <tr key={idx}>
                            <td><b>{cand?.title || cand?.company_name || "—"}</b></td>
                            <td>{cand?.company_number || cand?.ticker || "—"}</td>
                            <td>{cand?.company_status || "—"}</td>
                            <td>{cand?.similarity ? `${Math.round(cand.similarity * 100)}%` : "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            )}

            <div className="metric-grid">
              <Metric
                label="Verified company"
                value={f?.trading_brand ? `${f.trading_brand}` : companyName}
              />

              <Metric
                label="Legal entity / group"
                value={legalEntityOrGroup}
              />

              <Metric
                label="Financial scope"
                value={formattedScope}
              />

              <Metric
                label="Company number / ticker"
                value={identifier}
              />

              <Metric
                label="Currency"
                value={currency}
              />

              <Metric
                label="Reporting period"
                value={period}
              />

              <Metric
                label="Match confidence"
                value={formatConfidence(
                  f?.match_confidence
                )}
              />
            </div>

            {fmp?.status === "available" && (
              <section className="panel">
                <span className="eyebrow">
                  COMPANY FINANCIAL CONTEXT
                </span>

                <h2>
                  Structured FMP data
                </h2>

                <div className="metric-grid">
                  <Metric
                    label="Operating expenses"
                    value={formatMoney(
                      fmp?.operating_expenses,
                      fmp?.currency || currency
                    )}
                  />

                  <Metric
                    label="Reporting period"
                    value={
                      fmp?.fiscal_year
                        ? `FY${fmp.fiscal_year}`
                        : "Unavailable"
                    }
                  />

                  <Metric
                    label="Ticker"
                    value={fmp?.symbol || "Unavailable"}
                  />

                  <Metric
                    label="Source"
                    value="Financial Modeling Prep"
                  />
                </div>

                <p>
                  Company-wide operating expenses are financial context,
                  not the ROI cost base for a process-specific implementation.
                </p>
              </section>
            )}

            {graphRows.length >
            0 ? (
              <section className="panel">
                <span className="eyebrow">
                  FINANCIAL SCALE
                </span>

                <h2>
                  Reported metrics
                </h2>

                <HorizontalBars
                  rows={
                    graphRows
                  }
                />
              </section>
            ) : (
              <div className="empty-state">
                <b>
                  No verified financial
                  metrics are available.
                </b>{" "}
                {status === "identity_verified_financials_unavailable" || (companyName !== "Unavailable" && status !== "ambiguous_company" && status !== "not_requested")
                  ? "Company identity verified, but no sufficiently reliable financial metrics were found from the configured sources."
                  : message
                    ? message
                    : "The company identity may not have been supplied, matched, or supported by readable official financial evidence."}
              </div>
            )}

            {availableMetrics.length > 0 && (
            <section className="panel table-panel">
              <div className="panel-head">
                <div>
                  <span className="eyebrow">
                    VERIFIED FINANCIAL
                    DATA
                  </span>

                  <h2>
                    Company metrics
                  </h2>
                </div>
              </div>

              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>
                        Metric
                      </th>

                      <th>
                        Value
                      </th>

                      <th>
                        Period
                      </th>

                      <th>
                        Source
                      </th>
                    </tr>
                  </thead>

                  <tbody>
                    {availableMetrics.map(
                      (
                        [
                          key,
                          label,
                        ]
                      ) => {
                        const value =
                          f?.[key];

                        const metricPeriod =
                          f?.[
                            `${key}_reporting_period`
                          ] ||
                          f?.[
                            `${key}_period`
                          ] ||
                          f?.reporting_period ||
                          f?.fiscal_year ||
                          "—";

                        const metricSource =
                          f?.[
                            `${key}_source_url`
                          ] ||
                          f?.[
                            `${key}_source`
                          ] ||
                          f?.source_url ||
                          f?.source ||
                          null;

                        return (
                          <tr
                            key={
                              key
                            }
                          >
                            <td>
                              <b>
                                {label}
                              </b>
                            </td>

                            <td>
                              {key ===
                              "employees"
                                ? formatEmployees(
                                    value
                                  )
                                : formatMoney(
                                    value,
                                    currency
                                  )}
                            </td>

                            <td>
                              {metricPeriod}
                            </td>

                            <td>
                              {isUrl(
                                metricSource
                              ) ? (
                                <a
                                  href={String(
                                    metricSource
                                  )}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  Open source{" "}
                                  <ExternalLink
                                    size={
                                      14
                                    }
                                  />
                                </a>
                              ) : (
                                sourceLabel(
                                  metricSource
                                )
                              )}
                            </td>
                          </tr>
                        );
                      }
                    )}
                  </tbody>
                </table>
              </div>
            </section>
            )}

            {Array.isArray(
              f?.evidence
            ) &&
              f.evidence.length >
                0 && (
                <section className="panel table-panel">
                  <div className="panel-head">
                    <div>
                      <span className="eyebrow">
                        FINANCIAL
                        SOURCES
                      </span>

                      <h2>
                        Supporting
                        evidence
                      </h2>
                    </div>
                  </div>

                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>
                            Source
                          </th>

                          <th>
                            Metric /
                            claim
                          </th>

                          <th>
                            Period
                          </th>

                          <th>
                            Link
                          </th>
                        </tr>
                      </thead>

                      <tbody>
                        {f.evidence.map(
                          (
                            item: any,
                            index: number
                          ) => {
                            const url =
                              item?.source_url ||
                              item?.url ||
                              "";

                            return (
                              <tr
                                key={
                                  index
                                }
                              >
                                <td>
                                  {item?.source ||
                                    item?.source_title ||
                                    item?.title ||
                                    "Financial evidence"}
                                </td>

                                <td>
                                  {item?.metric ||
                                    item?.claim ||
                                    item?.supporting_text ||
                                    "—"}
                                </td>

                                <td>
                                  {item?.reporting_period ||
                                    item?.period ||
                                    item?.fiscal_year ||
                                    "—"}
                                </td>

                                <td>
                                  {isUrl(
                                    url
                                  ) ? (
                                    <a
                                      href={
                                        url
                                      }
                                      target="_blank"
                                      rel="noreferrer"
                                    >
                                      Open{" "}
                                      <ExternalLink
                                        size={
                                          14
                                        }
                                      />
                                    </a>
                                  ) : (
                                    "—"
                                  )}
                                </td>
                              </tr>
                            );
                          }
                        )}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}
          </>
        );
      }}
    </ResultGuard>
  );
}

function Metric({
  label,
  value,
}: {
  label: string;
  value: any;
}) {
  return (
    <div className="metric-card">
      <span>
        {label}
      </span>

      <strong className="metric-text">
        {String(
          value ??
            "Unavailable"
        )}
      </strong>
    </div>
  );
}
