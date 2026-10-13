import { useEffect, useState } from "react";
import { ApiError, friendlyError, getResult, getTask } from "../api/client";
import type { StudyResult, TaskDetail } from "../api/client";

export function useTask(id: string | null, revision: number) {
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [result, setResult] = useState<StudyResult | null>(null);
  const [error, setError] = useState("");
  const [corrupt, setCorrupt] = useState(false);
  useEffect(() => {
    setDetail(null); setResult(null); setError(""); setCorrupt(false);
    if (!id) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined, failures = 0;
    async function refresh() {
      try {
        const next = await getTask(id!, controller.signal);
        if (controller.signal.aborted) return;
        setDetail(next);
        const output = await getResult(id!, controller.signal);
        if (controller.signal.aborted) return;
        setResult(output); setError(""); setCorrupt(false); failures = 0;
        if (["queued", "running"].includes(next.task.status)) timer = setTimeout(refresh, 2000);
      } catch (failure) {
        if (controller.signal.aborted) return;
        setError(friendlyError(failure));
        setCorrupt(failure instanceof ApiError && failure.code === "STORAGE_ERROR");
        if (!(failure instanceof ApiError) || failure.status >= 500 || failure.status === 0) {
          timer = setTimeout(refresh, Math.min(10000, 2000 * 2 ** failures++));
        }
      }
    }
    void refresh();
    return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [id, revision]);
  return { detail, result, error, corrupt };
}
