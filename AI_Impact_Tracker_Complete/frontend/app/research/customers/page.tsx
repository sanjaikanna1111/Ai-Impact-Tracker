"use client";

import ResultGuard from "@/components/ResultGuard";
import { customerRows } from "@/lib/data";
import { ExternalLink } from "lucide-react";

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

function getCustomerName(row: any): string {
  return (
    row?.customer ||
    row?.customer_company ||
    row?.company ||
    row?.organisation ||
    row?.organization ||
    "—"
  );
}

function getProductName(row: any): string {
  return (
    row?.product ||
    row?.tool ||
    row?.tool_name ||
    "—"
  );
}

function getSourceUrl(row: any): string {
  return (
    row?.source_url ||
    row?.url ||
    row?.evidence_url ||
    ""
  );
}

function getSourceName(row: any): string {
  const explicit =
    row?.source ||
    row?.source_name ||
    row?.platform ||
    row?.source_title;

  if (explicit) {
    return String(explicit);
  }

  const url = getSourceUrl(row);

  if (!url) {
    return "Source";
  }

  try {
    const hostname =
      new URL(url).hostname
        .replace(/^www\./, "")
        .toLowerCase();

    if (
      hostname === "theirstack.com" ||
      hostname.endsWith(".theirstack.com")
    ) {
      return "TheirStack";
    }

    return hostname;
  } catch {
    return "Source";
  }
}

function isTheirStack(row: any): boolean {
  const source =
    getSourceName(row).toLowerCase();

  const url =
    getSourceUrl(row).toLowerCase();

  return (
    source.includes("theirstack") ||
    url.includes("theirstack.com")
  );
}

function getEvidenceType(row: any): string {
  if (isTheirStack(row)) {
    return "Technographic adoption";
  }

  const type = String(
    row?.record_type ||
      row?.evidence_type ||
      row?.source_type ||
      row?.relationship_type ||
      ""
  ).toLowerCase();

  if (
    type.includes("impact") ||
    numberOrNull(row?.impact_value) !== null
  ) {
    return "Quantified outcome";
  }

  if (
    type.includes("case") ||
    type.includes("customer")
  ) {
    return "Customer evidence";
  }

  if (
    type.includes("adoption") ||
    type.includes("technology")
  ) {
    return "Adoption evidence";
  }

  return "Customer evidence";
}

function getApplicationOrOutcome(
  row: any
): string {
  return (
    row?.outcome ||
    row?.application ||
    row?.description ||
    row?.claim ||
    row?.relationship ||
    row?.use_case ||
    row?.context ||
    "Customer / adoption reference"
  );
}

function formatImpact(row: any): string {
  const value =
    numberOrNull(row?.impact_value);

  if (value === null) {
    return "Qualitative evidence only";
  }

  const unit =
    row?.impact_unit ||
    row?.unit ||
    "";

  const direction =
    row?.direction
      ? ` ${row.direction}`
      : "";

  return `${value}${unit}${direction}`;
}

/* =========================================================
   PAGE
========================================================= */

export default function CustomersPage() {
  return (
    <ResultGuard>
      {(data) => {
        const customers =
          customerRows(data) || [];

        /*
         * A quantified record must contain an
         * actual numeric impact_value.
         */
        const quantified =
          customers.filter(
            (row: any) =>
              numberOrNull(
                row?.impact_value
              ) !== null
          );

        /*
         * Named customer/adoption records.
         */
        const named =
          customers.filter(
            (row: any) => {
              const name =
                getCustomerName(row);

              return (
                name !== "—" &&
                name.trim() !== ""
              );
            }
          );

        /*
         * TheirStack is counted separately
         * because it is technographic/adoption
         * evidence, not automatically proof of
         * business impact.
         */
        const technographic =
          customers.filter(
            (row: any) =>
              isTheirStack(row)
          );

        const qualitative =
          customers.filter(
            (row: any) =>
              numberOrNull(
                row?.impact_value
              ) === null
          );

        return (
          <>
            <header className="page-header">
              <div>
                <span className="eyebrow">
                  06 / CUSTOMER IMPACT
                </span>

                <h1>
                  Who uses it, and what
                  changed?
                </h1>

                <p>
                  Named customer adoption
                  and quantified outcomes
                  are shown separately.
                  Vendor case studies,
                  independent evidence and
                  technographic sources
                  such as TheirStack can
                  support evidence that a
                  company uses a product,
                  but a quantified business
                  outcome is shown only
                  when the source explicitly
                  reports one.
                </p>
              </div>
            </header>

            {!customers.length && (
              <div className="empty-state">
                <b>
                  No verified customer
                  evidence found.
                </b>{" "}
                No retained source safely
                proved a named customer,
                technology-adoption
                relationship or customer
                outcome for the researched
                products.
              </div>
            )}

            {customers.length > 0 && (
              <div className="metric-grid">
                <Metric
                  label="Customer evidence records"
                  value={
                    customers.length
                  }
                />

                <Metric
                  label="Named customer records"
                  value={
                    named.length
                  }
                />

                <Metric
                  label="Technographic records"
                  value={
                    technographic.length
                  }
                />

                <Metric
                  label="Quantified outcomes"
                  value={
                    quantified.length
                  }
                />
              </div>
            )}

            {/* ==============================================
                CUSTOMER / ADOPTION EVIDENCE
            ============================================== */}

            <section className="panel table-panel">
              <div className="panel-head">
                <div>
                  <span className="eyebrow">
                    CUSTOMER ADOPTION
                  </span>

                  <h2>
                    Named customers and
                    technology users
                  </h2>

                  <p>
                    These records support
                    product adoption or a
                    customer relationship.
                    They do not automatically
                    prove financial or
                    operational impact.
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
                        Customer
                      </th>

                      <th>
                        Evidence type
                      </th>

                      <th>
                        Application /
                        evidence
                      </th>

                      <th>
                        Source
                      </th>
                    </tr>
                  </thead>

                  <tbody>
                    {named.length ? (
                      named.map(
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
                                  {getProductName(
                                    row
                                  )}
                                </b>
                              </td>

                              <td>
                                {getCustomerName(
                                  row
                                )}
                              </td>

                              <td>
                                {getEvidenceType(
                                  row
                                )}
                              </td>

                              <td>
                                {getApplicationOrOutcome(
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
                                    {getSourceName(
                                      row
                                    )}{" "}
                                    <ExternalLink
                                      size={
                                        14
                                      }
                                    />
                                  </a>
                                ) : (
                                  getSourceName(
                                    row
                                  )
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
                          No verified named
                          customer or
                          technology-adoption
                          records available.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>

            {/* ==============================================
                QUANTIFIED CUSTOMER IMPACT
            ============================================== */}

            <section className="panel table-panel">
              <div className="panel-head">
                <div>
                  <span className="eyebrow">
                    QUANTIFIED IMPACT
                  </span>

                  <h2>
                    Measured customer
                    outcomes
                  </h2>

                  <p>
                    Only records containing
                    an explicit numeric
                    customer outcome are
                    shown here.
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
                        Customer
                      </th>

                      <th>
                        Outcome
                      </th>

                      <th>
                        Measured impact
                      </th>

                      <th>
                        Source
                      </th>
                    </tr>
                  </thead>

                  <tbody>
                    {quantified.length ? (
                      quantified.map(
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
                                  {getProductName(
                                    row
                                  )}
                                </b>
                              </td>

                              <td>
                                {getCustomerName(
                                  row
                                )}
                              </td>

                              <td>
                                {getApplicationOrOutcome(
                                  row
                                )}
                              </td>

                              <td>
                                <b>
                                  {formatImpact(
                                    row
                                  )}
                                </b>
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
                                    {getSourceName(
                                      row
                                    )}{" "}
                                    <ExternalLink
                                      size={
                                        14
                                      }
                                    />
                                  </a>
                                ) : (
                                  getSourceName(
                                    row
                                  )
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
                          No verified
                          quantified customer
                          outcomes are
                          available. Named
                          customer evidence
                          may still be shown
                          above.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>

            {/* ==============================================
                QUALITATIVE EVIDENCE
            ============================================== */}

            {qualitative.length >
              0 && (
              <section className="panel table-panel">
                <div className="panel-head">
                  <div>
                    <span className="eyebrow">
                      QUALITATIVE EVIDENCE
                    </span>

                    <h2>
                      Adoption without a
                      quantified outcome
                    </h2>

                    <p>
                      These sources support
                      adoption, deployment
                      or customer use but do
                      not provide a reliable
                      numeric impact figure.
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
                          Customer
                        </th>

                        <th>
                          Evidence type
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
                      {qualitative.map(
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
                                  {getProductName(
                                    row
                                  )}
                                </b>
                              </td>

                              <td>
                                {getCustomerName(
                                  row
                                )}
                              </td>

                              <td>
                                {getEvidenceType(
                                  row
                                )}
                              </td>

                              <td>
                                {getApplicationOrOutcome(
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
                                    {getSourceName(
                                      row
                                    )}{" "}
                                    <ExternalLink
                                      size={
                                        14
                                      }
                                    />
                                  </a>
                                ) : (
                                  getSourceName(
                                    row
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