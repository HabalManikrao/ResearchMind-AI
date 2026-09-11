import { useCallback, useEffect, useState } from "react";
import { Plus, Save, Trash2 } from "lucide-react";
import { api } from "../api/client";
import type { Constraint, Objective, ResearchBrief, Terminology } from "../api/types";
import { Card } from "./ui";

const CONSTRAINT_TYPES = [
  "technical", "time", "dataset", "hardware", "regulatory", "geographic", "budget", "scope", "other",
];
const OBJECTIVE_STATUSES = ["not_started", "in_progress", "achieved", "blocked", "abandoned"];

const toLines = (xs: string[]) => (xs ?? []).join("\n");
const fromLines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

/**
 * R&D layer Phase A — the research "front matter": Brief (structured + version-aware),
 * Objectives, typed Constraints, and Terminology. Deterministic CRUD over the Phase A API.
 */
export default function BriefPanel({ projectId }: { projectId: string }) {
  const [brief, setBrief] = useState<ResearchBrief | null>(null);
  const [objectives, setObjectives] = useState<Objective[]>([]);
  const [constraints, setConstraints] = useState<Constraint[]>([]);
  const [terms, setTerms] = useState<Terminology[]>([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    const [b, o, c, t] = await Promise.all([
      api.brief(projectId),
      api.objectives(projectId),
      api.constraints(projectId),
      api.terminology(projectId),
    ]);
    setBrief(b);
    setObjectives(o);
    setConstraints(c);
    setTerms(t);
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  if (!brief) return <Card><p className="text-sm text-slate-500">Loading brief…</p></Card>;

  const set = (patch: Partial<ResearchBrief>) => setBrief({ ...brief, ...patch });

  const saveBrief = async () => {
    setSaving(true);
    setSaved(false);
    try {
      const updated = await api.updateBrief(projectId, {
        problem_statement: brief.problem_statement,
        background: brief.background,
        expected_outcome: brief.expected_outcome,
        scope_included: brief.scope_included,
        scope_excluded: brief.scope_excluded,
        assumptions: brief.assumptions,
        target_users: brief.target_users,
        success_criteria: brief.success_criteria,
      });
      setBrief(updated);
      setSaved(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* --- Research Brief --- */}
      <Card>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">Research Brief</h2>
          <span className="text-xs text-slate-400">v{brief.version}</span>
        </div>
        <div className="space-y-3">
          <Field label="Problem statement">
            <textarea
              className={inputCls}
              rows={2}
              value={brief.problem_statement}
              onChange={(e) => set({ problem_statement: e.target.value })}
            />
          </Field>
          <Field label="Background">
            <textarea className={inputCls} rows={2} value={brief.background}
              onChange={(e) => set({ background: e.target.value })} />
          </Field>
          <Field label="Expected outcome">
            <textarea className={inputCls} rows={2} value={brief.expected_outcome}
              onChange={(e) => set({ expected_outcome: e.target.value })} />
          </Field>
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="In scope (one per line)">
              <textarea className={inputCls} rows={3} value={toLines(brief.scope_included)}
                onChange={(e) => set({ scope_included: fromLines(e.target.value) })} />
            </Field>
            <Field label="Out of scope (one per line)">
              <textarea className={inputCls} rows={3} value={toLines(brief.scope_excluded)}
                onChange={(e) => set({ scope_excluded: fromLines(e.target.value) })} />
            </Field>
            <Field label="Assumptions (one per line)">
              <textarea className={inputCls} rows={3} value={toLines(brief.assumptions)}
                onChange={(e) => set({ assumptions: fromLines(e.target.value) })} />
            </Field>
            <Field label="Success criteria (one per line)">
              <textarea className={inputCls} rows={3} value={toLines(brief.success_criteria)}
                onChange={(e) => set({ success_criteria: fromLines(e.target.value) })} />
            </Field>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={saveBrief} disabled={saving} className={btnCls}>
              <Save className="h-4 w-4" /> {saving ? "Saving…" : "Save brief"}
            </button>
            {saved && <span className="text-xs text-green-600">Saved (v{brief.version})</span>}
          </div>
        </div>
      </Card>

      {/* --- Objectives --- */}
      <ListSection<Objective>
        title="Objectives"
        items={objectives}
        empty="No objectives yet."
        render={(o) => (
          <div className="flex-1">
            <p className="text-sm text-slate-800">{o.description}</p>
            <p className="text-xs text-slate-500">
              priority {o.priority} · {o.status.replace("_", " ")} · {o.completion_pct}%
            </p>
          </div>
        )}
        onDelete={async (o) => {
          await api.deleteObjective(projectId, o.id);
          setObjectives((xs) => xs.filter((x) => x.id !== o.id));
        }}
        adder={
          <ObjectiveAdder
            onAdd={async (description) => {
              const created = await api.createObjective(projectId, { description });
              setObjectives((xs) => [...xs, created]);
            }}
          />
        }
      />

      {/* --- Constraints --- */}
      <ListSection<Constraint>
        title="Constraints"
        items={constraints}
        empty="No constraints yet."
        render={(c) => (
          <div className="flex-1">
            <span className="mr-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
              {c.ctype}
            </span>
            <span className="text-sm text-slate-800">{c.text}</span>
          </div>
        )}
        onDelete={async (c) => {
          await api.deleteConstraint(projectId, c.id);
          setConstraints((xs) => xs.filter((x) => x.id !== c.id));
        }}
        adder={
          <ConstraintAdder
            onAdd={async (ctype, text) => {
              const created = await api.createConstraint(projectId, { ctype, text });
              setConstraints((xs) => [...xs, created]);
            }}
          />
        }
      />

      {/* --- Terminology --- */}
      <ListSection<Terminology>
        title="Terminology"
        items={terms}
        empty="No terms defined yet."
        render={(t) => (
          <div className="flex-1">
            <span className="text-sm font-medium text-slate-900">{t.term}</span>
            {t.definition && <span className="ml-2 text-sm text-slate-600">— {t.definition}</span>}
          </div>
        )}
        onDelete={async (t) => {
          await api.deleteTerm(projectId, t.id);
          setTerms((xs) => xs.filter((x) => x.id !== t.id));
        }}
        adder={
          <TermAdder
            onAdd={async (term, definition) => {
              const created = await api.createTerm(projectId, { term, definition });
              setTerms((xs) => [...xs, created]);
            }}
          />
        }
      />
    </div>
  );
}

const inputCls =
  "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500";
const btnCls =
  "inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-600">{label}</span>
      {children}
    </label>
  );
}

function ListSection<T extends { id: string }>({
  title, items, empty, render, onDelete, adder,
}: {
  title: string;
  items: T[];
  empty: string;
  render: (item: T) => React.ReactNode;
  onDelete: (item: T) => void;
  adder: React.ReactNode;
}) {
  return (
    <Card>
      <h2 className="mb-3 text-lg font-semibold text-slate-900">{title}</h2>
      {items.length === 0 ? (
        <p className="mb-3 text-sm text-slate-500">{empty}</p>
      ) : (
        <ul className="mb-3 divide-y divide-slate-100">
          {items.map((item) => (
            <li key={item.id} className="flex items-center gap-2 py-2">
              {render(item)}
              <button
                onClick={() => onDelete(item)}
                title="Delete"
                className="shrink-0 rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {adder}
    </Card>
  );
}

function ObjectiveAdder({ onAdd }: { onAdd: (description: string) => Promise<void> }) {
  const [text, setText] = useState("");
  return (
    <div className="flex gap-2">
      <input className={inputCls} placeholder="New objective…" value={text}
        onChange={(e) => setText(e.target.value)} />
      <button
        className={btnCls}
        disabled={text.trim().length < 3}
        onClick={async () => { await onAdd(text.trim()); setText(""); }}
      >
        <Plus className="h-4 w-4" /> Add
      </button>
    </div>
  );
}

function ConstraintAdder({ onAdd }: { onAdd: (ctype: string, text: string) => Promise<void> }) {
  const [ctype, setCtype] = useState("technical");
  const [text, setText] = useState("");
  return (
    <div className="flex gap-2">
      <select className={inputCls + " max-w-[9rem]"} value={ctype}
        onChange={(e) => setCtype(e.target.value)}>
        {CONSTRAINT_TYPES.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      <input className={inputCls} placeholder="Constraint…" value={text}
        onChange={(e) => setText(e.target.value)} />
      <button className={btnCls} disabled={!text.trim()}
        onClick={async () => { await onAdd(ctype, text.trim()); setText(""); }}>
        <Plus className="h-4 w-4" /> Add
      </button>
    </div>
  );
}

function TermAdder({ onAdd }: { onAdd: (term: string, definition: string) => Promise<void> }) {
  const [term, setTerm] = useState("");
  const [def, setDef] = useState("");
  return (
    <div className="flex gap-2">
      <input className={inputCls + " max-w-[12rem]"} placeholder="Term…" value={term}
        onChange={(e) => setTerm(e.target.value)} />
      <input className={inputCls} placeholder="Definition…" value={def}
        onChange={(e) => setDef(e.target.value)} />
      <button className={btnCls} disabled={!term.trim()}
        onClick={async () => { await onAdd(term.trim(), def.trim()); setTerm(""); setDef(""); }}>
        <Plus className="h-4 w-4" /> Add
      </button>
    </div>
  );
}

// The status list is exported for reuse by future R&D tabs; referenced to satisfy noUnusedLocals.
export { OBJECTIVE_STATUSES };
