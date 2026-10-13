import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "../App";
import SafeMarkdown from "../components/SafeMarkdown";

beforeEach(() => history.replaceState(null, "", "/"));
const health = { schema_version: "1.0", service: "VideoStudyAgent", status: "ok", version: "0.1.0", stage: 6 };
function connected() {
  const fetchMock = vi.fn(async (url: string) => ({ ok: true, json: async () => url === "/api/health" ? health : url === "/api/config" ? { schema_version: "1.0", max_video_bytes: 1000, max_subtitle_bytes: 1000, max_duration_ms: 5000, export_formats: [] } : [] }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
test("opens the working upload form and connects to the service", async () => {
  connected(); render(<App />);
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("都成为自己的知识");
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("本地服务已连接"));
  expect(screen.getByRole("button", { name: "开始整理" })).toBeEnabled();
});
test("empty upload fails before sending a task", async () => {
  const fetchMock = connected(); render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "开始整理" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("请选择视频或字幕文件");
  expect(fetchMock.mock.calls.every(([url]) => url !== "/api/tasks")).toBe(true);
});
test("shows the connection failure without exposing network details", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("private-proxy-details")));
  render(<App />);
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("请启动后端后刷新"));
  expect(screen.queryByText(/private-proxy-details/)).toBeNull();
});
test("unmount aborts outstanding requests", () => {
  const fetchMock = vi.fn().mockReturnValue(new Promise(() => {})); vi.stubGlobal("fetch", fetchMock);
  const { unmount } = render(<App />); unmount();
  expect(fetchMock.mock.calls.every(([, init]) => init.signal.aborted)).toBe(true);
});
test("Markdown renders math and tables while suppressing HTML, images and unsafe links", () => {
  const { container } = render(<SafeMarkdown content={'<script>alert(1)</script>\n\n[bad](javascript:alert(1)) ![image](https://remote.invalid/a.png) [safe](https://example.com)\n\n$x^2$\n\n|a|b|\n|-|-|\n|1|2|'} />);
  expect(container.querySelector("script,img")).toBeNull();
  expect(container.querySelectorAll("a")).toHaveLength(1);
  expect(screen.getByRole("link", { name: "safe" })).toHaveAttribute("rel", "noopener noreferrer");
  expect(container.querySelector(".katex")).not.toBeNull();
  expect(screen.getByRole("table")).toBeInTheDocument();
});
