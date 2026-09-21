"use client";

import {
  FormEvent,
  useEffect,
  useMemo,
  useState,
} from "react";

const STORAGE_KEY =
  "ai-impact-tracker:last-research";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ||
  "http://127.0.0.1:8000/api";

type ImpactForm = {
  kpi_name: string;
  baseline: string;
  target: string;
  actual: string;
  direction: "lower" | "higher";
  annual_financial_benefit: string;
  investment: string;
};

type ImpactResult = {
  status?: string;
  message?: string;
  actual_impact_percent?: number | null;
  actual_roi_percent?: number | null;
  actual_payback_months?: number | null;
};

function asNumber(
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

function formatNumber(
  value: number | null,
  decimals = 1
) {
  if (value === null) {
    return "Pending";
  }

  return value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function formatMoney(
  value: number | null
) {
  if (value === null) {
    return "Unavailable";
  }

  return `£${value.toLocaleString(undefined, {
    maximumFractionDigits: 2,
  })}`;
}

function getRootResult(
  payload: any
) {
  if (!payload) {
    return {};
  }

  return payload?.result || payload;
}

function getResearchRunId(
  payload: any
): number | string | null {
  if (!payload) {
    return null;
  }

  return (
    payload?.research_run_id ??
    payload?.id ??
    payload?.research_id ??
    payload?.run_id ??
    payload?.result?.research_run_id ??
    payload?.result?.id ??
    null
  );
}

function getRecommendations(
  payload: any
): any[] {
  const root = getRootResult(payload);

  if (
    Array.isArray(root?.recommendations)
  ) {
    return root.recommendations;
  }

  if (
    Array.isArray(root?.validated_products)
  ) {
    return root.validated_products;
  }

  if (
    Array.isArray(root?.candidates)
  ) {
    return root.candidates;
  }

  const single =
    root?.recommendation ||
    root?.best_recommendation ||
    root?.best;

  return single ? [single] : [];
}

function getProductName(
  recommendation: any
) {
  return (
    recommendation?.product ||
    recommendation?.tool_name ||
    recommendation?.tool ||
    recommendation?.name ||
    "Recommended software"
  );
}

function getValueAssessment(
  recommendation: any
) {
  return (
    recommendation?.value_assessment ||
    recommendation?.value ||
    {}
  );
}

function getRecommendedInvestment(
  recommendation: any
): number | null {
  if (!recommendation) {
    return null;
  }

  const value =
    getValueAssessment(recommendation);

  const explicitInvestment =
    asNumber(
      value?.first_year_investment ??
        value?.first_year_cost ??
        value?.investment ??
        recommendation?.first_year_investment
    );

  if (explicitInvestment !== null) {
    return explicitInvestment;
  }

  const annualSoftwareCost =
    asNumber(
      value?.annual_software_cost ??
        value?.estimated_annual_cost ??
        recommendation?.annual_software_cost
    );

  const implementationCost =
    asNumber(
      value?.implementation_cost ??
        value?.estimated_implementation_cost ??
        recommendation?.implementation_cost
    );

  if (
    annualSoftwareCost === null &&
    implementationCost === null
  ) {
    return null;
  }

  return (
    (annualSoftwareCost || 0) +
    (implementationCost || 0)
  );
}

function getForecastAnnualBenefit(
  recommendation: any
): number | null {
  if (!recommendation) {
    return null;
  }

  const value =
    getValueAssessment(recommendation);

  return asNumber(
    value?.expected_annual_benefit ??
      value?.expected_benefit ??
      value?.annual_benefit ??
      null
  );
}

function getStoredImpact(
  payload: any
) {
  const root = getRootResult(payload);

  return (
    root?.impact_tracking ||
    root?.impact_measurement ||
    null
  );
}

function errorMessage(
  payload: any,
  fallback: string
) {
  if (!payload) {
    return fallback;
  }

  if (typeof payload === "string") {
    return payload;
  }

  if (
    typeof payload?.detail === "string"
  ) {
    return payload.detail;
  }

  if (
    Array.isArray(payload?.detail)
  ) {
    return payload.detail
      .map((item: any) => {
        const field = Array.isArray(
          item?.loc
        )
          ? item.loc[
              item.loc.length - 1
            ]
          : "field";

        return `${field}: ${
          item?.msg ||
          "Invalid value"
        }`;
      })
      .join(" | ");
  }

  return (
    payload?.message ||
    payload?.error ||
    fallback
  );
}

export default function ImpactPage() {
  const [researchData, setResearchData] =
    useState<any>(null);

  const [form, setForm] =
    useState<ImpactForm>({
      kpi_name: "",
      baseline: "",
      target: "",
      actual: "",
      direction: "lower",
      annual_financial_benefit: "",
      investment: "",
    });

  const [result, setResult] =
    useState<ImpactResult | null>(null);

  const [loading, setLoading] =
    useState(false);

  const [error, setError] =
    useState("");

  const [success, setSuccess] =
    useState("");

  useEffect(() => {
    if (
      typeof window === "undefined"
    ) {
      return;
    }

    try {
      const stored =
        sessionStorage.getItem(
          STORAGE_KEY
        );

      if (!stored) {
        return;
      }

      const parsed =
        JSON.parse(stored);

      setResearchData(parsed);

      const storedImpact =
        getStoredImpact(parsed);

      if (storedImpact) {
        setForm((current) => ({
          ...current,

          kpi_name:
            storedImpact?.kpi_name ??
            storedImpact?.kpi ??
            current.kpi_name,

          baseline:
            storedImpact?.baseline !==
              null &&
            storedImpact?.baseline !==
              undefined
              ? String(
                  storedImpact.baseline
                )
              : current.baseline,

          target:
            storedImpact?.target !==
              null &&
            storedImpact?.target !==
              undefined
              ? String(
                  storedImpact.target
                )
              : current.target,

          actual:
            storedImpact?.actual !==
              null &&
            storedImpact?.actual !==
              undefined
              ? String(
                  storedImpact.actual
                )
              : current.actual,

          direction:
            storedImpact?.direction ===
            "higher"
              ? "higher"
              : storedImpact
                    ?.kpi_direction ===
                  "higher"
                ? "higher"
                : current.direction,

          annual_financial_benefit:
            storedImpact
              ?.annual_financial_benefit !==
              null &&
            storedImpact
              ?.annual_financial_benefit !==
              undefined
              ? String(
                  storedImpact
                    .annual_financial_benefit
                )
              : storedImpact
                    ?.financialBenefit !==
                    null &&
                  storedImpact
                    ?.financialBenefit !==
                    undefined
                ? String(
                    storedImpact
                      .financialBenefit
                  )
                : current
                    .annual_financial_benefit,

          investment:
            storedImpact?.investment !==
              null &&
            storedImpact?.investment !==
              undefined
              ? String(
                  storedImpact.investment
                )
              : current.investment,
        }));

        setResult({
          actual_impact_percent:
            asNumber(
              storedImpact
                ?.actual_impact_percent
            ),

          actual_roi_percent:
            asNumber(
              storedImpact
                ?.actual_roi_percent
            ),

          actual_payback_months:
            asNumber(
              storedImpact
                ?.actual_payback_months
            ),
        });
      }
    } catch (err) {
      console.error(
        "Could not read research result:",
        err
      );
    }
  }, []);

  const researchRunId =
    useMemo(
      () =>
        getResearchRunId(
          researchData
        ),
      [researchData]
    );

  const recommendations =
    useMemo(
      () =>
        getRecommendations(
          researchData
        ),
      [researchData]
    );

  const recommendedProduct =
    recommendations[0] || null;

  const recommendedProductName =
    getProductName(
      recommendedProduct
    );

  const forecastInvestment =
    useMemo(
      () =>
        getRecommendedInvestment(
          recommendedProduct
        ),
      [recommendedProduct]
    );

  const forecastAnnualBenefit =
    useMemo(
      () =>
        getForecastAnnualBenefit(
          recommendedProduct
        ),
      [recommendedProduct]
    );

  const baseline =
    asNumber(form.baseline);

  const target =
    asNumber(form.target);

  const actual =
    asNumber(form.actual);

  const annualFinancialBenefit =
    asNumber(
      form.annual_financial_benefit
    );

  const actualInvestment =
    asNumber(form.investment);

  const localImpactPercent =
    useMemo(() => {
      if (
        baseline === null ||
        actual === null ||
        baseline === 0
      ) {
        return null;
      }

      if (
        form.direction === "higher"
      ) {
        return (
          ((actual - baseline) /
            baseline) *
          100
        );
      }

      return (
        ((baseline - actual) /
          baseline) *
        100
      );
    }, [
      baseline,
      actual,
      form.direction,
    ]);

  const targetImprovement =
    useMemo(() => {
      if (
        baseline === null ||
        target === null ||
        baseline === 0
      ) {
        return null;
      }

      if (
        form.direction === "higher"
      ) {
        return (
          ((target - baseline) /
            baseline) *
          100
        );
      }

      return (
        ((baseline - target) /
          baseline) *
        100
      );
    }, [
      baseline,
      target,
      form.direction,
    ]);

  const targetVariance =
    useMemo(() => {
      if (
        localImpactPercent === null ||
        targetImprovement === null
      ) {
        return null;
      }

      return (
        localImpactPercent -
        targetImprovement
      );
    }, [
      localImpactPercent,
      targetImprovement,
    ]);

  const localActualROI =
    useMemo(() => {
      if (
        actualInvestment === null ||
        annualFinancialBenefit ===
          null ||
        actualInvestment <= 0
      ) {
        return null;
      }

      return (
        ((annualFinancialBenefit -
          actualInvestment) /
          actualInvestment) *
        100
      );
    }, [
      actualInvestment,
      annualFinancialBenefit,
    ]);

  const localPayback =
    useMemo(() => {
      if (
        actualInvestment === null ||
        annualFinancialBenefit ===
          null ||
        actualInvestment <= 0 ||
        annualFinancialBenefit <= 0
      ) {
        return null;
      }

      return (
        actualInvestment /
        (annualFinancialBenefit / 12)
      );
    }, [
      actualInvestment,
      annualFinancialBenefit,
    ]);

  const operationalMeasured =
    baseline !== null && baseline > 0 &&
    target !== null && actual !== null;

  const financialMeasured =
    annualFinancialBenefit !== null &&
    actualInvestment !== null && actualInvestment > 0;

  const displayedImpact = operationalMeasured
    ? (result?.actual_impact_percent ?? localImpactPercent)
    : null;

  const displayedROI = financialMeasured
    ? (result?.actual_roi_percent ?? localActualROI)
    : null;

  const displayedPayback = financialMeasured
    ? (result?.actual_payback_months ?? localPayback)
    : null;

  async function saveMeasurement(
    event: FormEvent
  ) {
    event.preventDefault();

    setError("");
    setSuccess("");

    if (!researchRunId) {
      setError(
        "No research run ID is available. Run a new research assessment first."
      );
      return;
    }

    if (!form.kpi_name.trim()) {
      setError(
        "Enter the KPI name."
      );
      return;
    }

    if (baseline === null) {
      setError(
        "Enter the baseline KPI value."
      );
      return;
    }

    if (target === null) {
      setError(
        "Enter the target KPI value."
      );
      return;
    }

    if (actual === null) {
      setError(
        "Enter the actual KPI value."
      );
      return;
    }

    if (
      annualFinancialBenefit === null
    ) {
      setError(
        "Enter the realised annual financial benefit."
      );
      return;
    }

    if (
      actualInvestment === null
    ) {
      setError(
        "Enter the actual investment."
      );
      return;
    }

    const payload = {
      research_run_id:
        Number(researchRunId),

      kpi_name:
        form.kpi_name.trim(),

      baseline,

      target,

      actual,

      direction:
        form.direction,

      annual_financial_benefit:
        annualFinancialBenefit,

      investment:
        actualInvestment,
    };

    setLoading(true);

    try {
      const response = await fetch(
        `${API_BASE}/impact-measurement`,
        {
          method: "POST",

          headers: {
            "Content-Type":
              "application/json",
          },

          body: JSON.stringify(
            payload
          ),
        }
      );

      const responsePayload =
        await response
          .json()
          .catch(() => ({}));

      if (!response.ok) {
        throw new Error(
          errorMessage(
            responsePayload,
            `Failed to save measurement (${response.status}).`
          )
        );
      }

      const savedResult: ImpactResult =
        responsePayload;

      setResult(savedResult);

      setSuccess(
        savedResult?.message ||
          "Actual measurement saved successfully."
      );

      /*
       * Update the session copy as well.
       * This keeps the Impact Tracker page
       * consistent when the user navigates
       * away and comes back.
       */
      if (
        typeof window !==
        "undefined"
      ) {
        try {
          const stored =
            sessionStorage.getItem(
              STORAGE_KEY
            );

          if (stored) {
            const parsed =
              JSON.parse(stored);

            if (parsed?.result) {
              parsed.result
                .impact_tracking = {
                ...payload,

                actual_impact_percent:
                  savedResult
                    ?.actual_impact_percent ??
                  displayedImpact,

                actual_roi_percent:
                  savedResult
                    ?.actual_roi_percent ??
                  displayedROI,

                actual_payback_months:
                  savedResult
                    ?.actual_payback_months ??
                  displayedPayback,
              };
            } else {
              parsed.impact_tracking = {
                ...payload,

                actual_impact_percent:
                  savedResult
                    ?.actual_impact_percent ??
                  displayedImpact,

                actual_roi_percent:
                  savedResult
                    ?.actual_roi_percent ??
                  displayedROI,

                actual_payback_months:
                  savedResult
                    ?.actual_payback_months ??
                  displayedPayback,
              };
            }

            sessionStorage.setItem(
              STORAGE_KEY,
              JSON.stringify(
                parsed
              )
            );

            setResearchData(
              parsed
            );
          }
        } catch (
          storageError
        ) {
          console.error(
            "Could not update stored impact measurement:",
            storageError
          );
        }
      }
    } catch (err: any) {
      setError(
        err?.message ||
          "Failed to save actual measurement."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main>
      <div className="intro">
        <span>
          09 / IMPACT TRACKER
        </span>

        <h1>
          Measure realised value.
        </h1>

        <p>
          Post-implementation
          measurements are deliberately
          separate from the
          pre-implementation forecast.
          Record the actual operational
          KPI result and realised
          financial value after the
          selected software has been
          implemented.
        </p>
      </div>

      {!researchRunId && (
        <div className="error">
          No completed research run is
          currently loaded. Run research
          first before recording an
          actual measurement.
        </div>
      )}

      {error && (
        <div className="error">
          {error}
        </div>
      )}

      {success && (
        <div
          className="status green"
          style={{
            marginBottom: 18,
            padding: 12,
            borderRadius: 8,
          }}
        >
          {success}
        </div>
      )}

      <div
        className="panel"
        style={{
          marginBottom: 20,
        }}
      >
        <div className="panelhead">
          <div>
            <span>
              IMPLEMENTATION CONTEXT
            </span>

            <h2>
              Measurement subject
            </h2>
          </div>
        </div>

        <div className="assessment">
          <div>
            <strong>
              Recommended software
            </strong>

            <span>
              {recommendedProduct
                ? recommendedProductName
                : "Unavailable"}
            </span>
          </div>

          <div>
            <strong>
              Research run
            </strong>

            <span>
              {researchRunId ??
                "Unavailable"}
            </span>
          </div>

          <div>
            <strong>
              Forecast investment
            </strong>

            <span>
              {formatMoney(
                forecastInvestment
              )}
            </span>
          </div>

          <div>
            <strong>
              Forecast annual benefit
            </strong>

            <span>
              {formatMoney(
                forecastAnnualBenefit
              )}
            </span>
          </div>
        </div>
      </div>

      <form
        onSubmit={saveMeasurement}
      >
        <div
          className="panel impactInputs"
          style={{
            marginBottom: 20,
          }}
        >
          <div className="panelhead">
            <div>
              <span>
                ACTUAL MEASUREMENT
              </span>

              <h2>
                Record the outcome
              </h2>
            </div>
          </div>

          <div
            className="form-grid"
            style={{
              marginBottom: 18,
            }}
          >
            <label>
              KPI name

              <input
                type="text"
                placeholder="e.g. Average checkout waiting time"
                value={
                  form.kpi_name
                }
                onChange={(e) =>
                  setForm({
                    ...form,
                    kpi_name:
                      e.target
                        .value,
                  })
                }
              />

              <small>
                Name the operational
                measure being tracked.
              </small>
            </label>

            <label>
              KPI direction

              <select
                value={
                  form.direction
                }
                onChange={(e) =>
                  setForm({
                    ...form,
                    direction:
                      e.target
                        .value as
                        | "lower"
                        | "higher",
                  })
                }
              >
                <option value="lower">
                  Lower is better
                </option>

                <option value="higher">
                  Higher is better
                </option>
              </select>

              <small>
                Choose how improvement
                should be interpreted.
              </small>
            </label>
          </div>

          <div className="threeInputs">
            <label>
              Baseline KPI

              <input
                type="number"
                step="any"
                placeholder="Current baseline"
                value={
                  form.baseline
                }
                onChange={(e) =>
                  setForm({
                    ...form,
                    baseline:
                      e.target
                        .value,
                  })
                }
              />

              <small>
                KPI value before
                implementation.
              </small>
            </label>

            <label>
              Target KPI

              <input
                type="number"
                step="any"
                placeholder="Agreed target"
                value={
                  form.target
                }
                onChange={(e) =>
                  setForm({
                    ...form,
                    target:
                      e.target
                        .value,
                  })
                }
              />

              <small>
                Management target agreed
                before measurement.
              </small>
            </label>

            <label>
              Actual KPI

              <input
                type="number"
                step="any"
                placeholder="Measured result"
                value={
                  form.actual
                }
                onChange={(e) =>
                  setForm({
                    ...form,
                    actual:
                      e.target
                        .value,
                  })
                }
              />

              <small>
                Post-implementation KPI
                measurement.
              </small>
            </label>
          </div>
        </div>

        <div
          className="panel impactInputs"
          style={{
            marginBottom: 20,
          }}
        >
          <div className="panelhead">
            <div>
              <span>
                FINANCIAL REALISATION
              </span>

              <h2>
                Record realised
                financial value
              </h2>
            </div>
          </div>

          <div className="form-grid">
            <label>
              Realised annual financial
              benefit (£)

              <input
                type="number"
                min="0"
                step="any"
                placeholder="e.g. 125000"
                value={
                  form
                    .annual_financial_benefit
                }
                onChange={(e) =>
                  setForm({
                    ...form,
                    annual_financial_benefit:
                      e.target
                        .value,
                  })
                }
              />

              <small>
                Enter the measured annual
                financial benefit, not the
                operational KPI.
              </small>
            </label>

            <label>
              Actual investment (£)

              <input
                type="number"
                min="0"
                step="any"
                placeholder="Actual first-year investment"
                value={
                  form.investment
                }
                onChange={(e) =>
                  setForm({
                    ...form,
                    investment:
                      e.target
                        .value,
                  })
                }
              />

              <small>
                Use actual software plus
                implementation cost.
                Do not use an estimate:
                realised ROI requires an
                explicitly entered actual cost.
              </small>
            </label>
          </div>
        </div>

        <div
          className="panel"
          style={{
            marginBottom: 20,
          }}
        >
          <div className="panelhead">
            <div>
              <span>
                REALISED PERFORMANCE
              </span>

              <h2>
                Current impact assessment
              </h2>
            </div>
          </div>

          <div className="assessment">
            <div>
              <strong>
                Target improvement
              </strong>

              <span>
                {targetImprovement !==
                null
                  ? `${formatNumber(
                      targetImprovement
                    )}%`
                  : "Unavailable"}
              </span>
            </div>

            <div>
              <strong>
                Actual improvement
              </strong>

              <span>
                {displayedImpact !==
                null
                  ? `${formatNumber(
                      displayedImpact
                    )}%`
                  : "Unavailable"}
              </span>
            </div>

            <div>
              <strong>
                Actual ROI
              </strong>

              <span>
                {displayedROI !==
                null
                  ? `${formatNumber(
                      displayedROI
                    )}%`
                  : "Unavailable"}
              </span>
            </div>

            <div>
              <strong>
                Actual payback
              </strong>

              <span>
                {displayedPayback !==
                null
                  ? `${formatNumber(
                      displayedPayback
                    )} months`
                  : "Unavailable"}
              </span>
            </div>
          </div>

          {targetVariance !== null && (
            <div
              style={{
                marginTop: 16,
              }}
              className={
                targetVariance >= 0
                  ? "status green"
                  : "status amber"
              }
            >
              {Math.abs(
                targetVariance
              ).toFixed(1)}{" "}
              percentage points{" "}
              {targetVariance >= 0
                ? "above"
                : "below"}{" "}
              target
            </div>
          )}
          {targetVariance === null && (
            <div className="status amber" style={{ marginTop: 16 }}>
              Impact health: NOT MEASURED. Enter a positive baseline, target and actual KPI to assess progress.
            </div>
          )}
        </div>

        <div
          className="panel"
          style={{
            marginBottom: 20,
          }}
        >
          <div className="panelhead">
            <div>
              <span>
                IMPACT JOURNEY
              </span>

              <h2>
                Implementation timeline
              </h2>
            </div>
          </div>

          <div className="assessment">
            <div>
              <strong>
                01 · Baseline
              </strong>

              <span>
                Record current KPI
              </span>
            </div>

            <div>
              <strong>
                02 · Target
              </strong>

              <span>
                Define agreed outcome
              </span>
            </div>

            <div>
              <strong>
                03 · Implementation
              </strong>

              <span>
                Deploy selected software
              </span>
            </div>

            <div>
              <strong>
                04 · 30 days
              </strong>

              <span>
                First measurement
              </span>
            </div>

            <div>
              <strong>
                05 · 60 days
              </strong>

              <span>
                Validate trend
              </span>
            </div>

            <div>
              <strong>
                06 · 90 days
              </strong>

              <span>
                Assess realised value
              </span>
            </div>
          </div>
        </div>

        <button
          type="submit"
          disabled={
            loading ||
            !researchRunId
          }
          style={{
            minHeight: 46,
            padding:
              "0 22px",
            fontWeight: 700,
            cursor:
              loading ||
              !researchRunId
                ? "not-allowed"
                : "pointer",
            marginBottom: 24,
          }}
        >
          {loading
            ? "Saving measurement..."
            : "Save Actual Measurement"}
        </button>
      </form>
    </main>
  );
}
