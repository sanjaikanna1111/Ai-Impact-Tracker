"use client";

import ResultGuard from "@/components/ResultGuard";
import { allEvidence } from "@/lib/data";
import { ExternalLink } from "lucide-react";
import { useState } from "react";

/* =========================================================
   HELPERS
========================================================= */

function sourceUrl(row: any): string {
  return (
    row?.source_url ||
    row?.url ||
    row?.evidence_url ||
    ""
  );
}

function productName(row: any): string {
  return (
    row?.product ||
    row?.tool ||
    row?.vendor ||
    "—"
  );
}

function evidenceType(row: any): string {
  return (
    row?.evidence_type ||
    row?.type ||
    row?.category ||
    row?.source_type ||
    "Evidence"
  );
}

function evidenceText(row: any): string {
  return (
    row?.claim ||
    row?.supporting_text ||
    row?.snippet ||
    row?.content_excerpt ||
    row?.description ||
    row?.title ||
    "—"
  );
}

function sourceName(row: any): string {
  const explicit =
    row?.source ||
    row?.source_name ||
    row?.source_title ||
    row?.platform;

  if (explicit) {
    return String(explicit);
  }

  const url = sourceUrl(row);

  if (!url) {
    return "Source";
  }

  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "Source";
  }
}

function qualityLabel(row: any): string {
  const value =
    row?.source_quality ??
    row?.quality ??
    row?.confidence ??
    row?.evidence_quality ??
    null;

  if (
    value === null ||
    value === undefined ||
    value === ""
  ) {
    return "—";
  }

  const numeric = Number(value);

  if (Number.isFinite(numeric)) {
    const pct =
      numeric <= 1
        ? numeric * 100
        : numeric;

    return `${Math.round(pct)}%`;
  }

  return String(value);
}

/* =========================================================
   PAGE
========================================================= */

export default function EvidencePage() {
  const [selectedProduct, setSelectedProduct] =
    useState("all");

  return (
    <ResultGuard>
      {(data) => {
        const allRows = allEvidence(data);

        const products = new Set(
          allRows
            .map((row: any) => productName(row))
            .filter((name: string) => name && name !== "—")
        );

        const rows =
          selectedProduct === "all"
            ? allRows
            : allRows.filter(
                (row: any) =>
                  productName(row) === selectedProduct
              );

        const domains = new Set(
          rows
            .map((row: any) => {
              const url = sourceUrl(row);

              if (!url) {
                return "";
              }

              try {
                return new URL(url).hostname
                  .replace(/^www\./, "")
                  .toLowerCase();
              } catch {
                return "";
              }
            })
            .filter(Boolean)
        );

        const vendorEvidence = rows.filter((row: any) => {
          const type = evidenceType(row).toLowerCase();

          return (
            type.includes("vendor") ||
            type.includes("official")
          );
        }).length;

        const independentEvidence = rows.filter((row: any) => {
          const type = evidenceType(row).toLowerCase();

          return (
            type.includes("independent") ||
            type.includes("review") ||
            type.includes("academic") ||
            type.includes("government") ||
            type.includes("customer") ||
            type.includes("technographic")
          );
        }).length;

        return (
          <>
            <header className="page-header">
              <div>
                <span className="eyebrow">
                  04 / EVIDENCE
                </span>

                <h1>
                  Evidence library.
                </h1>

                <p>
                  Every retained source used to support product validation,
                  recommendation scoring, customer adoption, reviews, pricing or
                  business impact is shown here so the recommendation can be traced
                  back to its evidence.
                </p>
              </div>
            </header>

            {rows.length > 0 ? (
              <div className="metric-grid">
                <Metric
                  label="Retained evidence"
                  value={rows.length}
                />

                <Metric
                  label="Products covered"
                  value={products.size}
                />

                <Metric
                  label="Unique source domains"
                  value={domains.size}
                />

                <Metric
                  label="Vendor / official"
                  value={vendorEvidence}
                />

                <Metric
                  label="Independent / external"
                  value={independentEvidence}
                />
              </div>
            ) : (
              <div className="empty-state">
                <b>No retained evidence records are available.</b>{" "}
                This can happen when source discovery returned no relevant evidence
                or when records failed product/vendor validation.
              </div>
            )}

            <section className="panel table-panel">
              <div className="panel-head">
                <div>
                  <span className="eyebrow">
                    RETAINED SOURCES
                  </span>

                  <h2>
                    {rows.length} evidence records
                  </h2>
                </div>
                <label>
                  Product{" "}
                  <select
                    value={selectedProduct}
                    onChange={(event) =>
                      setSelectedProduct(event.target.value)
                    }
                  >
                    <option value="all">All products</option>
                    {[...products]
                      .sort()
                      .map((product) => (
                        <option key={product} value={product}>
                          {product}
                        </option>
                      ))}
                  </select>
                </label>
              </div>

              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th>Type</th>
                      <th>Claim / evidence</th>
                      <th>Quality</th>
                      <th>Source</th>
                    </tr>
                  </thead>

                  <tbody>
                    {rows.length ? (
                      rows.map((row: any, index: number) => {
                        const url = sourceUrl(row);

                        return (
                          <tr key={index}>
                            <td>
                              <b>
                                {productName(row)}
                              </b>
                            </td>

                            <td>
                              <span className="badge">
                                {evidenceType(row)}
                              </span>
                            </td>

                            <td>
                              {evidenceText(row)}
                            </td>

                            <td>
                              {qualityLabel(row)}
                            </td>

                            <td>
                              {url ? (
                                <a
                                  href={url}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  {sourceName(row)}{" "}
                                  <ExternalLink size={14} />
                                </a>
                              ) : (
                                sourceName(row)
                              )}
                            </td>
                          </tr>
                        );
                      })
                    ) : (
                      <tr>
                        <td colSpan={5}>
                          No retained evidence records available.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
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
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
