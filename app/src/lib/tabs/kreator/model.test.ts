import { describe, expect, it } from "vitest";
import { codeSkeleton, KIND_ID, KINDS, newParam, TEMPLATES, uniqueName, validIdent } from "./model.ts";

describe("code names", () => {
  it("are unique and valid Python names", () => {
    expect(uniqueName("mask", ["mask"])).toBe("mask_2");
    expect(uniqueName("mask", ["mask", "mask_2"])).toBe("mask_3");
    for (const k of KINDS) expect(validIdent(KIND_ID[k])).toBe(true);
    for (const t of ["number", "int", "bool", "select"] as const) expect(validIdent(newParam(t, []).key)).toBe(true);
    expect(validIdent("class")).toBe(false);
    expect(validIdent("Maska")).toBe(false);
  });
});

describe("templates", () => {
  it("use only valid, unique, English identifiers", () => {
    for (const t of TEMPLATES) {
      const m = t.manifest;
      expect(/^[a-z][a-z0-9_]*$/.test(t.slug)).toBe(true);
      for (const list of [m.inputs.map((p) => p.id), m.outputs.map((p) => p.id), m.params.map((p) => p.key)]) {
        expect(list.every(validIdent)).toBe(true);
        expect(new Set(list).size).toBe(list.length);
      }
      expect(m.outputs.length).toBeGreaterThan(0);
      // code refers only to declared names
      for (const r of (t.code ?? "").matchAll(/\binputs\.(\w+)/g)) expect(m.inputs.map((p) => p.id)).toContain(r[1]);
      for (const r of (t.code ?? "").matchAll(/\bparams\.(\w+)/g)) expect(m.params.map((p) => p.key)).toContain(r[1]);
    }
  });
  it("skeleton names every input, parameter and output", () => {
    const m = { ...TEMPLATES[1].manifest, outputs: TEMPLATES[3].manifest.outputs, slug: "s" };
    const code = codeSkeleton(m);
    expect(code).toContain("def run(inputs, params, ctx):");
    for (const p of m.inputs) expect(code).toContain(`inputs.${p.id}`);
    for (const p of m.params) expect(code).toContain(`params.${p.key}`);
    for (const o of m.outputs) expect(code).toContain(`"${o.id}":`);
  });
});
