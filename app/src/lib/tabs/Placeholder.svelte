<script lang="ts">
  import Icon, { type IconName } from "#lib/ui/Icon.svelte";

  let { title, stage, text, icon = "cube" }: {
    title: string;
    stage: string;
    text: string;
    icon?: IconName;
  } = $props();
</script>

<div class="wrap">
  <div class="ph">
    <span class="ic"><Icon name={icon} size={40} /></span>
    <span class="title">{title}</span>
    <span class="stage">{stage}</span>
    <span class="text">{text}</span>
  </div>
</div>

<style>
  .wrap {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .ph {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    max-width: 420px;
    text-align: center;
  }
  .ic {
    color: var(--text-dim-4);
  }
  .title {
    font-size: 1.2rem;
    font-weight: 600;
    color: var(--text-dim-3);
  }
  .stage {
    font-size: var(--fs-xs);
    color: var(--accent);
    background: var(--accent-a10);
    border: 1px solid var(--accent-a25);
    border-radius: var(--radius-sm);
    padding: 2px 8px;
  }
  .text {
    font-size: var(--fs-md);
    color: var(--text-dim-4);
    line-height: 1.7;
  }
</style>
