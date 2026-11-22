import { useEffect, useState } from "react";

import { getApiBaseUrl } from "../../config";

type Status = "connecting" | "online" | "offline";

const COPY: Record<Status, string> = {
  connecting: "正在连接服务…",
  online: "服务在线",
  offline: "无法连接服务，请确认后端服务已启动。",
};

/** Shows whether the backend answers its health check. */
export function ApiStatus() {
  const [status, setStatus] = useState<Status>("connecting");

  useEffect(() => {
    let cancelled = false;

    fetch(`${getApiBaseUrl()}/health`)
      .then((response) => {
        if (!response.ok) {
          throw new Error("Health request failed");
        }
        return response.json();
      })
      .then((data: { status: string }) => {
        if (!cancelled) {
          setStatus(data.status === "ok" ? "online" : "offline");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setStatus("offline");
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <p className={`api-status api-status--${status}`} role="status" aria-live="polite">
      <span className="api-status__dot" aria-hidden="true" />
      {COPY[status]}
    </p>
  );
}
