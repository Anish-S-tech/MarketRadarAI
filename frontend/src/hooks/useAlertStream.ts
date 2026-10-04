import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useToast } from "@/components/ui/toast";
import { tokenStore } from "@/lib/tokens";

interface AlertMessage {
  type: "alert";
  alert_id: string;
  event_id: string;
  title: string;
  priority: string;
  competitor: string;
}

/** Subscribes to server-sent alert events; refreshes cached queries and shows a toast. Reconnects with backoff. */
export function useAlertStream(enabled: boolean) {
  const qc = useQueryClient();
  const toast = useToast();

  useEffect(() => {
    if (!enabled) return;
    let es: EventSource | null = null;
    let retry = 1000;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;

    const connect = async () => {
      const token = await tokenStore.freshAccessToken();
      if (!token || closed) return;
      es = new EventSource(`/api/v1/stream?token=${encodeURIComponent(token)}`);
      es.addEventListener("ready", () => {
        retry = 1000;
      });
      es.addEventListener("alert", (e) => {
        const msg = JSON.parse((e as MessageEvent).data) as AlertMessage;
        toast({ title: msg.title, priority: msg.priority, href: `/events/${msg.event_id}`, body: msg.competitor });
        qc.invalidateQueries({ queryKey: ["alerts"] });
        qc.invalidateQueries({ queryKey: ["events"] });
        qc.invalidateQueries({ queryKey: ["stats"] });
      });
      es.onerror = () => {
        es?.close();
        if (!closed) {
          timer = setTimeout(connect, retry);
          retry = Math.min(retry * 2, 30_000);
        }
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      es?.close();
    };
  }, [enabled, qc, toast]);
}
