<script lang="ts">
  import { getJson } from "#lib/core/api.svelte.ts";

  interface Diagnostics {
    ok: boolean;
    deps: Record<string, string | null>;
    decoders: Record<string, boolean>;
    data_root: string;
    python: string;
    frozen: boolean;
  }

  // Fetched once, when the card first mounts (Settings is lazily mounted): the endpoint
  // imports the whole processing stack, so it must stay off the boot path.
  let diag = $state<Diagnostics | null>(null);
  let error = $state("");

  $effect(() => {
    const ctl = new AbortController();
    getJson<Diagnostics>("/diagnostics", ctl.signal)
      .then((d) => (diag = d))
      .catch((e) => {
        if (!ctl.signal.aborted) error = String(e?.message ?? e);
      });
    return () => ctl.abort();
  });

  const deps = $derived(
    diag ? Object.entries(diag.deps).filter(([k]) => !k.endsWith("_error")) : [],
  );
</script>

{#if error}
  <p class="err">{error}</p>
{:else if !diag}
  <p class="muted">Sprawdzanie bibliotek…</p>
{:else}
  <div class="status" class:bad={!diag.ok}>
    {diag.ok ? "Wszystkie biblioteki i dekodery dostępne" : "Brakuje bibliotek lub dekoderów"}
  </div>
  <dl>
    <dt>Folder danych</dt>
    <dd class="path">{diag.data_root}</dd>
    <dt>Python</dt>
    <dd>{diag.python}{diag.frozen ? " (PyInstaller)" : " (uv)"}</dd>
  </dl>
  <div class="grid">
    {#each deps as [name, ver] (name)}
      <span class="k">{name}</span>
      <span class="v" class:bad={ver === null} title={diag.deps[`${name}_error`] ?? ""}>
        {ver ?? "brak"}
      </span>
    {/each}
    {#each Object.entries(diag.decoders) as [name, ok] (name)}
      <span class="k">{name.replace("Decoder", "")}</span>
      <span class="v" class:bad={!ok}>{ok ? "tak" : "nie"}</span>
    {/each}
  </div>
{/if}

<style>
  .muted {
    font-size: var(--fs-sm);
    color: var(--text-dim-3);
  }
  .err {
    font-size: var(--fs-sm);
    color: var(--danger);
  }
  .status {
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--ok);
  }
  .status.bad {
    color: var(--danger);
  }
  dl {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 4px 12px;
    font-size: var(--fs-sm);
  }
  dt {
    color: var(--text-dim-3);
  }
  dd {
    color: var(--text-dim-1);
  }
  .path {
    word-break: break-all;
    -webkit-user-select: text;
    user-select: text;
  }
  .grid {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 3px 12px;
    padding: 10px;
    background: var(--bg-deep);
    border-radius: var(--radius-sm);
    font-size: var(--fs-xs);
  }
  .k {
    color: var(--text-dim-2);
  }
  .v {
    color: var(--text-dim-1);
    text-align: right;
  }
  .v.bad {
    color: var(--danger);
  }
</style>
