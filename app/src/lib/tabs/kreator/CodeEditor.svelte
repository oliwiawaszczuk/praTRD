<script lang="ts">
  // Python editor of a user node — CodeMirror 6, loaded on first use (import()). Completions
  // know the node: `inputs.` → its inputs, `params.` → its parameters, `ctx.` → the helper
  // API, a name bound to an input (`ct = inputs.ct`) → the members of that value, `import` →
  // the available libraries. `inputs.x` / `params.x` / output keys are coloured like on the
  // card (unknown names get a red squiggle). Errors from the sidecar (syntax while typing,
  // traceback line after a test) are drawn on the line.
  import { onMount } from "svelte";
  import type { EditorView as View, DecorationSet, ViewUpdate } from "@codemirror/view";
  import type { StateEffectType } from "@codemirror/state";
  import { PORT_COLORS } from "#lib/graph/types.ts";
  import { importableModules } from "./kreator.svelte.ts";
  import type { CompletionContext, CompletionResult, Completion } from "@codemirror/autocomplete";
  import ProgressRing from "#lib/ui/ProgressRing.svelte";
  import type { Manifest } from "./model.ts";
  import { KIND_IN } from "./model.ts";

  let {
    value,
    manifest,
    errors,
    onchange,
    onsave,
    onrun,
  }: {
    value: string;
    manifest: Manifest;
    errors: { line: number; message: string; severity: "error" | "warning" }[];
    onchange: (code: string) => void;
    onsave: () => void;
    onrun: () => void;
  } = $props();

  let host = $state<HTMLDivElement>();
  let view: View | null = null;
  let loading = $state(true);
  let lint: typeof import("@codemirror/lint") | null = null;

  const VOLUME: [string, string][] = [
    ["array", "tablica numpy [k, j, i] (tylko do odczytu)"],
    ["shape", "(k, j, i)"],
    ["spacing", "mm na woksel (i, j, k)"],
    ["spacing_kji", "mm na woksel w kolejności tablicy — dla scipy"],
    ["origin", "środek woksela (0,0,0), LPS mm"],
    ["direction", "macierz 3×3 kierunków osi"],
    ["geometry", "pełna geometria (do ctx.volume / ctx.grid)"],
    ["voxel_ml", "objętość woksela w ml"],
    ["info", "nazwa, okno, modalność…"],
    ["name", "nazwa wolumenu"],
    ["labels", "etykiety segmentacji [{id, name, color}]"],
    ["to_mm(ijk)", "indeks (i, j, k) → LPS mm"],
    ["to_ijk(xyz)", "LPS mm → indeks (i, j, k)"],
  ];
  const MESH: [string, string][] = [
    ["verts", "wierzchołki [N, 3] w mm (LPS)"],
    ["faces", "trójkąty [M, 3]"],
    ["info", "statystyki: ml, area, closed…"],
  ];
  const CTX: [string, string][] = [
    ["progress(fraction, message=None)", "pasek postępu 0..1 na karcie; tu da się anulować"],
    ["preview", "True w podglądzie (zmniejszone dane)"],
    ["quality", "\"preview\" / \"full\""],
    ["volume(arr, like=None, grid=None, name=None, window=None, color=None, labels=None)", "wynik z ustawieniami"],
    ["grid(like, spacing=None, origin=None, shape=None)", "nowa siatka (np. po zmianie rozdzielczości)"],
    ["mesh(verts, faces, name=None, color=None)", "mesh z nazwą i kolorem"],
    ["table(rows, columns=None, chart=None, title='')", "tabela; chart: bars / histogram / line"],
    ["raw", "wewnętrzny kontekst (zaawansowane)"],
  ];

  const opt = (label: string, detail: string, type: string): Completion => {
    const call = label.indexOf("(");
    return call > 0
      ? { label: label.slice(0, call), detail: label.slice(call), info: detail, type, apply: label.slice(0, call) + "(" }
      : { label, info: detail, type };
  };

  function members(obj: string, doc: string): Completion[] | null {
    const m = manifest;
    if (obj === "inputs") return m.inputs.map((p) => opt(p.id, `${p.label} · ${KIND_IN[p.kind]}`, "property"));
    if (obj === "params")
      return m.params.map((p) => opt(p.key, `${p.label}${p.unit ? ` [${p.unit}]` : ""} · domyślnie ${String(p.default)}`, "property"));
    if (obj === "ctx") return CTX.map(([l, d]) => opt(l, d, "method"));
    // `x = inputs.<id>` (or `inputs["<id>"]`) → members of that input's value
    const bound = new RegExp(`\\b${obj}\\s*(?:,[^=\\n]*)?=\\s*inputs(?:\\.(\\w+)|\\["(\\w+)"\\])`).exec(doc);
    const id = bound?.[1] ?? bound?.[2];
    const port = m.inputs.find((p) => p.id === id);
    if (!port) return null;
    if (port.kind === "mesh") return MESH.map(([l, d]) => opt(l, d, "property"));
    if (["wolumen", "segment", "segmentacja"].includes(port.kind)) return VOLUME.map(([l, d]) => opt(l, d, "property"));
    return null;
  }

  function complete(ctx: CompletionContext): CompletionResult | null {
    const imp = ctx.matchBefore(/^\s*(?:import|from)\s+\w*$/);
    if (imp) {
      const word = /\w*$/.exec(imp.text)![0];
      const mods = importableModules().map((name) => ({ label: name, type: "namespace", info: "dostępna biblioteka" }));
      return { from: imp.to - word.length, options: mods, validFor: /^\w*$/ };
    }
    const m = ctx.matchBefore(/(\w+)\.(\w*)$/);
    if (!m) return null;
    const [obj, part] = m.text.split(".");
    const list = members(obj, ctx.state.doc.toString());
    if (!list) return null;
    return { from: m.to - part.length, options: list, validFor: /^\w*$/ };
  }

  // ── colouring of node names in the code (visible lines only) ──
  let refresh: StateEffectType<null> | null = null;
  type Mk = { from: number; to: number; color: string | null; title: string };
  function refs(text: string, offset: number): Mk[] {
    const m = manifest;
    const out: Mk[] = [];
    for (const r of text.matchAll(/\b(inputs|params)\.([A-Za-z_]\w*)/g)) {
      const from = offset + r.index! + r[1].length + 1;
      if (r[1] === "inputs") {
        const p = m.inputs.find((x) => x.id === r[2]);
        out.push({ from, to: from + r[2].length, color: p ? PORT_COLORS[p.kind] : null, title: p ? p.label : "Nie ma takiego wejścia na karcie" });
      } else {
        const p = m.params.find((x) => x.key === r[2]);
        out.push({ from, to: from + r[2].length, color: p ? "var(--param)" : null, title: p ? p.label : "Nie ma takiego parametru na karcie" });
      }
    }
    for (const r of text.matchAll(/(["'])(\w+)\1(?=\s*:)/g)) {
      const o = m.outputs.find((x) => x.id === r[2]);
      if (o) out.push({ from: offset + r.index!, to: offset + r.index! + r[0].length, color: PORT_COLORS[o.kind], title: `wyjście: ${o.label}` });
    }
    return out.sort((a, b) => a.from - b.from);
  }

  onMount(() => {
    let alive = true;
    void (async () => {
      const [cm, st, viewMod, lang, py, auto, cmds, hl, ln] = await Promise.all([
        import("codemirror"),
        import("@codemirror/state"),
        import("@codemirror/view"),
        import("@codemirror/language"),
        import("@codemirror/lang-python"),
        import("@codemirror/autocomplete"),
        import("@codemirror/commands"),
        import("@lezer/highlight"),
        import("@codemirror/lint"),
      ]);
      if (!alive || !host) return;
      lint = ln;
      const t = hl.tags;
      const style = lang.HighlightStyle.define([
        { tag: [t.keyword, t.controlKeyword, t.definitionKeyword, t.moduleKeyword], color: "var(--code-keyword)" },
        { tag: [t.string, t.special(t.string)], color: "var(--code-string)" },
        { tag: [t.number, t.bool, t.null], color: "var(--code-number)" },
        { tag: t.comment, color: "var(--text-dim-3)", fontStyle: "italic" },
        { tag: [t.function(t.variableName), t.function(t.propertyName)], color: "var(--code-function)" },
        { tag: t.definition(t.variableName), color: "var(--accent)" },
        { tag: t.propertyName, color: "var(--text)" },
        { tag: [t.operator, t.punctuation], color: "var(--text-dim-1)" },
        { tag: t.self, color: "var(--code-self)" },
      ]);
      const theme = viewMod.EditorView.theme(
        {
          "&": { height: "100%", fontSize: "12.5px", background: "var(--bg-deep)", color: "var(--text)" },
          ".cm-scroller": { fontFamily: "var(--font)", lineHeight: "1.55" },
          ".cm-content": { caretColor: "var(--accent)", padding: "8px 0" },
          ".cm-cursor": { borderLeftColor: "var(--accent)" },
          ".cm-gutters": { background: "var(--bg-deep)", color: "var(--text-dim-4)", border: "none" },
          ".cm-activeLine, .cm-activeLineGutter": { background: "rgba(255,255,255,0.035)" },
          "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection": {
            background: "var(--accent-a25) !important",
          },
          ".cm-matchingBracket": { background: "var(--accent-a25)", outline: "none" },
          ".cm-tooltip": { background: "var(--bg-panel-2)", border: "1px solid var(--line-2)", borderRadius: "6px" },
          ".cm-tooltip-autocomplete ul li[aria-selected]": { background: "var(--accent-a25)", color: "var(--text-strong)" },
          ".cm-completionInfo": { maxWidth: "360px", padding: "6px 9px", color: "var(--text-dim-1)" },
          ".cm-completionDetail": { color: "var(--text-dim-3)", fontStyle: "normal", marginLeft: "4px" },
          ".cm-diagnostic-error": { borderLeft: "3px solid var(--danger)" },
          ".cm-lintRange-error": { backgroundImage: "none", textDecoration: "underline wavy var(--danger)" },
          ".cm-panels": { background: "var(--bg-panel-2)", color: "var(--text)" },
          ".cm-ref, .cm-ref span": { color: "var(--c) !important", fontWeight: "600" },
          ".cm-ref-bad": { textDecoration: "underline wavy var(--danger)" },
        },
        { dark: true },
      );
      refresh = st.StateEffect.define<null>();
      const markOf = (k: Mk) =>
        k.color
          ? viewMod.Decoration.mark({ class: "cm-ref", attributes: { style: `--c:${k.color}`, title: k.title } })
          : viewMod.Decoration.mark({ class: "cm-ref-bad", attributes: { title: k.title } });
      const build = (v: View): DecorationSet => {
        const b = new st.RangeSetBuilder<import("@codemirror/view").Decoration>();
        for (const { from, to } of v.visibleRanges) for (const k of refs(v.state.doc.sliceString(from, to), from)) b.add(k.from, k.to, markOf(k));
        return b.finish();
      };
      const colouring = viewMod.ViewPlugin.fromClass(
        class {
          decorations: DecorationSet;
          constructor(v: View) {
            this.decorations = build(v);
          }
          update(u: ViewUpdate) {
            if (u.docChanged || u.viewportChanged || u.transactions.some((t) => t.effects.some((e) => e.is(refresh!))))
              this.decorations = build(u.view);
          }
        },
        { decorations: (p) => p.decorations },
      );
      const keys = viewMod.keymap.of([
        { key: "Mod-s", preventDefault: true, run: () => (onsave(), true) },
        { key: "Mod-Enter", preventDefault: true, run: () => (onrun(), true) },
        cmds.indentWithTab,
      ]);
      view = new viewMod.EditorView({
        parent: host,
        state: st.EditorState.create({
          doc: value,
          extensions: [
            st.Prec.highest(keys),
            cm.basicSetup,
            py.python(),
            py.pythonLanguage.data.of({ autocomplete: complete }),
            auto.autocompletion({ activateOnTyping: true }),
            lang.syntaxHighlighting(style),
            colouring,
            viewMod.EditorView.lineWrapping, // narrow column between the card and the test panel
            theme,
            ln.lintGutter(),
            st.EditorState.tabSize.of(4),
            lang.indentUnit.of("    "),
            viewMod.EditorView.updateListener.of((u) => {
              if (u.docChanged) onchange(u.state.doc.toString());
            }),
          ],
        }),
      });
      loading = false;
      showErrors();
    })();
    return () => {
      alive = false;
      view?.destroy();
      view = null;
    };
  });

  // external change (another node opened, template) → replace the document
  $effect(() => {
    const v = value;
    if (view && v !== view.state.doc.toString()) {
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: v } });
    }
  });

  $effect(() => {
    void errors;
    showErrors();
  });

  // sockets / parameters renamed on the card → recolour the code
  $effect(() => {
    void JSON.stringify([manifest.inputs, manifest.outputs, manifest.params.map((p) => p.key)]);
    if (view && refresh) view.dispatch({ effects: refresh.of(null) });
  });

  /** Add an import line at the top (after the existing imports) unless it is there. */
  export function addImport(line: string): void {
    if (!view) return;
    const doc = view.state.doc;
    if (doc.toString().split("\n").some((l) => l.trim() === line)) return;
    let at = 0;
    for (let n = 1; n <= doc.lines; n++) {
      const l = doc.line(n);
      if (/^(import|from)\s/.test(l.text)) at = l.to + 1;
      else if (l.text.trim() && !l.text.startsWith("#")) break;
    }
    at = Math.min(at, doc.length);
    view.dispatch({ changes: { from: at, insert: `${line}\n` } });
  }

  function showErrors(): void {
    if (!view || !lint) return;
    const doc = view.state.doc;
    const diags = errors
      .filter((e) => e.line >= 1 && e.line <= doc.lines)
      .map((e) => {
        const l = doc.line(e.line);
        return { from: l.from, to: l.to, severity: e.severity, message: e.message };
      });
    view.dispatch(lint.setDiagnostics(view.state, diags));
  }

  /** Insert at the cursor (chips above the editor). */
  export function insert(text: string): void {
    if (!view) return;
    const { from, to } = view.state.selection.main;
    view.dispatch({ changes: { from, to, insert: text }, selection: { anchor: from + text.length } });
    view.focus();
  }

  export function goto(line: number): void {
    if (!view) return;
    const l = view.state.doc.line(Math.min(Math.max(1, line), view.state.doc.lines));
    view.dispatch({ selection: { anchor: l.from, head: l.to }, scrollIntoView: true });
    view.focus();
  }
</script>

<div class="editor" bind:this={host}>
  {#if loading}<div class="loading"><ProgressRing size={22} /></div>{/if}
</div>

<style>
  .editor {
    position: relative;
    flex: 1;
    min-height: 0;
    overflow: hidden;
    background: var(--bg-deep);
  }
  .editor :global(.cm-editor) {
    height: 100%;
  }
  .editor :global(.cm-editor.cm-focused) {
    outline: none;
  }
  .loading {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
  }
</style>
