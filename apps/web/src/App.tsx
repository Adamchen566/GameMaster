import { useEffect, useState } from "react";

import "./styles.css";

type ApiStatus = "connecting" | "online" | "offline";

export default function App() {
  const [status, setStatus] = useState<ApiStatus>("connecting");

  useEffect(() => {
    fetch("/api/health")
      .then((response) => {
        if (!response.ok) {
          throw new Error("Health request failed");
        }

        return response.json();
      })
      .then((data: { status: string }) => {
        if (data.status === "ok") {
          setStatus("online");
        } else {
          setStatus("offline");
        }
      })
      .catch(() => {
        setStatus("offline");
      });
  }, []);

  const copy = {
    connecting: {
      eyebrow: "Council gateway · 00",
      title: "召集圆桌",
      message: "正在连接议会…",
      detail: "正在确认主持服务与规则引擎的状态。",
    },
    online: {
      eyebrow: "Council gateway · 01",
      title: "议会已响应",
      message: "服务在线",
      detail: "通往阿瓦隆的道路已经开启。",
    },
    offline: {
      eyebrow: "Council gateway · 02",
      title: "城门暂闭",
      message: "无法连接服务",
      detail: "请确认后端已在 8000 端口运行。",
    },
  }[status];

  return (
    <main className={`gateway gateway--${status}`}>
      <div className="gateway__atmosphere" aria-hidden="true" />

      <section className="gateway__panel" aria-labelledby="gateway-title">
        <p className="gateway__eyebrow">{copy.eyebrow}</p>

        <div className="council-seal" aria-hidden="true">
          <span className="council-seal__core" />
        </div>

        <div className="gateway__copy">
          <h1 id="gateway-title">{copy.title}</h1>
          <div className="gateway__status" role="status" aria-live="polite">
            <span className="gateway__status-dot" aria-hidden="true" />
            <p>{copy.message}</p>
          </div>
          <p className="gateway__detail">{copy.detail}</p>
        </div>

        <footer className="gateway__footer">
          <span>5–12 seats</span>
          <span aria-hidden="true">◆</span>
          <span>Human + AI</span>
        </footer>
      </section>
    </main>
  );
}
