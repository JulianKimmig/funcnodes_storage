import assert from "assert";

describe("Test Helpers", () => {
  it("test import", async () => {
    const moduleExports = await import("../dist/js/main.js");
    console.log(moduleExports);
    console.log(moduleExports.default); // This should log all exported elements
    assert.ok(moduleExports.default.RendererPlugin);
  });
});
