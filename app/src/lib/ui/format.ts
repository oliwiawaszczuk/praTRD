// Polish number formatting for the UI (decimal comma, MB/GB).

const nf = (digits: number) =>
  new Intl.NumberFormat("pl-PL", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
const nf2 = nf(2);
const nf1 = nf(1);

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1 << 20) return `${nf1.format(n / 1024)} KB`;
  if (n < 1 << 30) return `${nf1.format(n / (1 << 20))} MB`;
  return `${nf2.format(n / (1 << 30))} GB`;
}

export const dims = (s: readonly number[]): string => s.join(" × ");

export const mm = (s: readonly number[]): string => `${s.map((x) => nf2.format(x)).join(" × ")} mm`;

export const num = (x: number, digits = 1): string => nf(digits).format(x);

/** Polish plural: plural(1, "wiersz", "wiersze", "wierszy") → "1 wiersz", 3 → "3 wiersze", 5 → "5 wierszy". */
export function plural(n: number, one: string, few: string, many: string): string {
  const d = n % 10;
  const t = n % 100;
  const w = n === 1 ? one : d >= 2 && d <= 4 && (t < 12 || t > 14) ? few : many;
  return `${n.toLocaleString("pl-PL")} ${w}`;
}
