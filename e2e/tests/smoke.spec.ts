import { test, expect } from "./fixtures";

test.beforeAll(async ({ request }) => {
  // Start every run from the default scenario so the assertions below hold.
  const r = await request.post("/api/scenarios/gl-extract-abend/activate");
  expect(r.ok()).toBeTruthy();
});

test("command center shows the four connectors and the at-risk processes", async ({ page, problems }) => {
  await page.goto("/");
  for (const name of ["Control-M", "AutoSys", "Airflow", "Azure Data Factory"]) {
    await expect(page.getByText(name, { exact: false }).first()).toBeVisible();
  }
  await expect(page.getByText(/cross-scheduler links/i).first()).toBeVisible();
  await expect(page.getByText(/Regulatory liquidity reporting/).first()).toBeVisible();
});

test("regulatory process spans three schedulers and names the root cause", async ({ page, problems }) => {
  await page.goto("/processes/bp-reg-liquidity");
  await expect(page.getByText("CBK_GL_EXTRACT").first()).toBeVisible();
  await expect(page.getByText(/S0C7/).first()).toBeVisible();
  await expect(page.locator(".react-flow").first()).toBeVisible();
});

test("lineage renders the whole estate graph", async ({ page, problems }) => {
  await page.goto("/lineage");
  await expect(page.locator(".react-flow__node").first()).toBeVisible();
  expect(await page.locator(".react-flow__node").count()).toBeGreaterThan(20);
});

test("connectors page shows a native payload next to the unified model", async ({ page, problems }) => {
  await page.goto("/connectors");
  await expect(page.getByText(/eventsToWaitFor/).first()).toBeVisible();
});

test("ask the estate answers from grounded tools (offline provider)", async ({ page, problems }) => {
  await page.goto("/ask");
  await page.getByRole("textbox").first().fill("Why is regulatory reporting at risk?");
  await page.keyboard.press("Enter");
  await expect(page.getByText(/CBK_GL_EXTRACT/).last()).toBeVisible({ timeout: 30_000 });
});

test("API health and readiness", async ({ request }) => {
  expect((await request.get("/api/meta")).ok()).toBeTruthy();
});
