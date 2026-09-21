"use client";

import ResultGuard from "@/components/ResultGuard";
import { HorizontalBars } from "@/components/Charts";
import { recommendations } from "@/lib/data";

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

  const parsed = Number(value);

  return Number.isFinite(parsed)
    ? parsed
    : null;
}

function money(
  value: unknown
): string {
  const n = numberOrNull(value);

  if (n === null) {
    return "Unavailable";
  }

  return `£${n.toLocaleString(undefined, {
    maximumFractionDigits: 2,
  })}`;
}

function pct(
  value: unknown
): string {
  const n = numberOrNull(value);

  if (n === null) {
    return "Unavailable";
  }

  return `${n.toFixed(1)}%`;
}

function months(
  value: unknown
): string {
  const n = numberOrNull(value);

  if (n === null) {
    return "Unavailable";
  }

  return `${n.toFixed(1)} months`;
}

export default function ValuePage() {
  return (
    <ResultGuard>
      {(data) => {
        const recs =
          recommendations(data);

        const scenarioRows =
          recs
            .map((r: any) => {
              const improvement =
                numberOrNull(
                  r?.value_assessment
                    ?.expected_improvement_percent
                );

              return {
                label:
                  r?.product ||
                  "Product",
                value:
                  improvement,
              };
            })
            .filter(
              (
                row: {
                  label: string;
                  value: number | null;
                }
              ) =>
                row.value !==
                null
            )
            .map((row) => ({
              label:
                row.label,
              value:
                row.value as number,
            }));

        return (
          <>
            <header className="page-header">
              <div>
                <span className="eyebrow">
                  08 / ROI & VALUE
                </span>

                <h1>
                  Pre-implementation
                  value case.
                </h1>

                <p>
                  The value case is
                  shown even when ROI
                  is unavailable. ROI
                  and payback are
                  calculated only when
                  the research has a
                  baseline,
                  evidence-supported
                  improvement and
                  verified first-year
                  investment.
                </p>
              </div>
            </header>

            {scenarioRows.length ? (
              <section className="panel">
                <span className="eyebrow">
                  EXPECTED IMPROVEMENT
                </span>

                <h2>
                  Evidence-derived
                  scenarios
                </h2>

                <HorizontalBars
                  rows={
                    scenarioRows
                  }
                  max={100}
                  suffix="%"
                />
              </section>
            ) : (
              <div className="empty-state">
                <b>
                  No
                  evidence-supported
                  improvement
                  percentage is
                  available yet.
                </b>{" "}
                The fit/evidence case
                below is still a valid
                pre-implementation
                assessment; ROI
                remains unavailable
                until the missing
                financial and impact
                inputs are found.
              </div>
            )}

            <section className="panel table-panel">
              <div className="panel-head">
                <div>
                  <span className="eyebrow">
                    PRE-IMPLEMENTATION
                    CASE
                  </span>

                  <h2>
                    Fit, evidence and
                    readiness
                  </h2>
                </div>
              </div>

              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>
                        Product
                      </th>

                      <th>
                        Goal fit
                      </th>

                      <th>
                        Sector fit
                      </th>

                      <th>
                        Evidence
                      </th>

                      <th>
                        Implementation
                      </th>

                      <th>
                        Budget fit
                      </th>

                      <th>
                        Reviews
                      </th>

                      <th>
                        Customer
                        evidence
                      </th>
                    </tr>
                  </thead>

                  <tbody>
                    {recs.map(
                      (
                        r: any,
                        i: number
                      ) => {
                        const v =
                          r?.value_assessment
                            ?.pre_implementation_value_case ||
                          {};

                        const reviews =
                          numberOrNull(
                            v?.classified_review_count ??
                              r
                                ?.sentiment_summary
                                ?.classified_review_count
                          );

                        const customerRecords =
                          Array.isArray(
                            r?.customers
                          )
                            ? r.customers
                                .length
                            : 0;

                        const customerImpacts =
                          Array.isArray(
                            r?.customer_impact
                          )
                            ? r
                                .customer_impact
                                .length
                            : 0;

                        const customers =
                          numberOrNull(
                            v?.verified_customer_records
                          ) ??
                          customerRecords;

                        const quantified =
                          numberOrNull(
                            v?.quantified_customer_impacts
                          ) ??
                          customerImpacts;

                        return (
                          <tr
                            key={
                              i
                            }
                          >
                            <td>
                              <b>
                                {r?.product ||
                                  "—"}
                              </b>
                            </td>

                            <td>
                              {pct(
                                v?.goal_fit_score ??
                                  r?.goal_fit
                              )}
                            </td>

                            <td>
                              {pct(
                                v?.sector_fit_score ??
                                  r?.sector_fit
                              )}
                            </td>

                            <td>
                              {pct(
                                v?.evidence_score ??
                                  r?.evidence_score
                              )}
                            </td>

                            <td>
                              {pct(
                                v?.implementation_score ??
                                  r?.implementation_score
                              )}
                            </td>

                            <td>
                              {pct(
                                v?.budget_fit_score ??
                                  r?.budget_score
                              )}
                            </td>

                            <td>
                              {reviews ??
                                0}
                            </td>

                            <td>
                              {customers ??
                                0}
                              {quantified >
                              0
                                ? ` (${quantified} quantified)`
                                : ""}
                            </td>
                          </tr>
                        );
                      }
                    )}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="panel table-panel">
              <div className="panel-head">
                <div>
                  <span className="eyebrow">SOFTWARE COST / BUDGET CASE</span>
                  <h2>Verified subscription cost</h2>
                </div>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th>Pricing basis</th>
                      <th>Annual software cost</th>
                      <th>Monthly equivalent</th>
                      <th>Budget utilisation</th>
                      <th>Budget remaining</th>
                      <th>3-year software cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recs.map((r: any, i: number) => {
                      const v = r?.value_assessment || {};
                      const pricing = Array.isArray(r?.pricing_evidence) ? r.pricing_evidence[0] : null;
                      return <tr key={i}>
                        <td><b>{r?.product || "â€”"}</b></td>
                        <td>{r?.pricing_basis || pricing?.claim || "Not publicly verified"}{pricing?.source_url ? <><br /><a href={pricing.source_url} target="_blank" rel="noreferrer">Source</a></> : null}</td>
                        <td>{money(v?.annual_software_cost ?? r?.annual_software_cost)}</td>
                        <td>{money(v?.monthly_equivalent)}</td>
                        <td>{pct(v?.budget_utilisation_pct)}</td>
                        <td>{money(v?.budget_remaining)}</td>
                        <td>{money(v?.three_year_software_cost)}</td>
                      </tr>;
                    })}
                  </tbody>
                </table>
              </div>
              {recs.some((r: any) => {
                const v = r?.value_assessment || {};
                return (v?.annual_software_cost ?? r?.annual_software_cost) != null && v?.expected_roi_percent == null;
              }) && (
                <p style={{ marginTop: 14, fontSize: 13, color: "var(--text-muted, #6b7280)" }}>
                  Full ROI is not yet calculable because the required process-benefit inputs are unavailable. Verified software-cost analysis is shown above.
                </p>
              )}
            </section>

            <section className="panel table-panel">
              <div className="panel-head">
                <div>
                  <span className="eyebrow">
                    FINANCIAL VALUE
                  </span>

                  <h2>
                    ROI and payback
                  </h2>
                </div>
              </div>

              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>
                        Product
                      </th>

                      <th>
                        Baseline
                        process cost
                      </th>

                      <th>
                        Annual
                        software
                      </th>

                      <th>
                        Implementation
                      </th>

                      <th>
                        Expected
                        improvement
                      </th>

                      <th>
                        Expected
                        annual benefit
                      </th>

                      <th>
                        ROI
                      </th>

                      <th>
                        Payback
                      </th>
                    </tr>
                  </thead>

                  <tbody>
                    {recs.map(
                      (
                        r: any,
                        i: number
                      ) => {
                        const v =
                          r?.value_assessment ||
                          {};

                        const baseline =
                          v?.baseline_annual_process_cost ??
                          v?.baseline_process_cost ??
                          v?.baseline_cost ??
                          null;

                        const annualSoftware =
                          v?.annual_software_cost ??
                          v?.estimated_annual_cost ??
                          r?.annual_software_cost ??
                          null;

                        const implementation =
                          v?.implementation_cost ??
                          v?.estimated_implementation_cost ??
                          r?.implementation_cost ??
                          null;

                        const improvement =
                          v?.expected_improvement_percent ??
                          v?.expected_improvement ??
                          null;

                        const annualBenefit =
                          v?.expected_annual_benefit ??
                          v?.expected_benefit ??
                          null;

                        const roi =
                          v?.expected_roi_percent ??
                          v?.expected_roi ??
                          null;

                        const payback =
                          v?.expected_payback_months ??
                          v?.payback_months ??
                          null;

                        return (
                          <tr
                            key={
                              i
                            }
                          >
                            <td>
                              <b>
                                {r?.product ||
                                  "—"}
                              </b>
                            </td>

                            <td>
                              {money(
                                baseline
                              )}
                            </td>

                            <td>
                              {money(
                                annualSoftware
                              )}
                            </td>

                            <td>
                              {money(
                                implementation
                              )}
                            </td>

                            <td>
                              {pct(
                                improvement
                              )}
                            </td>

                            <td>
                              {money(
                                annualBenefit
                              )}
                            </td>

                            <td>
                              {pct(
                                roi
                              )}
                            </td>

                            <td>
                              {months(
                                payback
                              )}
                            </td>
                          </tr>
                        );
                      }
                    )}
                  </tbody>
                </table>
              </div>

              {recs.some((r: any) => {
                const v = r?.value_assessment || {};
                const reasons = v?.missing_reasons || (v?.unavailable_reason ? [v.unavailable_reason] : []);
                return reasons.length > 0 && v?.expected_roi_percent == null;
              }) && (
                <div style={{ marginTop: 24 }}>
                  <span className="eyebrow">INPUT PREREQUISITES & AVAILABILITY</span>
                  <h3 style={{ marginTop: 4, marginBottom: 8, fontSize: 16 }}>Missing-Input Breakdown</h3>
                  <p style={{ fontSize: 13, color: "var(--text-muted, #6b7280)", marginBottom: 14 }}>
                    ROI and payback require verified values for the process cost baseline, software pricing, implementation costs, and quantified impact.
                    The items below identify the specific inputs preventing calculation:
                  </p>
                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    {recs.map((r: any, idx: number) => {
                      const v = r?.value_assessment || {};
                      const isAvailable = v?.expected_roi_percent != null;
                      const reasons: string[] = Array.isArray(v?.missing_reasons) && v.missing_reasons.length > 0
                        ? v.missing_reasons
                        : v?.unavailable_reason
                          ? [v.unavailable_reason]
                          : [];

                      return (
                        <div
                          key={idx}
                          style={{
                            padding: "12px 16px",
                            borderRadius: 6,
                            background: isAvailable ? "rgba(34, 197, 94, 0.06)" : "rgba(245, 158, 11, 0.06)",
                            borderLeft: isAvailable ? "4px solid #22c55e" : "4px solid #f59e0b",
                          }}
                        >
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                            <strong style={{ fontSize: 14 }}>{r?.product || `Product ${idx + 1}`}</strong>
                            <span style={{
                              fontSize: 11,
                              fontWeight: 600,
                              padding: "2px 6px",
                              borderRadius: 4,
                              background: isAvailable ? "#22c55e" : "#f59e0b",
                              color: "#fff",
                            }}>
                              {isAvailable ? "ROI Available" : "Inputs Missing"}
                            </span>
                          </div>
                          {isAvailable ? (
                            <p style={{ margin: 0, fontSize: 13, color: "var(--text-muted, #6b7280)" }}>
                              All prerequisites verified. Expected ROI: {pct(v.expected_roi_percent)}, payback: {months(v.expected_payback_months)}.
                            </p>
                          ) : reasons.length > 0 ? (
                            <ul style={{ margin: "4px 0 0 16px", padding: 0, fontSize: 13, lineHeight: 1.5 }}>
                              {reasons.map((reason: string, rIdx: number) => (
                                <li key={rIdx}>{reason}</li>
                              ))}
                            </ul>
                          ) : (
                            <p style={{ margin: 0, fontSize: 13, color: "var(--text-muted, #6b7280)" }}>
                              Baseline process cost or software investment data not available.
                            </p>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </section>
          </>
        );
      }}
    </ResultGuard>
  );
}
