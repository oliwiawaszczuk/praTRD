import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { debouncedSaver } from "./persisted";

describe("debouncedSaver", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("coalesces bursts into one write", async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    const s = debouncedSaver(500, write);
    for (let i = 0; i < 20; i++) s.schedule();
    await vi.advanceTimersByTimeAsync(499);
    expect(write).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(write).toHaveBeenCalledTimes(1);
  });

  it("flush writes immediately, once, and is a no-op when clean", async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    const s = debouncedSaver(500, write);
    s.schedule();
    await s.flush({ keepalive: true });
    expect(write).toHaveBeenCalledWith({ keepalive: true });
    await vi.advanceTimersByTimeAsync(1000);
    await s.flush();
    expect(write).toHaveBeenCalledTimes(1);
  });

  it("keeps the change dirty when a write fails", async () => {
    const write = vi.fn().mockRejectedValueOnce(new Error("down")).mockResolvedValue(undefined);
    vi.spyOn(console, "error").mockImplementation(() => {});
    const s = debouncedSaver(10, write);
    s.schedule();
    await s.flush();
    await s.flush();
    expect(write).toHaveBeenCalledTimes(2);
  });
});
