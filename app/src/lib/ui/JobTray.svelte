<script lang="ts">
  // Floating list of background jobs (bottom-right). Running/queued jobs always shown;
  // finished ones linger briefly, errors stay until dismissed.
  import { allJobs, cancelJob, isStaleJob, type Job } from "#lib/core/events.svelte.ts";
  import Icon from "./Icon.svelte";

  const LINGER_MS = 4000;
  let dismissed = $state<Set<string>>(new Set());
  let now = $state(Date.now());

  $effect(() => {
    const t = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(t);
  });

  // Completion time is not sent by the sidecar; remember when we first saw it finished.
  const finishedAt = new Map<string, number>();

  const visible = $derived(
    allJobs().filter((j) => {
      // scans and graph runs report in place (import dialog / node cards / graph toolbar)
      if (dismissed.has(j.id) || j.kind === "scan" || j.kind === "graph" || isStaleJob(j.id)) return false;
      if (j.state === "running" || j.state === "queued" || j.state === "error") return true;
      if (!finishedAt.has(j.id)) finishedAt.set(j.id, now);
      return now - (finishedAt.get(j.id) ?? now) < LINGER_MS;
    }),
  );

  const label: Record<Job["state"], string> = {
    queued: "W kolejce",
    running: "",
    done: "Gotowe",
    error: "Błąd",
    cancelled: "Anulowano",
  };

  const dismiss = (id: string) => (dismissed = new Set(dismissed).add(id));
</script>

{#if visible.length}
  <div class="tray">
    {#each visible as j (j.id)}
      <div class="job {j.state}">
        <div class="top">
          <span class="title">{j.title}</span>
          {#if j.state === "running" || j.state === "queued"}
            <button class="x" title="Anuluj" onclick={() => cancelJob(j.id)}>✕</button>
          {:else if j.state === "error"}
            <button class="x" title="Zamknij" onclick={() => dismiss(j.id)}>✕</button>
          {/if}
        </div>
        {#if j.state === "running"}
          <div class="track"><div class="bar" style:transform="scaleX({j.progress})"></div></div>
          <span class="msg">{j.message} · {Math.round(j.progress * 100)}%</span>
        {:else if j.state === "error"}
          <span class="msg err"><Icon name="alert" size={11} /> {j.error}</span>
        {:else}
          <span class="msg">{label[j.state]}</span>
        {/if}
      </div>
    {/each}
  </div>
{/if}

<style>
  .tray {
    position: fixed;
    right: 16px;
    bottom: 16px;
    z-index: 800;
    width: 320px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .job {
    padding: 9px 11px;
    background: var(--bg-panel);
    border: 1px solid var(--line-2);
    border-radius: var(--radius-md);
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.4);
    display: flex;
    flex-direction: column;
    gap: 6px;
    animation: slide 0.2s ease;
  }
  .job.error {
    border-color: var(--danger);
  }
  .job.done {
    border-color: var(--accent-a30);
  }
  .top {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .title {
    flex: 1;
    min-width: 0;
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .x {
    background: none;
    border: none;
    color: var(--text-dim-3);
    cursor: pointer;
    font-size: 0.7rem;
  }
  .x:hover {
    color: var(--danger);
  }
  .track {
    height: 3px;
    background: var(--line-1);
    border-radius: 2px;
    overflow: hidden;
  }
  /* transform instead of width: compositor-only, no layout per progress tick */
  .bar {
    height: 100%;
    background: var(--accent);
    transform-origin: left;
    transition: transform 0.15s linear;
    box-shadow: 0 0 6px var(--accent-a70);
  }
  .msg {
    font-size: var(--fs-xs);
    color: var(--text-dim-3);
    display: flex;
    gap: 5px;
    align-items: center;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .msg.err {
    color: var(--danger);
    white-space: normal;
  }
  @keyframes slide {
    from {
      opacity: 0;
      transform: translateY(8px);
    }
  }
</style>
