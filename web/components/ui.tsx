import type { EventKind, IssueType, PhaseKey, RunStatus } from "@/lib/types";
import { STATUS_LABEL, TYPE_LABEL } from "@/lib/mock";
import {
  IconAlert,
  IconBolt,
  IconCheck,
  IconCommit,
  IconCpu,
  IconGate,
  IconMessage,
} from "./icons";

export const statusColor: Record<RunStatus, string> = {
  running: "var(--color-signal)",
  waiting: "var(--color-amber)",
  suspended: "var(--color-rose)",
  done: "var(--color-cyan)",
  blocked: "var(--color-violet)",
};

export function StatusPill({ status }: { status: RunStatus }) {
  const c = statusColor[status];
  const live = status === "running";
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium"
      style={{ color: c, borderColor: `color-mix(in srgb, ${c} 35%, transparent)`, background: `color-mix(in srgb, ${c} 10%, transparent)` }}
    >
      <span className={live ? "pulse" : ""} style={{ color: c }}>
        <span className="block h-1.5 w-1.5 rounded-full" style={{ background: c }} />
      </span>
      {STATUS_LABEL[status]}
    </span>
  );
}

export function TypeTag({ type }: { type: IssueType }) {
  const map: Record<IssueType, string> = {
    bug: "var(--color-rose)",
    "feature-m": "var(--color-cyan)",
    "feature-l": "var(--color-violet)",
  };
  const c = map[type];
  return (
    <span
      className="font-mono text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded"
      style={{ color: c, background: `color-mix(in srgb, ${c} 12%, transparent)` }}
    >
      {TYPE_LABEL[type]}
    </span>
  );
}

export function Money({ value }: { value: number }) {
  return <span className="font-mono tnum">${value.toFixed(2)}</span>;
}

export function eventIcon(kind: EventKind) {
  const map: Record<EventKind, { icon: typeof IconCommit; color: string }> = {
    phase: { icon: IconBolt, color: "var(--color-signal)" },
    agent: { icon: IconCpu, color: "var(--color-cyan)" },
    commit: { icon: IconCommit, color: "var(--color-ink-dim)" },
    ci: { icon: IconBolt, color: "var(--color-amber)" },
    comment: { icon: IconMessage, color: "var(--color-cyan)" },
    gate: { icon: IconGate, color: "var(--color-amber)" },
    error: { icon: IconAlert, color: "var(--color-rose)" },
  };
  return map[kind];
}

export const phaseAccent: Record<PhaseKey, string> = {
  intake: "var(--color-ink-dim)",
  clarify: "var(--color-cyan)",
  split: "var(--color-violet)",
  plan: "var(--color-cyan)",
  approve: "var(--color-amber)",
  implement: "var(--color-signal)",
  review: "var(--color-amber)",
  revise: "var(--color-signal)",
  done: "var(--color-cyan)",
};

export { IconCheck };
