import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import { Card, Loading, ErrorBanner, Empty, Modal } from "../components/ui.jsx";

// 0..1 -> "87%"; null/undefined -> "—"
const fpct = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);
const FIELDS = ["vendor", "date", "total", "vat_amount", "vat_rate", "category"];
const FIELD_LABEL = {
  vendor: "Vendor", date: "Date", total: "Total",
  vat_amount: "VAT amount", vat_rate: "VAT rate", category: "Category",
};
const tone = (a) => (a == null ? "accent" : a >= 0.95 ? "good" : a >= 0.8 ? "accent" : "warn");

function Section({ title, note, children }) {
  return (
    <Card style={{ marginBottom: 18 }}>
      <div className="card-head">
        <div className="card-title">{title}</div>
      </div>
      {note ? <p className="me-note">{note}</p> : null}
      {children}
    </Card>
  );
}

function Bar({ label, value, pct, t = "accent" }) {
  return (
    <div className="me-bar-row">
      <span className="me-bar-label">{label}</span>
      <span className="me-bar-track">
        <span className={`me-bar-fill tone-${t}`} style={{ width: `${Math.round((pct ?? 0) * 100)}%` }} />
      </span>
      <span className="me-bar-val num">{value}</span>
    </div>
  );
}

function Stat({ label, value, foot }) {
  return (
    <Card className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value num">{value}</div>
      <div className="stat-foot">{foot}</div>
    </Card>
  );
}

const ASK_EVAL_FIELDS = [
  ["tool_selection", "Right calculation"],
  ["answer_correctness", "Right figure"],
  ["refusal", "Out-of-scope declined"],
  ["faithfulness", "Faithful wording"],
];

// What's behind an accuracy tile: every question it scored, failures first.
function AskQuestionsModal({ metric, label, onClose }) {
  const q = useQuery({ queryKey: ["metrics-ask-questions"], queryFn: api.askEvalQuestions });
  const kind = metric === "refusal" ? "refusal" : "answerable";
  const rows = (q.data?.questions || [])
    .filter((r) => r.kind === kind)
    .sort((a, b) => Number(a[metric] === true) - Number(b[metric] === true));
  const passed = rows.filter((r) => r[metric] === true).length;
  return (
    <Modal title={label} onClose={onClose} width={720}>
      <div className="modal-body">
        <ErrorBanner error={q.error} />
        <p className="me-note">
          {passed}/{rows.length} passed in the last live run. These questions run against a made-up ledger, so they hold none of your data.
        </p>
        {q.isLoading ? (
          <Loading label="Loading questions…" />
        ) : (
          <div className="me-questions">
            {rows.map((r) => {
              const result = r[metric];
              const state = result === true ? "pass" : result === false ? "fail" : "none";
              return (
                <div className="me-question" key={r.id}>
                  <span className={`me-q-mark ${state}`} aria-label={state === "none" ? "not run" : state}>
                    {state === "pass" ? "✓" : state === "fail" ? "✗" : "–"}
                  </span>
                  <span className="me-q-text">
                    {r.question}
                    {r.tools?.length ? <span className="me-q-tools">{[...new Set(r.tools)].join(", ")}</span> : null}
                    {state === "none" ? <span className="me-q-tools">Not run on this machine</span> : null}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Modal>
  );
}

function AskSection() {
  const [openMetric, setOpenMetric] = useState(null);
  const usageQ = useQuery({ queryKey: ["metrics-ask"], queryFn: api.askMetrics });
  const evalQ = useQuery({ queryKey: ["metrics-ask-eval"], queryFn: api.askEvalMetrics });
  const usage = usageQ.data;
  const ev = evalQ.data;

  return (
    <Section
      title="Ask chatbot"
      note={`Accuracy comes from the eval over a fixed synthetic ledger${ev?.run_date ? ` (${ev.model}, run ${ev.run_date})` : ""}. Latency and cost come from your own questions; the question text isn't stored.`}
    >
      <ErrorBanner error={usageQ.error || evalQ.error} />
      {ev?.available ? (
        <>
          <div className="grid grid-stats" style={{ marginBottom: 14 }}>
            {ASK_EVAL_FIELDS.map(([key, label]) => {
              const f = ev.fields?.[key];
              return f ? (
                <button type="button" className="me-stat-btn" key={key} onClick={() => setOpenMetric([key, label])} title="See the questions behind this score">
                  <Stat label={label} value={fpct(f.accuracy)} foot={`${f.correct}/${f.scored} · view questions`} />
                </button>
              ) : null;
            })}
          </div>
        </>
      ) : null}
      {usageQ.isLoading ? (
        <Loading label="Loading traces…" />
      ) : !usage?.total_reads ? (
        <Empty>No questions traced yet. Ask something and it will appear here.</Empty>
      ) : (
        <>
          <div className="grid grid-stats">
            <Stat label="Questions" value={usage.total_reads} foot={`${usage.cached} from cache · ${usage.failed} failed`} />
            <Stat label="Latency" value={`${(usage.latency_ms.p50 / 1000).toFixed(1)}s`}
              foot={`p50 · p95 ${(usage.latency_ms.p95 / 1000).toFixed(1)}s`} />
            <Stat label="Est. cost" value={`$${usage.cost_usd.total.toFixed(4)}`}
              foot={`≈ $${usage.cost_usd.avg.toFixed(4)}/answer`} />
            <Stat label="Tokens" value={`${(usage.tokens.total / 1000).toFixed(1)}k`}
              foot={`${(usage.tokens.input / 1000).toFixed(1)}k in · ${(usage.tokens.output / 1000).toFixed(1)}k out`} />
          </div>
          <div className="me-subhead">Recent questions</div>
          <div className="me-table-wrap">
            <table className="me-table">
              <thead>
                <tr>
                  <th>When</th><th>Model</th><th className="num">Latency</th>
                  <th className="num">Tokens</th><th className="num">Cost</th><th>Calculations</th>
                </tr>
              </thead>
              <tbody>
                {usage.recent.map((t, i) => (
                  <tr key={i}>
                    <td>{t.created_at ? new Date(t.created_at).toLocaleString() : "—"}</td>
                    <td>{t.model}</td>
                    <td className="num">{t.cached ? "cached" : `${((t.latency_ms || 0) / 1000).toFixed(1)}s`}</td>
                    <td className="num">{((t.input_tokens || 0) + (t.output_tokens || 0)) || "—"}</td>
                    <td className="num">{`$${Number(t.est_cost_usd || 0).toFixed(4)}`}</td>
                    <td>
                      {t.success === false ? <span className="me-tag">failed</span> : (t.tools || []).join(", ") || "none"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {openMetric ? <AskQuestionsModal metric={openMetric[0]} label={openMetric[1]} onClose={() => setOpenMetric(null)} /> : null}
    </Section>
  );
}

export default function ModelEvals() {
  const evalQ = useQuery({ queryKey: ["metrics-eval"], queryFn: api.evalMetrics });
  const llmQ = useQuery({ queryKey: ["metrics-llm"], queryFn: api.llmMetrics });

  const ev = evalQ.data;
  const llm = llmQ.data;
  const g = ev?.guardrails;
  const rfc = ev?.receipts_fully_correct;

  return (
    <div className="rise">
      <div className="page-head">
        <div>
          <h1 className="page-title">Model &amp; Evals</h1>
          <div className="page-sub">
            How the receipt reader and Ask perform, whether the guardrails actually catch bad
            reads, and what each call costs — measured, not asserted.
          </div>
        </div>
      </div>

      <ErrorBanner error={evalQ.error || llmQ.error} />

      {/* ---------- Extraction accuracy (offline eval) ---------- */}
      {evalQ.isLoading ? (
        <Loading label="Loading eval…" />
      ) : !ev?.available ? (
        <Section title="Extraction accuracy">
          <Empty>Run <code>backend/scripts/eval_extraction.py</code> over the labelled receipt set to populate this.</Empty>
        </Section>
      ) : (
        <>
          <div className="grid grid-stats" style={{ marginBottom: 18 }}>
            <Stat
              label="Overall field accuracy"
              value={fpct(ev.overall?.accuracy)}
              foot={<>{ev.overall?.correct}/{ev.overall?.scored} fields · {ev.provider} · <b>{ev.model}</b></>}
            />
            <Stat
              label="Receipts fully correct"
              value={fpct(rfc?.n ? rfc.count / rfc.n : null)}
              foot={<>{rfc?.count}/{rfc?.n} receipts, every field right</>}
            />
            <Stat label="Eval set" value={ev.n_receipts} foot={`hand-labelled real receipts · run ${ev.run_date}`} />
          </div>

          <Section title="Accuracy by field">
            <div className="me-bars">
              {FIELDS.map((f) => {
                const fd = ev.fields?.[f];
                if (!fd || !fd.scored) return null;
                return (
                  <Bar key={f} label={FIELD_LABEL[f]} pct={fd.accuracy}
                    value={`${fpct(fd.accuracy)}  (${fd.correct}/${fd.scored})`} t={tone(fd.accuracy)} />
                );
              })}
            </div>
          </Section>

          {g && (
            <Section
              title="Guardrail effectiveness"
              note="Does the review gate catch the reads that are actually wrong? Measured by running the shipped gate over the eval set and comparing its decision to whether each read was correct."
            >
              <div className="grid grid-stats">
                <Stat label="Wrong reads caught" value={fpct(g.guardrail_recall_on_wrong)}
                  foot={`${g.wrong_reads - g.false_auto_posts}/${g.wrong_reads} wrong reads routed to review`} />
                <Stat label="False auto-posts" value={g.false_auto_posts}
                  foot={`a wrong read that still auto-posted (${fpct(g.false_auto_post_rate)} of wrong reads)`} />
                <Stat label="Over-review" value={fpct(g.over_review_rate)}
                  foot={`correct reads held for review (${g.over_reviewed}/${g.correct_reads}) — friction, not risk`} />
              </div>
            </Section>
          )}

          {ev.calibration?.some((b) => b.n) && (
            <Section
              title="Confidence calibration"
              note="Accuracy grouped by the model's self-reported confidence. If the bars don't rise with confidence, that score isn't a trustworthy gate signal on its own."
            >
              <div className="me-bars">
                {ev.calibration.filter((b) => b.n).map((b) => (
                  <Bar key={b.range} label={b.range} pct={b.accuracy}
                    value={`${fpct(b.accuracy)}  (n=${b.n})`} t={tone(b.accuracy)} />
                ))}
              </div>
            </Section>
          )}
        </>
      )}

      {/* ---------- Live LLM operations ---------- */}
      <Section
        title="Live receipt reads"
        note="Every receipt read is traced: latency, tokens, estimated cost and the gate outcome. This is your own usage (nothing synthetic)."
      >
        {llmQ.isLoading ? (
          <Loading label="Loading traces…" />
        ) : !llm?.total_reads ? (
          <Empty>No reads traced yet — upload a receipt and it will appear here.</Empty>
        ) : (
          <>
            <div className="grid grid-stats">
              <Stat label="Reads traced" value={llm.total_reads} foot={`${llm.fell_back} fell back to raw parse`} />
              <Stat label="Latency" value={`${(llm.latency_ms.p50 / 1000).toFixed(1)}s`}
                foot={`p50 · p95 ${(llm.latency_ms.p95 / 1000).toFixed(1)}s`} />
              <Stat label="Est. cost" value={`$${llm.cost_usd.total.toFixed(2)}`}
                foot={`≈ $${llm.cost_usd.avg.toFixed(4)}/read`} />
              <Stat label="Tokens" value={`${(llm.tokens.total / 1000).toFixed(1)}k`}
                foot={`${(llm.tokens.input / 1000).toFixed(1)}k in · ${(llm.tokens.output / 1000).toFixed(1)}k out`} />
            </div>

            <div className="me-subhead">Recent reads</div>
            <div className="me-table-wrap">
              <table className="me-table">
                <thead>
                  <tr>
                    <th>When</th><th>Model</th><th className="num">Latency</th>
                    <th className="num">Tokens</th><th className="num">Cost</th><th>Outcome</th>
                  </tr>
                </thead>
                <tbody>
                  {llm.recent.map((t, i) => (
                    <tr key={i}>
                      <td>{t.created_at ? new Date(t.created_at).toLocaleString() : "—"}</td>
                      <td>{t.model}{t.fell_back ? " ⚠︎" : ""}</td>
                      <td className="num">{t.latency_ms ? `${(t.latency_ms / 1000).toFixed(1)}s` : "—"}</td>
                      <td className="num">{((t.input_tokens || 0) + (t.output_tokens || 0)) || "—"}</td>
                      <td className="num">{t.est_cost_usd != null ? `$${Number(t.est_cost_usd).toFixed(4)}` : "—"}</td>
                      <td>
                        <span className={`me-tag out-${t.gated_to || "none"}`}>{t.gated_to || t.source || "—"}</span>
                        {(t.guardrails_fired || []).length ? (
                          <span className="me-guardrails">{t.guardrails_fired.join(", ")}</span>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Section>

      <AskSection />
    </div>
  );
}
