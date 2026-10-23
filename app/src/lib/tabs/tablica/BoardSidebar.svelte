<script lang="ts">
  // Tablica sidebar (ported from praSzczur): add tools, properties of the selection,
  // export, the list of boards, shortcuts.
  import Icon, { type IconName } from "#lib/ui/Icon.svelte";
  import { confirmAction } from "#lib/ui/dialogs.svelte.ts";
  import type { BoardMeta, BoardObject, BoardTool, DrawObject, ShapeKind, ShapeObject, TextObject } from "./board.svelte.ts";

  interface Props {
    boardList: BoardMeta[];
    activeBoardId: string;
    selected: BoardObject[];
    tool: BoardTool;
    draw: { color: string; width: number };
    shape: {
      kind: ShapeKind;
      fillColor: string;
      fillTransparent: boolean;
      strokeColor: string;
      strokeWidth: number;
      strokeTransparent: boolean;
      cornerRadius: number;
    };
    onselectboard: (id: string) => void;
    oncreateboard: (name: string) => void;
    onrenameboard: (id: string, name: string) => void;
    ondeleteboard: (id: string) => void;
    onpropchange: (id: string, patch: Partial<BoardObject>) => void;
    onaddimagefiles: (files: File[]) => void;
    onsettool: (t: BoardTool) => void;
    ondraw: (patch: Partial<{ color: string; width: number }>) => void;
    onshape: (patch: Partial<Props["shape"]>) => void;
    onexportpng: () => void;
    onshowshortcuts: () => void;
  }
  let p: Props = $props();

  let creating = $state(false);
  let newName = $state("");
  let renamingId = $state<string | null>(null);
  let renameVal = $state("");

  const TOOLS: { t: BoardTool | "image"; icon: IconName; label: string; title: string }[] = [
    { t: "select", icon: "cursor", label: "Kursor", title: "Zaznaczanie (W)" },
    { t: "text", icon: "text", label: "Tekst", title: "Kliknij na tablicy, aby dodać tekst (T)" },
    { t: "image", icon: "image", label: "Obraz", title: "Dodaj obraz (albo przeciągnij / wklej)" },
    { t: "shape", icon: "shape", label: "Kształt", title: "Prostokąt / elipsa" },
    { t: "draw", icon: "pen", label: "Pędzel", title: "Rysowanie odręczne (P)" },
  ];

  const single = $derived(p.selected.length === 1 ? p.selected[0] : null);
  const all = (type: BoardObject["type"]) => p.selected.length > 0 && p.selected.every((o) => o.type === type);
  const selTitle = $derived(
    p.selected.length > 1
      ? `Zaznaczono: ${p.selected.length}`
      : ({ text: "Tekst", draw: "Rysunek", shape: "Kształt", image: "Obraz" } as const)[single?.type ?? "image"],
  );
  const patchAll = (patch: Partial<BoardObject>) => p.selected.forEach((o) => p.onpropchange(o.id, patch));
  const val = (e: Event) => (e.currentTarget as HTMLInputElement).value;
  const num = (e: Event) => Number((e.currentTarget as HTMLInputElement).value);
  const chk = (e: Event) => (e.currentTarget as HTMLInputElement).checked;

  function create(): void {
    if (!newName.trim()) return;
    p.oncreateboard(newName.trim());
    newName = "";
    creating = false;
  }
  function commitRename(): void {
    if (renamingId && renameVal.trim()) p.onrenameboard(renamingId, renameVal.trim());
    renamingId = null;
  }
  async function remove(b: BoardMeta): Promise<void> {
    if (await confirmAction("Usunąć tablicę?", `„${b.name}” razem z obrazami — tej operacji nie można cofnąć.`, { confirmText: "Usuń", danger: true }))
      p.ondeleteboard(b.id);
  }
  const date = (iso: string) => {
    try {
      return new Date(iso).toLocaleString("pl-PL", { dateStyle: "short", timeStyle: "short" });
    } catch {
      return iso;
    }
  };
  let fileInput = $state<HTMLInputElement>();
</script>

<aside class="side">
  <section class="panel">
    <div class="tools">
      {#each TOOLS as b (b.t)}
        <button
          class="tool"
          class:on={p.tool === b.t}
          title={b.title}
          onclick={() => (b.t === "image" ? fileInput?.click() : p.onsettool(p.tool === b.t && b.t !== "select" ? "select" : (b.t as BoardTool)))}
        >
          <Icon name={b.icon} size={15} />
          <span>{b.label}</span>
        </button>
      {/each}
      <input
        bind:this={fileInput}
        type="file"
        accept="image/*"
        multiple
        hidden
        onchange={(e) => {
          const files = [...(e.currentTarget.files ?? [])];
          if (files.length) p.onaddimagefiles(files);
          e.currentTarget.value = "";
        }}
      />
    </div>

    {#if p.tool === "draw"}
      <div class="sub row">
        <input class="color" type="color" value={p.draw.color} oninput={(e) => p.ondraw({ color: val(e) })} />
        <input class="grow" type="range" min="1" max="24" value={p.draw.width} oninput={(e) => p.ondraw({ width: num(e) })} />
        <span class="v">{p.draw.width}px</span>
      </div>
    {/if}
    {#if p.tool === "shape"}
      <div class="sub">
        <div class="seg">
          <button class:on={p.shape.kind === "rect"} title="Prostokąt" onclick={() => p.onshape({ kind: "rect" })}>
            <svg width="16" height="12" viewBox="0 0 16 12"><rect x="1" y="1" width="14" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.6" /></svg>
          </button>
          <button class:on={p.shape.kind === "ellipse"} title="Elipsa" onclick={() => p.onshape({ kind: "ellipse" })}>
            <svg width="16" height="12" viewBox="0 0 16 12"><ellipse cx="8" cy="6" rx="7" ry="5" fill="none" stroke="currentColor" stroke-width="1.6" /></svg>
          </button>
        </div>
        <div class="hint">Shift = kwadrat / koło</div>
        <div class="row">
          <input class="color" type="color" value={p.shape.fillColor} disabled={p.shape.fillTransparent} oninput={(e) => p.onshape({ fillColor: val(e) })} />
          <label class="cb"><input type="checkbox" checked={p.shape.fillTransparent} onchange={(e) => p.onshape({ fillTransparent: chk(e) })} /> bez wypełnienia</label>
        </div>
        <div class="row">
          <input class="color" type="color" value={p.shape.strokeColor} disabled={p.shape.strokeTransparent} oninput={(e) => p.onshape({ strokeColor: val(e) })} />
          <label class="cb"><input type="checkbox" checked={p.shape.strokeTransparent} onchange={(e) => p.onshape({ strokeTransparent: chk(e) })} /> bez obramowania</label>
        </div>
        {#if !p.shape.strokeTransparent}
          <input type="range" min="1" max="20" value={p.shape.strokeWidth} oninput={(e) => p.onshape({ strokeWidth: num(e) })} title="Grubość obramowania" />
        {/if}
        {#if p.shape.kind === "rect"}
          <input type="range" min="0" max="60" value={p.shape.cornerRadius} oninput={(e) => p.onshape({ cornerRadius: num(e) })} title="Zaokrąglenie rogów" />
        {/if}
      </div>
    {/if}
  </section>

  {#if p.selected.length}
    <section class="panel">
      <h4>{selTitle}</h4>
      {#if all("text")}
        {@const t = single as TextObject | null}
        <div class="row">
          <input class="color" type="color" value={t?.color ?? "#f0f0f0"} oninput={(e) => patchAll({ color: val(e) })} title="Kolor" />
          <input class="field" type="number" min="6" max="200" value={t?.fontSize ?? 20} oninput={(e) => patchAll({ fontSize: num(e) })} title="Rozmiar czcionki" />
          <button class="chip" class:on={t?.bold} title="Pogrubienie" onclick={() => patchAll({ bold: !(t?.bold ?? false) })}><b>B</b></button>
        </div>
        <div class="seg">
          {#each [["left", "M4 6h16M4 10h10M4 14h16M4 18h10"], ["center", "M4 6h16M7 10h10M4 14h16M7 18h10"], ["right", "M4 6h16M10 10h10M4 14h16M10 18h10"]] as [a, d] (a)}
            <button class:on={(t?.align ?? "left") === a} title="Wyrównanie" onclick={() => patchAll({ align: a as TextObject["align"] })}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path {d} /></svg>
            </button>
          {/each}
        </div>
        <label class="cb"><input type="checkbox" checked={t?.borderEnabled ?? false} onchange={(e) => patchAll({ borderEnabled: chk(e) })} /> obrys liter</label>
        {#if t?.borderEnabled}
          <div class="row">
            <input class="color" type="color" value={t.borderColor} oninput={(e) => patchAll({ borderColor: val(e) })} />
            <input class="grow" type="range" min="0.5" max="6" step="0.5" value={t.borderWidth} oninput={(e) => patchAll({ borderWidth: num(e) })} />
          </div>
        {/if}
      {/if}
      {#if all("draw")}
        {@const d = single as DrawObject | null}
        <div class="row">
          <input class="color" type="color" value={d?.color ?? "#ffc951"} oninput={(e) => patchAll({ color: val(e) })} />
          <input class="grow" type="range" min="1" max="24" value={d?.strokeWidth ?? 4} oninput={(e) => patchAll({ strokeWidth: num(e) })} />
        </div>
      {/if}
      {#if all("shape")}
        {@const s = single as ShapeObject | null}
        <div class="row">
          <input class="color" type="color" value={s?.fillColor ?? "#ffc951"} disabled={s?.fillTransparent} oninput={(e) => patchAll({ fillColor: val(e) })} />
          <label class="cb"><input type="checkbox" checked={s?.fillTransparent ?? false} onchange={(e) => patchAll({ fillTransparent: chk(e) })} /> bez wypełnienia</label>
        </div>
        <div class="row">
          <input class="color" type="color" value={s?.strokeColor ?? "#ffc951"} disabled={s?.strokeTransparent} oninput={(e) => patchAll({ strokeColor: val(e) })} />
          <label class="cb"><input type="checkbox" checked={s?.strokeTransparent ?? false} onchange={(e) => patchAll({ strokeTransparent: chk(e) })} /> bez obramowania</label>
        </div>
      {/if}
      {#if all("image")}
        <div class="row" title="Przezroczystość">
          <svg width="14" height="14" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2" /><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor" /></svg>
          <input class="grow" type="range" min="0.05" max="1" step="0.05" value={single?.opacity ?? 1} oninput={(e) => patchAll({ opacity: num(e) })} />
        </div>
      {/if}
      {#if single}
        <div class="row nums">
          <label title="Obrót [°]">⟳<input class="field" type="number" step="1" value={Math.round(single.rotation)} oninput={(e) => p.onpropchange(single.id, { rotation: num(e) })} /></label>
          {#if single.type !== "draw"}
            <label title="Szerokość">W<input class="field" type="number" min="4" value={Math.round(single.width)} oninput={(e) => p.onpropchange(single.id, { width: num(e) })} /></label>
            <label title="Wysokość">H<input class="field" type="number" min="4" value={Math.round(single.height)} oninput={(e) => p.onpropchange(single.id, { height: num(e) })} /></label>
          {/if}
        </div>
      {/if}
    </section>
  {/if}

  <section class="panel">
    <div class="h">
      <h4>Tablice</h4>
      <button class="chip" title="Nowa tablica" onclick={() => (creating = !creating)}><Icon name="plus" size={12} /></button>
    </div>
    {#if creating}
      <div class="row">
        <!-- svelte-ignore a11y_autofocus -->
        <input class="field grow" placeholder="nazwa tablicy" bind:value={newName} autofocus onkeydown={(e) => e.key === "Enter" && create()} />
        <button class="btn primary" disabled={!newName.trim()} onclick={create}>Utwórz</button>
      </div>
    {/if}
    <div class="boards">
      {#each p.boardList as b (b.id)}
        {@const act = b.id === p.activeBoardId}
        <div class="board" class:act>
          <span class="dot"></span>
          {#if renamingId === b.id}
            <!-- svelte-ignore a11y_autofocus -->
            <input class="field grow" bind:value={renameVal} autofocus onkeydown={(e) => e.key === "Enter" && commitRename()} onblur={commitRename} />
          {:else}
            <button class="bname" disabled={act} onclick={() => p.onselectboard(b.id)} ondblclick={() => ((renamingId = b.id), (renameVal = b.name))} title="Dwuklik: zmień nazwę">
              <span>{b.name}</span>
              <small>{date(b.updatedAt)}</small>
            </button>
          {/if}
          <button class="ib del" title="Usuń" disabled={p.boardList.length <= 1} onclick={() => remove(b)}><Icon name="trash" size={13} /></button>
        </div>
      {/each}
    </div>
  </section>

  <section class="panel actions">
    <button class="btn" onclick={p.onexportpng}><Icon name="download" size={13} /> PNG</button>
    <button class="btn" onclick={p.onshowshortcuts}><Icon name="keyboard" size={13} /> Skróty</button>
  </section>
</aside>

<style>
  .side {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 12px;
    overflow-y: auto;
    background: var(--bg-panel-2);
    border-left: 1px solid var(--line-1);
  }
  .panel {
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 10px;
    background: var(--bg-panel);
    border: 1px solid var(--line-1);
    border-radius: 10px;
  }
  h4 {
    font-size: 0.64rem;
    font-weight: 700;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--text-dim-2);
  }
  .h {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .tools {
    display: flex;
    gap: 4px;
  }
  .tool {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    padding: 7px 0 5px;
    font: inherit;
    font-size: 0.54rem;
    font-weight: 600;
    color: var(--text-dim-1);
    background: var(--hover);
    border: 1px solid var(--line-2);
    border-radius: 8px;
    cursor: pointer;
  }
  .tool:hover {
    color: var(--accent);
    border-color: var(--accent-a40);
  }
  .tool.on {
    color: var(--accent);
    background: var(--accent-a15);
    border-color: var(--accent);
  }
  .sub {
    display: flex;
    flex-direction: column;
    gap: 7px;
    padding-top: 8px;
    border-top: 1px solid var(--line-1);
  }
  .row {
    display: flex;
    align-items: center;
    gap: 7px;
    color: var(--text-dim-2);
  }
  .sub.row {
    flex-direction: row;
  }
  .grow {
    flex: 1;
    min-width: 0;
  }
  .v {
    width: 32px;
    font-size: 0.64rem;
    color: var(--text-dim-2);
    text-align: right;
  }
  .hint {
    font-size: 0.6rem;
    color: var(--text-dim-4);
    text-align: center;
  }
  .color {
    width: 34px;
    height: 26px;
    padding: 2px;
    background: var(--bg-deep);
    border: 1px solid var(--line-2);
    border-radius: 6px;
    cursor: pointer;
    flex-shrink: 0;
  }
  .color:disabled {
    opacity: 0.3;
  }
  .field {
    width: 100%;
    min-width: 0;
    padding: 4px 7px;
    font: inherit;
    font-size: 0.7rem;
    color: var(--text);
    background: var(--bg-deep);
    border: 1px solid var(--line-2);
    border-radius: 6px;
    outline: none;
  }
  .field:focus {
    border-color: var(--accent);
  }
  .nums label {
    flex: 1;
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 0.64rem;
  }
  .cb {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.66rem;
    color: var(--text-dim-1);
    cursor: pointer;
  }
  .cb input {
    accent-color: var(--accent);
  }
  input[type="range"] {
    accent-color: var(--accent);
  }
  .seg {
    display: flex;
    background: var(--bg-deep);
    border: 1px solid var(--line-2);
    border-radius: 7px;
    overflow: hidden;
  }
  .seg button {
    flex: 1;
    height: 26px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-dim-2);
    background: none;
    border: 0;
    cursor: pointer;
  }
  .seg button.on {
    color: #111;
    background: var(--accent);
  }
  .chip {
    display: flex;
    align-items: center;
    justify-content: center;
    min-width: 26px;
    height: 24px;
    font: inherit;
    color: var(--text-dim-1);
    background: var(--hover);
    border: 1px solid var(--line-2);
    border-radius: 6px;
    cursor: pointer;
  }
  .chip.on,
  .chip:hover {
    color: var(--accent);
    border-color: var(--accent-a40);
  }
  .boards {
    display: flex;
    flex-direction: column;
    gap: 3px;
    max-height: 210px;
    overflow-y: auto;
  }
  .board {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 5px 6px 5px 9px;
    border: 1px solid var(--line-1);
    border-radius: 7px;
  }
  .board.act {
    border-color: var(--accent-a30);
    background: var(--accent-a10);
  }
  .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--line-3);
    flex-shrink: 0;
  }
  .act .dot {
    background: var(--accent);
    box-shadow: 0 0 6px var(--accent-a70);
  }
  .bname {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    font: inherit;
    text-align: left;
    color: var(--text);
    background: none;
    border: 0;
    cursor: pointer;
  }
  .bname span {
    max-width: 100%;
    font-size: 0.72rem;
    font-weight: 600;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .bname:disabled {
    cursor: default;
  }
  .act .bname span {
    color: var(--accent);
  }
  .bname small {
    font-size: 0.56rem;
    color: var(--text-dim-4);
  }
  .ib {
    display: flex;
    padding: 3px;
    color: var(--text-dim-3);
    background: none;
    border: 0;
    border-radius: 5px;
    cursor: pointer;
  }
  .ib.del:hover:not(:disabled) {
    color: var(--danger);
  }
  .ib:disabled {
    opacity: 0.25;
    cursor: not-allowed;
  }
  .actions {
    flex-direction: row;
  }
  .actions .btn {
    flex: 1;
    justify-content: center;
  }
</style>
