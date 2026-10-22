// Promise-based modal dialogs. window.prompt/confirm are unavailable in the Tauri
// webview, so every component awaits these instead; one <DialogHost/> renders them.

export type Dialog =
  | {
      kind: "prompt";
      title: string;
      label?: string;
      value: string;
      confirmText: string;
      resolve: (v: string | null) => void;
    }
  | {
      kind: "confirm";
      title: string;
      message: string;
      confirmText: string;
      danger: boolean;
      resolve: (v: boolean) => void;
    }
  | { kind: "alert"; title: string; message: string; error: boolean; resolve: () => void };

let current = $state<Dialog | null>(null);

export const currentDialog = (): Dialog | null => current;

export function closeDialog(): void {
  current = null;
}

export function promptText(
  title: string,
  opts: { label?: string; value?: string; confirmText?: string } = {},
): Promise<string | null> {
  return new Promise((resolve) => {
    current = {
      kind: "prompt",
      title,
      label: opts.label,
      value: opts.value ?? "",
      confirmText: opts.confirmText ?? "OK",
      resolve,
    };
  });
}

export function confirmAction(
  title: string,
  message: string,
  opts: { confirmText?: string; danger?: boolean } = {},
): Promise<boolean> {
  return new Promise((resolve) => {
    current = {
      kind: "confirm",
      title,
      message,
      confirmText: opts.confirmText ?? "OK",
      danger: opts.danger ?? false,
      resolve,
    };
  });
}

function alert(title: string, message: string, error: boolean): Promise<void> {
  return new Promise((resolve) => {
    current = { kind: "alert", title, message, error, resolve };
  });
}

export const showInfo = (title: string, message: string): Promise<void> =>
  alert(title, message, false);

export const showError = (title: string, err: unknown): Promise<void> =>
  alert(title, err instanceof Error ? err.message : String(err), true);
