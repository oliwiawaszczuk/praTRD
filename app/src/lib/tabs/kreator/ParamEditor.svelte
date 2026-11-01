<script lang="ts">
  // Settings of one parameter (opened by the pencil on the card): name, key in the code,
  // type, range / unit or the options of a choice, tooltip.
  import Icon from "#lib/ui/Icon.svelte";
  import { kreator, touch } from "./kreator.svelte.ts";
  import { validIdent, type ParamType } from "./model.ts";

  let { index, onremove }: { index: number; onremove: () => void } = $props();

  const p = $derived(kreator.draft!.manifest.params[index]);
  const taken = $derived(kreator.draft!.manifest.params.filter((_, j) => j !== index).map((x) => x.key));
  let keyDraft = $state("");
  $effect(() => {
    keyDraft = p.key;
  });
  const keyOk = $derived(validIdent(keyDraft) && !taken.includes(keyDraft));

  const TYPES: { t: ParamType; label: string }[] = [
    { t: "number", label: "1.5" },
    { t: "int", label: "12" },
    { t: "bool", label: "◐" },
    { t: "select", label: "A|B" },
  ];

  function setType(t: ParamType): void {
    if (p.type === t) return;
    p.type = t;
    if (t === "bool") p.default = false;
    else if (t === "select") {
      p.options = p.options?.length ? p.options : [{ value: "a", label: "A" }, { value: "b", label: "B" }];
      p.default = p.options[0].value;
    } else {
      p.default = Number(p.default) || 0;
      p.min ??= 0;
      p.max ??= 10;
      p.step = t === "int" ? 1 : (p.step ?? 0.1);
    }
    touch();
  }

  function num(v: string): number | null {
    return v.trim() === "" || !Number.isFinite(Number(v)) ? null : Number(v);
  }

  function setOpt(i: number, field: "value" | "label", v: string): void {
    const o = p.options![i];
    const wasDefault = p.default === o.value;
    o[field] = v;
    if (field === "value" && wasDefault) p.default = v;
    touch();
  }
</script>

<div class="ed">
  <div class="row">
    <input
      class="lbl"
      value={p.label}
      placeholder="Etykieta"
      oninput={(e) => {
        p.label = e.currentTarget.value;
        touch();
      }}
    />
    <span class="code" class:bad={!keyOk}>
      params.<input
        value={keyDraft}
        title="Nazwa w kodzie"
        oninput={(e) => (keyDraft = e.currentTarget.value)}
        onblur={() => {
          if (keyOk) {
            p.key = keyDraft;
            touch();
          } else keyDraft = p.key;
        }}
      />
    </span>
  </div>
  <div class="row">
    <div class="segs">
      {#each TYPES as t (t.t)}
        <button class:on={p.type === t.t} title={{ number: "Liczba", int: "Całkowita", bool: "Tak / nie", select: "Wybór" }[t.t]} onclick={() => setType(t.t)}>
          {t.label}
        </button>
      {/each}
    </div>
    <button class="del" title="Usuń parametr" onclick={onremove}><Icon name="trash" size={12} /></button>
  </div>
  {#if p.type === "number" || p.type === "int"}
    <div class="row nums">
      {#each [["min", "min"], ["max", "max"], ["step", "krok"]] as const as [k, l] (k)}
        <label
          >{l}<input
            type="number"
            value={p[k] ?? ""}
            onchange={(e) => {
              p[k] = num(e.currentTarget.value);
              touch();
            }}
          /></label
        >
      {/each}
      <label
        >jedn.<input
          class="unit"
          value={p.unit ?? ""}
          maxlength="12"
          placeholder="mm"
          oninput={(e) => {
            p.unit = e.currentTarget.value;
            touch();
          }}
        /></label
      >
    </div>
  {:else if p.type === "select"}
    <div class="opts">
      {#each p.options ?? [] as o, i (i)}
        <div class="opt">
          <input class="ov" value={o.value} title="Wartość w kodzie" oninput={(e) => setOpt(i, "value", e.currentTarget.value)} />
          <input value={o.label} placeholder="Etykieta" oninput={(e) => setOpt(i, "label", e.currentTarget.value)} />
          <button
            class="del"
            title="Usuń opcję"
            disabled={(p.options?.length ?? 0) <= 1}
            onclick={() => {
              p.options!.splice(i, 1);
              if (!p.options!.some((x) => x.value === p.default)) p.default = p.options![0].value;
              touch();
            }}><Icon name="trash" size={11} /></button
          >
        </div>
      {/each}
      <button
        class="addopt"
        onclick={() => {
          const n = (p.options?.length ?? 0) + 1;
          (p.options ??= []).push({ value: `opcja${n}`, label: `Opcja ${n}` });
          touch();
        }}><Icon name="plus" size={11} />opcja</button
      >
    </div>
  {/if}
  <input
    class="help"
    value={p.help ?? ""}
    placeholder="Podpowiedź (tooltip)"
    oninput={(e) => {
      p.help = e.currentTarget.value;
      touch();
    }}
  />
</div>

<style>
  .ed {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin: 0 8px 6px;
    padding: 8px;
    background: var(--bg-deep);
    border: 1px solid var(--accent-a25);
    border-radius: 8px;
    font-size: 0.66rem;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  input {
    min-width: 0;
    padding: 3px 6px;
    font: inherit;
    color: var(--text);
    background: var(--bg-panel);
    border: 1px solid var(--line-2);
    border-radius: 4px;
  }
  input:focus {
    outline: none;
    border-color: var(--accent-a70);
  }
  .lbl {
    flex: 1;
  }
  .code {
    display: flex;
    align-items: center;
    color: var(--text-dim-3);
  }
  .code input {
    width: 90px;
    padding: 2px 4px;
    color: var(--accent);
  }
  .code.bad input {
    border-color: var(--danger);
  }
  .segs {
    display: flex;
    flex: 1;
    border: 1px solid var(--line-2);
    border-radius: 5px;
    overflow: hidden;
  }
  .segs button {
    flex: 1;
    padding: 3px 0;
    font: inherit;
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
  .nums label {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 2px;
    color: var(--text-dim-3);
  }
  .nums input {
    width: 100%;
  }
  .opts {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .opt {
    display: flex;
    gap: 4px;
  }
  .opt input {
    flex: 1;
  }
  .opt .ov {
    flex: 0 0 80px;
    color: var(--accent);
  }
  .del,
  .addopt {
    display: flex;
    align-items: center;
    gap: 3px;
    padding: 3px 5px;
    font: inherit;
    color: var(--text-dim-3);
    background: none;
    border: 0;
    border-radius: 4px;
    cursor: pointer;
  }
  .del:hover {
    color: var(--danger);
  }
  .del:disabled {
    opacity: 0.3;
    cursor: default;
  }
  .addopt {
    align-self: flex-start;
  }
  .addopt:hover {
    color: var(--accent);
  }
  .help {
    color: var(--text-dim-1);
  }
</style>
