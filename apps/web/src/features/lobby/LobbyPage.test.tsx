import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LobbyPage } from "./LobbyPage";

function renderLobby(props: Partial<Parameters<typeof LobbyPage>[0]> = {}) {
  const onCreate = vi.fn();
  render(<LobbyPage creating={false} error={null} onCreate={onCreate} {...props} />);
  return { onCreate };
}

const DEFAULT_OPTIONS = { aiSeats: 0, aiStyle: "baseline", gm: "template" };

describe("LobbyPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
  });

  it("creates a game with the trimmed nickname and the chosen player count", () => {
    const { onCreate } = renderLobby();

    fireEvent.change(screen.getByLabelText("昵称"), { target: { value: "  Adam  " } });
    fireEvent.click(screen.getByLabelText("7 人"));
    fireEvent.click(screen.getByRole("button", { name: "创建对局" }));

    expect(onCreate).toHaveBeenCalledExactlyOnceWith("Adam", 7, DEFAULT_OPTIONS);
  });

  it("defaults to five players", () => {
    const { onCreate } = renderLobby();

    fireEvent.change(screen.getByLabelText("昵称"), { target: { value: "Adam" } });
    fireEvent.click(screen.getByRole("button", { name: "创建对局" }));

    expect(onCreate).toHaveBeenCalledWith("Adam", 5, DEFAULT_OPTIONS);
  });

  it("asks for a nickname instead of submitting an empty one", () => {
    const { onCreate } = renderLobby();

    fireEvent.change(screen.getByLabelText("昵称"), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "创建对局" }));

    expect(onCreate).not.toHaveBeenCalled();
    expect(screen.getByText("请输入昵称。")).toBeInTheDocument();
    expect(screen.getByLabelText("昵称")).toHaveAttribute("aria-invalid", "true");
  });

  it("rejects a nickname that is too long", () => {
    const { onCreate } = renderLobby();

    fireEvent.change(screen.getByLabelText("昵称"), { target: { value: "x".repeat(21) } });
    fireEvent.click(screen.getByRole("button", { name: "创建对局" }));

    expect(onCreate).not.toHaveBeenCalled();
    expect(screen.getByText("昵称最多 20 个字。")).toBeInTheDocument();
  });

  it("does not complain before the player has typed or submitted anything", () => {
    renderLobby();

    expect(screen.queryByText("请输入昵称。")).not.toBeInTheDocument();
  });

  it("cannot be submitted twice while the room is being created", () => {
    const { onCreate } = renderLobby({ creating: true });

    const button = screen.getByRole("button", { name: "正在创建…" });
    fireEvent.change(screen.getByLabelText("昵称"), { target: { value: "Adam" } });
    fireEvent.submit(button.closest("form") as HTMLFormElement);

    expect(button).toBeDisabled();
    expect(onCreate).not.toHaveBeenCalled();
  });

  it("keeps what was typed when the request fails", () => {
    const onCreate = vi.fn();
    const { rerender } = render(<LobbyPage creating={false} error={null} onCreate={onCreate} />);
    fireEvent.change(screen.getByLabelText("昵称"), { target: { value: "Adam" } });
    fireEvent.click(screen.getByLabelText("8 人"));

    rerender(<LobbyPage creating={false} error="连不上服务器" onCreate={onCreate} />);

    expect(screen.getByRole("alert")).toHaveTextContent("连不上服务器");
    expect(screen.getByLabelText("昵称")).toHaveValue("Adam");
    expect(screen.getByLabelText("8 人")).toBeChecked();
    expect(screen.getByRole("button", { name: "创建对局" })).toBeEnabled();
  });
});
