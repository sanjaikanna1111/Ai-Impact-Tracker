"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { loadResearchResult } from "@/lib/research-store";

export default function ResultGuard({
  children,
}: {
  children: (data: any) => React.ReactNode;
}) {
  const [data, setData] = useState<any | undefined>(undefined);

  useEffect(() => {
    setData(loadResearchResult());
  }, []);

  if (data === undefined) {
    return <div className="empty-state">Loading research workspace…</div>;
  }

  if (!data) {
    return (
      <div className="empty-state">
        <span>NO ACTIVE RESEARCH</span>
        <h2>Run research first</h2>
        <p>The result pages use the latest evidence-based research run.</p>
        <Link className="button primary" href="/research">Start research</Link>
      </div>
    );
  }

  return <>{children(data)}</>;
}
