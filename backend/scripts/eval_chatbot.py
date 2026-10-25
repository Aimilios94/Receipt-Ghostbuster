"""Chatbot eval harness (v0.5 Slice 2).

Measures the quality of the NL Q&A chatbot (`/ask`, [D40]) — the LLM's actual job
there is to SELECT and PARAMETERISE the right analytics tool; every number is then
computed in code (`services/analytics.py`, [D1]). This harness scores that, over a
fixed SYNTHETIC ledger so it is reproducible and public-safe (unlike the git-ignored
extraction receipts).

Three things are scored (see docs/design/chatbot.md "Evaluation"):

  * answer_correctness — the computed figure is correct. Graded in CODE, no judge:
    dispatch the tool over the fixed ledger and deep-subset-compare the structured
    result to the committed expected answer. Deterministic → runs offline, in CI.
  * tool_selection    — did the model call the RIGHT tool with the RIGHT args? The
    key metric (the LLM's real job). Needs the model → local run, cached.
  * refusal           — out-of-scope questions (weather, stock tips, another user's
    data) must be DECLINED — a correct refusal calls NO analytics tool.

Prose faithfulness (does the sentence follow from the numbers?) is deliberately NOT
graded here — that is the calibrated LLM-as-judge in Slice 3. We verify the number is
tool-derived, consistent with D1.

Two modes, mirroring the extraction eval's "real number local / deterministic mock in CI":

    # offline, no API key, deterministic — this is what CI runs
    python scripts/eval_chatbot.py --check \
        --metrics-out eval/chatbot/metrics.mock.json \
        --results-out eval/chatbot/RESULTS.mock.md

    # the real numbers (needs OPENAI_API_KEY, LLM_PROVIDER=openai); per-question cached
    python scripts/eval_chatbot.py --live          # writes eval/chatbot/metrics.json + RESULTS.md
    python scripts/eval_chatbot.py --live --refresh # ignore the cache, re-call the model

Gate the result with the shared regression gate:
    python scripts/check_regression.py --metrics eval/chatbot/metrics.json --baseline eval/chatbot/baseline.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
EVAL_DIR = BACKEND / "eval" / "chatbot"
LEDGER = EVAL_DIR / "ledger.json"
QUESTIONS = EVAL_DIR / "questions.json"
CACHE_DIR = EVAL_DIR / ".cache"
RESULTS_MD = EVAL_DIR / "RESULTS.md"
METRICS_JSON = EVAL_DIR / "metrics.json"
DETAIL_JSON = EVAL_DIR / "results.detail.json"

sys.path.insert(0, str(BACKEND))
from app.config import Settings  # noqa: E402
from app.services import chat as chat_service  # noqa: E402
from app.services import chat_cache  # noqa: E402
from app.services import chat_judge  # noqa: E402
from app.services import eval_metrics  # noqa: E402

MONEY_TOL = 0.01
CALIBRATION = EVAL_DIR / "calibration.json"
CALIBRATION_MD = EVAL_DIR / "CALIBRATION.md"
# The judge is only "trusted" if it clears this bar on the calibration set: it must
# catch EVERY unfaithful answer (recall 1.0 — the safety-critical direction) and agree
# with the human labels at least this often overall.
JUDGE_TRUST_MIN_ACCURACY = 0.9


# --------------------------------------------------------------------------- #
# Scoring helpers (pure — unit-tested in tests/test_eval_chatbot.py)
# --------------------------------------------------------------------------- #
def deep_subset(expected: Any, actual: Any) -> bool:
    """True if `expected` is a 'deep subset' of `actual`:
      - numbers match within MONEY_TOL,
      - dicts: every expected key is present and its value is a deep subset,
      - lists: every expected item deep-subset-matches SOME actual item (order-free),
      - everything else: exact equality.
    Lets a label assert just the figures that matter without pinning the whole result."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        # bool only matches bool (guard against Python's True == 1)
        return isinstance(expected, bool) and isinstance(actual, bool) and expected == actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) <= MONEY_TOL
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(k in actual and deep_subset(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        return all(any(deep_subset(item, cand) for cand in actual) for item in expected)
    return expected == actual


def _norm_arg(value: Any) -> Any:
    """Normalise an argument for comparison: strings lowercased/stripped; everything
    else left as-is. Month/date/category strings become case-insensitive."""
    if isinstance(value, str):
        return value.strip().lower()
    return value


def args_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    """The expected args must be a subset of the actual call's args (normalised).
    Optional args the label doesn't pin are ignored; extra model args are allowed."""
    for k, v in (expected or {}).items():
        if k not in (actual or {}):
            return False
        if _norm_arg(actual[k]) != _norm_arg(v):
            return False
    return True


def tool_call_matches(expected_tool: Any, used_tools: list[dict[str, Any]]) -> bool:
    """Did the model make a call matching the expected tool (name + args)? `expected_tool`
    may be a single {name,args} or a LIST of acceptable alternatives."""
    alts = expected_tool if isinstance(expected_tool, list) else [expected_tool]
    for alt in alts:
        name = alt.get("name")
        want_args = alt.get("args", {})
        for call in used_tools:
            if call.get("name") == name and args_match(want_args, call.get("args") or {}):
                return True
    return False


def answer_offline(question: dict[str, Any], ledger: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Deterministic (no LLM): dispatch the FIRST expected tool over the ledger and
    deep-subset-compare to the expected answer. Returns (ok, dispatched_result)."""
    spec = question["expected_tool"]
    spec = spec[0] if isinstance(spec, list) else spec
    result = chat_service.dispatch_tool(spec["name"], dict(spec.get("args") or {}), ledger)
    return deep_subset(question["expected_answer"], result), result


def answer_from_used_tools(question: dict[str, Any], used_tools: list[dict[str, Any]],
                           ledger: dict[str, Any]) -> bool:
    """Live answer check: dispatch the MODEL's own tool calls and pass if ANY of them
    yields the expected answer — i.e. the figure the model will cite is tool-derived
    and correct, never invented."""
    for call in used_tools:
        result = chat_service.dispatch_tool(call.get("name"), dict(call.get("args") or {}), ledger)
        if deep_subset(question["expected_answer"], result):
            return True
    return False


def refusal_ok(used_tools: list[dict[str, Any]]) -> bool:
    """A correct refusal of an out-of-scope question calls NO analytics tool."""
    return len(used_tools) == 0


# --------------------------------------------------------------------------- #
# Live model call (cached per question)
# --------------------------------------------------------------------------- #
def _ledger_fingerprint(ledger: dict[str, Any]) -> str:
    return chat_cache.ledger_fingerprint(ledger)  # shared with the runtime cache (DRY)


def _ask_live(question: str, ledger: dict[str, Any], settings: Settings,
              today: datetime.date, *, qid: str, use_cache: bool) -> dict[str, Any]:
    """Return {used_tools, answer, grounded} from the live chatbot, cached per question
    (keyed on qid + ledger fingerprint + model) so re-runs cost no API calls."""
    model = settings.openai_model
    model_tag = re.sub(r"[^a-z0-9]+", "-", model.lower())
    cache = CACHE_DIR / f"{qid}.{_ledger_fingerprint(ledger)}.{model_tag}.json"
    if use_cache and cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    res = chat_service.answer_question(question, [], ledger, settings, today=today)
    out = {"used_tools": res.get("used_tools", []), "answer": res.get("answer", ""),
           "grounded": res.get("grounded", False)}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
# Faithfulness judge (v0.5 Slice 3) — needs the model, cached like --live
# --------------------------------------------------------------------------- #
def _tool_results_for(used_tools: list[dict[str, Any]], ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Reconstruct the exact tool results the chatbot saw, by re-dispatching its
    recorded calls over the ledger — the ground-truth facts the prose must match."""
    return [chat_service.dispatch_tool(c.get("name"), dict(c.get("args") or {}), ledger) for c in used_tools]


def _judge_cached(key: str, question: str, answer: str, tool_results: list[dict[str, Any]],
                  settings: Settings, *, use_cache: bool) -> dict[str, Any]:
    """Judge one answer, cached under `.cache/judge.<key>.<model>.json`."""
    model_tag = re.sub(r"[^a-z0-9]+", "-", settings.openai_model.lower())
    cache = CACHE_DIR / f"judge.{key}.{model_tag}.json"
    if use_cache and cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    verdict = chat_judge.judge_faithfulness(question, answer, tool_results, settings)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")
    return verdict


def _run_calibration(settings: Settings, *, use_cache: bool) -> dict[str, Any] | None:
    """Judge every example in calibration.json and measure agreement with the human
    labels. Writes CALIBRATION.md and returns the agreement dict (or None if missing)."""
    if not CALIBRATION.exists():
        print(f"\nNo calibration set at {CALIBRATION} — skipping judge calibration.")
        return None
    cal = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    items = cal["examples"] if isinstance(cal, dict) else cal
    print(f"\nJudge calibration over {len(items)} labelled examples:")
    rows: list[dict[str, Any]] = []
    for it in items:
        v = _judge_cached(it["id"], it["question"], it["answer"], it.get("tool_results", []),
                          settings, use_cache=use_cache)
        agree = v["verdict"] == it["label"]
        rows.append({"human_label": it["label"], "judge_verdict": v["verdict"]})
        print(f"  {'ok  ' if agree else 'DISAGREE'} {it['id']:<10} human={it['label']:<10} "
              f"judge={v['verdict']:<10} ({it.get('origin', '')})")
    agreement = eval_metrics.judge_agreement(rows)
    trusted = (agreement["accuracy"] is not None
               and agreement["accuracy"] >= JUDGE_TRUST_MIN_ACCURACY
               and agreement["unfaithful_recall"] == 1.0)
    agreement["trusted"] = trusted
    agreement["trust_threshold"] = {"min_accuracy": JUDGE_TRUST_MIN_ACCURACY, "min_unfaithful_recall": 1.0}

    def rp(v: Any) -> str:
        return "n/a" if v is None else f"{100.0 * v:.0f}%"

    print(f"  --> accuracy {rp(agreement['accuracy'])} · "
          f"caught unfaithful {rp(agreement['unfaithful_recall'])} · "
          f"precision {rp(agreement['unfaithful_precision'])}")
    print(f"  --> {'TRUSTED' if trusted else 'DO NOT TRUST'} "
          f"(needs accuracy >= {JUDGE_TRUST_MIN_ACCURACY:.0%} AND caught-unfaithful = 100%)")
    _write_calibration_md(settings, agreement, len(items), out=CALIBRATION_MD)
    return agreement


def _write_calibration_md(settings: Settings, agreement: dict[str, Any], n: int, *, out: Path) -> None:
    def rp(v: Any) -> str:
        return "n/a" if v is None else f"{100.0 * v:.0f}%"

    c = agreement["confusion"]
    lines = [
        "# Chatbot faithfulness judge — calibration",
        "",
        f"Does the LLM faithfulness judge agree with **human-verified** labels? Measured over "
        f"`eval/chatbot/calibration.json` ({n} examples: real chatbot answers labelled *faithful*, "
        f"plus copies with an injected/invented figure labelled *unfaithful*; labels confirmed by a human). "
        f"An uncalibrated judge is just vibes — this is the number that lets us trust it. "
        f"Generated by `backend/scripts/eval_chatbot.py --judge`.",
        "",
        f"- **Judge model:** `{settings.openai_model}`",
        f"- **Run date:** {datetime.date.today().isoformat()}",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Agreement with humans (accuracy) | **{rp(agreement['accuracy'])}** |",
        f"| Caught unfaithful answers (recall — safety-critical) | **{rp(agreement['unfaithful_recall'])}** |",
        f"| Flag precision (of flags, share humans agreed) | {rp(agreement['unfaithful_precision'])} |",
        f"| Faithful recall (good answers left alone) | {rp(agreement['faithful_recall'])} |",
        "",
        f"**Verdict: {'TRUSTED' if agreement.get('trusted') else 'NOT TRUSTED'}** — the judge is trusted only "
        f"if it agrees with humans at least {JUDGE_TRUST_MIN_ACCURACY:.0%} of the time **and** catches 100% of "
        f"the unfaithful answers (missing a bad answer is the failure that matters).",
        "",
        "Confusion (human → judge):",
        "",
        "| human \\\\ judge | faithful | unfaithful |",
        "|---|---:|---:|",
        f"| faithful | {c['faithful']['faithful']} | {c['faithful']['unfaithful']} |",
        f"| unfaithful | {c['unfaithful']['faithful']} | {c['unfaithful']['unfaithful']} |",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def _field(correct: int, scored: int) -> dict[str, Any]:
    return {"accuracy": (correct / scored) if scored else None, "correct": correct, "scored": scored}


def main() -> int:
    ap = argparse.ArgumentParser(description="Chatbot eval harness (tool-selection + answers + refusals).")
    ap.add_argument("--check", action="store_true",
                    help="offline deterministic mode: grade answers via dispatch only (no API, CI-safe)")
    ap.add_argument("--live", action="store_true",
                    help="run the real model for tool-selection + refusal (needs OPENAI_API_KEY)")
    ap.add_argument("--judge", action="store_true",
                    help="run the faithfulness judge: calibrate it vs human labels (calibration.json), and "
                         "with --live also grade the prose of each real answer (needs OPENAI_API_KEY)")
    ap.add_argument("--refresh", action="store_true", help="ignore the per-question cache (--live/--judge)")
    ap.add_argument("--ledger", default=str(LEDGER))
    ap.add_argument("--questions", default=str(QUESTIONS))
    ap.add_argument("--metrics-out", default=None)
    ap.add_argument("--results-out", default=None)
    ap.add_argument("--detail-out", default=None)
    args = ap.parse_args()

    if not args.check and not args.live and not args.judge:
        args.check = True  # default to the offline, deterministic path

    metrics_out = Path(args.metrics_out) if args.metrics_out else METRICS_JSON
    results_out = Path(args.results_out) if args.results_out else RESULTS_MD
    detail_out = Path(args.detail_out) if args.detail_out else DETAIL_JSON

    ledger = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
    qdoc = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    questions = qdoc["questions"]
    today = datetime.date.fromisoformat(qdoc.get("today", datetime.date.today().isoformat()))
    answerable = [q for q in questions if q.get("kind") == "answerable"]
    refusals = [q for q in questions if q.get("kind") == "refusal"]

    settings = None
    model = "offline"
    if args.live or args.judge:
        settings = Settings(_env_file=str(BACKEND / ".env"))
        if settings.llm_provider != "openai" or not settings.llm_configured:
            print("Live/judge mode needs the OpenAI provider configured (OPENAI_API_KEY, LLM_PROVIDER=openai).")
            return 2
        model = settings.openai_model

    # --judge alone = calibrate the judge only (no Q&A loop, no metrics/RESULTS overwrite).
    if args.judge and not args.live and not args.check:
        print(f"Chatbot judge calibration | model: {model}")
        agreement = _run_calibration(settings, use_cache=not args.refresh)
        if agreement is None:
            return 1
        return 0 if agreement.get("trusted") else 1

    mode = "live" if args.live else "check"
    print(f"Chatbot eval | mode: {mode} | model: {model} | today: {today.isoformat()}")
    print(f"Questions: {len(answerable)} answerable, {len(refusals)} refusal\n")

    faith_correct = faith_scored = 0  # prose faithfulness of real answers (--live --judge)

    ts_correct = ts_scored = 0        # tool_selection (live only)
    ans_correct = ans_scored = 0      # answer_correctness
    ref_correct = ref_scored = 0      # refusal (live only)
    details: list[dict[str, Any]] = []

    for q in answerable:
        qid, text = q["id"], q["question"]
        if args.live:
            got = _ask_live(text, ledger, settings, today, qid=qid, use_cache=not args.refresh)
            used = got["used_tools"]
            tool_ok = tool_call_matches(q["expected_tool"], used)
            ans_ok = answer_from_used_tools(q, used, ledger)
            ts_correct += int(tool_ok); ts_scored += 1
            ans_correct += int(ans_ok); ans_scored += 1
            detail = {"id": qid, "question": text, "tool_ok": tool_ok, "answer_ok": ans_ok,
                      "used_tools": used}
            faith_mark = ""
            if args.judge:
                tr = _tool_results_for(used, ledger)
                v = _judge_cached(f"live.{qid}.{_ledger_fingerprint(ledger)}", text, got["answer"], tr,
                                  settings, use_cache=not args.refresh)
                faithful = v["verdict"] == "faithful"
                faith_correct += int(faithful); faith_scored += 1
                detail["faithful"] = faithful
                faith_mark = f" faith={'y' if faithful else 'N'}"
            mark = "ok  " if (tool_ok and ans_ok) else "MISS"
            print(f"  {mark} {qid}  tool={'y' if tool_ok else 'N'} ans={'y' if ans_ok else 'N'}{faith_mark}  {text}")
            details.append(detail)
        else:
            ans_ok, result = answer_offline(q, ledger)
            ans_correct += int(ans_ok); ans_scored += 1
            print(f"  {'ok  ' if ans_ok else 'MISS'} {qid}  {text}")
            if not ans_ok:
                print(f"       expected {q['expected_answer']}  got {result}")
            details.append({"id": qid, "question": text, "answer_ok": ans_ok})

    if args.live:
        for q in refusals:
            qid, text = q["id"], q["question"]
            got = _ask_live(text, ledger, settings, today, qid=qid, use_cache=not args.refresh)
            ok = refusal_ok(got["used_tools"])
            ref_correct += int(ok); ref_scored += 1
            print(f"  {'ok  ' if ok else 'MISS'} {qid}  (refusal)  {text}")
            details.append({"id": qid, "question": text, "refusal_ok": ok,
                            "used_tools": got["used_tools"], "answer": got["answer"]})

    # ---- aggregate ----
    fields: dict[str, Any] = {"answer_correctness": _field(ans_correct, ans_scored)}
    if args.live:
        fields["tool_selection"] = _field(ts_correct, ts_scored)
        fields["refusal"] = _field(ref_correct, ref_scored)
    if args.live and args.judge:
        fields["faithfulness"] = _field(faith_correct, faith_scored)
    total_correct = ans_correct + (ts_correct + ref_correct if args.live else 0)
    total_scored = ans_scored + (ts_scored + ref_scored if args.live else 0)

    def pct(c: int, s: int) -> str:
        return f"{100.0 * c / s:5.1f}%" if s else "   n/a"

    print("\n" + "=" * 52)
    print(f"{'metric':<20}{'accuracy':>10}{'correct/scored':>18}")
    print("-" * 52)
    order = ["tool_selection", "answer_correctness", "refusal", "faithfulness"]
    for f in order:
        if f in fields:
            c, s = fields[f]["correct"], fields[f]["scored"]
            print(f"{f:<20}{pct(c, s):>10}{f'{c}/{s}':>18}")
    print("-" * 52)
    print(f"{'OVERALL':<20}{pct(total_correct, total_scored):>10}{f'{total_correct}/{total_scored}':>18}")
    print("  (overall = tool-selection + answer + refusal; faithfulness reported separately)")
    print("=" * 52)

    if total_scored == 0:
        print("\nNothing scored — leaving committed results untouched.")
        return 1

    metrics = {
        "mode": mode,
        "model": model,
        "run_date": datetime.date.today().isoformat(),
        "eval_today": today.isoformat(),
        "n_questions": len(questions),
        "n_receipts": len(answerable),  # named for the shared check_regression.py n-comparison
        "n_answerable": len(answerable),
        "n_refusal": len(refusals) if args.live else 0,
        "fields": fields,
        "overall": _field(total_correct, total_scored),
    }
    metrics_out.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    _write_results_md(metrics, out=results_out)
    detail_out.write_text(json.dumps(details, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {metrics_out.name} + {results_out.name} (committable aggregates) "
          f"and {detail_out.name} (per-question, git-ignored).")

    # With --live --judge, also calibrate the judge against the human labels.
    if args.judge:
        _run_calibration(settings, use_cache=not args.refresh)
    return 0


def _write_results_md(metrics: dict[str, Any], *, out: Path) -> None:
    def pct(f: dict[str, Any] | None) -> str:
        if not f or f.get("accuracy") is None:
            return "n/a"
        return f"{100.0 * f['accuracy']:.1f}%"

    fields = metrics["fields"]
    live = metrics["mode"] == "live"
    lines = [
        "# Chatbot eval",
        "",
        f"Quality of the NL Q&A chatbot (`/ask`, [D40]) over a **committed synthetic** fixed "
        f"ledger (`eval/chatbot/ledger.json`), so the eval is reproducible and public-safe. "
        f"Generated by `backend/scripts/eval_chatbot.py`.",
        "",
        f"- **Mode:** {metrics['mode']} "
        f"({'real model, cached' if live else 'offline / deterministic — graded in code, no API'})",
        f"- **Model:** `{metrics['model']}`" if live else "- **Model:** none (dispatch-only)",
        f"- **Run date:** {metrics['run_date']} · eval date {metrics['eval_today']}",
        f"- **Questions:** {metrics['n_answerable']} answerable"
        + (f", {metrics['n_refusal']} refusal" if live else ""),
        "",
        "| Metric | Accuracy | Correct / scored |",
        "|---|---:|---:|",
    ]
    labels = {
        "tool_selection": "Tool-selection (right tool + args)",
        "answer_correctness": "Answer correctness (figure from the tool)",
        "refusal": "Refusal (out-of-scope declined)",
        "faithfulness": "Prose faithfulness (judge; calibrated — see CALIBRATION.md)",
    }
    for key in ["tool_selection", "answer_correctness", "refusal", "faithfulness"]:
        if key in fields:
            f = fields[key]
            lines.append(f"| {labels[key]} | {pct(f)} | {f['correct']}/{f['scored']} |")
    ov = metrics["overall"]
    lines += [
        f"| **Overall** | **{pct(ov)}** | {ov['correct']}/{ov['scored']} |",
        "",
        "> `answer_correctness` is graded in **code** — the tool is dispatched over the fixed "
        "ledger and its structured result is compared to the expected figure (no LLM judge). "
        "`tool_selection` is the model's real job: did it call the right analytics tool with the "
        "right arguments. Prose faithfulness (does the sentence follow from the numbers) is a "
        "separate calibrated judge — see docs/design/chatbot.md, Slice 3.",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
