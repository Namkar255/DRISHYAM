// @ts-nocheck
/* NETWORK_INTELLIGENCE_20260908: the SIH26189 criminal-network surface.
 *
 * House rule for this whole view: a centrality score is never rendered on its own. The server
 * sends `why` and `caveat` with every ranked entity and both are always shown, because a bare
 * number invites the reading that DRISHYAM is scoring people for criminality. It is not.
 *
 * The presentational primitives below intentionally repeat the classes used in Workspace.tsx
 * rather than importing them. Workspace.tsx renders this module, so importing back out of it
 * would be circular; these are six one-line components and the look must stay identical.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, Check, Loader2, Network, RefreshCw, Route, ShieldCheck, Users, X } from "lucide-react";
import { getApiErrorMessage } from "@/api/client";
import {
  getEntityRelationSummary, getEntityRelations, getImportantEntities, getNetworkBridges, getNetworkCommunities, getNetworkOverview, getNetworkPath, getNetworkSubgraph, reviewEntityRelation,
  type BridgeRecord, type CommunityRecord, type EntityRelationRecord, type EntityRelationSummaryRecord, type ImportanceMetric, type ImportantEntityRecord, type NetworkEdgeRecord, type NetworkOverviewRecord, type NetworkPathRecord, type NetworkSubgraphRecord,
} from "@/api/network";

const A = {
  hero: "/assets/cap-original-relationship-graph.png",
  importance: "/assets/journey-analyze-graph-monitor.png",
  bridge: "/assets/trail-map-evidence_71482f25.png",
  community: "/assets/cap-relationship-graph_b226489e.png",
  board: "/assets/workspace-map-board_c063d31f.png",
  identity: "/assets/reference-fingerprint_4cf2ff3f.png",
};

function Panel({ children, className = "" }) { return <section className={`rounded-xl border border-white/[.09] bg-[#1d201f] shadow-[0_16px_42px_rgba(0,0,0,.17)] ${className}`}>{children}</section>; }
function Eyebrow({ children }) { return <p className="mb-2 text-[8px] font-bold uppercase tracking-[.15em] text-[#b0807a]">{children}</p>; }
function Pill({ children, tone = "blue" }) { const s = { red: "border-[#a94742]/40 bg-[#3b1716] text-[#f0aaa4]", amber: "border-[#9c6a2e]/45 bg-[#362710] text-[#e3c48a]", green: "border-[#3f7d56]/40 bg-[#12321f] text-[#9bd4aa]", blue: "border-[#427989]/40 bg-[#15303a] text-[#a9cbd6]" }[tone] || "border-white/10 bg-white/[.05] text-[#ddd6ca]"; return <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[8px] font-bold tracking-[.05em] ${s}`}><i className="h-1.5 w-1.5 rounded-full bg-current" />{children}</span>; }
function Empty({ title, detail }) { return <div className="rounded-lg border border-dashed border-white/[.15] bg-black/[.1] p-6 text-center"><AlertTriangle className="mx-auto text-[#c9a268]" size={20} /><h2 className="mt-3 text-[12px] font-bold">{title}</h2><p className="mx-auto mt-2 max-w-xl text-[9px] leading-5 text-[#979188]">{detail}</p></div>; }
function Button({ children, onClick, tone = "outline", disabled = false }) { const s = tone === "burgundy" ? "bg-[#7f1d1d] text-white hover:bg-[#962b29]" : tone === "quiet" ? "text-[#d4cec3] hover:bg-white/[.06]" : "border border-white/[.11] bg-white/[.035] text-[#ddd6ca] hover:border-[#a85e58] hover:bg-white/[.06]"; return <button type="button" onClick={onClick} disabled={disabled} className={`inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-[10px] font-bold transition disabled:cursor-not-allowed disabled:opacity-50 ${s}`}>{children}</button>; }
function Trace() { return <div className="mt-6 border-t border-white/[.07] pt-4"><p className="text-[8px] font-bold uppercase tracking-[.12em] text-[#8f8a80]">Route back to evidence</p><p className="mono mt-2 text-[8px] text-[#e0a49c]">GRAPH <span className="text-[#7f1d1d]">›</span> RELATIONSHIP <span className="text-[#7f1d1d]">›</span> CLAIM <span className="text-[#7f1d1d]">›</span> EVIDENCE <span className="text-[#7f1d1d]">›</span> ORIGINAL SOURCE</p></div>; }

const RELATION_TONE = { TRANSFERRED_TO: "#3f8f5c", REQUESTED_PAYMENT_FROM: "#c08a2e", MESSAGED: "#3d84a3", COMMUNICATED_WITH: "#8064bb", ASSOCIATED_WITH: "#9a7b45", MENTIONED_WITH: "#7a766f" };
const relationTone = (type) => RELATION_TONE[type] || "#7a766f";
const entityTone = (kind) => { const k = String(kind || "").toLowerCase(); if (k.includes("person") || k === "party") return "#b8433c"; if (k.includes("vehicle")) return "#c2702e"; if (k.includes("organisation")) return "#8064bb"; if (k.includes("location")) return "#3d84a3"; if (k.includes("upi") || k.includes("account") || k.includes("ifsc")) return "#3f8f5c"; if (k.includes("phone")) return "#d8a02b"; if (k.includes("email")) return "#4aa0a8"; return "#5b8ba0"; };
const readable = (value) => String(value || "").replace(/_/g, " ");
const verificationTone = (state) => (state === "human_verified" ? "green" : state === "rejected" ? "red" : "amber");

/** The exact place in the source a relationship was read from, phrased for a person. */
function sourceLocation(reference) {
  if (!reference || typeof reference !== "object") return "Whole record";
  const kind = reference.kind;
  if (kind === "table_cell") return `Row ${reference.row}, column "${reference.column}"`;
  if (kind === "table_row") return `Row ${reference.row}`;
  if (kind === "ocr_block" || reference.bbox) { const box = reference.bbox || []; return `Image region ${box.length === 4 ? `[${box.join(", ")}]` : ""}`.trim(); }
  if (reference.page) return `Page ${reference.page}${reference.line ? `, line ${reference.line}` : ""}`;
  if (reference.line) return `Line ${reference.line}`;
  return kind ? readable(kind) : "Whole record";
}

function Metric({ label, value, detail, image, tone = "burgundy" }) {
  const tint = { burgundy: "text-[#efb1a8]", green: "text-[#9bd4aa]", amber: "text-[#e3c48a]", blue: "text-[#a9cbd6]" }[tone] || "text-[#efb1a8]";
  return <Panel className="relative overflow-hidden p-4"><img src={image} alt="" aria-hidden className="pointer-events-none absolute -right-4 -top-3 h-24 w-24 object-contain opacity-[.13]" /><b className={`block text-[24px] font-extrabold tracking-tight ${tint}`}>{value}</b><p className="mt-1 text-[10px] font-bold text-[#e4ded4]">{label}</p><p className="relative mt-1 max-w-[90%] text-[9px] leading-4 text-[#8e8b83]">{detail}</p></Panel>;
}

function ImportanceCard({ record, onOpen }) {
  return <button onClick={onOpen} className="w-full rounded-xl border border-white/[.09] bg-[#1d201f] p-4 text-left shadow-[0_16px_42px_rgba(0,0,0,.17)] transition hover:-translate-y-0.5 hover:border-[#9a5a55]/60">
    <div className="flex items-start justify-between gap-3">
      <span className="flex min-w-0 items-center gap-2.5"><i className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: entityTone(record.entity_type) }} /><span className="min-w-0"><b className="block truncate text-[12px] text-[#f1ebe0]">{record.label}</b><small className="mono mt-0.5 block text-[8px] uppercase tracking-[.1em] text-[#928d84]">{record.entity_type}</small></span></span>
      <span className="shrink-0 text-right"><b className="block text-[15px] font-extrabold text-[#e0a49c]">#{record.rank}</b><small className="mono block text-[8px] text-[#847f76]">{record.score.toFixed(3)}</small></span>
    </div>
    <p className="mt-3 text-[9px] leading-5 text-[#b9b2a7]">{record.why}</p>
    <div className="mt-3 flex flex-wrap items-center gap-1.5"><Pill tone="blue">{record.connections} links</Pill><Pill tone="green">{record.supporting_evidence_count} sources</Pill>{record.communities_linked > 1 && <Pill tone="amber">{record.communities_linked} groups</Pill>}{record.is_bridge && <Pill tone="red">Bridge</Pill>}</div>
    <p className="mt-3 border-t border-white/[.07] pt-2 text-[8px] leading-4 text-[#8b8680]">{record.caveat}</p>
  </button>;
}

function NetworkCanvas({ nodes, edges, selected, onSelect }) {
  // Rings sized to the canvas rather than to a fixed radius. The first layout packed every node
  // into a circle of radius 118 inside a 900x520 frame, so labels collided in the middle while the
  // sides stayed empty.
  const positions = useMemo(() => {
    const result = new Map();
    const total = nodes.length;
    if (total === 1) { result.set(nodes[0].id, { x: 450, y: 262 }); return result; }
    const firstRing = Math.min(total, 9);
    const rings = [{ from: 0, to: firstRing, radius: total <= 4 ? 130 : 196 }];
    if (total > firstRing) rings.push({ from: firstRing, to: total, radius: 118 });
    rings.forEach(({ from, to, radius }, ringIndex) => {
      const size = to - from;
      for (let index = from; index < to; index += 1) {
        // Offsetting alternate rings keeps an inner node from hiding directly behind an outer one.
        const angle = ((index - from) / size) * Math.PI * 2 - Math.PI / 2 + (ringIndex ? Math.PI / size : 0);
        result.set(nodes[index].id, { x: 450 + Math.cos(angle) * radius, y: 262 + Math.sin(angle) * radius * 0.82 });
      }
    });
    return result;
  }, [nodes]);
  const touching = new Set(edges.filter((e) => e.subject_entity_id === selected || e.object_entity_id === selected).flatMap((e) => [e.subject_entity_id, e.object_entity_id]));
  if (!nodes.length) return <Empty title="No relationships to draw yet" detail="Relationships appear once evidence has been processed and identities resolved. Nothing is drawn that the evidence does not support." />;
  return <Panel className="overflow-hidden">
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/[.07] px-4 py-3"><Eyebrow>Relationship map / every edge opens at its source</Eyebrow>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">{Object.keys(RELATION_TONE).map((type) => <span key={type} className="inline-flex items-center gap-1.5 text-[8px] font-bold uppercase tracking-[.06em] text-[#948e85]"><i className="h-1 w-4 rounded-full" style={{ background: relationTone(type) }} />{readable(type)}</span>)}</div>
    </div>
    <div className="overflow-x-auto bg-[#131615]"><svg viewBox="0 0 900 520" className="h-[520px] w-full min-w-[820px]" role="img" aria-label="Case relationship map">
      <defs><pattern id="net-grid" width="34" height="34" patternUnits="userSpaceOnUse"><path d="M34 0H0V34" fill="none" stroke="rgba(255,255,255,.035)" strokeWidth="1" /></pattern></defs>
      <rect width="900" height="520" fill="url(#net-grid)" />
      {edges.map((edge, index) => { const a = positions.get(edge.subject_entity_id); const b = positions.get(edge.object_entity_id); if (!a || !b) return null; const dim = selected && !(edge.subject_entity_id === selected || edge.object_entity_id === selected); const type = edge.relation_types?.[0] || "MENTIONED_WITH";
        return <line key={`${edge.subject_entity_id}-${edge.object_entity_id}-${index}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={relationTone(type)} strokeWidth={Math.max(1.1, edge.confidence * 3.2)} strokeDasharray={edge.confidence < 0.5 ? "5 4" : undefined} strokeLinecap="round" opacity={dim ? 0.14 : 0.92} />; })}
      {nodes.map((node) => { const point = positions.get(node.id); if (!point) return null; const dim = selected && node.id !== selected && !touching.has(node.id); const active = node.id === selected;
        return <g key={node.id} transform={`translate(${point.x},${point.y})`} opacity={dim ? 0.2 : 1} className="cursor-pointer" onClick={() => onSelect(active ? null : node.id)}>
          <circle r={active ? 15 : 11} fill={entityTone(node.entity_type)} stroke={active ? "#f4e7c9" : "rgba(0,0,0,.45)"} strokeWidth={active ? 2.4 : 1} />
          <text y={-22} textAnchor="middle" className="fill-[#ded7cb] text-[9px] font-bold">{node.label?.length > 19 ? `${node.label.slice(0, 18)}…` : node.label}</text>
          <text y={28} textAnchor="middle" className="fill-[#8d887f] text-[7px] uppercase tracking-[.1em]">{node.entity_type}</text>
        </g>; })}
    </svg></div>
    <p className="border-t border-white/[.07] px-4 py-2.5 text-[8px] leading-4 text-[#8b8680]">A thicker line means the source states the relationship more firmly. A dashed line is co-occurrence only: the source named both in one record and stated no relationship between them.</p>
  </Panel>;
}

/** Relationship detail: the differentiating chain, ending at the exact region of the original file. */
function RelationDrawer({ relation, caseId, onClose, onReviewed, say }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  if (!relation) return null;
  const decide = async (action) => {
    setBusy(true);
    try { await reviewEntityRelation(caseId, relation.id, action, note.trim() || undefined); say(action === "confirm_relationship" ? "Relationship confirmed and recorded against your account." : "Relationship rejected. The original machine reading is kept for audit."); await onReviewed(); onClose(); }
    catch (error) { say(getApiErrorMessage(error, "The relationship review could not be recorded.")); }
    finally { setBusy(false); }
  };
  const rows = [
    ["Relationship", readable(relation.relation_type)],
    ["Direction", relation.directed ? `${relation.subject.label} → ${relation.object.label}` : "Not established by the source"],
    ["Read from", readable(relation.basis)],
    ["Source evidence", relation.source_evidence_id],
    ["Source location", sourceLocation(relation.source_reference)],
    ["Observed at", relation.observed_at ? new Date(relation.observed_at).toLocaleString() : "Time not established"],
    ["Time precision", readable(relation.time_precision)],
    ["Confidence", relation.confidence.toFixed(2)],
    ["Verification", readable(relation.verification_status)],
  ];
  return <><button aria-label="Close relationship detail" onClick={onClose} className="fixed inset-0 z-[70] bg-black/60 backdrop-blur-[1px]" />
    <aside className="fixed inset-y-0 right-0 z-[71] flex w-full max-w-[540px] flex-col border-l border-white/[.1] bg-[#171a19] shadow-[-24px_0_80px_rgba(0,0,0,.45)]">
      <div className="flex items-start justify-between border-b border-white/[.08] px-5 py-5"><div><Eyebrow>Relationship detail / one observation, one source</Eyebrow><h2 className="text-lg font-extrabold text-[#f2ece0]">{relation.subject.label} <span className="text-[#a45d57]">{relation.directed ? "→" : "—"}</span> {relation.object.label}</h2></div><button onClick={onClose} className="grid h-9 w-9 place-items-center rounded-md border border-white/[.1] text-[#b4ada2] hover:bg-white/[.06]"><X size={17} /></button></div>
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
        <Panel className="p-4"><Eyebrow>What the source states</Eyebrow><p className="text-[10px] leading-5 text-[#c7c0b5]">{RELATION_MEANING[relation.relation_type] || "The source records these two together."}</p></Panel>
        <Panel className="p-4"><Eyebrow>Provenance</Eyebrow><div className="space-y-2">{rows.map(([label, value]) => <div key={label} className="flex justify-between gap-3 text-[9px]"><span className="text-[#878179]">{label}</span><span className="mono max-w-[280px] break-all text-right font-bold text-[#ddd6ca]">{value}</span></div>)}</div></Panel>
        {relation.review_note && <Panel className="p-4"><Eyebrow>Reviewer note</Eyebrow><p className="text-[10px] leading-5 text-[#c7c0b5]">{relation.review_note}</p></Panel>}
        <Panel className="p-4"><Eyebrow>Record your decision</Eyebrow>
          <textarea value={note} onChange={(event) => setNote(event.target.value)} rows={3} placeholder="Why this relationship is or is not supported by the source." className="w-full rounded-md border border-white/[.11] bg-black/[.18] px-3 py-2 text-[10px] text-[#e6dfd4] outline-none placeholder:text-[#77736b] focus:border-[#a85e58]" />
          <div className="mt-3 flex flex-wrap gap-2"><Button tone="burgundy" onClick={() => decide("confirm_relationship")} disabled={busy}>{busy ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />} Confirm relationship</Button><Button onClick={() => decide("reject_relationship")} disabled={busy}><X size={13} /> Reject</Button></div>
          <p className="mt-3 text-[8px] leading-4 text-[#8b8680]">A decision annotates this observation. The original machine reading is never deleted, so the record stays auditable.</p>
        </Panel>
        <Trace />
      </div>
    </aside></>;
}

const RELATION_MEANING = {
  TRANSFERRED_TO: "The source states that the first party sent money to the second.",
  REQUESTED_PAYMENT_FROM: "The source states that the first party asked the second for money. It does not record that any money moved.",
  MESSAGED: "The source states that the first party sent a message to the second.",
  COMMUNICATED_WITH: "The source records contact between the two parties but does not state who initiated it.",
  ASSOCIATED_WITH: "The source names these two as the parties to the same record, without stating what passed between them.",
  MENTIONED_WITH: "The source names both in the same record. It does not state any relationship between them.",
};

/** One entity's neighbourhood, loaded on demand rather than with the whole case. */
function EntityDrawer({ entity, caseId, onClose, say }) {
  const [hops, setHops] = useState(1);
  const [subgraph, setSubgraph] = useState(null);
  const [relations, setRelations] = useState([]);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!entity) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([getNetworkSubgraph(caseId, entity.entity_id, hops), getEntityRelations(caseId, { entity_id: entity.entity_id, limit: 200 })])
      .then(([graph, page]) => { if (!cancelled) { setSubgraph(graph); setRelations(page.items); } })
      .catch((error) => { if (!cancelled) say(getApiErrorMessage(error, "The entity neighbourhood could not be loaded.")); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [entity, caseId, hops, say]);
  if (!entity) return null;
  return <><button aria-label="Close entity profile" onClick={onClose} className="fixed inset-0 z-[70] bg-black/60 backdrop-blur-[1px]" />
    <aside className="fixed inset-y-0 right-0 z-[71] flex w-full max-w-[620px] flex-col border-l border-white/[.1] bg-[#171a19] shadow-[-24px_0_80px_rgba(0,0,0,.45)]">
      <div className="flex items-start justify-between border-b border-white/[.08] px-5 py-5"><div className="min-w-0"><Eyebrow>Entity profile / no identity conclusion</Eyebrow><h2 className="flex items-center gap-2 truncate text-lg font-extrabold text-[#f2ece0]"><i className="h-3 w-3 shrink-0 rounded-full" style={{ background: entityTone(entity.entity_type) }} />{entity.label}</h2><p className="mono mt-1 text-[8px] uppercase tracking-[.12em] text-[#928d84]">{entity.entity_type}</p></div><button onClick={onClose} className="grid h-9 w-9 place-items-center rounded-md border border-white/[.1] text-[#b4ada2] hover:bg-white/[.06]"><X size={17} /></button></div>
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
        <Panel className="relative overflow-hidden p-4"><img src={A.identity} alt="" aria-hidden className="pointer-events-none absolute -right-3 -top-3 h-24 w-24 object-contain opacity-[.12]" /><Eyebrow>Why this entity ranks where it does</Eyebrow><p className="text-[10px] leading-5 text-[#c7c0b5]">{entity.why}</p><p className="mt-3 border-t border-white/[.07] pt-2 text-[8px] leading-4 text-[#8b8680]">{entity.caveat}</p></Panel>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">{[["Rank", `#${entity.rank}`], ["Links", String(entity.connections)], ["Sources", String(entity.supporting_evidence_count)], ["Groups", String(entity.communities_linked)]].map(([label, value]) => <div key={label} className="rounded-lg border border-white/[.07] bg-black/[.12] p-3"><small className="text-[8px] uppercase tracking-[.1em] text-[#827d74]">{label}</small><b className="mt-2 block text-[13px] text-[#e6dfd4]">{value}</b></div>)}</div>
        <div><div className="mb-2 flex items-center justify-between"><Eyebrow>Neighbourhood</Eyebrow><div className="flex gap-1.5">{[1, 2, 3].map((value) => <button key={value} onClick={() => setHops(value)} className={`rounded-md px-2.5 py-1 text-[9px] font-bold ${hops === value ? "bg-[#7f1d1d] text-white" : "border border-white/[.11] text-[#c4beb4] hover:bg-white/[.05]"}`}>{value} hop{value > 1 ? "s" : ""}</button>)}</div></div>
          {loading ? <div className="grid h-40 place-items-center rounded-lg border border-white/[.08] bg-black/[.1]"><Loader2 className="animate-spin text-[#b0807a]" size={20} /></div> : <NetworkCanvas nodes={subgraph?.nodes || []} edges={subgraph?.edges || []} selected={entity.entity_id} onSelect={() => {}} />}
        </div>
        <div><Eyebrow>Relationships involving this entity</Eyebrow>{relations.length === 0 ? <Empty title="No relationships recorded" detail="This entity was observed in the evidence but no source states a relationship between it and another entity." /> : <div className="space-y-2">{relations.map((relation) => <div key={relation.id} className="rounded-lg border border-white/[.08] bg-black/[.12] p-3"><div className="flex flex-wrap items-center justify-between gap-2"><b className="text-[10px] text-[#e6dfd4]">{relation.subject.label} <span style={{ color: relationTone(relation.relation_type) }}>{relation.directed ? "→" : "—"}</span> {relation.object.label}</b><Pill tone={verificationTone(relation.verification_status)}>{readable(relation.verification_status)}</Pill></div><p className="mono mt-1.5 text-[8px] text-[#8f8a81]">{readable(relation.relation_type)} · {readable(relation.basis)} · {sourceLocation(relation.source_reference)}</p></div>)}</div>}</div>
        <Trace />
      </div>
    </aside></>;
}

export default function NetworkIntelligence({ caseId, say }: { caseId: string; say: (message: string) => void }) {
  const [overview, setOverview] = useState<NetworkOverviewRecord | null>(null);
  const [important, setImportant] = useState<ImportantEntityRecord[]>([]);
  const [bridges, setBridges] = useState<BridgeRecord[]>([]);
  const [communities, setCommunities] = useState<CommunityRecord[]>([]);
  const [summary, setSummary] = useState<EntityRelationSummaryRecord[]>([]);
  const [relations, setRelations] = useState<EntityRelationRecord[]>([]);
  const [metric, setMetric] = useState<ImportanceMetric>("betweenness_centrality");
  const [minConfidence, setMinConfidence] = useState(0);
  const [typeFilter, setTypeFilter] = useState("");
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [openRelation, setOpenRelation] = useState<EntityRelationRecord | null>(null);
  const [openEntity, setOpenEntity] = useState<ImportantEntityRecord | null>(null);
  const [path, setPath] = useState<NetworkPathRecord | null>(null);
  const [pathFrom, setPathFrom] = useState("");
  const [pathTo, setPathTo] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [overviewData, importantData, bridgeData, communityData, summaryData, relationPage] = await Promise.all([
        getNetworkOverview(caseId), getImportantEntities(caseId, { metric, min_confidence: minConfidence, limit: 12 }),
        getNetworkBridges(caseId, minConfidence), getNetworkCommunities(caseId, minConfidence),
        getEntityRelationSummary(caseId), getEntityRelations(caseId, { limit: 300, relation_type: typeFilter || undefined }),
      ]);
      setOverview(overviewData); setImportant(importantData); setBridges(bridgeData); setCommunities(communityData); setSummary(summaryData); setRelations(relationPage.items);
    } catch (error) { say(getApiErrorMessage(error, "The network could not be loaded for this case.")); }
    finally { setLoading(false); }
  }, [caseId, metric, minConfidence, typeFilter, say]);

  useEffect(() => { load(); }, [load]);

  // The canvas is drawn from the relationship summary: one line per distinct relationship rather
  // than one per observation, so a pair seen in three records is one edge and not three.
  const canvas = useMemo(() => {
    const nodes = new Map<string, { id: string; label: string; entity_type: string }>();
    const edges: NetworkEdgeRecord[] = [];
    summary.forEach((entry) => {
      [entry.subject, entry.object].forEach((end) => { if (end?.id && !nodes.has(end.id)) nodes.set(end.id, { id: end.id, label: end.label || end.id, entity_type: end.type || "unknown" }); });
      edges.push({ subject_entity_id: entry.subject.id, object_entity_id: entry.object.id, relation_types: [entry.relation_type], confidence: entry.confidence, observations: entry.observation_count, supporting_evidence_count: entry.supporting_evidence_count });
    });
    return { nodes: [...nodes.values()], edges };
  }, [summary]);

  const relationTypes = useMemo(() => [...new Set(summary.map((entry) => entry.relation_type))].sort(), [summary]);
  const findPath = async () => { try { setPath(await getNetworkPath(caseId, pathFrom, pathTo)); } catch (error) { say(getApiErrorMessage(error, "The path could not be traced.")); } };

  if (loading && !overview) return <div className="grid h-64 place-items-center"><Loader2 className="animate-spin text-[#b0807a]" size={26} /></div>;
  if (overview && overview.entities === 0) return <Empty title="No network yet for this case" detail="Upload and process evidence first. Relationships are derived only from what a source states, so a case with no processed evidence has no network to analyse." />;

  return <div className="space-y-5">
    <Panel className="relative overflow-hidden p-5"><img src={A.hero} alt="" aria-hidden className="pointer-events-none absolute -right-6 -top-6 h-40 w-40 object-contain opacity-[.14]" />
      <Eyebrow>Network intelligence / evidence-supported relationships only</Eyebrow>
      <h2 className="text-[15px] font-extrabold text-[#f1ebe0]">Who connects what, and on whose evidence</h2>
      <p className="relative mt-2 max-w-3xl text-[10px] leading-5 text-[#a09a91]">Every relationship on this page was read from a source and can be opened at the row, page or image region it came from. Network position indicates review priority. It is never an indication of guilt.</p>
      <div className="relative mt-4 flex flex-wrap gap-2"><Pill tone="green">{overview?.relationships ?? 0} relationships</Pill><Pill tone="blue">{overview?.entities ?? 0} entities</Pill><Pill tone="amber">{overview?.communities ?? 0} groups</Pill><Pill tone="red">{overview?.bridges ?? 0} bridges</Pill><Button tone="quiet" onClick={load}><RefreshCw size={13} /> Refresh</Button></div>
    </Panel>

    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Metric label="Entities in the network" value={String(overview?.entities ?? 0)} detail="Resolved identities that at least one source relates to another." image={A.board} tone="blue" />
      <Metric label="Stated relationships" value={String(overview?.relationships ?? 0)} detail="Distinct pairs. Repeat observations of one pair count once here." image={A.hero} tone="green" />
      <Metric label="Connected groups" value={String(overview?.communities ?? 0)} detail="Clusters more connected internally than to the rest of the case." image={A.community} tone="amber" />
      <Metric label="Bridge relationships" value={String(overview?.bridges ?? 0)} detail="Single links holding two parts of the network together. Verify these first." image={A.bridge} tone="burgundy" />
    </div>

    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-white/[.08] bg-black/[.14] px-3 py-2.5">
      <span className="text-[8px] font-bold uppercase tracking-[.12em] text-[#827d74]">Ranking</span>
      {(["betweenness_centrality", "degree_centrality", "eigenvector_centrality"] as ImportanceMetric[]).map((value) => <button key={value} onClick={() => setMetric(value)} className={`rounded-md px-2.5 py-1.5 text-[9px] font-bold ${metric === value ? "bg-[#7f1d1d] text-white" : "border border-white/[.11] text-[#c4beb4] hover:bg-white/[.05]"}`}>{readable(value.replace("_centrality", ""))}</button>)}
      <span className="ml-3 text-[8px] font-bold uppercase tracking-[.12em] text-[#827d74]">Minimum confidence</span>
      {[0, 0.5, 0.8].map((value) => <button key={value} onClick={() => setMinConfidence(value)} className={`rounded-md px-2.5 py-1.5 text-[9px] font-bold ${minConfidence === value ? "bg-[#7f1d1d] text-white" : "border border-white/[.11] text-[#c4beb4] hover:bg-white/[.05]"}`}>{value === 0 ? "All" : value.toFixed(1)}</button>)}
    </div>

    <NetworkCanvas nodes={canvas.nodes} edges={canvas.edges} selected={selectedNode} onSelect={setSelectedNode} />

    <div><div className="mb-2 flex items-center gap-2"><Network size={14} className="text-[#b0807a]" /><Eyebrow>Most important entities / review priority, not guilt</Eyebrow></div>
      {important.length === 0 ? <Empty title="Nothing ranked yet" detail="Ranking needs at least one stated relationship between two resolved identities." /> : <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{important.map((record) => <ImportanceCard key={record.entity_id} record={record} onOpen={() => setOpenEntity(record)} />)}</div>}
    </div>

    <div className="grid gap-3 xl:grid-cols-2">
      <Panel className="p-4"><div className="mb-3 flex items-center gap-2"><ShieldCheck size={14} className="text-[#e0a49c]" /><Eyebrow>Bridge relationships / verify these first</Eyebrow></div>
        {bridges.length === 0 ? <p className="text-[9px] leading-5 text-[#928d84]">No single relationship is currently holding two parts of this network together.</p> : <div className="space-y-2">{bridges.slice(0, 6).map((bridge, index) => <div key={`${bridge.subject.id}-${bridge.object.id}-${index}`} className="rounded-lg border border-white/[.08] bg-black/[.12] p-3"><div className="flex flex-wrap items-center justify-between gap-2"><b className="text-[10px] text-[#e6dfd4]">{bridge.subject.label} <span className="text-[#a45d57]">—</span> {bridge.object.label}</b><Pill tone="green">{bridge.supporting_evidence_count} sources</Pill></div><p className="mt-1.5 text-[9px] leading-5 text-[#a49e95]">{bridge.why}</p><p className="mono mt-1 text-[8px] text-[#8f8a81]">{bridge.relation_types.map(readable).join(" · ")}</p></div>)}</div>}
      </Panel>
      <Panel className="p-4"><div className="mb-3 flex items-center gap-2"><Users size={14} className="text-[#e3c48a]" /><Eyebrow>Connected groups / a pattern, not an organisation</Eyebrow></div>
        {communities.length === 0 ? <p className="text-[9px] leading-5 text-[#928d84]">The network is not yet large enough to separate into groups.</p> : <div className="space-y-2">{communities.slice(0, 6).map((cluster) => <div key={cluster.community_id} className="rounded-lg border border-white/[.08] bg-black/[.12] p-3"><div className="flex items-center justify-between gap-2"><b className="text-[10px] text-[#e6dfd4]">Group {cluster.community_id + 1}</b><Pill tone="blue">{cluster.size} entities</Pill></div><p className="mt-1.5 text-[9px] leading-5 text-[#a49e95]">{cluster.members.slice(0, 6).map((member) => member.label).filter(Boolean).join(", ")}{cluster.members.length > 6 ? ` and ${cluster.members.length - 6} more` : ""}</p></div>)}<p className="pt-1 text-[8px] leading-4 text-[#8b8680]">{communities[0]?.caveat}</p></div>}
      </Panel>
    </div>

    <Panel className="p-4"><div className="mb-3 flex items-center gap-2"><Route size={14} className="text-[#a9cbd6]" /><Eyebrow>Trace a connection / "no path" is a real answer</Eyebrow></div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-[190px] flex-1"><small className="mb-1 block text-[8px] uppercase tracking-[.1em] text-[#827d74]">From</small><select value={pathFrom} onChange={(event) => setPathFrom(event.target.value)} className="w-full rounded-md border border-white/[.11] bg-black/[.18] px-2.5 py-2 text-[10px] text-[#e6dfd4] outline-none focus:border-[#a85e58]"><option value="">Select an entity</option>{canvas.nodes.map((node) => <option key={node.id} value={node.id}>{node.label}</option>)}</select></label>
        <label className="min-w-[190px] flex-1"><small className="mb-1 block text-[8px] uppercase tracking-[.1em] text-[#827d74]">To</small><select value={pathTo} onChange={(event) => setPathTo(event.target.value)} className="w-full rounded-md border border-white/[.11] bg-black/[.18] px-2.5 py-2 text-[10px] text-[#e6dfd4] outline-none focus:border-[#a85e58]"><option value="">Select an entity</option>{canvas.nodes.map((node) => <option key={node.id} value={node.id}>{node.label}</option>)}</select></label>
        <Button tone="burgundy" onClick={findPath} disabled={!pathFrom || !pathTo}><ArrowRight size={13} /> Trace</Button>
      </div>
      {path && <div className="mt-3 rounded-lg border border-white/[.08] bg-black/[.12] p-3">{path.found ? <><p className="text-[10px] font-bold text-[#e6dfd4]">{path.nodes.map((node) => node.label).join("  →  ")}</p><div className="mt-2 flex flex-wrap gap-1.5"><Pill tone="blue">{path.edges.length} steps</Pill><Pill tone={path.weakest_link_confidence >= 0.8 ? "green" : "amber"}>Weakest link {path.weakest_link_confidence?.toFixed(2)}</Pill></div><p className="mt-2 text-[8px] leading-4 text-[#8b8680]">{path.caveat}</p></> : <p className="text-[9px] leading-5 text-[#c9a268]">{path.reason}</p>}</div>}
    </Panel>

    <div><div className="mb-2 flex flex-wrap items-center justify-between gap-2"><Eyebrow>Relationship observations / one row is one source statement</Eyebrow>
      <div className="flex flex-wrap gap-1.5"><button onClick={() => setTypeFilter("")} className={`rounded-md px-2.5 py-1.5 text-[9px] font-bold ${!typeFilter ? "bg-[#7f1d1d] text-white" : "border border-white/[.11] text-[#c4beb4] hover:bg-white/[.05]"}`}>All</button>{relationTypes.map((type) => <button key={type} onClick={() => setTypeFilter(type)} className={`rounded-md px-2.5 py-1.5 text-[9px] font-bold ${typeFilter === type ? "bg-[#7f1d1d] text-white" : "border border-white/[.11] text-[#c4beb4] hover:bg-white/[.05]"}`}>{readable(type)}</button>)}</div>
    </div>
      {relations.length === 0 ? <Empty title="No relationship observations" detail="Nothing in the processed evidence states a relationship of this kind." /> : <Panel className="overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[860px] text-left text-[9px] text-[#cfc7bb]">
        <thead className="bg-black/[.12] text-[8px] uppercase tracking-[.12em] text-[#77746d]"><tr><th className="px-4 py-3">Relationship</th><th className="py-3">Type</th><th className="py-3">Read from</th><th className="py-3">Source location</th><th className="py-3">Confidence</th><th className="py-3">Verification</th><th className="py-3" /></tr></thead>
        <tbody className="divide-y divide-white/[.06]">{relations.map((relation) => <tr key={relation.id} className="hover:bg-white/[.03]">
          <td className="px-4 py-3"><b className="text-[#e6dfd4]">{relation.subject.label}</b> <span style={{ color: relationTone(relation.relation_type) }}>{relation.directed ? "→" : "—"}</span> <b className="text-[#e6dfd4]">{relation.object.label}</b></td>
          <td className="py-3"><span className="inline-flex items-center gap-1.5"><i className="h-1.5 w-1.5 rounded-full" style={{ background: relationTone(relation.relation_type) }} />{readable(relation.relation_type)}</span></td>
          <td className="py-3">{readable(relation.basis)}</td>
          <td className="mono py-3 text-[8px] text-[#948e85]">{sourceLocation(relation.source_reference)}</td>
          <td className="py-3">{relation.confidence.toFixed(2)}</td>
          <td className="py-3"><Pill tone={verificationTone(relation.verification_status)}>{readable(relation.verification_status)}</Pill></td>
          <td className="py-3 pr-4 text-right"><Button tone="quiet" onClick={() => setOpenRelation(relation)}>Open source</Button></td>
        </tr>)}</tbody>
      </table></div></Panel>}
    </div>

    <Trace />
    <RelationDrawer relation={openRelation} caseId={caseId} onClose={() => setOpenRelation(null)} onReviewed={load} say={say} />
    <EntityDrawer entity={openEntity} caseId={caseId} onClose={() => setOpenEntity(null)} say={say} />
  </div>;
}
