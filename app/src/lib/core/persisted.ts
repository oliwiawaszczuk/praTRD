// Debounced "save the whole object" helper shared by the workspace and global
// settings stores. One pending timer per store; flush() writes immediately
// (used before switching workspace and on window unload via keepalive).

export interface Saver {
  schedule(): void;
  flush(opts?: { keepalive?: boolean }): Promise<void>;
}

export function debouncedSaver(
  delayMs: number,
  write: (opts: { keepalive: boolean }) => Promise<unknown>,
): Saver {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let dirty = false;

  async function flush(opts: { keepalive?: boolean } = {}): Promise<void> {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    if (!dirty) return;
    dirty = false;
    try {
      await write({ keepalive: opts.keepalive ?? false });
    } catch (e) {
      dirty = true; // retry on next change / flush
      console.error("[persist] save failed", e);
    }
  }

  return {
    schedule() {
      dirty = true;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => void flush(), delayMs);
    },
    flush,
  };
}
