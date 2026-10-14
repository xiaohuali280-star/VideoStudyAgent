import type { components } from "./schema";

export type HealthResponse = components["schemas"]["HealthResponse"];
export type Task = components["schemas"]["Task"];
export type TaskDetail = components["schemas"]["TaskDetail"];
export type StudyResult = components["schemas"]["StudyResult"];
export type StudyOptions = components["schemas"]["StudyOptions"];
export type PublicConfig = components["schemas"]["PublicConfig"];
export type NotesDocument = components["schemas"]["NotesDocument"];
export type QuizDocument = components["schemas"]["QuizDocument"] | components["schemas"]["QuizDocumentV11"];
export type StudyOperation = components["schemas"]["StudyOperation"];
export type CourseStudyState = components["schemas"]["CourseStudyState"];
export const getStudyState = (id: string) => jsonRequest<CourseStudyState>(`/api/tasks/${id}/study-state`);
export const getOperations = (id: string) => jsonRequest<StudyOperation[]>(`/api/tasks/${id}/operations`);
export const submitOperation = (id: string, request: StudyOperation["request"], key = crypto.randomUUID()) =>
  jsonRequest<StudyOperation>(`/api/tasks/${id}/operations`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": key }, body: JSON.stringify(request) });
export type Transcript = components["schemas"]["Transcript"];
export type ExportFormat = PublicConfig["export_formats"][number];

export class ApiError extends Error {
  constructor(public code: string, message: string, public status = 0, public retryable = false) {
    super(message);
  }
}

const messages: Record<string, string> = {
  MIGRATION_REQUIRED: "现有课程库需要先备份升级，请查看本地启动指南。",
  UPLOAD_TOO_LARGE: "文件超过上传大小限制。", UNSUPPORTED_MEDIA: "请选择有效的 MP4、SRT 或 VTT 文件。",
  INVALID_SUBTITLE: "字幕格式或编码无效，请检查文件。", EMPTY_UPLOAD: "文件不能为空。",
  VALIDATION_ERROR: "请检查题数、难度和课程标题。", INPUT_REQUIRED: "请选择视频或字幕文件。",
  INVALID_UPLOAD: "上传内容不符合要求，请重新选择文件。", NOT_FOUND: "未找到对应课程或文件。",
  RESULT_NOT_READY: "对应学习资料尚未生成。", TASK_NOT_RETRYABLE: "当前课程不能重试。",
  STORAGE_ERROR: "学习结果缺失或损坏，可尝试重新处理。",
};

async function responseError(response: Response): Promise<never> {
  let code = "REQUEST_FAILED", retryable = false;
  try {
    const body = await response.json();
    if (body.schema_version === "1.0" && typeof body.error?.code === "string") {
      code = body.error.code; retryable = body.error.retryable === true;
    }
  } catch { /* Never display proxy HTML or raw provider messages. */ }
  throw new ApiError(code, messages[code] || "请求未完成，请稍后重试。", response.status, retryable);
}

export function friendlyError(error: unknown): string {
  return error instanceof ApiError ? error.message : "暂时无法连接服务，请稍后重试。";
}

async function jsonRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) return responseError(response);
  return response.json() as Promise<T>;
}

export const getConfig = (signal?: AbortSignal) => jsonRequest<PublicConfig>("/api/config", { signal });
export const getTasks = (offset = 0, signal?: AbortSignal) =>
  jsonRequest<Task[]>(`/api/tasks?limit=20&offset=${offset}`, { signal });
export const getTask = (id: string, signal?: AbortSignal) =>
  jsonRequest<TaskDetail>(`/api/tasks/${encodeURIComponent(id)}`, { signal });
export const getResult = (id: string, signal?: AbortSignal) =>
  jsonRequest<StudyResult>(`/api/tasks/${encodeURIComponent(id)}/result`, { signal });
export const createTask = (body: FormData, signal?: AbortSignal) =>
  jsonRequest<Task>("/api/tasks", { method: "POST", body, signal });
export const retryTask = (id: string) =>
  jsonRequest<Task>(`/api/tasks/${encodeURIComponent(id)}/retry`, { method: "POST" });
export const videoURL = (id: string) => `/api/tasks/${encodeURIComponent(id)}/video`;

export async function downloadExport(id: string, format: ExportFormat) {
  const response = await fetch(`/api/tasks/${encodeURIComponent(id)}/exports/${format}`);
  if (!response.ok) return responseError(response);
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = format;
  document.body.appendChild(anchor); anchor.click(); anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch("/api/health", { signal });
  if (!response.ok) throw new Error("服务暂时无法连接");
  const data: unknown = await response.json();
  if (
    typeof data !== "object" || data === null ||
    !("status" in data) || data.status !== "ok" ||
    !("service" in data) || data.service !== "VideoStudyAgent" ||
    !("schema_version" in data) || data.schema_version !== "1.0" ||
    !("stage" in data) || typeof data.stage !== "number" || !Number.isInteger(data.stage) || data.stage < 1 || data.stage > 14 ||
    !("version" in data) || typeof data.version !== "string"
  ) throw new Error("服务返回了不兼容的数据");
  return data as HealthResponse;
}
