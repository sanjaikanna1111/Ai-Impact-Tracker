"use client";

import ResultGuard from "@/components/ResultGuard";
import { Donut, ScoreBars } from "@/components/Charts";
import {
  customerImpactAvailable,
  recommendations,
  researchComplete,
  scoreOf,
  sentimentAvailable,
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

function scoreValue(
  primary: unknown,
  fallback?: unknown
): number | null {
  const first = numberOrNull(primary);

  if (first !== null) {
    return first;
  }

  return numberOrNull(fallback);
}

function validScoreRow(
  label: string,
  value: number | null
) {
  if (value === null) {
    return null;
  }

  return {
    label,
    value,
  };
}

function confidenceLabel(
  row: any
): string {
  const confidence =
    numberOrNull(
      row?.recommendation_confidence ??
        row?.confidence ??
        row?.evidence_confidence
    );

  if (
    confidence === null ||
    confidence <= 0
  ) {
    return "Unavailable";
  }

  const pct =
    confidence <= 1
      ? confidence * 100
      : confidence;

  return `${Math.round(pct)}%`;
}

/* =========================================================
   PAGE
========================================================= */

export default function RecommendationsPage() {
  return (
    <ResultGuard>
      {(data) => {
        const recs =
          recommendations(data);

        const complete =
          researchComplete(data);

        return (
          <>
            <header className="page-header">
              <div>
                <span className="eyebrow">
                  03 / RECOMMENDATIONS
                </span>

                <h1>
                  Compare the shortlist.
                </h1>

                <p>
                  {complete
                    ? "Final ranking after evidence, sentiment, customer adoption, quantified impact, pricing and implementation analysis."
                    : "Preliminary ranking. Deep research is incomplete, so missing sentiment, customer evidence or confidence is shown as unavailable rather than being replaced by neutral scores."}
                </p>
              </div>
            </header>

            {!recs.length && (
              <div className="empty-state">
                <b>
                  No recommendation
                  records are available.
                </b>{" "}
                The research run did not
                return a validated
                shortlist.
              </div>
            )}

            <div className="recommendation-list">
              {recs.map(
                (
                  r: any,
                  i: number
                ) => {
                  const goalFit =
                    scoreValue(
                      r?.goal_fit,
                      r?.scores?.goal_fit
                    );

                  const sectorFit =
                    scoreValue(
                      r?.sector_fit,
                      r?.scores?.sector_fit
                    );

                  const evidence =
                    scoreValue(
                      r?.evidence_score,
                      r?.scores?.evidence
                    );

                  const sentiment =
                    sentimentAvailable(r)
                      ? scoreValue(
                          r?.sentiment_score,
                          r?.scores?.sentiment
                        )
                      : null;

                  const customerImpact =
                    customerImpactAvailable(
                      r
                    )
                      ? scoreValue(
                          r?.customer_impact_score ??
                            r?.impact_score,
                          r?.scores
                            ?.customer_impact
                        )
                      : null;

                  const implementation =
                    scoreValue(
                      r?.implementation_score,
                      r?.scores
                        ?.implementation
                    );

                  const budget =
                    scoreValue(
                      r?.budget_score ??
                        r?.budget_fit_score,
                      r?.scores?.budget
                    );

                  const rows = [
                    validScoreRow(
                      "Goal fit",
                      goalFit
                    ),

                    validScoreRow(
                      "Sector fit",
                      sectorFit
                    ),

                    validScoreRow(
                      "Evidence",
                      evidence
                    ),

                    validScoreRow(
                      "Sentiment",
                      sentiment
                    ),

                    validScoreRow(
                      "Customer impact",
                      customerImpact
                    ),

                    validScoreRow(
                      "Implementation",
                      implementation
                    ),

                    validScoreRow(
                      "Budget fit",
                      budget
                    ),
                  ].filter(
                    (
                      row
                    ): row is {
                      label: string;
                      value: number;
                    } =>
                      row !== null
                  );

                  const finalScore =
                    numberOrNull(
                      scoreOf(r)
                    );

                  const hasFinalScore =
                    finalScore !==
                    null;

                  return (
                    <article
                      className="panel recommendation-card"
                      key={`${r?.product || "product"}-${i}`}
                    >
                      <div className="rank">
                        #{i + 1}
                      </div>

                      <div className="rec-main">
                        <span className="eyebrow">
                          {r?.vendor ||
                            "VENDOR"}
                        </span>

                        <h2>
                          {r?.product ||
                            "Unnamed product"}
                        </h2>

                        <p>
                          {r?.description ||
                            r?.reason ||
                            r?.recommendation_reason ||
                            "Validated commercial solution."}
                        </p>

                        {rows.length >
                        0 ? (
                          <ScoreBars
                            rows={
                              rows
                            }
                          />
                        ) : (
                          <div className="empty-state">
                            No component
                            scores are
                            available for
                            this product.
                          </div>
                        )}

                        {!sentimentAvailable(
                          r
                        ) && (
                          <p className="muted">
                            <b>
                              Sentiment:
                            </b>{" "}
                            insufficient
                            classified review
                            evidence.
                          </p>
                        )}

                        {!customerImpactAvailable(
                          r
                        ) && (
                          <p className="muted">
                            <b>
                              Customer
                              evidence:
                            </b>{" "}
                            no verified
                            customer adoption
                            or quantified
                            impact evidence
                            found.
                          </p>
                        )}

                        {!complete && (
                          <p className="muted">
                            <b>
                              Research
                              status:
                            </b>{" "}
                            preliminary.
                            Deep analysis was
                            not completed for
                            all evidence
                            dimensions.
                          </p>
                        )}

                        <p className="muted">
                          <b>
                            Recommendation
                            confidence:
                          </b>{" "}
                          {confidenceLabel(
                            r
                          )}
                        </p>
                      </div>

                      <div className="rec-score">
                        {hasFinalScore ? (
                          <Donut
                            value={
                              finalScore
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
                    </article>
                  );
                }
              )}
            </div>
          </>
        );
      }}
    </ResultGuard>
  );
}