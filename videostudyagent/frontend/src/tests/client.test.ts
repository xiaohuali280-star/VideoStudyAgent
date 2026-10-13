import { getHealth } from "../api/client";

test.each([
  null,
  { status: "ok" },
  { status: "ok", service: "VideoStudyAgent", schema_version: "2.0", stage: 1, version: "1" },
])("rejects an incompatible health payload: %j", async (data) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => data }));
  await expect(getHealth()).rejects.toThrow("不兼容");
});

test("does not display raw server errors", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
  await expect(getHealth()).rejects.toThrow("服务暂时无法连接");
});
