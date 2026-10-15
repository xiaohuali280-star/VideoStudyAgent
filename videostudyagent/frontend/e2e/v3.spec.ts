import { test, expect } from "@playwright/test";

test("live updates reconnect, source-only search and reload preserve the course", async ({ page }) => {
  let interrupt = true;
  await page.route("**/api/tasks/*/events*", route => {
    if (interrupt) { interrupt = false; return route.abort("failed"); }
    return route.continue();
  });
  await page.goto("/");
  await page.getByLabel("课程名称（可选）").fill("V3 evidence acceptance");
  await page.getByLabel("字幕文件（SRT / VTT，可选）").setInputFiles({ name: "v3.srt", mimeType: "text/plain", buffer: Buffer.from("1\n00:00:01,234 --> 00:00:05,000\n梯度下降 uses rate -0.1.\n") });
  await page.getByLabel("梳理笔记", { exact: true }).uncheck();
  await page.getByLabel("生成自测（每批 5 题）", { exact: true }).uncheck();
  await page.getByRole("button", { name: /^开始整理/ }).click();
  await expect(page.locator(".status-badge")).toHaveText("已完成");
  await expect(page.getByText(/^课程进展实时更新/)).toBeVisible();
  await page.getByText("在课程原文中查找", { exact: true }).click();
  await page.getByLabel("课程术语", { exact: true }).fill("梯度");
  await page.getByRole("button", { name: "查找课程证据", exact: true }).click();
  await expect(page.locator(".evidence-search article")).toHaveCount(1);
  await expect(page.locator(".evidence-search article")).toContainText("00:01");
  await expect(page.locator(".evidence-search article")).toContainText("rate -0.1");
  const id = new URL(page.url()).searchParams.get("task")!;
  const result = await (await page.request.get(`/api/tasks/${id}/result`)).json();
  expect(result.notes).toBeNull(); expect(result.quiz).toBeNull();
  await page.reload();
  await expect(page.getByRole("heading", { name: "V3 evidence acceptance", exact: true })).toBeVisible();
  await expect(page.getByText(/^课程进展实时更新/)).toBeVisible();
});
