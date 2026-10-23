// Viewport screenshots → Tablica. A view composes its own layers (WebGL / vtk.js image,
// 2-D overlay canvas, SVG markups) into one canvas; this module turns it into a board image.

import { goToTab } from "#lib/core/nav.svelte.ts";
import { showError } from "#lib/ui/dialogs.svelte.ts";
import { toast } from "#lib/ui/toast.svelte.ts";
import { addImageToBoard } from "#lib/tabs/tablica/board.svelte.ts";

// computed styles an SVG needs once it leaves the page (scoped CSS does not travel)
const PROPS = [
  "fill", "fill-opacity", "stroke", "stroke-width", "stroke-dasharray", "stroke-opacity", "opacity",
  "font-size", "font-weight", "font-family", "filter", "color", "visibility", "display",
] as const;

function inline(src: Element, dst: Element): void {
  const cs = getComputedStyle(src);
  const style = PROPS.map((p) => `${p}:${cs.getPropertyValue(p)}`).join(";");
  dst.setAttribute("style", style);
  for (let n = 0; n < src.children.length; n++) inline(src.children[n], dst.children[n]);
}

/** Draw an on-page SVG (CSS px, at `x, y` inside the view) onto a canvas scaled by `scale`. */
export async function drawSvg(ctx: CanvasRenderingContext2D, svg: SVGSVGElement, x: number, y: number, scale: number): Promise<void> {
  const r = svg.getBoundingClientRect();
  if (!r.width || !r.height) return;
  const clone = svg.cloneNode(true) as SVGSVGElement;
  inline(svg, clone);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(r.width));
  clone.setAttribute("height", String(r.height));
  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)], { type: "image/svg+xml" }));
  try {
    const img = new Image();
    await new Promise<void>((res, rej) => {
      img.onload = () => res();
      img.onerror = () => rej(new Error("svg"));
      img.src = url;
    });
    ctx.drawImage(img, x * scale, y * scale, r.width * scale, r.height * scale);
  } catch {
    // an SVG that fails to rasterise is left out rather than failing the screenshot
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** All `svg` elements matching `selector` inside `host`, drawn at their place. */
export async function drawSvgs(ctx: CanvasRenderingContext2D, host: HTMLElement, selector: string, scale: number): Promise<void> {
  const h = host.getBoundingClientRect();
  for (const svg of host.querySelectorAll<SVGSVGElement>(selector)) {
    const r = svg.getBoundingClientRect();
    await drawSvg(ctx, svg, r.left - h.left, r.top - h.top, scale);
  }
}

/** Send a composed view to the board the user worked on last (toast → open Tablica). */
export async function sendToBoard(canvas: HTMLCanvasElement, caption: string, cssW: number, cssH: number): Promise<void> {
  try {
    const blob = await new Promise<Blob | null>((res) => canvas.toBlob(res, "image/png"));
    if (!blob) throw new Error("Pusty obraz");
    const name = await addImageToBoard(blob, cssW, cssH, caption);
    toast(`Dodano do tablicy „${name}”`, { icon: "camera", action: () => goToTab("tablica") });
  } catch (e) {
    await showError("Nie udało się wysłać zrzutu", e);
  }
}
