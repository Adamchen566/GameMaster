import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ServerConfig } from "../../api/client";
import { LobbyPage } from "./LobbyPage";

const PERSONAS = ["Gawain", "Lancelot", "Tristan", "Galahad", "Bors", "Kay"].map((name) => ({
  name,
  title: `${name} 的称号`,
  manner: "……",
  color: "#e0763c",
}));

/** A server with a DeepSeek key and a logged-in Claude Code, but no Claude key. */
const WITH_MODELS: ServerConfig = {
  llm_available: true,
  gm_ai_available: true,
  drivers: [
    { id: "claude", label: "Claude", available: false, problem: "missing_anthropic_api_key" },
    { id: "deepseek", label: "DeepSeek", available: true, problem: null },
    { id: "claude_code", label: "Claude Code", available: true, problem: null },
  ],
  personas: PERSONAS,
};

function renderLobby(props: Partial<Parameters<typeof LobbyPage>[0]> = {}) {
  const onCreate = vi.fn();
  render(<LobbyPage creating={false} error={null} onCreate={onCreate} {...props} />);
  return { onCreate };
}

function typeName(name = "Adam") {
  fireEvent.change(screen.getByLabelText("昵称"), { target: { value: name } });
}

const BOTS = (count: number) => Array(count).fill("bot");
const options = (overrides = {}) => ({
  seats: BOTS(4),
  spectate: false,
  aiStyle: "baseline",
  gm: "template",
  ...overrides,
});

describe("LobbyPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
  });

  it("creates a game with the trimmed nickname and the chosen player count", () => {
    const { onCreate } = renderLobby();

    typeName("  Adam  ");
    fireEvent.click(screen.getByLabelText("7 人"));
    fireEvent.click(screen.getByRole("button", { name: "创建对局" }));

    expect(onCreate).toHaveBeenCalledExactlyOnceWith("Adam", 7, options({ seats: BOTS(6) }));
  });

  it("defaults to five players, all other seats played by the built-in bot", () => {
    const { onCreate } = renderLobby();

    typeName();
    fireEvent.click(screen.getByRole("button", { name: "创建对局" }));

    expect(onCreate).toHaveBeenCalledWith("Adam", 5, options());
  });

  it("asks for a nickname instead of submitting an empty one", () => {
    const { onCreate } = renderLobby();

    typeName("   ");
    fireEvent.click(screen.getByRole("button", { name: "创建对局" }));

    expect(onCreate).not.toHaveBeenCalled();
    expect(screen.getByText("请输入昵称。")).toBeInTheDocument();
    expect(screen.getByLabelText("昵称")).toHaveAttribute("aria-invalid", "true");
  });

  it("rejects a nickname that is too long", () => {
    const { onCreate } = renderLobby();

    typeName("x".repeat(21));
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
    typeName();
    fireEvent.submit(button.closest("form") as HTMLFormElement);

    expect(button).toBeDisabled();
    expect(onCreate).not.toHaveBeenCalled();
  });

  it("keeps what was typed when the request fails", () => {
    const onCreate = vi.fn();
    const { rerender } = render(<LobbyPage creating={false} error={null} onCreate={onCreate} />);
    typeName();
    fireEvent.click(screen.getByLabelText("8 人"));

    rerender(<LobbyPage creating={false} error="连不上服务器" onCreate={onCreate} />);

    expect(screen.getByRole("alert")).toHaveTextContent("连不上服务器");
    expect(screen.getByLabelText("昵称")).toHaveValue("Adam");
    expect(screen.getByLabelText("8 人")).toBeChecked();
    expect(screen.getByRole("button", { name: "创建对局" })).toBeEnabled();
  });
});

describe("lobby: who plays each seat", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
  });

  it("offers only the built-in bot and no AI host when the server has no model", () => {
    const { onCreate } = renderLobby();

    expect(screen.getByText(/没有配置模型/)).toBeInTheDocument();
    expect(screen.queryByLabelText("AI 主持")).not.toBeInTheDocument();
    expect(screen.queryByText("AI 玩家的打法")).not.toBeInTheDocument();
    for (const select of screen.getAllByRole("combobox")) {
      expect(within(select).getAllByRole("option")).toHaveLength(1);
    }

    typeName();
    fireEvent.click(screen.getByLabelText("关闭"));
    fireEvent.click(screen.getByRole("button", { name: "创建对局" }));

    expect(onCreate).toHaveBeenCalledWith("Adam", 5, options({ gm: "off" }));
  });

  it("shows one row per bot seat, with the character who sits there", () => {
    renderLobby({ config: WITH_MODELS });

    expect(screen.getAllByRole("combobox")).toHaveLength(4);
    expect(screen.getByLabelText("Gawain 由谁来打")).toHaveValue("bot");
    expect(screen.getByText("Gawain 的称号")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("6 人"));
    expect(screen.getAllByRole("combobox")).toHaveLength(5);
  });

  it("says what each model needs, and will not let you pick one that is missing", () => {
    renderLobby({ config: WITH_MODELS });

    const status = screen.getByRole("list", { name: "模型状态" });
    expect(within(status).getByText("没有设置 ANTHROPIC_API_KEY")).toBeInTheDocument();
    expect(within(status).getAllByText("可用")).toHaveLength(2);

    const gawain = screen.getByLabelText("Gawain 由谁来打");
    expect(within(gawain).getByRole("option", { name: "Claude（API）（不可用）" })).toBeDisabled();
    expect(within(gawain).getByRole("option", { name: "DeepSeek（API）" })).toBeEnabled();
    expect(within(gawain).getByRole("option", { name: "本机 Claude Code" })).toBeEnabled();
  });

  it("sends a different model for each seat, with the style and the host", () => {
    const { onCreate } = renderLobby({ config: WITH_MODELS });

    // The style and the cost only matter once a model sits down.
    expect(screen.queryByText("AI 玩家的打法")).not.toBeInTheDocument();
    expect(screen.queryByText(/按量计费/)).not.toBeInTheDocument();

    typeName();
    fireEvent.change(screen.getByLabelText("Gawain 由谁来打"), { target: { value: "deepseek" } });
    fireEvent.change(screen.getByLabelText("Tristan 由谁来打"), {
      target: { value: "claude_code" },
    });
    expect(screen.getByText(/按量计费.*订阅额度/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("谨慎"));
    fireEvent.click(screen.getByLabelText("AI 主持"));
    fireEvent.click(screen.getByRole("button", { name: "创建对局" }));

    expect(onCreate).toHaveBeenCalledWith(
      "Adam",
      5,
      options({ seats: ["deepseek", "bot", "claude_code", "bot"], aiStyle: "cautious", gm: "ai" }),
    );
  });

  it("drops the choices of seats that are no longer at the table", () => {
    const { onCreate } = renderLobby({ config: WITH_MODELS });

    typeName();
    fireEvent.click(screen.getByLabelText("6 人"));
    fireEvent.change(screen.getByLabelText("Bors 由谁来打"), { target: { value: "deepseek" } });
    fireEvent.click(screen.getByLabelText("5 人"));
    fireEvent.click(screen.getByRole("button", { name: "创建对局" }));

    expect(onCreate).toHaveBeenCalledWith("Adam", 5, options());
  });

  it("fills every seat with an AI when you only watch", () => {
    const { onCreate } = renderLobby({ config: WITH_MODELS });

    typeName();
    fireEvent.click(screen.getByLabelText("观战"));

    expect(screen.getByText(/你能看到每个人的身份和心声/)).toBeInTheDocument();
    expect(screen.getAllByRole("combobox")).toHaveLength(5);
    fireEvent.change(screen.getByLabelText("Bors 由谁来打"), { target: { value: "deepseek" } });
    fireEvent.click(screen.getByRole("button", { name: "创建并观战" }));

    expect(onCreate).toHaveBeenCalledWith(
      "Adam",
      5,
      options({ seats: ["bot", "bot", "bot", "bot", "deepseek"], spectate: true }),
    );
  });
});
