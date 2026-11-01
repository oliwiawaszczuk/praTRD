<script lang="ts">
  // Test of the draft: where each input comes from (phantom, a library series, a node of
  // the open graph), then the automatic checks, a preview of every output and print().
  import Icon from "#lib/ui/Icon.svelte";
  import ProgressRing from "#lib/ui/ProgressRing.svelte";
  import NodeThumb from "#lib/graph/NodeThumb.svelte";
  import TableChart from "#lib/graph/TableChart.svelte";
  import { libraryVolumes } from "#lib/core/library.svelte.ts";
  import { meshThumbUrl } from "#lib/core/meshes.svelte.ts";
  import { graph } from "#lib/graph/store.svelte.ts";
  import { nodeType } from "#lib/graph/registry.svelte.ts";
  import { PORT_COLORS, PORT_LABELS, type PortKind } from "#lib/graph/types.ts";
  import type { TableValue } from "#lib/graph/tables.ts";
  import { num } from "#lib/ui/format.ts";
  import { installLibrary, kreator, libraries, pipNameFor, runTest, touch, type Check, type Source } from "./kreator.svelte.ts";
  import type { PortDef } from "./model.ts";

  let { ongoto, onlibraries }: { ongoto: (line: number) => void; onlibraries: (spec: string) => void } = $props();

  const d = $derived(kreator.draft!);
  const r = $derived(kreator.result);

  function source(p: PortDef): Source {
    return d.sources[p.id] ?? { source: "fantom" };
  }
  function setSource(p: PortDef, s: Source): void {
    d.sources[p.id] = s;
    touch();
  }

  /** Outputs of the open graph's nodes with this kind (test on real intermediate data). */
  function graphOutputs(kind: PortKind): { node: string; socket: string; label: string }[] {
    const out = [];
    for (const n of graph.doc.nodes) {
      const t = nodeType(n.type);
      if (!t || t.id === `wlasne/${d.slug}`) continue;
      for (const o of t.outputs)
        if (o.kind === kind) out.push({ node: n.id, socket: o.id, label: t.outputs.length > 1 ? `${t.label} · ${o.label}` : t.label });
    }
    return out;
  }

  const ICON: Record<Check["level"], string> = { ok: "M5 12l5 5L20 7", info: "M12 11v6M12 7.5v.5", warn: "M12 6v8M12 17.5v.5", fail: "M6 6l12 12M18 6L6 18" };
  const kindOf = (id: string): PortKind | undefined => d.manifest.outputs.find((o) => o.id === id)?.kind;
  const stat = (id: string) => r?.stats[id] ?? {};
  const kilo = (n: number) => (n >= 1e6 ? `${num(n / 1e6, 1)} mln` : n >= 1e4 ? `${num(n / 1e3, 0)} tys.` : n.toLocaleString("pl-PL"));
  const range = (s: Record<string, unknown>) =>
    s.min !== undefined ? `${num(Number(s.min), 1)} … ${num(Number(s.max), 1)}` : "";
  const colorsOf = (o: { kind: string; info?: Record<string, unknown> }): Record<number, string> | undefined =>
    o.kind === "segment"
      ? { 1: String(o.info?.color ?? "#7bc47f") }
      : o.kind === "segmentacja"
        ? Object.fromEntries(((o.info?.labels as { id: number; color: string }[]) ?? []).map((l) => [l.id, l.color]))
        : undefined;
</script>

<div class="panel">
  <div class="head">
    <span class="h">Test</span>
    {#if r && !kreator.testing}
      <span class="ms" class:stale={kreator.resultStale} title={kreator.resultStale ? "Kod lub ustawienia zmieniły się od testu" : ""}>
        {r.ms} ms{kreator.resultStale ? " · nieaktualny" : ""}
      </span>
    {/if}
    <button class="run" disabled={kreator.testing} title="Uruchom test (⌘/Ctrl + Enter)" onclick={runTest}>
      {#if kreator.testing}<ProgressRing size={13} />{:else}<Icon name="play" size={12} />{/if}Testuj
    </button>
  </div>

  <div class="scroll">
    {#if d.manifest.inputs.length}
      <section>
        <h6>Wejścia</h6>
        {#each d.manifest.inputs as p (p.id)}
          {@const s = source(p)}
          {@const inp = r?.inputs[p.id]}
          <div class="src">
            <div class="srow">
              <i class="sock" style:--c={PORT_COLORS[p.kind]}></i>
              <span class="pl">{p.label}</span>
              <div class="segs">
                <button class:on={s.source === "fantom"} title="Syntetyczny fantom: kula w szumie, siatka 0,8 × 0,8 × 1,5 mm" onclick={() => setSource(p, { source: "fantom" })}>fantom</button>
                {#if p.kind === "wolumen"}
                  <button
                    class:on={s.source === "seria"}
                    disabled={!libraryVolumes().length}
                    title="Seria z biblioteki (w podglądzie)"
                    onclick={() => setSource(p, { source: "seria", vid: libraryVolumes()[0]?.id ?? "" })}>seria</button
                  >
                {/if}
                <button
                  class:on={s.source === "graf"}
                  disabled={!graphOutputs(p.kind).length}
                  title="Wynik node'a z otwartego grafu (Scena)"
                  onclick={() => {
                    const g = graphOutputs(p.kind)[0];
                    setSource(p, { source: "graf", node: g.node, socket: g.socket });
                  }}>graf</button
                >
                {#if p.optional}
                  <button class:on={s.source === "brak"} title="Bez połączenia (inputs.{p.id} = None)" onclick={() => setSource(p, { source: "brak" })}>brak</button>
                {/if}
              </div>
            </div>
            {#if s.source === "seria"}
              <select value={s.vid} onchange={(e) => setSource(p, { source: "seria", vid: e.currentTarget.value })}>
                {#each libraryVolumes() as v (v.id)}<option value={v.id}>{v.name}</option>{/each}
              </select>
            {:else if s.source === "graf"}
              <select
                value="{s.node}:{s.socket}"
                onchange={(e) => {
                  const [node, socket] = e.currentTarget.value.split(":");
                  setSource(p, { source: "graf", node, socket });
                }}
              >
                {#each graphOutputs(p.kind) as g (g.node + g.socket)}<option value="{g.node}:{g.socket}">{g.label}</option>{/each}
              </select>
            {/if}
            {#if inp?.ref && (inp.kind === "wolumen" || inp.kind === "segment" || inp.kind === "segmentacja")}
              <div class="mini"><NodeThumb volRef={inp.ref} window={inp.info?.window as never} colors={colorsOf(inp)} /></div>
            {/if}
          </div>
        {/each}
      </section>
    {/if}

    {#if kreator.testing && !r}
      <div class="wait"><ProgressRing size={28} /></div>
    {:else if !r}
      <div class="empty">
        <Icon name="play" size={22} />
        <span>Testuj na fantomie lub prawdziwych danych — zobaczysz każde wyjście, kontrole i wydruki <code>print()</code>.</span>
      </div>
    {:else}
      <div class="result" class:stale={kreator.resultStale || kreator.testing}>
        <section>
          <h6>Kontrole</h6>
          <div class="checks">
            {#each r.checks as c, i (i)}
              <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
              <div class="check {c.level}" class:link={!!c.line} onclick={() => c.line && ongoto(c.line)} title={c.line ? `Przejdź do linii ${c.line}` : ""}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d={ICON[c.level]} /></svg>
                <b>{c.label}</b>
                {#if c.message}<span>{c.message}</span>{/if}
                {#if c.line}<em>:{c.line}</em>{/if}
              </div>
            {/each}
          </div>
          {#if r.error?.module}
            {@const pkg = pipNameFor(r.error.module)}
            <div class="missing">
              <Icon name="package" size={13} />
              <span>Brak biblioteki <code>{r.error.module}</code></span>
              <button
                class="inst"
                disabled={!!libraries.installing}
                title="pip install {pkg} — potem test uruchomi się ponownie"
                onclick={async () => {
                  if (await installLibrary(pkg)) void runTest();
                }}
              >
                {#if libraries.installing}<ProgressRing size={12} />{:else}<Icon name="download" size={11} />{/if}Zainstaluj {pkg}
              </button>
              <button class="other" title="Inna nazwa paczki / wersja" onclick={() => onlibraries(pkg)}>…</button>
            </div>
          {/if}
          {#if r.error?.trace}<pre class="trace">{r.error.trace}</pre>{/if}
        </section>

        {#if r.state === "done"}
          <section>
            <h6>Wyjścia</h6>
            <div class="outs">
              {#each d.manifest.outputs as o (o.id)}
                {@const v = r.outputs[o.id]}
                {@const s = stat(o.id)}
                {#if v}
                  <div class="out">
                    <div class="otitle"><i class="sock" style:--c={PORT_COLORS[o.kind]}></i>{o.label}<small>{PORT_LABELS[kindOf(o.id) ?? o.kind]}</small></div>
                    {#if (v.kind === "wolumen" || v.kind === "segment" || v.kind === "segmentacja") && v.ref}
                      <NodeThumb volRef={v.ref} window={v.info?.window as never} colors={colorsOf(v)} />
                      <div class="meta">
                        {#if s.shape}<span>{(s.shape as number[]).slice().reverse().join("×")}</span>{/if}
                        {#if v.kind === "wolumen"}
                          <span>{s.converted ?? s.dtype}</span><span>{range(s)}</span>
                        {:else}
                          <b>{num(Number(v.info?.ml ?? 0), 2)} ml</b><span>{kilo(Number(v.info?.voxels ?? 0))} vox</span>
                        {/if}
                      </div>
                      {#if v.kind === "segmentacja"}
                        <div class="legend">
                          {#each (v.info?.labels as { id: number; name: string; color: string }[]) ?? [] as l (l.id)}<span><i style:background={l.color}></i>{l.name}</span>{/each}
                        </div>
                      {/if}
                    {:else if v.kind === "mesh" && v.ref}
                      <div class="mthumb"><img src={meshThumbUrl(v.ref)} alt="" /></div>
                      <div class="meta">
                        <span>{kilo(Number(v.info?.faces ?? 0))} △</span>
                        {#if v.info?.closed}<b>{num(Number(v.info?.ml ?? 0), 2)} ml</b>{:else}<span class="warn">otwarty</span>{/if}
                      </div>
                    {:else if v.kind === "tabela"}
                      {@const t = v.value as TableValue}
                      {#if t.chart}<div class="chart"><TableChart table={t} height={60} /></div>{/if}
                      <table>
                        <thead><tr>{#each t.columns as c (c.key)}<th>{c.label}{c.unit ? ` [${c.unit}]` : ""}</th>{/each}</tr></thead>
                        <tbody>
                          {#each t.rows.slice(0, 8) as row, i (i)}
                            <tr>{#each t.columns as c (c.key)}<td>{typeof row[c.key] === "number" ? num(row[c.key] as number, 3) : (row[c.key] ?? "")}</td>{/each}</tr>
                          {/each}
                        </tbody>
                      </table>
                      {#if t.rows.length > 8}<div class="more">+ {t.rows.length - 8} wierszy</div>{/if}
                    {:else if v.kind === "liczba"}
                      <div class="big">{num(Number(v.value), 4)}</div>
                    {:else if v.kind === "punkty"}
                      {@const items = ((v.value as { items: { name: string; p: number[][] }[] })?.items ?? [])}
                      <div class="pts">
                        {#each items.slice(0, 6) as it, i (i)}<span>{it.name}: {it.p.map((q) => q.map((c) => num(c, 1)).join(", ")).join(" → ")}</span>{/each}
                        {#if items.length > 6}<span class="more">+ {items.length - 6}</span>{/if}
                      </div>
                    {/if}
                  </div>
                {/if}
              {/each}
            </div>
          </section>
        {/if}

        <section>
          <h6>Konsola</h6>
          {#if r.logs.length}
            <pre class="logs">{r.logs.join("\n")}</pre>
          {:else}
            <div class="nolog">print() w kodzie trafi tutaj</div>
          {/if}
        </section>
      </div>
    {/if}
  </div>
</div>

<style>
  .panel {
    height: 100%;
    display: flex;
    flex-direction: column;
    min-height: 0;
  }
  .head {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 10px;
    border-bottom: 1px solid var(--line-1);
  }
  .h {
    font-size: 0.66rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--text-dim-2);
  }
  .ms {
    font-size: 0.6rem;
    color: var(--text-dim-3);
  }
  .ms.stale {
    color: var(--accent);
  }
  .run {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 4px 12px;
    font: inherit;
    font-size: 0.7rem;
    font-weight: 600;
    color: var(--bg-app);
    background: var(--accent);
    border: 0;
    border-radius: 6px;
    cursor: pointer;
  }
  .run:disabled {
    opacity: 0.7;
    cursor: default;
  }
  .scroll {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  section {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  h6 {
    margin: 0;
    font-size: 0.6rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--text-dim-3);
  }
  .src {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .srow {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.68rem;
  }
  .sock {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    flex-shrink: 0;
    background: var(--c);
    box-shadow: 0 0 0 1px var(--c);
    border: 2px solid var(--bg-panel);
  }
  .pl {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text-dim-1);
  }
  .segs {
    display: flex;
    border: 1px solid var(--line-2);
    border-radius: 5px;
    overflow: hidden;
  }
  .segs button {
    padding: 2px 7px;
    font: inherit;
    font-size: 0.6rem;
    color: var(--text-dim-2);
    background: none;
    border: 0;
    cursor: pointer;
  }
  .segs button + button {
    border-left: 1px solid var(--line-2);
  }
  .segs button.on {
    color: var(--accent);
    background: var(--accent-a15);
  }
  .segs button:disabled {
    opacity: 0.35;
    cursor: default;
  }
  select {
    font: inherit;
    font-size: 0.66rem;
    padding: 3px 5px;
    color: var(--text);
    background: var(--bg-deep);
    border: 1px solid var(--line-2);
    border-radius: 4px;
  }
  .mini :global(.thumb) {
    height: 56px !important;
    margin: 0;
  }
  .wait,
  .empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding: 30px 14px;
    text-align: center;
    font-size: 0.68rem;
    color: var(--text-dim-3);
  }
  .empty code {
    color: var(--accent);
  }
  .result {
    display: flex;
    flex-direction: column;
    gap: 12px;
    transition: opacity var(--t-fast);
  }
  .result.stale {
    opacity: 0.55;
  }
  .checks {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .check {
    display: flex;
    align-items: baseline;
    gap: 6px;
    padding: 4px 7px;
    font-size: 0.66rem;
    border-radius: 5px;
    background: var(--bg-deep);
  }
  .check svg {
    flex-shrink: 0;
    align-self: center;
  }
  .check b {
    font-weight: 600;
    white-space: nowrap;
  }
  .check span {
    color: var(--text-dim-1);
    word-break: break-word;
  }
  .check em {
    margin-left: auto;
    font-style: normal;
    color: var(--text-dim-3);
  }
  .check.link {
    cursor: pointer;
  }
  .check.link:hover {
    background: var(--hover);
  }
  .check.ok svg {
    color: var(--ok);
  }
  .check.info svg {
    color: var(--port-wolumen);
  }
  .check.warn svg {
    color: var(--accent);
  }
  .check.fail {
    background: var(--danger-a15);
  }
  .check.fail svg,
  .check.fail b {
    color: var(--danger);
  }
  .missing {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 8px;
    font-size: 0.66rem;
    color: var(--text-dim-1);
    background: var(--accent-a10);
    border: 1px solid var(--accent-a30);
    border-radius: 6px;
  }
  .missing > span {
    flex: 1;
  }
  .missing code {
    color: var(--code-keyword);
  }
  .inst,
  .other {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 3px 8px;
    font: inherit;
    font-weight: 600;
    color: var(--bg-app);
    background: var(--accent);
    border: 0;
    border-radius: 5px;
    cursor: pointer;
    white-space: nowrap;
  }
  .other {
    padding: 3px 6px;
    color: var(--text-dim-1);
    background: none;
    border: 1px solid var(--line-2);
  }
  .inst:disabled {
    opacity: 0.6;
  }
  .trace,
  .logs {
    margin: 0;
    padding: 7px 8px;
    max-height: 200px;
    overflow: auto;
    font-size: 0.62rem;
    line-height: 1.5;
    white-space: pre-wrap;
    color: var(--text-dim-1);
    background: var(--bg-deepest);
    border-radius: 5px;
  }
  .nolog {
    font-size: 0.62rem;
    color: var(--text-dim-4);
  }
  .outs {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .out {
    padding: 6px 0 4px;
    background: var(--bg-panel);
    border: 1px solid var(--line-1);
    border-radius: 8px;
    font-size: 0.66rem;
  }
  .otitle {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0 10px 2px;
    font-weight: 600;
    color: var(--text-strong);
  }
  .otitle small {
    margin-left: auto;
    font-weight: 400;
    color: var(--text-dim-3);
  }
  .meta {
    display: flex;
    gap: 8px;
    padding: 0 10px;
    color: var(--text-dim-3);
    font-size: 0.6rem;
  }
  .meta b {
    color: var(--text-strong);
  }
  .meta .warn {
    color: var(--accent);
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 3px 8px;
    padding: 3px 10px 0;
    font-size: 0.6rem;
    color: var(--text-dim-1);
  }
  .legend i {
    display: inline-block;
    width: 8px;
    height: 8px;
    margin-right: 3px;
    border-radius: 50%;
  }
  .mthumb {
    height: 96px;
    margin: 4px 10px 6px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 4px;
    background: radial-gradient(circle at 50% 45%, #1c2423, #050606 75%);
  }
  .mthumb img {
    max-width: 100%;
    max-height: 100%;
  }
  .chart {
    margin: 4px 10px;
  }
  table {
    width: calc(100% - 20px);
    margin: 4px 10px 0;
    border-collapse: collapse;
    font-size: 0.6rem;
  }
  th {
    text-align: left;
    font-weight: 600;
    color: var(--text-dim-2);
    border-bottom: 1px solid var(--line-2);
    padding: 2px 4px;
  }
  td {
    padding: 2px 4px;
    color: var(--text-dim-1);
    border-bottom: 1px solid var(--line-1);
  }
  .more {
    padding: 2px 10px;
    font-size: 0.58rem;
    color: var(--text-dim-3);
  }
  .big {
    padding: 4px 10px;
    font-size: 1.3rem;
    font-weight: 700;
    color: var(--port-liczba);
  }
  .pts {
    display: flex;
    flex-direction: column;
    padding: 2px 10px;
    font-size: 0.6rem;
    color: var(--text-dim-1);
  }
</style>
