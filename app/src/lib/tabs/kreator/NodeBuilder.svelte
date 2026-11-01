<script lang="ts">
  // The node card being built — looks like the card on the graph, but every part is
  // editable in place: name in the header, category chip, a socket's colour = its kind
  // (click to change), "+" under each side adds a socket, the parameter widgets are live
  // (their value is the default), the pencil opens the parameter's settings.
  import Icon from "#lib/ui/Icon.svelte";
  import ParamField from "#lib/graph/ParamField.svelte";
  import { DOMAIN_COLOR, domainLabels } from "#lib/graph/registry.svelte.ts";
  import { PORT_COLORS, PORT_LABELS, type PortKind } from "#lib/graph/types.ts";
  import { kreator, setLabel, touch } from "./kreator.svelte.ts";
  import { KIND_ID, KIND_IN, KIND_OUT, KINDS, newParam, paramSchema, uniqueName, validIdent, type ParamType, type PortDef } from "./model.ts";
  import ParamEditor from "./ParamEditor.svelte";

  const m = $derived(kreator.draft!.manifest);

  type Menu =
    | { kind: "domain" }
    | { kind: "add-port"; side: "in" | "out" }
    | { kind: "port-kind"; side: "in" | "out"; index: number }
    | { kind: "add-param" }
    | null;
  let menu = $state<Menu>(null);
  let menuPos = $state({ x: 0, y: 0 });
  let editParam = $state<number | null>(null);
  let editId = $state<string | null>(null); // "in:2" / "out:0" / "slug"
  let root = $state<HTMLDivElement>();

  const PARAM_TYPES: { type: ParamType; label: string; glyph: string }[] = [
    { type: "number", label: "Liczba", glyph: "1.5" },
    { type: "int", label: "Całkowita", glyph: "12" },
    { type: "bool", label: "Tak / nie", glyph: "◐" },
    { type: "select", label: "Wybór", glyph: "A|B" },
  ];

  function openMenu(e: MouseEvent, next: Menu): void {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const host = root!.getBoundingClientRect();
    menuPos = { x: r.left - host.left, y: r.bottom - host.top + 4 };
    menu = next;
  }

  function onWindowDown(e: PointerEvent): void {
    if (menu && !(e.target as HTMLElement).closest(".menu")) menu = null;
  }

  const ports = (side: "in" | "out"): PortDef[] => (side === "in" ? m.inputs : m.outputs);

  function addPort(side: "in" | "out", kind: PortKind): void {
    const list = ports(side);
    const id = uniqueName(KIND_ID[kind], list.map((p) => p.id));
    list.push({ id, label: PORT_LABELS[kind], kind, ...(side === "in" ? { multi: false, optional: false } : {}) });
    menu = null;
    touch();
  }

  function setKind(side: "in" | "out", i: number, kind: PortKind): void {
    const p = ports(side)[i];
    if (p.label === PORT_LABELS[p.kind]) p.label = PORT_LABELS[kind];
    p.kind = kind;
    menu = null;
    touch();
  }

  function removePort(side: "in" | "out", i: number): void {
    ports(side).splice(i, 1);
    touch();
  }

  function setPortId(side: "in" | "out", i: number, raw: string): void {
    const list = ports(side);
    const v = raw.trim();
    if (validIdent(v) && !list.some((p, j) => j !== i && p.id === v)) list[i].id = v;
    editId = null;
    touch();
  }

  function addParam(type: ParamType): void {
    m.params.push(newParam(type, m.params.map((p) => p.key)));
    editParam = m.params.length - 1;
    menu = null;
    touch();
  }

  function setSlug(raw: string): void {
    const v = raw.trim();
    if (/^[a-z][a-z0-9_]{0,39}$/.test(v)) {
      m.slug = v;
    }
    editId = null;
    touch();
  }

  const rows = $derived(Math.max(m.inputs.length, m.outputs.length));
</script>

<svelte:window onpointerdown={onWindowDown} />

<div class="wrap" bind:this={root}>
  <div class="card" style:--dom={DOMAIN_COLOR[m.domain] ?? "var(--accent)"}>
    <header>
      <span class="dot"></span>
      <input
        class="title"
        value={m.label}
        placeholder="Nazwa node'a"
        maxlength="60"
        oninput={(e) => setLabel(e.currentTarget.value)}
      />
      <button class="chip" title="Kategoria w palecie" onclick={(e) => openMenu(e, { kind: "domain" })}>
        <i style:background="var(--dom)"></i>{domainLabels()[m.domain] ?? m.domain}
      </button>
    </header>
    <div class="sub">
      {#if editId === "slug"}
        <!-- svelte-ignore a11y_autofocus -->
        <input
          class="idin"
          value={m.slug}
          autofocus
          onblur={(e) => setSlug(e.currentTarget.value)}
          onkeydown={(e) => e.key === "Enter" && e.currentTarget.blur()}
        />
      {:else}
        <button class="slug" title="Identyfikator (zapisane grafy go używają) — kliknij, aby zmienić" onclick={() => (editId = "slug")}>
          wlasne/{m.slug}
        </button>
      {/if}
      <button
        class="cost"
        class:heavy={m.cost === "heavy"}
        title={m.cost === "heavy" ? "Ciężki: liczy się dopiero po bezczynności / w pełnej rozdzielczości" : "Lekki: liczy się na żywo w podglądzie"}
        onclick={() => {
          m.cost = m.cost === "heavy" ? "light" : "heavy";
          touch();
        }}
      >
        <Icon name="pulse" size={11} />{m.cost === "heavy" ? "ciężki" : "lekki"}
      </button>
    </div>

    <div class="ports" style:min-height="{rows * 40 + 26}px">
      {#each ["in", "out"] as const as side (side)}
        <div class="col {side}">
          <div
            class="shead"
            title={side === "in"
              ? "Dane z innych node'ów — połączenia na grafie. W kodzie: inputs.<nazwa>"
              : "Wyniki node'a — to, co zwraca run(). Łączysz je dalej na grafie"}
          >
            {#if side === "in"}<Icon name="input" size={12} /><b>Wejścia</b><code>inputs.*</code>{:else}<code>return</code><b>Wyjścia</b><Icon
                name="output"
                size={12}
              />{/if}
          </div>
          {#each ports(side) as p, i (i)}
            <div class="port" title={side === "in" ? `inputs.${p.id} → ${KIND_IN[p.kind]}` : `zwróć: ${KIND_OUT[p.kind]}`}>
              <button
                class="sock"
                style:--c={PORT_COLORS[p.kind]}
                title="{PORT_LABELS[p.kind]} — kliknij, aby zmienić rodzaj"
                onclick={(e) => openMenu(e, { kind: "port-kind", side, index: i })}
                aria-label="Rodzaj gniazda"
              ></button>
              <div class="pbody">
                <input
                  class="plabel"
                  value={p.label}
                  maxlength="40"
                  oninput={(e) => {
                    p.label = e.currentTarget.value;
                    touch();
                  }}
                />
                {#if editId === `${side}:${i}`}
                  <!-- svelte-ignore a11y_autofocus -->
                  <input
                    class="idin"
                    value={p.id}
                    autofocus
                    onblur={(e) => setPortId(side, i, e.currentTarget.value)}
                    onkeydown={(e) => e.key === "Enter" && e.currentTarget.blur()}
                  />
                {:else}
                  <button class="pid" style:--c={PORT_COLORS[p.kind]} title="Nazwa w kodzie — kliknij, aby zmienić" onclick={() => (editId = `${side}:${i}`)}>
                    {side === "in" ? `inputs.${p.id}` : `"${p.id}"`}
                  </button>
                {/if}
              </div>
              <div class="pact">
                {#if side === "in"}
                  <button
                    class="flag"
                    class:on={p.optional}
                    title="Opcjonalne: node działa bez połączenia (inputs.{p.id} = None)"
                    onclick={() => {
                      p.optional = !p.optional;
                      touch();
                    }}>opc</button
                  >
                  <button
                    class="flag"
                    class:on={p.multi}
                    title="Wiele połączeń: inputs.{p.id} to lista"
                    onclick={() => {
                      p.multi = !p.multi;
                      touch();
                    }}>[ ]</button
                  >
                {/if}
                <button class="x" title="Usuń gniazdo" onclick={() => removePort(side, i)}><Icon name="trash" size={11} /></button>
              </div>
            </div>
          {/each}
          <button class="add" title={side === "in" ? "Dodaj wejście" : "Dodaj wyjście"} onclick={(e) => openMenu(e, { kind: "add-port", side })}>
            <Icon name="plus" size={12} />{side === "in" ? "wejście" : "wyjście"}
          </button>
        </div>
      {/each}
    </div>

    <div class="params">
      <div class="shead par" title="Ustawienia na karcie (suwaki, przełączniki) — nie łączy się ich na grafie. W kodzie: params.<klucz>">
        <Icon name="sliders" size={12} /><b>Parametry</b><code>params.*</code>
      </div>
      {#each m.params as p, i (i)}
        <div class="prow" class:editing={editParam === i}>
          <div class="pf">
            <ParamField
              p={paramSchema(p)}
              code="params.{p.key}"
              value={p.default}
              onchange={(v) => {
                p.default = v;
                touch();
              }}
            />
          </div>
          <button class="pe" title="Ustawienia parametru (params.{p.key})" onclick={() => (editParam = editParam === i ? null : i)}>
            <Icon name="edit" size={11} />
          </button>
        </div>
        {#if editParam === i}
          <ParamEditor
            index={i}
            onremove={() => {
              m.params.splice(i, 1);
              editParam = null;
              touch();
            }}
          />
        {/if}
      {/each}
      <button class="add wide" title="Dodaj parametr (suwak, przełącznik, wybór)" onclick={(e) => openMenu(e, { kind: "add-param" })}>
        <Icon name="plus" size={12} />parametr
      </button>
    </div>
  </div>

  <textarea
    class="desc"
    placeholder="Opis — pokazywany po najechaniu na (i) i w Dokumentacji (Markdown)"
    value={m.description}
    rows="3"
    oninput={(e) => {
      m.description = e.currentTarget.value;
      touch();
    }}
  ></textarea>

  {#if menu}
    <div class="menu" style:left="{menuPos.x}px" style:top="{menuPos.y}px">
      {#if menu.kind === "domain"}
        {#each Object.entries(domainLabels()) as [d, label] (d)}
          <button
            class:on={m.domain === d}
            onclick={() => {
              m.domain = d;
              menu = null;
              touch();
            }}
          >
            <i style:background={DOMAIN_COLOR[d]}></i>{label}
          </button>
        {/each}
      {:else if menu.kind === "add-port" || menu.kind === "port-kind"}
        {@const mk = menu}
        {#each KINDS as k (k)}
          <button
            class:on={mk.kind === "port-kind" && ports(mk.side)[mk.index]?.kind === k}
            title={mk.side === "in" ? KIND_IN[k] : KIND_OUT[k]}
            onclick={() => (mk.kind === "add-port" ? addPort(mk.side, k) : setKind(mk.side, mk.index, k))}
          >
            <i class="ring" style:--c={PORT_COLORS[k]}></i>{PORT_LABELS[k]}
          </button>
        {/each}
      {:else if menu.kind === "add-param"}
        {#each PARAM_TYPES as t (t.type)}
          <button onclick={() => addParam(t.type)}><b class="glyph">{t.glyph}</b>{t.label}</button>
        {/each}
      {/if}
    </div>
  {/if}
</div>

<style>
  .wrap {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .card {
    background: var(--bg-panel);
    border: 1px solid var(--line-2);
    border-radius: var(--radius-md);
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.4);
    font-size: var(--fs-xs);
    padding-bottom: 6px;
  }
  header {
    display: flex;
    align-items: center;
    gap: 7px;
    height: 34px;
    padding: 0 8px 0 10px;
    border-top: 3px solid var(--dom);
    border-radius: var(--radius-md) var(--radius-md) 0 0;
    background: var(--bg-panel-2);
  }
  .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--line-3);
    flex-shrink: 0;
  }
  input,
  textarea {
    font: inherit;
    color: inherit;
  }
  .title {
    flex: 1;
    min-width: 0;
    font-weight: 600;
    font-size: var(--fs-sm);
    color: var(--text-strong);
    background: none;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 3px 5px;
  }
  .title:hover,
  .plabel:hover {
    border-color: var(--line-2);
  }
  .title:focus,
  .plabel:focus,
  .idin:focus {
    outline: none;
    border-color: var(--accent-a70);
    background: var(--bg-deep);
  }
  .chip {
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 3px 8px;
    font: inherit;
    font-size: 0.64rem;
    color: var(--text-dim-1);
    background: var(--bg-deep);
    border: 1px solid var(--line-2);
    border-radius: 999px;
    cursor: pointer;
    white-space: nowrap;
  }
  .chip:hover {
    color: var(--text-strong);
    border-color: var(--line-3);
  }
  .chip i,
  .menu i {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .sub {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 10px 6px;
    border-bottom: 1px solid var(--line-1);
  }
  .slug,
  .pid {
    padding: 0 3px;
    font: inherit;
    font-size: 0.6rem;
    color: var(--text-dim-3);
    background: none;
    border: 0;
    border-radius: 3px;
    cursor: text;
    text-align: left;
  }
  .slug:hover,
  .pid:hover {
    color: var(--accent);
    background: var(--hover);
  }
  .pid {
    color: color-mix(in srgb, var(--c) 75%, var(--text-dim-3));
  }
  .idin {
    width: 100%;
    max-width: 180px;
    padding: 1px 4px;
    font-size: 0.6rem;
    background: var(--bg-deep);
    border: 1px solid var(--line-2);
    border-radius: 3px;
  }
  .cost {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 1px 7px;
    font: inherit;
    font-size: 0.58rem;
    color: var(--text-dim-3);
    background: none;
    border: 1px solid var(--line-1);
    border-radius: 999px;
    cursor: pointer;
  }
  .cost.heavy {
    color: var(--accent);
    border-color: var(--accent-a40);
  }
  .ports {
    display: grid;
    grid-template-columns: 1fr 1fr;
    padding: 0 0 2px;
  }
  .col.in {
    background: linear-gradient(90deg, rgba(255, 255, 255, 0.03), transparent 70%);
  }
  .col.out {
    background: linear-gradient(270deg, rgba(255, 255, 255, 0.03), transparent 70%);
  }
  .shead {
    display: flex;
    align-items: center;
    gap: 5px;
    height: 24px;
    padding: 0 12px;
    font-size: 0.58rem;
    color: var(--text-dim-2);
  }
  .shead b {
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .shead code {
    color: var(--text-dim-4);
  }
  .shead.par {
    color: var(--param);
    border-left: 2px solid var(--param);
    padding-left: 10px;
    margin-bottom: 2px;
  }
  .col {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .col.out {
    align-items: flex-end;
    text-align: right;
  }
  .port {
    position: relative;
    display: flex;
    align-items: center;
    gap: 4px;
    width: 100%;
    min-height: 38px;
    padding: 0 10px 0 14px;
  }
  .col.out .port {
    flex-direction: row-reverse;
    padding: 0 14px 0 10px;
  }
  .sock {
    position: absolute;
    left: -8px;
    width: 14px;
    height: 14px;
    padding: 0;
    border-radius: 50%;
    background: var(--c);
    border: 2px solid var(--bg-panel);
    box-shadow: 0 0 0 1px var(--c);
    cursor: pointer;
    transition: transform var(--t-fast);
  }
  .col.out .sock {
    left: auto;
    right: -8px;
  }
  .sock:hover {
    transform: scale(1.35);
  }
  .pbody {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .col.out .pbody {
    align-items: flex-end;
  }
  .plabel {
    width: 100%;
    padding: 1px 4px;
    color: var(--text-dim-1);
    background: none;
    border: 1px solid transparent;
    border-radius: 4px;
  }
  .col.out .plabel {
    text-align: right;
  }
  .pact {
    display: flex;
    gap: 1px;
    opacity: 0;
    transition: opacity var(--t-fast);
  }
  .port:hover .pact,
  .pact:has(.flag.on) {
    opacity: 1;
  }
  .flag,
  .x,
  .pe {
    display: flex;
    align-items: center;
    padding: 2px 3px;
    font: inherit;
    font-size: 0.56rem;
    color: var(--text-dim-4);
    background: none;
    border: 0;
    border-radius: 3px;
    cursor: pointer;
  }
  .flag.on {
    color: var(--accent);
    background: var(--accent-a15);
  }
  .flag:hover,
  .pe:hover {
    color: var(--text-strong);
  }
  .x:hover {
    color: var(--danger);
  }
  .add {
    display: flex;
    align-items: center;
    gap: 4px;
    margin: 2px 10px 4px;
    padding: 3px 8px;
    font: inherit;
    font-size: 0.62rem;
    color: var(--text-dim-3);
    background: none;
    border: 1px dashed var(--line-2);
    border-radius: 6px;
    cursor: pointer;
  }
  .add:hover {
    color: var(--accent);
    border-color: var(--accent-a40);
  }
  .add.wide {
    justify-content: center;
  }
  .params {
    display: flex;
    flex-direction: column;
    border-top: 1px solid var(--line-1);
    padding-top: 2px;
    background: linear-gradient(180deg, color-mix(in srgb, var(--param) 5%, transparent), transparent 60px);
  }
  .prow {
    display: flex;
    align-items: center;
    padding-right: 6px;
  }
  .prow.editing {
    background: var(--accent-a10);
  }
  .pf {
    flex: 1;
    min-width: 0;
  }
  .desc {
    resize: vertical;
    padding: 8px 10px;
    font-size: 0.68rem;
    color: var(--text-dim-1);
    background: var(--bg-panel);
    border: 1px solid var(--line-1);
    border-radius: var(--radius-md);
  }
  .desc:focus {
    outline: none;
    border-color: var(--accent-a40);
  }
  .menu {
    position: absolute;
    z-index: 20;
    min-width: 150px;
    display: flex;
    flex-direction: column;
    padding: 4px;
    background: var(--bg-panel-2);
    border: 1px solid var(--line-2);
    border-radius: 8px;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
  }
  .menu button {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 5px 8px;
    font: inherit;
    font-size: 0.7rem;
    text-align: left;
    color: var(--text-dim-1);
    background: none;
    border: 0;
    border-radius: 5px;
    cursor: pointer;
  }
  .menu button:hover {
    color: var(--text-strong);
    background: var(--hover);
  }
  .menu button.on {
    color: var(--accent);
  }
  .menu .ring {
    width: 10px;
    height: 10px;
    background: var(--c);
    border: 2px solid var(--bg-panel-2);
    box-shadow: 0 0 0 1px var(--c);
  }
  .glyph {
    width: 26px;
    font-size: 0.6rem;
    color: var(--accent);
    text-align: center;
  }
</style>
