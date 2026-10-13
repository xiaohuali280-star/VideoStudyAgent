import type { components } from "./schema";

export type HealthResponse = components["schemas"]["HealthResponse"];

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch("/api/health", { signal });
  if (!response.ok) throw new Error("服务暂时无法连接");
  const data: unknown = await response.json();
  if (
    typeof data !== "object" || data === null ||
    !("status" in data) || data.status !== "ok" ||
    !("service" in data) || data.service !== "VideoStudyAgent" ||
    !("schema_version" in data) || data.schema_version !== "1.0" ||
    !("stage" in data) || typeof data.stage !== "number" || !Number.isInteger(data.stage) || data.stage < 1 || data.stage > 7 ||
    !("version" in data) || typeof data.version !== "string"
  ) throw new Error("服务返回了不兼容的数据");
  return data as HealthResponse;
}
