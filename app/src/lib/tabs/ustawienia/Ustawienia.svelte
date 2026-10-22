<script lang="ts">
  import Icon from "#lib/ui/Icon.svelte";
  import WorkspacesCard from "./WorkspacesCard.svelte";
  import DiagnosticsCard from "./DiagnosticsCard.svelte";
  import ImportCard from "./ImportCard.svelte";
  import PerformanceCard from "./PerformanceCard.svelte";
</script>

<div class="settings">
  <section class="col">
    <h3><Icon name="layers" /> Workspace'y</h3>
    <WorkspacesCard />
  </section>
  <section class="col">
    <h3><Icon name="folderIn" /> Import i prywatność</h3>
    <ImportCard />
  </section>
  <section class="col">
    <h3><Icon name="cube" /> Wydajność</h3>
    <PerformanceCard />
  </section>
  <section class="col">
    <h3><Icon name="pulse" /> Diagnostyka</h3>
    <DiagnosticsCard />
  </section>
</div>

<style>
  .settings {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
    align-items: start;
    gap: 16px;
    padding: 18px;
  }
  .col {
    display: flex;
    flex-direction: column;
    gap: 10px;
    background: var(--bg-panel-2);
    border: 1px solid var(--line-1);
    border-radius: var(--radius-md);
    padding: 14px;
  }
  h3 {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: var(--fs-md);
    font-weight: 600;
    color: var(--text-strong);
    letter-spacing: 0.04em;
  }
</style>
