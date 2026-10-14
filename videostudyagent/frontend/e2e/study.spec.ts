import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";

const subtitle = "1\n00:00:00,000 --> 00:00:02,500\nGradient descent reduces the loss.\n\n2\n00:00:02,500 --> 00:00:05,000\nThe learning rate controls the step size.\n";
test("upload, persisted course, notes, folded quiz and five matching exports", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("课程名称（可选）").fill("Gradient descent lesson");
  await page.getByLabel("字幕文件（SRT / VTT，可选）").setInputFiles({ name: "lesson.srt", mimeType: "text/plain", buffer: Buffer.from(subtitle) });
  await page.getByLabel("难度", { exact: true }).selectOption("hard");
  await page.getByRole("button", { name: "开始整理" }).click();
  await expect(page.getByRole("heading", { name: "Gradient descent lesson", exact: true }).first()).toBeVisible();
  await expect(page.locator(".status-badge")).toHaveText("已完成");
  await expect(page.getByRole("button", { name: "导出笔记 Markdown" })).toBeEnabled();
  const taskId = new URL(page.url()).searchParams.get("task")!;
  const result = await (await page.request.get(`/api/tasks/${taskId}/result`)).json();
  expect(result.quiz.questions).toHaveLength(5);
  expect(result.quiz.difficulty).toBe("hard");
  await page.reload();
  await expect(page.locator(".status-badge")).toHaveText("已完成");
  await page.screenshot({ path: "../.cache/qa/stage6-notes.png", fullPage: true });
  await page.getByRole("tab", { name: "自测练习" }).click();
  await expect(page.locator("details")).toHaveCount(5);
  await expect(page.locator("details").first()).not.toHaveAttribute("open");
  await page.getByText("查看答案与解析", { exact: true }).first().click();
  await expect(page.locator("details").first()).toHaveAttribute("open");
  await expect(page.getByRole("heading", { name: "参考答案", exact: true }).first()).toBeVisible();
  for (const [label, filename] of [["笔记 Markdown", "notes.md"], ["自测 Markdown", "quiz.md"], ["自测 JSON", "quiz.json"], ["字幕 JSON", "transcript.json"], ["字幕 SRT", "transcript.srt"]]) {
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: `导出${label}`, exact: true }).click();
    const file = await download;
    expect(file.suggestedFilename()).toBe(filename);
    const content = await fs.readFile((await file.path())!, "utf8");
    if (filename.endsWith(".json")) expect(JSON.parse(content)).toEqual(result[filename.startsWith("quiz") ? "quiz" : "transcript"]);
    else expect(content).toContain(filename === "notes.md" ? result.notes.title : "Gradient descent");
  }
  await page.getByRole("tab", { name: "课程字幕" }).click();
  await expect(page.getByText("00:00–00:02", { exact: true })).toBeVisible();
});

test("mobile layout and invalid upload remain usable", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await page.getByRole("button", { name: "开始整理" }).click();
  await expect(page.getByRole("alert")).toHaveText("请选择视频或字幕文件。");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "../.cache/qa/stage6-mobile.png", fullPage: true });
});
