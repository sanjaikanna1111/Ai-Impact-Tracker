"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Building2,
  BriefcaseBusiness,
  Target,
  PoundSterling,
  Users,
  Globe2,
  Play,
  Loader2,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";

import { getResearch, postResearch } from "@/lib/api";

const STORAGE_KEY = "ai-impact-tracker:last-research";

type ResearchForm = {
  company_name: string;
  company_country: string;
  sector: string;
  business_goal: string;
  budget: string;
  company_size: "Small" | "Medium" | "Large" | "Enterprise";
  employees: string;
  current_annual_process_cost: string;
};

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function saveResearchResult(payload: any) {
  if (typeof window === "undefined") return;

  sessionStorage.setItem(
    STORAGE_KEY,
    JSON.stringify(payload)
  );
}

function extractRunId(payload: any): number | string | null {
  return (
    payload?.id ??
    payload?.research_run_id ??
    payload?.research_id ??
    payload?.run_id ??
    null
  );
}

function extractStatus(payload: any): string {
  return String(
    payload?.status ??
      payload?.result?.status ??
      ""
  ).toLowerCase();
}

function hasResearchResult(payload: any): boolean {
  if (!payload) return false;

  if (payload?.result) {
    const result = payload.result;

    if (
      Array.isArray(result?.recommendations) ||
      Array.isArray(result?.validated_products) ||
      result?.business_problem ||
      result?.data_quality
    ) {
      return true;
    }
  }

  if (
    Array.isArray(payload?.recommendations) ||
    Array.isArray(payload?.validated_products) ||
    payload?.business_problem ||
    payload?.data_quality
  ) {
    return true;
  }

  return false;
}

export default function ResearchPage() {
  const router = useRouter();

  const [form, setForm] = useState<ResearchForm>({
    company_name: "",
    company_country: "United Kingdom",
    sector: "Retail",
    business_goal: "Reduce customer checkout waiting time",
    budget: "100000",
    company_size: "Large",
    employees: "5000",
    current_annual_process_cost: "",
  });

  const [loading, setLoading] = useState(false);
  const [stage, setStage] = useState("");
  const [error, setError] = useState("");

  function updateField<K extends keyof ResearchForm>(
    key: K,
    value: ResearchForm[K]
  ) {
    setForm((current) => ({
      ...current,
      [key]: value,
    }));
  }

  async function pollResearch(runId: number | string) {
    const maxAttempts = 240;

    for (
      let attempt = 0;
      attempt < maxAttempts;
      attempt += 1
    ) {
      const response = await getResearch(runId);

      const status = extractStatus(response);

      if (
        status === "failed" ||
        status === "error"
      ) {
        throw new Error(
          response?.error ||
            response?.detail ||
            response?.result?.error ||
            "Research failed."
        );
      }

      if (
        status === "completed" ||
        status === "complete" ||
        status === "partial" ||
        hasResearchResult(response)
      ) {
        return response;
      }

      setStage(
        `Research is running... ${
          attempt > 0
            ? `(${Math.floor((attempt * 3) / 60)} min)`
            : ""
        }`
      );

      await sleep(3000);
    }

    throw new Error(
      "Research is still running after the polling window. Check the backend terminal for its current stage."
    );
  }

  async function handleSubmit(
    event: FormEvent<HTMLFormElement>
  ) {
    event.preventDefault();

    if (loading) return;

    setError("");

    const budget = Number(form.budget);
    const employees = Number(form.employees);

    const currentAnnualProcessCost =
      form.current_annual_process_cost.trim() === ""
        ? null
        : Number(form.current_annual_process_cost);

    if (!form.sector.trim()) {
      setError("Sector is required.");
      return;
    }

    if (form.business_goal.trim().length < 5) {
      setError(
        "Please enter a clearer business goal."
      );
      return;
    }

    if (
      !Number.isFinite(budget) ||
      budget <= 0
    ) {
      setError(
        "Budget must be greater than zero."
      );
      return;
    }

    if (
      !Number.isFinite(employees) ||
      employees <= 0
    ) {
      setError(
        "Employee count must be greater than zero."
      );
      return;
    }

    if (
      currentAnnualProcessCost !== null &&
      (
        !Number.isFinite(currentAnnualProcessCost) ||
        currentAnnualProcessCost <= 0
      )
    ) {
      setError(
        "Current annual process cost must be greater than zero when supplied."
      );
      return;
    }

    const payload = {
      sector: form.sector.trim(),
      business_goal: form.business_goal.trim(),
      budget,
      company_size: form.company_size,
      employees,

      company_name:
        form.company_name.trim() || null,

      company_country:
        form.company_country.trim() || null,

      current_annual_process_cost:
        currentAnnualProcessCost,
    };

    try {
      setLoading(true);
      setStage(
        "Starting evidence-based research..."
      );

      sessionStorage.removeItem(STORAGE_KEY);

      const started =
        await postResearch(payload);

      const runId = extractRunId(started);

      let completed = started;

      if (!hasResearchResult(started)) {
        if (runId === null) {
          throw new Error(
            "The backend accepted the request but did not return a research-run ID or result."
          );
        }

        setStage(
          "Research started. Discovering and validating products..."
        );

        completed =
          await pollResearch(runId);
      }

      saveResearchResult(completed);

      setStage("Research complete.");

      router.push("/research/overview");
    } catch (err: any) {
      console.error(
        "Research request failed:",
        err
      );

      setError(
        err?.message ||
          "Research could not be completed."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <header className="page-header">
        <div>
          <span className="eyebrow">
            01 / RESEARCH
          </span>

          <h1>
            Build the evidence base.
          </h1>

          <p>
            Define the business problem,
            discover relevant AI and software
            products, validate the evidence,
            and create an evidence-based
            recommendation.
          </p>
        </div>
      </header>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr)",
          gap: 24,
        }}
      >
        <section className="panel">
          <div className="panel-head">
            <div>
              <span className="eyebrow">
                RESEARCH INPUT
              </span>

              <h2>
                Business context
              </h2>

              <p>
                Fields marked as required are
                validated against the backend
                research schema.
              </p>
            </div>
          </div>

          <form
            onSubmit={handleSubmit}
            style={{
              display: "grid",
              gap: 20,
            }}
          >
            <div
              style={{
                display: "grid",
                gridTemplateColumns:
                  "repeat(auto-fit, minmax(240px, 1fr))",
                gap: 16,
              }}
            >
              <label
                style={{
                  display: "grid",
                  gap: 8,
                }}
              >
                <span
                  style={{
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                    fontWeight: 600,
                  }}
                >
                  <Building2 size={16} />
                  Company name
                </span>

                <input
                  type="text"
                  value={form.company_name}
                  onChange={(event) =>
                    updateField(
                      "company_name",
                      event.target.value
                    )
                  }
                  placeholder="e.g. Tesco"
                />
              </label>

              <label
                style={{
                  display: "grid",
                  gap: 8,
                }}
              >
                <span
                  style={{
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                    fontWeight: 600,
                  }}
                >
                  <Globe2 size={16} />
                  Company country
                </span>

                <input
                  type="text"
                  value={form.company_country}
                  onChange={(event) =>
                    updateField(
                      "company_country",
                      event.target.value
                    )
                  }
                  placeholder="United Kingdom"
                />
              </label>
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns:
                  "repeat(auto-fit, minmax(240px, 1fr))",
                gap: 16,
              }}
            >
              <label
                style={{
                  display: "grid",
                  gap: 8,
                }}
              >
                <span
                  style={{
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                    fontWeight: 600,
                  }}
                >
                  <BriefcaseBusiness size={16} />
                  Sector *
                </span>

                <input
                  required
                  minLength={2}
                  maxLength={120}
                  type="text"
                  value={form.sector}
                  onChange={(event) =>
                    updateField(
                      "sector",
                      event.target.value
                    )
                  }
                  placeholder="Retail"
                />
              </label>

              <label
                style={{
                  display: "grid",
                  gap: 8,
                }}
              >
                <span
                  style={{
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                    fontWeight: 600,
                  }}
                >
                  <Users size={16} />
                  Company size *
                </span>

                <select
                  required
                  value={form.company_size}
                  onChange={(event) =>
                    updateField(
                      "company_size",
                      event.target
                        .value as ResearchForm["company_size"]
                    )
                  }
                >
                  <option value="Small">
                    Small
                  </option>

                  <option value="Medium">
                    Medium
                  </option>

                  <option value="Large">
                    Large
                  </option>

                  <option value="Enterprise">
                    Enterprise
                  </option>
                </select>
              </label>
            </div>

            <label
              style={{
                display: "grid",
                gap: 8,
              }}
            >
              <span
                style={{
                  display: "flex",
                  gap: 8,
                  alignItems: "center",
                  fontWeight: 600,
                }}
              >
                <Target size={16} />
                Business goal *
              </span>

              <textarea
                required
                minLength={5}
                maxLength={1000}
                rows={4}
                value={form.business_goal}
                onChange={(event) =>
                  updateField(
                    "business_goal",
                    event.target.value
                  )
                }
                placeholder="Describe the measurable business problem you want AI or software to address."
              />
            </label>

            <div
              style={{
                display: "grid",
                gridTemplateColumns:
                  "repeat(auto-fit, minmax(220px, 1fr))",
                gap: 16,
              }}
            >
              <label
                style={{
                  display: "grid",
                  gap: 8,
                }}
              >
                <span
                  style={{
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                    fontWeight: 600,
                  }}
                >
                  <PoundSterling size={16} />
                  AI adoption budget (£) *
                </span>

                <input
                  required
                  type="number"
                  min="1"
                  step="1"
                  value={form.budget}
                  onChange={(event) =>
                    updateField(
                      "budget",
                      event.target.value
                    )
                  }
                />
              </label>

              <label
                style={{
                  display: "grid",
                  gap: 8,
                }}
              >
                <span
                  style={{
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                    fontWeight: 600,
                  }}
                >
                  <Users size={16} />
                  Employees *
                </span>

                <input
                  required
                  type="number"
                  min="1"
                  step="1"
                  value={form.employees}
                  onChange={(event) =>
                    updateField(
                      "employees",
                      event.target.value
                    )
                  }
                />
              </label>

              <label
                style={{
                  display: "grid",
                  gap: 8,
                }}
              >
                <span
                  style={{
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                    fontWeight: 600,
                  }}
                >
                  <PoundSterling size={16} />
                  Current annual process cost (£)
                </span>

                <input
                  type="number"
                  min="1"
                  step="1"
                  value={
                    form.current_annual_process_cost
                  }
                  onChange={(event) =>
                    updateField(
                      "current_annual_process_cost",
                      event.target.value
                    )
                  }
                  placeholder="Optional"
                />
              </label>
            </div>

            {error && (
              <div
                style={{
                  display: "flex",
                  gap: 10,
                  alignItems: "flex-start",
                  padding: 14,
                  border:
                    "1px solid rgba(220, 38, 38, 0.28)",
                  borderRadius: 12,
                }}
              >
                <AlertCircle
                  size={18}
                  style={{
                    marginTop: 2,
                    flexShrink: 0,
                  }}
                />

                <div>
                  <strong>
                    Research failed
                  </strong>
                  <div>{error}</div>
                </div>
              </div>
            )}

            {loading && (
              <div
                style={{
                  display: "flex",
                  gap: 10,
                  alignItems: "center",
                  padding: 14,
                  borderRadius: 12,
                }}
              >
                <Loader2
                  size={18}
                  className="spin"
                />

                <span>
                  {stage ||
                    "Research is running..."}
                </span>
              </div>
            )}

            {!loading &&
              stage === "Research complete." && (
                <div
                  style={{
                    display: "flex",
                    gap: 10,
                    alignItems: "center",
                    padding: 14,
                    borderRadius: 12,
                  }}
                >
                  <CheckCircle2 size={18} />

                  <span>
                    Research complete.
                  </span>
                </div>
              )}

            <button
              type="submit"
              disabled={loading}
              className="primary-button"
              style={{
                display: "inline-flex",
                justifyContent: "center",
                alignItems: "center",
                gap: 10,
                minHeight: 48,
                cursor: loading
                  ? "not-allowed"
                  : "pointer",
              }}
            >
              {loading ? (
                <>
                  <Loader2
                    size={18}
                    className="spin"
                  />
                  Researching...
                </>
              ) : (
                <>
                  <Play size={18} />
                  Start research
                </>
              )}
            </button>
          </form>
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <span className="eyebrow">
                RESEARCH PIPELINE
              </span>

              <h2>
                What happens next
              </h2>
            </div>
          </div>

          <div
            style={{
              display: "grid",
              gap: 12,
            }}
          >
            <div>
              <b>01</b>{" "}
              Understand the business problem
              and required capabilities.
            </div>

            <div>
              <b>02</b>{" "}
              Discover and validate commercial
              products.
            </div>

            <div>
              <b>03</b>{" "}
              Collect product-specific evidence
              and independent review evidence.
            </div>

            <div>
              <b>04</b>{" "}
              Analyse sentiment, customers,
              quantified outcomes and pricing.
            </div>

            <div>
              <b>05</b>{" "}
              Calculate deterministic fit,
              value, ROI and payback where
              evidence supports them.
            </div>

            <div>
              <b>06</b>{" "}
              Rank eligible products and retain
              source traceability.
            </div>
          </div>
        </section>
      </div>
    </>
  );
}