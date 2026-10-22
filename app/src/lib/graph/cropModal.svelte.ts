// Which "Przytnij" node has its 3-D box editor open (one at a time).

let nodeId = $state<string | null>(null);

export const cropModal = {
  get nodeId() {
    return nodeId;
  },
};

export const openCrop = (id: string): void => {
  nodeId = id;
};

export const closeCrop = (): void => {
  nodeId = null;
};

/** Crop params (percent per index axis) ↔ fractions. */
export const AXES = ["i", "j", "k"] as const;
export type Box = Record<(typeof AXES)[number], [number, number]>;

export function boxFromParams(p: Record<string, unknown>): Box {
  const f = (k: string, d: number) => Math.min(1, Math.max(0, Number(p[k] ?? d) / 100));
  const pair = (a: string): [number, number] => {
    const x = f(`${a}0`, 0);
    const y = f(`${a}1`, 100);
    return x <= y ? [x, y] : [y, x];
  };
  return { i: pair("i"), j: pair("j"), k: pair("k") };
}
