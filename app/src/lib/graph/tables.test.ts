import { describe, expect, it } from "vitest";
import { toCsv, type TableValue } from "./tables.ts";

describe("toCsv", () => {
  it("uses ; and decimal comma, units in the header, drops empty columns", () => {
    const t: TableValue = {
      title: "S",
      columns: [
        { key: "name", label: "Segment", unit: "" },
        { key: "ml", label: "Objętość", unit: "ml" },
        { key: "mean", label: "Średnia", unit: "" },
      ],
      rows: [
        { name: "Kość; lewa", ml: 12.5, mean: null },
        { name: "Naczynie", ml: 0.25, mean: null },
      ],
      chart: null,
    };
    expect(toCsv(t)).toBe('Segment;Objętość [ml]\r\n"Kość; lewa";12,5\r\nNaczynie;0,25\r\n');
  });
});
