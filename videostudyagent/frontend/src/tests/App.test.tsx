import { render, screen, waitFor } from "@testing-library/react";
import App from "../App";

const health = { schema_version: "1.0", service: "VideoStudyAgent", status: "ok", version: "0.1.0", stage: 1 };

test("renders the stage-one shell and connects only to health", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => health });
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("都成为自己的知识");
  expect(screen.getByText("学习空间正在准备中")).toBeVisible();
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("本地服务已连接"));
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0][0]).toBe("/api/health");
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

test("shows an actionable connection state when backend is absent", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  render(<App />);
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("请启动后端后刷新"));
});

test("aborts the health request on unmount", () => {
  const fetchMock = vi.fn().mockReturnValue(new Promise(() => {}));
  vi.stubGlobal("fetch", fetchMock);
  const { unmount } = render(<App />);
  const signal = fetchMock.mock.calls[0][1].signal as AbortSignal;
  unmount();
  expect(signal.aborted).toBe(true);
});
