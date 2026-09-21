"use client";

import ResultGuard from "@/components/ResultGuard";
import { SentimentPie } from "@/components/Charts";
import {
  classifiedReviewRows,
  reviewRows,
} from "@/lib/data";
import { ExternalLink } from "lucide-react";

/* =========================================================
   HELPERS
========================================================= */

function getSentiment(
  row: any
): "positive" | "neutral" | "negative" | "" {
  const value = String(
    row?.sentiment ||
      row?.label ||
      ""
  )
    .trim()
    .toLowerCase();

  if (
    value === "positive" ||
    value === "neutral" ||
    value === "negative"
  ) {
    return value;
  }

  return "";
}

function getPlatform(row: any): string {
  const explicit =
    row?.platform ||
    row?.source_platform ||
    row?.review_platform ||
    row?.domain;

  if (explicit) {
    return String(explicit);
  }

  const url =
    row?.url ||
    row?.source_url ||
    "";

  if (!url) {
    return "Web";
  }

  try {
    const hostname = new URL(
      url
    ).hostname
      .replace(/^www\./, "")
      .toLowerCase();

    const labels: Record<
      string,
      string
    > = {
      "reddit.com": "Reddit",
      "quora.com": "Quora",
      "g2.com": "G2",
      "capterra.com": "Capterra",
      "trustpilot.com": "Trustpilot",
      "trustradius.com": "TrustRadius",
      "getapp.com": "GetApp",
      "softwareadvice.com":
        "Software Advice",
      "peerspot.com": "PeerSpot",
      "gartner.com":
        "Gartner Peer Insights",
      "producthunt.com":
        "Product Hunt",
      "youtube.com": "YouTube",
      "youtu.be": "YouTube",
    };

    for (const [
      domain,
      label,
    ] of Object.entries(labels)) {
      if (
        hostname === domain ||
        hostname.endsWith(
          `.${domain}`
        )
      ) {
        return label;
      }
    }

    return hostname;
  } catch {
    return "Web";
  }
}

function getReviewText(row: any): string {
  return (
    row?.summary ||
    row?.review_text ||
    row?.text ||
    row?.claim ||
    row?.snippet ||
    row?.content_excerpt ||
    row?.supporting_text ||
    row?.title ||
    "—"
  );
}

function getSourceUrl(row: any): string {
  return (
    row?.url ||
    row?.source_url ||
    row?.review_url ||
    ""
  );
}

function getProduct(row: any): string {
  return (
    row?.product ||
    row?.tool ||
    row?.tool_name ||
    "—"
  );
}

function sentimentLabel(
  value: string
): string {
  if (!value) {
    return "Unknown";
  }

  return (
    value.charAt(0).toUpperCase() +
    value.slice(1)
  );
}

/* =========================================================
   PAGE
========================================================= */

export default function SentimentPage() {
  return (
    <ResultGuard>
      {(data) => {
        const allReviews =
          reviewRows(data);

        const reviews =
          classifiedReviewRows(data);

        const positive =
          reviews.filter(
            (row: any) =>
              getSentiment(row) ===
              "positive"
          ).length;

        const neutral =
          reviews.filter(
            (row: any) =>
              getSentiment(row) ===
              "neutral"
          ).length;

        const negative =
          reviews.filter(
            (row: any) =>
              getSentiment(row) ===
              "negative"
          ).length;

        const total =
          reviews.length;

        const positivePct =
          total > 0
            ? (positive / total) *
              100
            : 0;

        const neutralPct =
          total > 0
            ? (neutral / total) *
              100
            : 0;

        const negativePct =
          total > 0
            ? (negative / total) *
              100
            : 0;

        const platforms =
          new Set(
            reviews
              .map((row: any) =>
                getPlatform(row)
              )
              .filter(Boolean)
          );

        return (
          <>
            <header className="page-header">
              <div>
                <span className="eyebrow">
                  05 / SENTIMENT
                </span>

                <h1>
                  Independent review
                  sentiment.
                </h1>

                <p>
                  Sentiment is shown
                  only for retained
                  review or user-opinion
                  evidence that could be
                  classified as
                  positive, neutral or
                  negative. Unknown
                  evidence is not
                  converted into a fake
                  neutral score.
                </p>
              </div>
            </header>

            {reviews.length >
            0 ? (
              <>
                <div className="metric-grid">
                  <Metric
                    label="Classified reviews"
                    value={total}
                  />

                  <Metric
                    label="Positive"
                    value={`${positive} (${positivePct.toFixed(
                      0
                    )}%)`}
                  />

                  <Metric
                    label="Neutral"
                    value={`${neutral} (${neutralPct.toFixed(
                      0
                    )}%)`}
                  />

                  <Metric
                    label="Negative"
                    value={`${negative} (${negativePct.toFixed(
                      0
                    )}%)`}
                  />

                  <Metric
                    label="Platforms"
                    value={
                      platforms.size
                    }
                  />
                </div>

                <section className="panel">
                  <span className="eyebrow">
                    SENTIMENT MIX
                  </span>

                  <h2>
                    {reviews.length}{" "}
                    classified review
                    records
                  </h2>

                  <SentimentPie
                    positive={
                      positive
                    }
                    neutral={
                      neutral
                    }
                    negative={
                      negative
                    }
                  />
                </section>
              </>
            ) : (
              <div className="empty-state">
                <b>
                  No classified review
                  evidence found.
                </b>{" "}
                {allReviews.length
                  ? `${allReviews.length} review-source records were retained, but none could be reliably classified as positive, neutral or negative.`
                  : "No relevant review or user-opinion records were retained for this research run."}
              </div>
            )}

            <section className="panel table-panel">
              <div className="panel-head">
                <div>
                  <span className="eyebrow">
                    REVIEW EVIDENCE
                  </span>

                  <h2>
                    Review-by-review
                    classification
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
                        Platform
                      </th>

                      <th>
                        Review /
                        evidence
                      </th>

                      <th>
                        Sentiment
                      </th>

                      <th>
                        Source
                      </th>
                    </tr>
                  </thead>

                  <tbody>
                    {reviews.length ? (
                      reviews.map(
                        (
                          row: any,
                          index: number
                        ) => {
                          const sentiment =
                            getSentiment(
                              row
                            );

                          const url =
                            getSourceUrl(
                              row
                            );

                          return (
                            <tr
                              key={
                                index
                              }
                            >
                              <td>
                                <b>
                                  {getProduct(
                                    row
                                  )}
                                </b>
                              </td>

                              <td>
                                {getPlatform(
                                  row
                                )}
                              </td>

                              <td>
                                {getReviewText(
                                  row
                                )}
                              </td>

                              <td>
                                <span className="badge">
                                  {sentimentLabel(
                                    sentiment
                                  )}
                                </span>
                              </td>

                              <td>
                                {url ? (
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
                      )
                    ) : (
                      <tr>
                        <td
                          colSpan={5}
                        >
                          No classified
                          review evidence
                          available.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>

            {allReviews.length >
              reviews.length && (
              <section className="panel table-panel">
                <div className="panel-head">
                  <div>
                    <span className="eyebrow">
                      UNCLASSIFIED
                      REVIEW SOURCES
                    </span>

                    <h2>
                      Retained but not
                      scored
                    </h2>

                    <p>
                      These records were
                      retained as possible
                      review or opinion
                      sources but were not
                      assigned a sentiment
                      label, so they do
                      not contribute to
                      the sentiment
                      percentages above.
                    </p>
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
                          Platform
                        </th>

                        <th>
                          Evidence
                        </th>

                        <th>
                          Source
                        </th>
                      </tr>
                    </thead>

                    <tbody>
                      {allReviews
                        .filter(
                          (row: any) =>
                            !getSentiment(
                              row
                            )
                        )
                        .map(
                          (
                            row: any,
                            index: number
                          ) => {
                            const url =
                              getSourceUrl(
                                row
                              );

                            return (
                              <tr
                                key={
                                  index
                                }
                              >
                                <td>
                                  <b>
                                    {getProduct(
                                      row
                                    )}
                                  </b>
                                </td>

                                <td>
                                  {getPlatform(
                                    row
                                  )}
                                </td>

                                <td>
                                  {getReviewText(
                                    row
                                  )}
                                </td>

                                <td>
                                  {url ? (
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