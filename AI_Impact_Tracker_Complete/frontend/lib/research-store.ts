"use client";

const KEY = "ai-impact-tracker:last-research";

export function saveResearchResult(data: any) {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(KEY, JSON.stringify(data));
}

export function loadResearchResult(): any | null {
  if (typeof window === "undefined") return null;
  const raw = window.sessionStorage.getItem(KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function clearResearchResult() {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(KEY);
}
