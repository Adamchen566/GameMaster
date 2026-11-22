import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

describe("API status", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a connecting state while the health request is pending", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));

    render(<App />);

    expect(screen.getByText("正在连接议会…")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith("/api/health");
  });

  it("shows an online state after a successful health response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: "ok" }),
      }),
    );

    render(<App />);

    expect(await screen.findByText("服务在线")).toBeInTheDocument();
  });

  it("shows a useful failure state when the API cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network unavailable")));

    render(<App />);

    expect(await screen.findByText("无法连接服务")).toBeInTheDocument();
    expect(screen.getByText("请确认后端已在 8000 端口运行。")).toBeInTheDocument();
  });
});
