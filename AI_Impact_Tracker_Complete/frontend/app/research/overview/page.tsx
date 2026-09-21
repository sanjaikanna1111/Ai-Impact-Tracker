"use client";

import ResultGuard from "@/components/ResultGuard";
import { Donut, HorizontalBars } from "@/components/Charts";
import {
  allEvidence,
  bestRecommendation,
  classifiedReviewRows,
  customerRows,
  dataQuality,
  recommendations,
  researchComplete,
} from "@/lib/data";

/* =========================================================
   HELPERS
========================================================= */

function numberOrNull(value: unknown): number | null {
  if (
    value === null ||
    value === undefined ||
    value === ""
  ) {
    return null;
  }

  const n = Number(value);

  return Number.isFinite(n) ? n : null;
}

function recommendationScore(row: any): number | null {
  return numberOrNull(
    row?.final_score ??
      row?.score ??
      row?.overall_score
  );
}

function metricValue(
  primary: unknown,
  fallback: number
): number {
  const value = numberOrNull(primary);

  return value === null
    ? fallback
    : value;
}

function isQuantifiedImpact(row: any): boolean {
  return (
    numberOrNull(
      row?.impact_value
    ) !== null
  );
}

/* =========================================================
   PAGE
========================================================= */

export default function OverviewPage() {
  return (
    <ResultGuard>
      {(data) => {
        const recs =
          recommendations(data);

        const best =
          bestRecommendation(data);

        const evidence =
          allEvidence(data);

        const classifiedReviews =
          classifiedReviewRows(data);

        const customers =
          customerRows(data);

        const quality =
          dataQuality(data);

        const complete =
          researchComplete(data);

        /*
         * Only explicit numeric customer impacts
         * count as quantified outcomes.
         *
         * Number(null) must NOT become 0 and then
         * accidentally count as a numeric impact.
         */
        const quantified =
          customers.filter(
            isQuantifiedImpact
          ).length;

        const namedCustomers =
          customers.filter(
            (row: any) =>
              Boolean(
                row?.customer ||
                  row?.customer_company ||
                  row?.company ||
                  row?.organisation ||
                  row?.organization
              )
          ).length;

        const validatedCount =
          metricValue(
            quality?.validated_count,
            recs.length
          );

        const retainedEvidenceCount =
          metricValue(
            quality?.retained_product_evidence ??
              quality?.retained_evidence,
            evidence.length
          );

        const classifiedReviewCount =
          metricValue(
            quality?.classified_review_sources ??
              quality?.classified_review_count,
            classifiedReviews.length
          );

        const quantifiedImpactCount =
          metricValue(
            quality?.quantified_customer_impacts,
            quantified
          );

        const bestScore =
          best
            ? recommendationScore(
                best
              )
            : null;

        /*
         * Only recommendations that actually have
         * a score are included in the ranking chart.
         * Missing scores are NOT converted to zero.
         */
        const rankingRows =
          recs
            .map((row: any) => ({
              label:
                row?.product ||
                row?.vendor ||
                "Product",

              value:
                recommendationScore(
                  row
                ),
            }))
            .filter(
              (
                row
              ): row is {
                label: string;
                value: number;
              } =>
                row.value !==
                null
            )
            .slice(0, 8);

        return (
          <>
            <header className="page-header">
              <div>
                <span className="eyebrow">
                  02 / OVERVIEW
                </span>

                <h1>
                  Decision overview.
                </h1>

                <p>
                  {complete
                    ? "Executive view of the completed research run. Recommendation rankings reflect the evidence retained across product fit, implementation, reviews, customer adoption and financial value where available."
                    : "Research results are partial. Extracted evidence is shown, but incomplete deep analysis is not presented as final confidence or a fully completed recommendation."}
                </p>
              </div>
            </header>

            {!complete && (
              <div className="empty-state">
                <b>
                  Partial research.
                </b>{" "}
                {quality?.partial_reason ||
                  quality?.message ||
                  "One or more products did not complete every deep-research stage. The ranking below should therefore be treated as preliminary."}
              </div>
            )}

            {/* =============================================
                EXECUTIVE METRICS
            ============================================= */}

            <div className="metric-grid">
              <Metric
                label="Validated products"
                value={
                  validatedCount
                }
              />

              <Metric
                label="Retained evidence"
                value={
                  retainedEvidenceCount
                }
              />

              <Metric
                label="Classified reviews"
                value={
                  classifiedReviewCount
                }
              />

              <Metric
                label="Named customer evidence"
                value={
                  namedCustomers
                }
              />

              <Metric
                label="Quantified impacts"
                value={
                  quantifiedImpactCount
                }
              />
            </div>

            {/* =============================================
                TOP RECOMMENDATION + RANKING
            ============================================= */}

            {best ? (
              <div className="two-col">
                <section className="panel hero-rec">
                  <span className="eyebrow">
                    {complete
                      ? "TOP RECOMMENDATION"
                      : "PRELIMINARY LEADER"}
                  </span>

                  <h2>
                    {best?.product ||
                      "Recommended solution"}
                  </h2>

                  <p className="vendor">
                    {best?.vendor ||
                      best?.company ||
                      "Vendor unavailable"}
                  </p>

                  <p>
                    {best?.description ||
                      best?.reason ||
                      best?.recommendation_reason ||
                      "Highest-ranked validated solution in the currently retained evidence."}
                  </p>

                  <div className="donut-row">
                    {bestScore !==
                    null ? (
                      <Donut
                        value={
                          bestScore
                        }
                        label={
                          complete
                            ? "Final score"
                            : "Preliminary score"
                        }
                      />
                    ) : (
                      <div className="metric-card">
                        <span>
                          {complete
                            ? "Final score"
                            : "Preliminary score"}
                        </span>

                        <strong>
                          Unavailable
                        </strong>
                      </div>
                    )}
                  </div>

                  {!complete && (
                    <p className="muted">
                      This product is
                      currently the
                      highest-ranked
                      validated candidate,
                      but it should not be
                      treated as a final
                      recommendation until
                      the remaining
                      research stages have
                      completed.
                    </p>
                  )}
                </section>

                <section className="panel">
                  <span className="eyebrow">
                    {complete
                      ? "FINAL RANKING"
                      : "PRELIMINARY RANKING"}
                  </span>

                  <h2>
                    Recommendation scores
                  </h2>

                  {rankingRows.length >
                  0 ? (
                    <HorizontalBars
                      rows={
                        rankingRows
                      }
                      max={100}
                    />
                  ) : (
                    <div className="empty-state">
                      Recommendation
                      records exist, but
                      no valid overall
                      scores were returned.
                    </div>
                  )}
                </section>
              </div>
            ) : (
              <div className="empty-state">
                <b>
                  No validated
                  recommendation was
                  returned.
                </b>{" "}
                Review the research
                execution logs to check
                whether product discovery
                or validation failed.
              </div>
            )}

            {/* =============================================
                RESEARCH STATUS
            ============================================= */}

            <section className="panel">
              <span className="eyebrow">
                RESEARCH STATUS
              </span>

              <h2>
                Evidence readiness
              </h2>

              <div className="assessment">
                <div>
                  <span>
                    Product validation
                  </span>

                  <strong>
                    {validatedCount >
                    0
                      ? `${validatedCount} validated`
                      : "No validated products"}
                  </strong>
                </div>

                <div>
                  <span>
                    Product evidence
                  </span>

                  <strong>
                    {retainedEvidenceCount >
                    0
                      ? `${retainedEvidenceCount} retained records`
                      : "No retained evidence"}
                  </strong>
                </div>

                <div>
                  <span>
                    Review sentiment
                  </span>

                  <strong>
                    {classifiedReviewCount >
                    0
                      ? `${classifiedReviewCount} classified reviews`
                      : "Insufficient classified reviews"}
                  </strong>
                </div>

                <div>
                  <span>
                    Customer adoption
                  </span>

                  <strong>
                    {namedCustomers >
                    0
                      ? `${namedCustomers} named records`
                      : "No verified named customers"}
                  </strong>
                </div>

                <div>
                  <span>
                    Quantified impact
                  </span>

                  <strong>
                    {quantifiedImpactCount >
                    0
                      ? `${quantifiedImpactCount} quantified outcomes`
                      : "No verified quantified outcomes"}
                  </strong>
                </div>

                <div>
                  <span>
                    Overall research
                  </span>

                  <strong>
                    {complete
                      ? "Complete"
                      : "Partial / preliminary"}
                  </strong>
                </div>
              </div>
            </section>
          </>
        );
      }}
    </ResultGuard>
  );
}

/* =========================================================
   METRIC
========================================================= */

function Metric({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="metric-card">
      <span>
        {label}
      </span>

      <strong>
        {value}
      </strong>
    </div>
  );
}