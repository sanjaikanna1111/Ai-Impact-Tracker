const API_BASE = (
  process.env.NEXT_PUBLIC_API_BASE ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8000/api"
).replace(/\/+$/, "");

function errorMessage(
  payload: any,
  status: number
): string {
  if (!payload) {
    return `Request failed (${status})`;
  }

  if (
    typeof payload.detail === "string"
  ) {
    return payload.detail;
  }

  if (Array.isArray(payload.detail)) {
    return payload.detail
      .map((item: any) => {
        const location =
          Array.isArray(item?.loc)
            ? item.loc
                .filter(
                  (part: any) =>
                    part !== "body"
                )
                .join(".")
            : "";

        const message =
          item?.msg ||
          item?.message ||
          "Invalid value";

        return location
          ? `${location}: ${message}`
          : message;
      })
      .join(" | ");
  }

  if (
    typeof payload.message ===
    "string"
  ) {
    return payload.message;
  }

  if (
    typeof payload.error === "string"
  ) {
    return payload.error;
  }

  return `Request failed (${status})`;
}

async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const url = `${API_BASE}${path}`;
  let response: Response;

  try {
    response = await fetch(url, {
      ...options,
      headers: {
        "Content-Type":
          "application/json",
        Accept: "application/json",
        ...(options?.headers || {}),
      },
      cache: "no-store",
    });
  } catch (error) {
    const reason =
      error instanceof Error
        ? error.message
        : String(error);

    throw new Error(
      `Network request to ${url} failed: ${reason}. Check that the FastAPI server is running and that its CORS configuration permits this frontend origin.`
    );
  }

  const responseText = await response.text();
  let payload: unknown = null;

  try {
    payload = JSON.parse(responseText);
  } catch {
    if (response.ok) {
      throw new Error(
        `Request to ${url} returned HTTP ${response.status}, but the response was not valid JSON: ${responseText.slice(0, 1000) || "empty response body"}`
      );
    }
  }

  if (!response.ok) {
    throw new Error(
      `Request to ${url} failed with HTTP ${response.status}: ${responseText.slice(0, 1000) || errorMessage(payload, response.status)}`
    );
  }

  return payload as T;
}

export function postResearch(
  payload: Record<string, unknown>
) {
  return request<any>("/research", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getResearch(
  id: number | string
) {
  return request<any>(
    `/research/${id}`
  );
}

export function saveImpactMeasurement(
  payload: Record<string, unknown>
) {
  return request<any>(
    "/impact-measurement",
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export function getValueAssessments(
  id: number | string
) {
  return request<any>(
    `/value-assessments/${id}`
  );
}

export function health() {
  return request<any>("/health");
}
