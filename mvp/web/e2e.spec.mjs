import { test, expect } from "@playwright/test";

test.use({
  baseURL: process.env.MVP_URL || "http://localhost:8000",
  channel: "chrome",
  headless: true,
  viewport: { width: 1440, height: 1100 },
});

test("desktop dashboard and complete dispatcher scenario", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Город под наблюдением." }),
  ).toBeVisible();
  await expect(page.locator(".incident-row").first()).toBeVisible();
  await expect(page.locator(".detail-card")).toBeVisible();
  await page.screenshot({
    path: "/tmp/warm-route-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Добавить обращение" }).click();
  await page
    .getByRole("combobox", { name: "Участок", exact: true })
    .selectOption("3");
  await page.getByLabel("Тип проблемы").selectOption("snow");
  const message = "Демонстрационная проверка: снег на участке " + Date.now();
  await page.getByLabel("Описание").fill(message);
  // Simulate losing the HTTP response after the server has committed the report.
  let first = true;
  await page.route("**/reports", async (route) => {
    if (first) {
      first = false;
      await route.fetch();
      await route.abort("failed");
    } else await route.continue();
  });
  await page.getByRole("button", { name: "Отправить обращение" }).click();
  await expect(page.locator('dialog [role="alert"]')).toBeVisible();
  await page.getByRole("button", { name: "Отправить обращение" }).click();
  await expect(page.locator("dialog")).not.toBeVisible();
  await expect(
    page.locator(".evidence-item").filter({ hasText: message }),
  ).toHaveCount(1, { timeout: 20000 });
  for (const [action, status] of [
    ["Подтвердить проблему", "Активна"],
    ["Отметить устранение", "Устранена"],
    ["Проверить сейчас", "Повторная проверка"],
    ["Подтвердить закрытие", "Закрыта"],
  ]) {
    await page.getByRole("button", { name: action }).click();
    await page
      .getByLabel("Результат проверки")
      .fill("Участок осмотрен диспетчером: " + status);
    await page.getByRole("button", { name: "Сохранить решение" }).click();
    await expect(page.locator("dialog")).not.toBeVisible();
    await expect(page.locator(".detail-card .badge")).toHaveText(status, {
      timeout: 20000,
    });
  }
  await expect(page.locator(".impact-box strong")).toHaveText(/^0\s*\/\s*100$/);
  await page.getByLabel("Фильтр статуса").selectOption("CLOSED");
  await expect(page.locator(".incident-row").first()).toBeVisible();
  await page.reload();
  await expect(page.locator(".incident-row").first()).toBeVisible();
  expect(errors).toEqual([]);
});

test("mobile layout and map without network", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("https://tile.openstreetmap.org/**", (route) =>
    route.abort(),
  );
  await page.goto("/");
  await expect(page.locator(".detail-card")).toBeVisible();
  await expect(page.locator(".tile-warning")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: "/tmp/warm-route-mobile.png", fullPage: true });
  await page.getByRole("button", { name: "Добавить обращение" }).click();
  await expect(page.getByLabel("Описание")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("dialog")).not.toBeVisible();
});

test("API outage is visible and retry recovers", async ({ page }) => {
  await page.route("**/incidents?*", (route) =>
    route.fulfill({ status: 503, body: "Unavailable" }),
  );
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("503");
  await page.unroute("**/incidents?*");
  await page.getByRole("button", { name: "Повторить", exact: true }).click();
  await expect(page.locator(".incident-row").first()).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("all map markers stay inside the viewport on load and resize", async ({
  page,
}) => {
  await page.route("https://tile.openstreetmap.org/**", (route) =>
    route.abort(),
  );
  await page.goto("/");
  for (const viewport of [
    { width: 1440, height: 1100 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await expect(page.locator(".map-marker")).toHaveCount(8);
    await expect
      .poll(async () =>
        page.locator(".map").evaluate((map) => {
          const box = map.getBoundingClientRect();
          return [...map.querySelectorAll(".map-marker")].every((marker) => {
            const p = marker.getBoundingClientRect();
            return (
              p.top >= box.top + 95 &&
              p.bottom <= box.bottom - 40 &&
              p.left >= box.left &&
              p.right <= box.right
            );
          });
        }),
      )
      .toBe(true);
  }
});
