// Small transient notifications (bottom centre): "Dodano do tablicy ›" and the like.
// An optional action turns the toast into a button.

export interface Toast {
  id: number;
  text: string;
  icon?: string;
  action?: () => void;
  error?: boolean;
}

let list = $state<Toast[]>([]);
let next = 1;

export const toasts = () => list;

export function toast(text: string, opts: { icon?: string; action?: () => void; error?: boolean; ms?: number } = {}): void {
  const t: Toast = { id: next++, text, icon: opts.icon, action: opts.action, error: opts.error };
  list = [...list.slice(-2), t];
  setTimeout(() => dismiss(t.id), opts.ms ?? 3500);
}

export function dismiss(id: number): void {
  list = list.filter((t) => t.id !== id);
}
