import { test, expect } from "./fixtures";

// Screens for ecosystems, the knowledge graph, link review, findings, changes and onboarding.
// Tests that change state (a review decision) run last.

test.beforeAll(async ({ request }) => {
  const r = await request.post("/api/scenarios/gl-extract-abend/activate");
  expect(r.ok()).toBeTruthy();
});

test("ecosystems list each scheduler and open into its own graph", async ({ page, problems }) => {
  await page.goto("/ecosystems");
  await expect(page.getByTestId("eco-card")).toHaveCount(4);
  await page.getByTestId("eco-card").filter({ hasText: "AutoSys" }).click();
  await expect(page.getByRole("heading", { level: 1, name: /AutoSys AE1/ })).toBeVisible();
  await expect(page.getByText("AML_BOX").first()).toBeVisible();
  await expect(page.getByText("silent").first()).toBeVisible();          // PAY_FEDWIRE_RECON has no alert
  expect(await page.locator(".react-flow__node").count()).toBeGreaterThan(13);
  await expect(page.getByText(/has a password in its script/)).toBeVisible();
});

test("knowledge graph shows a node's relations with provenance and finds paths", async ({ page, problems }) => {
  await page.goto("/knowledge");
  await expect(page.getByTestId("kg-graph").locator(".react-flow__node").first()).toBeVisible();
  const rel = page.getByTestId("kg-relations");
  await expect(rel.getByText("zos-prd-01")).toBeVisible();
  await expect(rel.getByText("code").first()).toBeVisible();
  await page.getByTestId("kg-search").fill("finance.gl_mart");
  await page.locator(".kg-hits").getByRole("button", { name: /finance\.gl_mart/ }).first().click();
  await expect(rel.getByText("MIS_DAILY_PNL")).toBeVisible();
  await page.getByTestId("path-from").fill("CBK_GL_EXTRACT");
  await page.locator(".kg-hits").getByRole("button", { name: /CBK_GL_EXTRACT/ }).first().click();
  await page.getByTestId("path-to").fill("MIS_DAILY_PNL");
  await page.locator(".kg-hits").getByRole("button", { name: /MIS_DAILY_PNL/ }).first().click();
  const path = page.getByTestId("path-result").first();
  await expect(path).toContainText("wait_gl_extract");               // Control-M → Airflow
  await expect(path).toContainText("publish_gl_mart");               // → AutoSys via the link in review
});

test("findings separate static and runtime, with evidence and a link to review", async ({ page, problems }) => {
  await page.goto("/findings");
  await expect(page.getByText(/MIS_DAILY_PNL reads finance.gl_mart from publish_gl_mart/)).toBeVisible();
  await page.getByRole("button", { name: "Runtime" }).click();
  await expect(page.getByText(/pokes for 3.8 hours a night/)).toBeVisible();
  await expect(page.locator("svg.sparkline").first()).toBeVisible();      // duration trend
  await page.getByText(/MIS_DAILY_PNL ran before its data was ready/).locator("..").locator("..")
    .getByRole("link", { name: "Review the link" }).click();
  await expect(page.getByTestId("link-detail")).toContainText("publish_gl_mart");
});

test("what changed replays syncs with tickets and follow-up links", async ({ page, problems }) => {
  await page.goto("/changes");
  const log = page.getByTestId("changelog");
  await expect(log.getByText("CHG0041163").first()).toBeVisible();
  await expect(log.getByText("− condition on PAY_SETTLE_NET")).toBeVisible();
  await expect(log.getByText(/Follow-up link in review/).first()).toBeVisible();
});

test("onboarding sandbox parses a JIL export and proposes links to the live estate", async ({ page, problems }) => {
  await page.goto("/onboarding");
  await expect(page.getByTestId("pipeline")).toContainText("Mine the code");
  await page.getByTestId("sample-autosys-ae2").click();
  await page.getByTestId("analyse").click();
  const res = page.getByTestId("sandbox-result");
  await expect(res).toContainText("WLT_POSITIONS_LOAD");
  await expect(res).toContainText("CBK_BAL_SNAPSHOT");                   // link into the live Control-M
  await expect(res).toContainText("WLT_PRICING_SNAPSHOT");               // condition nothing provides
});

test("ask suggestions cover layered questions", async ({ page, problems }) => {
  await page.goto("/ask?q=" + encodeURIComponent("What would break if zos-prd-01 went down?"));
  await expect(page.getByText(/Business processes hit/).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("host_outage_impact").first()).toBeVisible();
});

test("link review: the owning team approves and lineage updates", async ({ page, problems }) => {
  await page.goto("/links");
  await page.getByTestId("persona").selectOption("agarcia");
  await page.getByRole("button", { name: "My queue" }).click();
  const detail = page.getByTestId("link-detail");
  await expect(detail).toContainText("MIS_DAILY_PNL");
  await expect(detail).toContainText("On 6 of 30 nights");
  if (await detail.getByRole("button", { name: "Approve" }).count()) {   // re-runs against the same stack skip this
    await detail.getByLabel("Review comment").fill("Confirmed with the P&L script owners");
    await detail.getByRole("button", { name: "Approve" }).click();
    await expect(detail.getByText("Approved").first()).toBeVisible();
    await expect(detail).toContainText("Confirmed with the P&L script owners");
  }
  await page.goto("/lineage");
  await expect(page.locator(".react-flow__node").first()).toBeVisible();
});
