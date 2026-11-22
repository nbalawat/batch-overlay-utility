import { test as base, expect } from "@playwright/test";

// Every page must render without console errors or failed API calls. This catches the class of bug that unit
// tests cannot: a renamed field, a crashing component, a route that 500s.
export const test = base.extend<{ problems: string[] }>({
  problems: async ({ page }, use) => {
    const problems: string[] = [];
    page.on("console", (m) => { if (m.type() === "error") problems.push(`console: ${m.text()}`); });
    page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
    page.on("response", (r) => {
      if (r.url().includes("/api/") && r.status() >= 500) problems.push(`api ${r.status()}: ${r.url()}`);
    });
    await use(problems);
    expect(problems, problems.join("\n")).toEqual([]);
  },
});
export { expect };
