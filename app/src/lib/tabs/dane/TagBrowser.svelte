<script lang="ts">
  import { getJson } from "#lib/core/api.svelte.ts";
  import { volumePath } from "#lib/core/library.svelte.ts";

  interface TagRow {
    tag: string;
    name: string;
    vr: string;
    value: string;
    depth: number;
  }

  let { vid }: { vid: string } = $props();
  let rows = $state.raw<TagRow[]>([]);
  let query = $state("");
  let error = $state("");

  $effect(() => {
    const ctl = new AbortController();
    rows = [];
    error = "";
    getJson<TagRow[]>(`${volumePath(vid)}/tags`, ctl.signal)
      .then((r) => (rows = r))
      .catch((e) => !ctl.signal.aborted && (error = String(e?.message ?? e)));
    return () => ctl.abort();
  });

  const shown = $derived.by(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        r.name.toLowerCase().includes(q) ||
        r.tag.toLowerCase().includes(q) ||
        r.value.toLowerCase().includes(q),
    );
  });
</script>

<div class="tags">
  <input class="input" placeholder="Szukaj tagu, nazwy lub wartości…" bind:value={query} spellcheck="false" />
  {#if error}
    <p class="err">{error}</p>
  {:else if !rows.length}
    <p class="muted">Brak tagów (wolumen z pliku NIfTI/NRRD albo stary import).</p>
  {:else}
    <div class="table">
      {#each shown as r, n (n)}
        <div class="row" class:sq={r.vr === "SQ"}>
          <span class="t">{r.tag}</span>
          <span class="n" style:padding-left="{r.depth * 12}px">{r.name}</span>
          <span class="vr">{r.vr}</span>
          <span class="v" title={r.value}>{r.value}</span>
        </div>
      {/each}
    </div>
    <span class="count">{shown.length} / {rows.length}</span>
  {/if}
</div>

<style>
  .tags {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .table {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    background: var(--bg-deep);
    border-radius: var(--radius-sm);
    font-size: var(--fs-xs);
    /* off-screen rows skip layout/paint — cheap even for multi-thousand-row dumps */
    content-visibility: auto;
  }
  .row {
    display: grid;
    grid-template-columns: 80px minmax(140px, 1.2fr) 30px 2fr;
    gap: 10px;
    padding: 3px 10px;
    border-bottom: 1px solid var(--line-1);
    content-visibility: auto;
    contain-intrinsic-size: auto 20px;
  }
  .row:hover {
    background: var(--hover);
  }
  .row.sq .n {
    color: var(--accent);
  }
  .t {
    color: var(--text-dim-3);
  }
  .n {
    color: var(--text-dim-1);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .vr {
    color: var(--text-dim-4);
  }
  .v {
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    -webkit-user-select: text;
    user-select: text;
  }
  .muted,
  .count {
    font-size: var(--fs-xs);
    color: var(--text-dim-3);
  }
  .err {
    font-size: var(--fs-xs);
    color: var(--danger);
  }
</style>
