import { useState, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import { money } from "../lib/format.js";
import { Card, Button, Badge, Loading, ErrorBanner, Empty } from "../components/ui.jsx";
import { Icon } from "../components/icons.jsx";
import { useToast } from "../components/toast.jsx";

const CADENCE_LABEL = { weekly: "a week", monthly: "a month", quarterly: "a quarter", yearly: "a year", unknown: "" };

export default function RefundHunter() {
  const qc = useQueryClient();
  const toast = useToast();
  const [running, setRunning] = useState(false);
  const [busyId, setBusyId] = useState(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["subscriptions"],
    queryFn: api.listSubscriptions,
  });
  const subs = data || [];

  const stats = useMemo(() => {
    const live = subs.filter((s) => s.status !== "cancelled");
    const flagged = subs.filter((s) => s.status === "flagged" || (s.status === "active" && s.stale));
    const saved = subs
      .filter((s) => s.status === "cancelled")
      .reduce((t, s) => t + Number(s.saved_amount || s.annual_cost || 0), 0);
    return {
      total: live.reduce((t, s) => t + Number(s.annual_cost || 0), 0),
      liveCount: live.length,
      atRisk: flagged.reduce((t, s) => t + Number(s.annual_cost || 0), 0),
      flaggedCount: flagged.length,
      saved,
    };
  }, [subs]);

  const detect = async () => {
    setRunning(true);
    try {
      const res = await api.detectSubscriptions();
      qc.invalidateQueries({ queryKey: ["subscriptions"] });
      toast(
        res.detected
          ? `Detected ${res.detected} recurring charge${res.detected > 1 ? "s" : ""}`
          : "No recurring charges found — needs a few months of bank history",
        res.detected ? "ok" : "err"
      );
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setRunning(false);
    }
  };

  const patch = async (sub, body, msg) => {
    setBusyId(sub.id);
    try {
      await api.updateSubscription(sub.id, body);
      qc.invalidateQueries({ queryKey: ["subscriptions"] });
      toast(msg);
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="rise">
      <div className="page-head">
        <div>
          <div className="page-title-row">
            <h1 className="page-title">Refund Hunter</h1>
            <span className="badge badge-primary">Phase 2</span>
          </div>
          <div className="page-sub">
            Recurring charges found across your bank and card ledger. Flag what you don't use and
            draft a cancellation — nothing sends without your approval.
          </div>
        </div>
        <div className="head-actions">
          <Button variant="primary" icon={<Icon.refund size={15} />} onClick={detect} disabled={running}>
            {running ? "Scanning…" : "Run detection"}
          </Button>
        </div>
      </div>

      <ErrorBanner error={error} />

      {/* ---- Savings summary ---- */}
      <div className="grid grid-stats" style={{ marginBottom: 18 }}>
        <Card className="stat">
          <div className="stat-label">Recurring spend</div>
          <div className="stat-value num">{money(stats.total)}</div>
          <div className="stat-foot">{stats.liveCount} active subscriptions, per year</div>
        </Card>
        <Card className="stat">
          <div className="stat-label">Possibly unused</div>
          <div className="stat-value num" style={{ color: stats.atRisk ? "var(--amber)" : undefined }}>
            {money(stats.atRisk)}
          </div>
          <div className="stat-foot">{stats.flaggedCount} flagged, a year at stake</div>
        </Card>
        <Card className="stat">
          <div className="stat-label">Saved</div>
          <div className="stat-value num" style={{ color: stats.saved ? "var(--green)" : undefined }}>
            {money(stats.saved)}
          </div>
          <div className="stat-foot">a year, from cancellations</div>
        </Card>
      </div>

      {/* ---- Subscription list ---- */}
      <Card className="card-pad">
        <div className="card-head">
          <div>
            <div className="card-title">Your subscriptions</div>
            <div className="card-desc">Highest annual cost first.</div>
          </div>
        </div>

        {isLoading ? (
          <Loading />
        ) : subs.length === 0 ? (
          <Empty icon={<Icon.refund size={30} />}>
            No subscriptions detected yet. Run detection to scan your bank statement and ledger for
            recurring charges. (Detection needs a few months of history to spot a pattern.)
          </Empty>
        ) : (
          subs.map((s) => (
            <SubRow key={s.id} sub={s} busy={busyId === s.id} onPatch={patch} />
          ))
        )}
      </Card>
    </div>
  );
}

function SubRow({ sub, busy, onPatch }) {
  const cancelled = sub.status === "cancelled";
  const flagged = sub.status === "flagged" || (sub.status === "active" && sub.stale);

  const statusBadge = cancelled ? (
    <Badge tone="muted" icon={<Icon.check size={12} />}>Cancelled</Badge>
  ) : flagged ? (
    <Badge tone="amber" icon={<Icon.warn size={12} />}>Review</Badge>
  ) : (
    <Badge tone="green">Active</Badge>
  );

  const seen =
    sub.days_since_last == null
      ? null
      : sub.stale
      ? `Not seen in ${sub.days_since_last} days`
      : `Last charged ${sub.days_since_last} days ago`;

  return (
    <div className="litem" style={cancelled ? { opacity: 0.6 } : undefined}>
      <div className="litem-top">
        <div>
          <div className="litem-title">
            {sub.vendor} &nbsp;{statusBadge}
          </div>
          <div className="litem-meta">
            {money(sub.amount)} {CADENCE_LABEL[sub.cadence] || sub.cadence} · seen {sub.occurrences}×
            {seen ? <span className={sub.stale ? "conf-note" : ""}> · {seen}</span> : null}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div className="litem-amt num">{money(sub.annual_cost)}</div>
          <div className="pct num" style={{ fontSize: 11 }}>a year</div>
        </div>
      </div>

      {!cancelled && (
        <div className="litem-actions">
          {flagged ? (
            <Button
              size="sm"
              onClick={() => onPatch(sub, { status: "active" }, `Kept ${sub.vendor}`)}
              disabled={busy}
            >
              Keep it
            </Button>
          ) : (
            <Button
              size="sm"
              onClick={() => onPatch(sub, { status: "flagged" }, `Flagged ${sub.vendor} for review`)}
              disabled={busy}
            >
              Mark unused
            </Button>
          )}
          <button className="btn btn-sm" disabled title="Draft email arrives in the next step (T14)">
            <Icon.mail size={14} /> Draft email
          </button>
          <Button
            size="sm"
            variant="danger-ghost"
            onClick={() =>
              onPatch(
                sub,
                { status: "cancelled" },
                `Cancelled ${sub.vendor} — ${money(sub.annual_cost)}/yr saved`
              )
            }
            disabled={busy}
          >
            Cancel
          </Button>
        </div>
      )}
      {cancelled && (
        <div className="litem-actions">
          <span style={{ fontSize: 12, color: "var(--green)", marginRight: "auto" }}>
            Saving {money(sub.saved_amount || sub.annual_cost)} a year
          </span>
          <Button size="sm" onClick={() => onPatch(sub, { status: "active" }, `Reactivated ${sub.vendor}`)} disabled={busy}>
            Undo
          </Button>
        </div>
      )}
    </div>
  );
}
