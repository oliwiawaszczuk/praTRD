<script lang="ts" module>
  // Hand-written 24×24 stroke icons (praSzczur convention: inline SVG, currentColor, no emoji).
  const PATHS = {
    plus: "M12 5v14M5 12h14",
    trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
    edit: "M4 20h4L19 9l-4-4L4 16v4zM13 7l4 4",
    check: "M5 12l5 5L20 7",
    folderIn: "M3 7h6l2 2h10v10H3zM12 17v-6M9 14l3 3 3-3",
    folderOut: "M3 7h6l2 2h10v10H3zM12 11v6M9 14l3-3 3 3",
    layers: "M12 3l9 5-9 5-9-5 9-5zM3 13l9 5 9-5",
    pulse: "M3 12h4l3-7 4 14 3-7h4",
    cube: "M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3zM12 12l8-4.5M12 12v9M12 12L4 7.5",
    alert: "M12 4l9 16H3L12 4zM12 10v4M12 17v.5",
    info: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 11v6M12 7.5v.5",
    undo: "M9 14L4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3",
    redo: "M15 14l5-5-5-5M20 9H9a5 5 0 0 0 0 10h3",
    play: "M7 4l13 8-13 8z",
    search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5",
    download: "M12 4v11M7 10l5 5 5-5M5 20h14",
    table: "M4 5h16v14H4zM4 10h16M4 15h16M10 5v14",
  } as const;
  export type IconName = keyof typeof PATHS;
</script>

<script lang="ts">
  let { name, size = 14 }: { name: IconName; size?: number } = $props();
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="1.8"
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
>
  <path d={PATHS[name]} />
</svg>
