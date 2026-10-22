<script lang="ts">
  // Loading indicator: indeterminate spinning arc, or a determinate ring when `value` (0..1) is known.
  let { value = null, size = 44, label = "" }: { value?: number | null; size?: number; label?: string } = $props();
  const r = $derived(size / 2 - 3);
  const c = $derived(2 * Math.PI * r);
</script>

<div class="ring" style:width="{size}px" style:height="{size}px">
  <svg width={size} height={size} viewBox="0 0 {size} {size}" class:spin={value === null}>
    <circle cx={size / 2} cy={size / 2} {r} class="track" />
    <circle
      cx={size / 2}
      cy={size / 2}
      {r}
      class="arc"
      stroke-dasharray={c}
      stroke-dashoffset={value === null ? c * 0.72 : c * (1 - Math.min(1, Math.max(0, value)))}
    />
  </svg>
  {#if value !== null}<span class="pct">{Math.round(value * 100)}</span>{/if}
  {#if label}<span class="label">{label}</span>{/if}
</div>

<style>
  .ring {
    position: relative;
    display: inline-flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }
  svg {
    transform: rotate(-90deg);
  }
  svg.spin {
    animation: spin 0.9s linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(270deg);
    }
  }
  circle {
    fill: none;
    stroke-width: 3;
  }
  .track {
    stroke: rgba(255, 255, 255, 0.1);
  }
  .arc {
    stroke: var(--accent);
    stroke-linecap: round;
    transition: stroke-dashoffset 0.2s ease;
    filter: drop-shadow(0 0 4px var(--accent-a70));
  }
  .pct {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    font-size: 0.66rem;
    font-weight: 600;
    color: var(--accent);
  }
  .label {
    position: absolute;
    top: calc(100% + 6px);
    white-space: nowrap;
    font-size: var(--fs-xs);
    color: var(--text-dim-2);
  }
</style>
