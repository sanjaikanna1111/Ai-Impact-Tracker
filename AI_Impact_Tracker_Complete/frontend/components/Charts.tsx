"use client";

function clamp(value: number) {
  return Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
}

export function HorizontalBars({
  rows,
  suffix = "",
  max,
}: {
  rows: { label: string; value: number; note?: string }[];
  suffix?: string;
  max?: number;
}) {
  const ceiling =
    max ?? Math.max(1, ...rows.map((row) => Number(row.value) || 0));

  return (
    <div className="hbars">
      {rows.map((row) => {
        const value = Number(row.value) || 0;
        const width = Math.max(0, Math.min(100, (value / ceiling) * 100));
        return (
          <div className="hbar-row" key={row.label}>
            <div className="hbar-label">
              <span>{row.label}</span>
              <strong>{Number.isFinite(Number(row.value)) ? `${value.toFixed(1)}${suffix}` : "—"}</strong>
            </div>
            <div className="hbar-track">
              <div className="hbar-fill" style={{ width: `${width}%` }} />
            </div>
            {row.note ? <small>{row.note}</small> : null}
          </div>
        );
      })}
    </div>
  );
}

export function ScoreBars({
  rows,
}: {
  rows: { label: string; value: number }[];
}) {
  return (
    <HorizontalBars
      rows={rows.map((row) => ({ ...row, value: clamp(row.value) }))}
      max={100}
    />
  );
}

export function Donut({
  value,
  label,
}: {
  value: number;
  label: string;
}) {
  const v = clamp(value);
  const radius = 44;
  const circumference = 2 * Math.PI * radius;
  const dash = circumference * (v / 100);

  return (
    <div className="donut-wrap">
      <svg viewBox="0 0 120 120" className="donut" role="img" aria-label={`${label}: ${v.toFixed(0)}%`}>
        <circle cx="60" cy="60" r={radius} className="donut-bg" />
        <circle
          cx="60"
          cy="60"
          r={radius}
          className="donut-value"
          strokeDasharray={`${dash} ${circumference - dash}`}
        />
      </svg>
      <div className="donut-center">
        <strong>{v.toFixed(0)}%</strong>
        <span>{label}</span>
      </div>
    </div>
  );
}

export function GroupedColumns({
  rows,
  fields,
}: {
  rows: Array<{ label: string; [key: string]: string | number | null | undefined }>;
  fields: { key: string; label: string }[];
}) {
  const values = rows.flatMap((row) =>
    fields.map((field) => Number(row[field.key]) || 0)
  );
  const max = Math.max(1, ...values);

  return (
    <div className="column-chart">
      <div className="column-groups">
        {rows.map((row, index) => (
          <div className="column-group" key={`${row.label}-${index}`}>
            <div className="column-bars">
              {fields.map((field, fieldIndex) => {
                const value = Number(row[field.key]) || 0;
                return (
                  <div
                    key={field.key}
                    className={`column column-${fieldIndex + 1}`}
                    title={`${field.label}: ${value}`}
                    style={{ height: `${value <= 0 ? 2 : Math.max(4, (value / max) * 100)}%` }}
                  />
                );
              })}
            </div>
            <span>{row.label}</span>
          </div>
        ))}
      </div>
      <div className="chart-legend">
        {fields.map((field, index) => (
          <span key={field.key} className={`legend-${index + 1}`}>
            {field.label}
          </span>
        ))}
      </div>
    </div>
  );
}

export function SentimentPie({
  positive,
  neutral,
  negative,
}: {
  positive: number;
  neutral: number;
  negative: number;
}) {
  const total = positive + neutral + negative;
  if (total <= 0) return null;

  const p = (positive / total) * 100;
  const n = (neutral / total) * 100;
  const negStart = p + n;

  return (
    <div className="sentiment-pie-wrap">
      <div
        className="sentiment-pie"
        role="img"
        aria-label={`Sentiment distribution: ${positive} positive, ${neutral} neutral, ${negative} negative`}
        style={{
          background: `conic-gradient(#16a34a 0 ${p}%, #94a3b8 ${p}% ${negStart}%, #dc2626 ${negStart}% 100%)`,
        }}
      >
        <div className="sentiment-pie-center"><strong>{total}</strong><span>classified</span></div>
      </div>
      <div className="sentiment-legend">
        <span><i className="sentiment-dot positive" />Positive <b>{positive}</b></span>
        <span><i className="sentiment-dot neutral" />Neutral <b>{neutral}</b></span>
        <span><i className="sentiment-dot negative" />Negative <b>{negative}</b></span>
      </div>
    </div>
  );
}
