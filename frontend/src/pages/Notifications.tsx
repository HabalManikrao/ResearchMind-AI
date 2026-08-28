import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCheck, Trash2, CheckCircle2, XCircle, Clock, Bell } from "lucide-react";
import { api } from "../api/client";
import type { Notification } from "../api/types";
import { Card } from "../components/ui";

const ICONS: Record<string, typeof Bell> = {
  research_completed: CheckCircle2,
  research_failed: XCircle,
  schedule_run: Clock,
  info: Bell,
};

const ICON_COLOR: Record<string, string> = {
  research_completed: "text-emerald-500",
  research_failed: "text-red-500",
  schedule_run: "text-brand-500",
  info: "text-slate-400",
};

export default function Notifications() {
  const [items, setItems] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);

  const load = () =>
    api.listNotifications().then(setItems).finally(() => setLoading(false));

  useEffect(() => {
    load();
  }, []);

  const markRead = async (n: Notification) => {
    if (!n.read) {
      await api.markNotificationRead(n.id);
      setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, read: true } : x)));
    }
  };
  const markAll = async () => {
    await api.markAllNotificationsRead();
    await load();
  };
  const remove = async (n: Notification) => {
    await api.deleteNotification(n.id);
    setItems((prev) => prev.filter((x) => x.id !== n.id));
  };

  const unread = items.filter((n) => !n.read).length;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Notifications</h1>
          <p className="text-slate-500">
            {unread > 0 ? `${unread} unread` : "You're all caught up."}
          </p>
        </div>
        {unread > 0 && (
          <button
            onClick={markAll}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
          >
            <CheckCheck className="h-4 w-4" /> Mark all read
          </button>
        )}
      </div>

      {loading ? (
        <p className="text-slate-500">Loading…</p>
      ) : items.length === 0 ? (
        <Card>
          <p className="text-slate-500">No notifications yet.</p>
        </Card>
      ) : (
        <div className="space-y-2">
          {items.map((n) => {
            const Icon = ICONS[n.type] ?? Bell;
            return (
              <Card
                key={n.id}
                className={`flex items-start gap-3 ${n.read ? "" : "border-brand-300 bg-brand-50/40"}`}
              >
                <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${ICON_COLOR[n.type] ?? "text-slate-400"}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-slate-900">{n.title}</span>
                    {!n.read && <span className="h-2 w-2 rounded-full bg-brand-500" />}
                  </div>
                  {n.message && <p className="text-sm text-slate-600">{n.message}</p>}
                  <div className="mt-1 flex items-center gap-3 text-xs text-slate-400">
                    <span>{new Date(n.created_at).toLocaleString()}</span>
                    {n.project_id && (
                      <Link
                        to={`/research/${n.project_id}`}
                        className="text-brand-600 hover:underline"
                      >
                        View research
                      </Link>
                    )}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {!n.read && (
                    <button
                      onClick={() => markRead(n)}
                      title="Mark read"
                      className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100"
                    >
                      <CheckCircle2 className="h-4 w-4" />
                    </button>
                  )}
                  <button
                    onClick={() => remove(n)}
                    title="Delete"
                    className="rounded-md p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-500"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
