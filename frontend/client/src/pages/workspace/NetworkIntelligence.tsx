// @ts-nocheck
/* NETWORK_INTELLIGENCE_20260908: the SIH26189 criminal-network surface.
 *
 * House rule for this whole view: a centrality score is never rendered on its own. The server
 * sends `why` and `caveat` with every ranked entity and both are always shown, because a bare
 * number invites the reading that DRISHYAM is scoring people for criminality. It is not.
 *
 * Presentation follows the ivory case-overview surface, not the dark sidebar: cream cards on the
 * archive background, serif numerals, burgundy accents, and the evidence artwork sitting bottom
 * right of a card at full weight the way the overview metrics use it.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowRight, Check, FileSearch, Loader2, Network, RefreshCw, Route, ShieldCheck, Users, X } from "lucide-react";
import { getApiErrorMessage } from "@/api/client";
import EvidenceSourceViewer from "@/components/EvidenceSourceViewer";
import { targetFromReference } from "@/api/sourceView";
import {
  getEntityRelationSummary, getEntityRelations, getImportantEntities, getNetworkBridges, getNetworkCommunities, getNetworkOverview, getNetworkPath, getNetworkSubgraph, reviewEntityRelation,
  type ImportanceMetric,
} from "@/api/network";

const A = {
  hero: "/assets/cap-original-relationship-graph.png",
  importance: "/assets/journey-analyze-graph-monitor.png",
  bridge: "/assets/trail-map-evidence_71482f25.png",
  community: "/assets/cap-relationship-graph_b226489e.png",
  board: "/assets/workspace-map-board_c063d31f.png",
  identity: "/assets/reference-fingerprint_4cf2ff3f.png",
};

/* --- ivory surface primitives, matching the case-overview palette --------------------------- */
function Card({ children, className = "" }) { return <section className={`rounded-2xl border border-[#e2d5c7] bg-[#fffdf8] shadow-[0_14px_34px_rgba(82,49,36,.08)] ${className}`}>{children}</section>; }
function Eyebrow({ children }) { return <p className="mb-2 text-[8px] font-bold uppercase tracking-[.16em] text-[#8e2d28]">{children}</p>; }
function Pill({ children, tone = "burgundy" }) { const styles = { burgundy: "border-[#bd8177] bg-[#fff5f1] text-[#8f2f2a]", green: "border-[#9fc5a9] bg-[#f1f8f1] text-[#24633d]", blue: "border-[#b6cbd2] bg-[#f2f8fa] text-[#365e6c]", amber: "border-[#dcc08a] bg-[#fdf7ea] text-[#8a5f1c]", grey: "border-[#d8cec2] bg-[#f7f3ec] text-[#6d6055]" }; return <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[8px] font-bold tracking-[.05em] ${styles[tone] || styles.burgundy}`}><i className="h-1.5 w-1.5 rounded-full bg-current" />{children}</span>; }
function Button({ children, onClick, tone = "outline", disabled = false }) { const styles = tone === "burgundy" ? "bg-[#8e2d28] text-white hover:bg-[#7c2622] disabled:hover:bg-[#8e2d28]" : tone === "quiet" ? "text-[#7c4a44] hover:bg-[#f6ece5]" : "border border-[#ded0c0] bg-white text-[#5c4a3f] hover:border-[#bd8177] hover:bg-[#fff5f1]"; return <button type="button" onClick={onClick} disabled={disabled} className={`inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-[10px] font-bold transition disabled:cursor-not-allowed disabled:opacity-50 ${styles}`}>{children}</button>; }
function Chip({ active, children, onClick }) { return <button type="button" onClick={onClick} className={`rounded-lg px-2.5 py-1.5 text-[9px] font-bold transition ${active ? "bg-[#8e2d28] text-white shadow-[0_4px_12px_rgba(142,45,40,.24)]" : "border border-[#ded0c0] bg-white text-[#6b594d] hover:border-[#bd8177] hover:bg-[#fff5f1]"}`}>{children}</button>; }
function Blank({ title, detail }) { return <div className="rounded-2xl border border-dashed border-[#dccdbc] bg-[#fbf6ef] p-8 text-center"><AlertTriangle className="mx-auto text-[#b98a34]" size={20} /><h2 className="mt-3 text-[12px] font-bold text-[#42342c]">{title}</h2><p className="mx-auto mt-2 max-w-xl text-[9px] leading-5 text-[#88796d]">{detail}</p></div>; }
function Trace() { return <div className="border-t border-[#e6d9c9] pt-4"><p className="text-[8px] font-bold uppercase tracking-[.12em] text-[#8a7d71]">Route back to evidence</p><p className="mono mt-2 text-[8px] font-bold text-[#9b3730]">GRAPH <span className="text-[#c9a79c]">›</span> RELATIONSHIP <span className="text-[#c9a79c]">›</span> CLAIM <span className="text-[#c9a79c]">›</span> EVIDENCE <span className="text-[#c9a79c]">›</span> ORIGINAL SOURCE</p></div>; }

/* Relation colours are tuned for ink on cream, not for the dark sidebar. */
const RELATION_TONE = { TRANSFERRED_TO: "#277044", REQUESTED_PAYMENT_FROM: "#a9701a", MESSAGED: "#2f6274", COMMUNICATED_WITH: "#6a4f9c", ASSOCIATED_WITH: "#8a6a33", MENTIONED_WITH: "#9a8d80" };
const relationTone = (type) => RELATION_TONE[type] || "#9a8d80";
const entityTone = (kind) => { const k = String(kind || "").toLowerCase(); if (k.includes("person") || k === "party") return "#9d342e"; if (k.includes("vehicle")) return "#a85c22"; if (k.includes("organisation")) return "#6a4f9c"; if (k.includes("location")) return "#2f6274"; if (k.includes("upi") || k.includes("account") || k.includes("ifsc")) return "#277044"; if (k.includes("phone")) return "#a9701a"; if (k.includes("email")) return "#2d7b81"; return "#4d7387"; };
const readable = (value) => String(value || "").replace(/_/g, " ");
const verificationTone = (state) => (state === "human_verified" ? "green" : state === "rejected" ? "burgundy" : "amber");

const RELATION_MEANING = {
  TRANSFERRED_TO: "The source states that the first party sent money to the second.",
  REQUESTED_PAYMENT_FROM: "The source states that the first party asked the second for money. It does not record that any money moved.",
  MESSAGED: "The source states that the first party sent a message to the second.",
  COMMUNICATED_WITH: "The source records contact between the two parties but does not state who initiated it.",
  ASSOCIATED_WITH: "The source names these two as the parties to the same record, without stating what passed between them.",
  MENTIONED_WITH: "The source names both in the same record. It does not state any relationship between them.",
};

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
  const colors = { burgundy: "text-[#9d342e]", green: "text-[#277044]", blue: "text-[#365f70]", amber: "text-[#996422]" };
  return <article className="relative min-h-[128px] overflow-hidden rounded-xl border border-[#e8dccf] bg-[#fffdf8] p-4 shadow-[0_6px_16px_rgba(82,49,36,.05)]">
    <b className={`block font-serif text-[34px] leading-none ${colors[tone]}`}>{value}</b>
    <strong className="mt-2 block text-[10px] text-[#42342c]">{label}</strong>
    <small className="mt-1 block max-w-[64%] text-[8px] leading-4 text-[#88796d]">{detail}</small>
    <img src={image} alt="" aria-hidden loading="lazy" className="pointer-events-none absolute bottom-0 right-1 h-[62%] w-[32%] object-contain object-bottom-right opacity-70" />
  </article>;
}

function ImportanceCard({ record, onOpen, onOpenSource }) {
  return <div className="w-full rounded-xl border border-[#e8dccf] bg-[#fffdf8] p-4 text-left shadow-[0_6px_16px_rgba(82,49,36,.05)] transition hover:-translate-y-0.5 hover:border-[#bd8177] hover:shadow-[0_12px_26px_rgba(82,49,36,.1)]">
    <button onClick={onOpen} className="w-full text-left" aria-label={`Open details for ${record.label}`}>
    <div className="flex items-start justify-between gap-3">
      <span className="flex min-w-0 items-center gap-2.5"><i className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: entityTone(record.entity_type) }} /><span className="min-w-0"><b className="block truncate text-[12px] font-bold text-[#2e2520]">{record.label}</b><small className="mono mt-0.5 block text-[8px] font-bold uppercase tracking-[.1em] text-[#9b8a7c]">{record.entity_type}</small></span></span>
      <span className="shrink-0 text-right"><b className="block font-serif text-[20px] leading-none text-[#9d342e]">#{record.rank}</b><small className="mono mt-1 block text-[8px] text-[#9b8a7c]">{record.score.toFixed(3)}</small></span>
    </div>
    <p className="mt-3 text-[9px] leading-5 text-[#5f5147]">{record.why}</p>
    <div className="mt-3 flex flex-wrap items-center gap-1.5"><Pill tone="blue">{record.connections} links</Pill><Pill tone="green">{record.supporting_evidence_count} sources</Pill>{record.communities_linked > 1 && <Pill tone="amber">{record.communities_linked} groups</Pill>}{record.is_bridge && <Pill tone="burgundy">Cut point</Pill>}</div>
    <p className="mt-3 border-t border-[#eadfd3] pt-2 text-[8px] leading-4 text-[#94867a]">{record.caveat}</p>
    </button>
    <button onClick={onOpenSource} className="mt-2.5 inline-flex items-center gap-1.5 rounded-lg border border-[#dfd0c0] bg-[#fffaf4] px-2.5 py-1.5 text-[9px] font-bold text-[#8f302b] transition hover:border-[#b36b62] hover:bg-[#fff2ef]"><FileSearch size={11}/>Open in file</button>
  </div>;
}

function NetworkCanvas({ nodes, edges, selected, onSelect, height = 520 }) {
  // Rings sized to the frame rather than to a fixed radius, so labels do not collide in the middle
  // while the sides stay empty.
  const positions = useMemo(() => {
    const result = new Map();
    const total = nodes.length;
    if (!total) return result;
    if (total === 1) { result.set(nodes[0].id, { x: 450, y: 262 }); return result; }
    const firstRing = Math.min(total, 9);
    const rings = [{ from: 0, to: firstRing, radius: total <= 4 ? 130 : 196 }];
    if (total > firstRing) rings.push({ from: firstRing, to: total, radius: 112 });
    rings.forEach(({ from, to, radius }, ringIndex) => {
      const size = to - from;
      for (let index = from; index < to; index += 1) {
        const angle = ((index - from) / size) * Math.PI * 2 - Math.PI / 2 + (ringIndex ? Math.PI / size : 0);
        result.set(nodes[index].id, { x: 450 + Math.cos(angle) * radius, y: 262 + Math.sin(angle) * radius * 0.82 });
      }
    });
    return result;
  }, [nodes]);

  const touching = new Set(edges.filter((e) => e.subject_entity_id === selected || e.object_entity_id === selected).flatMap((e) => [e.subject_entity_id, e.object_entity_id]));
  if (!nodes.length) return <Blank title="No relationships to draw yet" detail="Relationships appear once evidence has been processed and identities resolved. Nothing is drawn that the evidence does not support." />;

  return <Card className="overflow-hidden">
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#eadfd3] px-4 py-3">
      <Eyebrow>Relationship map / every edge opens at its source</Eyebrow>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">{Object.keys(RELATION_TONE).map((type) => <span key={type} className="inline-flex items-center gap-1.5 text-[8px] font-bold uppercase tracking-[.06em] text-[#7d7065]"><i className="h-1 w-4 rounded-full" style={{ background: relationTone(type) }} />{readable(type)}</span>)}</div>
    </div>
    <div className="overflow-x-auto bg-[#fbf7f0]"><svg viewBox="0 0 900 520" style={{ height }} className="w-full min-w-[820px]" role="img" aria-label="Case relationship map">
      <defs><pattern id="net-grid" width="34" height="34" patternUnits="userSpaceOnUse"><path d="M34 0H0V34" fill="none" stroke="rgba(120,92,70,.09)" strokeWidth="1" /></pattern></defs>
      <rect width="900" height="520" fill="url(#net-grid)" />
      {edges.map((edge, index) => { const a = positions.get(edge.subject_entity_id); const b = positions.get(edge.object_entity_id); if (!a || !b) return null; const dim = selected && !(edge.subject_entity_id === selected || edge.object_entity_id === selected); const type = edge.relation_types?.[0] || "MENTIONED_WITH";
        return <line key={`${edge.subject_entity_id}-${edge.object_entity_id}-${index}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={relationTone(type)} strokeWidth={Math.max(1.2, edge.confidence * 3.2)} strokeDasharray={edge.confidence < 0.5 ? "5 4" : undefined} strokeLinecap="round" opacity={dim ? 0.15 : 0.85} />; })}
      {nodes.map((node) => { const point = positions.get(node.id); if (!point) return null; const dim = selected && node.id !== selected && !touching.has(node.id); const active = node.id === selected;
        return <g key={node.id} transform={`translate(${point.x},${point.y})`} opacity={dim ? 0.25 : 1} className="cursor-pointer" onClick={() => onSelect?.(active ? null : node.id)}>
          <circle r={active ? 15 : 11} fill={entityTone(node.entity_type)} stroke={active ? "#8e2d28" : "#fffdf8"} strokeWidth={active ? 3 : 2} />
          <text y={-22} textAnchor="middle" className="fill-[#2e2520] text-[9px] font-bold">{node.label?.length > 19 ? `${node.label.slice(0, 18)}…` : node.label}</text>
          <text y={28} textAnchor="middle" className="fill-[#94867a] text-[7px] font-bold uppercase tracking-[.1em]">{node.entity_type}</text>
        </g>; })}
    </svg></div>
    <p className="border-t border-[#eadfd3] px-4 py-2.5 text-[8px] leading-4 text-[#8a7d71]">A thicker line means the source states the relationship more firmly. A dashed line is co-occurrence only: the source named both in one record and stated no relationship between them.</p>
  </Card>;
}

function Drawer({ title, eyebrow, onClose, children, wide = false }) {
  return <><button aria-label="Close detail" onClick={onClose} className="fixed inset-0 z-[70] bg-[#2e2520]/45 backdrop-blur-[1px]" />
    <aside className={`fixed inset-y-0 right-0 z-[71] flex w-full ${wide ? "max-w-[640px]" : "max-w-[560px]"} flex-col border-l border-[#e2d5c7] bg-[#fbf7f0] shadow-[-24px_0_80px_rgba(82,49,36,.22)]`}>
      <div className="flex items-start justify-between gap-3 border-b border-[#e6d9c9] bg-[#fffdf8] px-5 py-5"><div className="min-w-0">{eyebrow}<h2 className="font-serif text-xl font-bold tracking-[-.02em] text-[#2e2520]">{title}</h2></div><button onClick={onClose} className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-[#ded0c0] bg-white text-[#7c6a5e] hover:border-[#bd8177] hover:bg-[#fff5f1]"><X size={17} /></button></div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">{children}</div>
    </aside></>;
}

function FactRows({ rows }) { return <div className="space-y-2">{rows.map(([label, value]) => <div key={label} className="flex justify-between gap-3 text-[9px]"><span className="text-[#8a7d71]">{label}</span><span className="mono max-w-[290px] break-all text-right font-bold text-[#42342c]">{value}</span></div>)}</div>; }

function RelationDrawer({ relation, caseId, onClose, onReviewed, say, onOpenSource }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  if (!relation) return null;
  const decide = async (action) => {
    setBusy(true);
    try { await reviewEntityRelation(caseId, relation.id, action, note.trim() || undefined); say(action === "confirm_relationship" ? "Relationship confirmed and recorded against your account." : "Relationship rejected. The original machine reading is kept for audit."); await onReviewed(); onClose(); }
    catch (error) { say(getApiErrorMessage(error, "The relationship review could not be recorded.")); }
    finally { setBusy(false); }
  };
  return <Drawer onClose={onClose} eyebrow={<Eyebrow>Relationship detail / one observation, one source</Eyebrow>} title={<>{relation.subject.label} <span className="text-[#b06058]">{relation.directed ? "→" : "—"}</span> {relation.object.label}</>}>
    <Card className="p-4"><Eyebrow>What the source states</Eyebrow><p className="text-[10px] leading-5 text-[#5f5147]">{RELATION_MEANING[relation.relation_type] || "The source records these two together."}</p></Card>
    <Card className="p-4"><Eyebrow>Provenance</Eyebrow><FactRows rows={[
      ["Relationship", readable(relation.relation_type)],
      ["Direction", relation.directed ? `${relation.subject.label} → ${relation.object.label}` : "Not established by the source"],
      ["Read from", readable(relation.basis)],
      ["Source evidence", relation.source_evidence_id],
      ["Source location", sourceLocation(relation.source_reference)],
      ["Observed at", relation.observed_at ? new Date(relation.observed_at).toLocaleString() : "Time not established"],
      ["Time precision", readable(relation.time_precision)],
      ["Confidence", relation.confidence.toFixed(2)],
      ["Verification", readable(relation.verification_status)],
    ]} />
    <button onClick={() => onOpenSource?.(relation)} className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-[#dfd0c0] bg-[#fffaf4] px-3 py-2 text-[9px] font-bold text-[#8f302b] transition hover:border-[#b36b62] hover:bg-[#fff2ef]"><FileSearch size={12}/>Open this place in the file</button></Card>
    {relation.review_note && <Card className="p-4"><Eyebrow>Reviewer note</Eyebrow><p className="text-[10px] leading-5 text-[#5f5147]">{relation.review_note}</p></Card>}
    <Card className="p-4"><Eyebrow>Record your decision</Eyebrow>
      <textarea value={note} onChange={(event) => setNote(event.target.value)} rows={3} placeholder="Why this relationship is or is not supported by the source." className="w-full rounded-lg border border-[#ded0c0] bg-white px-3 py-2 text-[10px] text-[#42342c] outline-none placeholder:text-[#a99c90] focus:border-[#bd8177]" />
      <div className="mt-3 flex flex-wrap gap-2"><Button tone="burgundy" onClick={() => decide("confirm_relationship")} disabled={busy}>{busy ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />} Confirm relationship</Button><Button onClick={() => decide("reject_relationship")} disabled={busy}><X size={13} /> Reject</Button></div>
      <p className="mt-3 text-[8px] leading-4 text-[#94867a]">A decision annotates this observation. The original machine reading is never deleted, so the record stays auditable.</p>
    </Card>
    <Trace />
  </Drawer>;
}

function EntityDrawer({ entity, caseId, onClose, say }) {
  const [hops, setHops] = useState(1);
  const [subgraph, setSubgraph] = useState(null);
  const [relations, setRelations] = useState([]);
  const [loading, setLoading] = useState(false);
  // `say` is recreated on every parent render, so it is held in a ref and kept out of the effect
  // dependencies. Depending on it re-ran the fetch after each response, forever.
  const notify = useRef(say); notify.current = say;
  const entityId = entity?.entity_id;
  useEffect(() => {
    if (!entityId) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([getNetworkSubgraph(caseId, entityId, hops), getEntityRelations(caseId, { entity_id: entityId, limit: 200 })])
      .then(([graph, page]) => { if (!cancelled) { setSubgraph(graph); setRelations(page.items); } })
      .catch((error) => { if (!cancelled) notify.current(getApiErrorMessage(error, "The entity neighbourhood could not be loaded.")); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [entityId, caseId, hops]);
  if (!entity) return null;
  return <Drawer wide onClose={onClose} eyebrow={<Eyebrow>Entity profile / no identity conclusion</Eyebrow>} title={<span className="flex items-center gap-2"><i className="h-3 w-3 shrink-0 rounded-full" style={{ background: entityTone(entity.entity_type) }} />{entity.label}</span>}>
    <Card className="relative overflow-hidden p-4"><Eyebrow>Why this entity ranks where it does</Eyebrow><p className="max-w-[76%] text-[10px] leading-5 text-[#5f5147]">{entity.why}</p><p className="mt-3 max-w-[76%] border-t border-[#eadfd3] pt-2 text-[8px] leading-4 text-[#94867a]">{entity.caveat}</p><img src={A.identity} alt="" aria-hidden loading="lazy" className="pointer-events-none absolute bottom-0 right-1 h-[64%] w-[22%] object-contain object-bottom-right opacity-70" /></Card>
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">{[["Rank", `#${entity.rank}`, "burgundy"], ["Links", String(entity.connections), "blue"], ["Sources", String(entity.supporting_evidence_count), "green"], ["Groups", String(entity.communities_linked), "amber"]].map(([label, value, tone]) => <div key={label} className="rounded-xl border border-[#e6d9c9] bg-[#fffdf8] p-3"><small className="text-[8px] font-bold uppercase tracking-[.1em] text-[#8a7d71]">{label}</small><b className={`mt-2 block font-serif text-[19px] leading-none ${{ burgundy: "text-[#9d342e]", green: "text-[#277044]", blue: "text-[#365f70]", amber: "text-[#996422]" }[tone]}`}>{value}</b></div>)}</div>
    <div><div className="mb-2 flex items-center justify-between"><Eyebrow>Neighbourhood</Eyebrow><div className="flex gap-1.5">{[1, 2, 3].map((value) => <Chip key={value} active={hops === value} onClick={() => setHops(value)}>{value} hop{value > 1 ? "s" : ""}</Chip>)}</div></div>
      {loading ? <div className="grid h-40 place-items-center rounded-2xl border border-[#e6d9c9] bg-[#fbf7f0]"><Loader2 className="animate-spin text-[#b06058]" size={20} /></div> : <NetworkCanvas height={340} nodes={subgraph?.nodes || []} edges={subgraph?.edges || []} selected={entity.entity_id} onSelect={null} />}
    </div>
    <div><Eyebrow>Relationships involving this entity</Eyebrow>{relations.length === 0 ? <Blank title="No relationships recorded" detail="This entity was observed in the evidence but no source states a relationship between it and another entity." /> : <div className="space-y-2">{relations.map((relation) => <div key={relation.id} className="rounded-xl border border-[#e6d9c9] bg-[#fffdf8] p-3"><div className="flex flex-wrap items-center justify-between gap-2"><b className="text-[10px] text-[#2e2520]">{relation.subject.label} <span style={{ color: relationTone(relation.relation_type) }}>{relation.directed ? "→" : "—"}</span> {relation.object.label}</b><Pill tone={verificationTone(relation.verification_status)}>{readable(relation.verification_status)}</Pill></div><p className="mono mt-1.5 text-[8px] text-[#8a7d71]">{readable(relation.relation_type)} · {readable(relation.basis)} · {sourceLocation(relation.source_reference)}</p></div>)}</div>}</div>
    <Trace />
  </Drawer>;
}

export default function NetworkIntelligence({ caseId, say }: { caseId: string; say: (message: string) => void }) {
  const [data, setData] = useState({ overview: null, important: [], bridges: [], communities: [], summary: [], relations: [] });
  const [metric, setMetric] = useState<ImportanceMetric>("betweenness_centrality");
  const [minConfidence, setMinConfidence] = useState(0);
  const [typeFilter, setTypeFilter] = useState("");
  const [selectedNode, setSelectedNode] = useState(null);
  const [openRelation, setOpenRelation] = useState(null);
  // The panel that shows a statement where it lives in the file it was read from.
  const [sourceRequest, setSourceRequest] = useState(null);
  const [openEntity, setOpenEntity] = useState(null);
  const [path, setPath] = useState(null);
  const [pathFrom, setPathFrom] = useState("");
  const [pathTo, setPathTo] = useState("");
  const [loading, setLoading] = useState(true);

  // The parent recreates `say` on every render. Holding it in a ref keeps `load` stable; depending
  // on it made the effect re-run after each response, which refetched forever and made the whole
  // page flicker.
  const notify = useRef(say); notify.current = say;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [overview, important, bridges, communities, summary, relationPage] = await Promise.all([
        getNetworkOverview(caseId), getImportantEntities(caseId, { metric, min_confidence: minConfidence, limit: 12 }),
        getNetworkBridges(caseId, minConfidence), getNetworkCommunities(caseId, minConfidence),
        getEntityRelationSummary(caseId), getEntityRelations(caseId, { limit: 300, relation_type: typeFilter || undefined }),
      ]);
      setData({ overview, important, bridges, communities, summary, relations: relationPage.items });
    } catch (error) { notify.current(getApiErrorMessage(error, "The network could not be loaded for this case.")); }
    finally { setLoading(false); }
  }, [caseId, metric, minConfidence, typeFilter]);

  useEffect(() => { load(); }, [load]);

  // Drawn from the relationship summary: one line per distinct relationship rather than one per
  // observation, so a pair seen in three records is one edge and not three.
  const canvas = useMemo(() => {
    const nodes = new Map(); const edges = [];
    data.summary.forEach((entry) => {
      [entry.subject, entry.object].forEach((end) => { if (end?.id && !nodes.has(end.id)) nodes.set(end.id, { id: end.id, label: end.label || end.id, entity_type: end.type || "unknown" }); });
      edges.push({ subject_entity_id: entry.subject.id, object_entity_id: entry.object.id, relation_types: [entry.relation_type], confidence: entry.confidence, observations: entry.observation_count, supporting_evidence_count: entry.supporting_evidence_count });
    });
    return { nodes: [...nodes.values()], edges };
  }, [data.summary]);

  // One relationship, opened at the cell, line or image region it was read from. The subject's
  // label goes along as the value to find: a stored image reference covers the whole canvas, so
  // the value is what lets the server narrow it to the region that actually reads it.
  const openRelationSource = (relation) => setSourceRequest({
    caseId,
    evidenceId: relation.source_evidence_id,
    target: targetFromReference(relation.source_reference, relation.subject?.label),
    title: `${relation.subject?.label ?? "?"} ${relation.directed ? "→" : "—"} ${relation.object?.label ?? "?"}`,
    subtitle: readable(relation.relation_type),
  });

  // An entity has no reference of its own -- it is a node, not an observation -- so it opens at the
  // first observation that states something about it. When nothing states anything, there is
  // nothing to open, and the button is not offered.
  const relationFor = (entityId) => data.relations.find(
    (relation) => relation.subject?.id === entityId || relation.object?.id === entityId,
  );

  const openEntitySource = (entityId, label) => {
    const relation = relationFor(entityId);
    if (!relation) { notify.current(`Nothing in this case states a relationship for ${label}, so there is no source to open.`); return; }
    setSourceRequest({
      caseId,
      evidenceId: relation.source_evidence_id,
      target: targetFromReference(relation.source_reference, label),
      title: label,
      subtitle: "Opened at the first evidence that states a relationship for this entity",
    });
  };

  // Clicking a node does both things a reader wants at once: it dims the rest of the map to what
  // this entity touches, and it opens the evidence that put the entity on the map at all. Clicking
  // the selected node again clears both.
  const selectNode = (nodeId) => {
    if (!nodeId || nodeId === selectedNode) { setSelectedNode(null); setSourceRequest(null); return; }
    setSelectedNode(nodeId);
    const node = canvas.nodes.find((item) => item.id === nodeId);
    openEntitySource(nodeId, node?.label ?? "This entity");
  };

  const relationTypes = useMemo(() => [...new Set(data.summary.map((entry) => entry.relation_type))].sort(), [data.summary]);
  const findPath = async () => { try { setPath(await getNetworkPath(caseId, pathFrom, pathTo)); } catch (error) { notify.current(getApiErrorMessage(error, "The path could not be traced.")); } };

  const { overview, important, bridges, communities, relations } = data;
  if (loading && !overview) return <div className="grid h-64 place-items-center"><Loader2 className="animate-spin text-[#b06058]" size={26} /></div>;
  if (overview && overview.entities === 0) return <Blank title="No network yet for this case" detail="Upload and process evidence first. Relationships are derived only from what a source states, so a case with no processed evidence has no network to analyse." />;

  return <div className="space-y-5 text-[#312722]">
    <Card className="relative overflow-hidden p-5 sm:p-6">
      <Eyebrow>Network intelligence / evidence-supported relationships only</Eyebrow>
      <h2 className="font-serif text-2xl font-bold tracking-[-.02em] text-[#2e2520]">Who connects what, and on whose evidence</h2>
      <p className="mt-2 max-w-2xl text-[10px] leading-5 text-[#74685e]">Every relationship on this page was read from a source and can be opened at the row, page or image region it came from. Network position indicates review priority. It is never an indication of guilt.</p>
      <div className="mt-4 flex flex-wrap items-center gap-2"><Pill tone="green">{overview?.relationships ?? 0} relationships</Pill><Pill tone="blue">{overview?.entities ?? 0} entities</Pill><Pill tone="amber">{overview?.communities ?? 0} groups</Pill><Pill tone="burgundy">{overview?.bridges ?? 0} bridges</Pill><Button tone="quiet" onClick={load} disabled={loading}>{loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Refresh</Button></div>
      <img src={A.hero} alt="" aria-hidden loading="lazy" className="pointer-events-none absolute bottom-0 right-2 hidden h-[86%] w-[20%] object-contain object-bottom-right opacity-70 sm:block" />
    </Card>

    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Metric label="Entities in the network" value={String(overview?.entities ?? 0)} detail="Resolved identities that at least one source relates to another." image={A.board} tone="blue" />
      <Metric label="Stated relationships" value={String(overview?.relationships ?? 0)} detail="Distinct pairs. Repeat observations count once." image={A.hero} tone="green" />
      <Metric label="Connected groups" value={String(overview?.communities ?? 0)} detail="Clusters more connected internally than to the rest of the case." image={A.community} tone="amber" />
      <Metric label="Bridge relationships" value={String(overview?.bridges ?? 0)} detail="Single links holding two parts of the network together." image={A.bridge} tone="burgundy" />
    </div>

    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-[#e8dccf] bg-[#fffdf8] px-4 py-3 shadow-[0_6px_16px_rgba(82,49,36,.05)]">
      <span className="text-[8px] font-bold uppercase tracking-[.12em] text-[#8a7d71]">Ranking</span>
      {(["betweenness_centrality", "degree_centrality", "eigenvector_centrality"] as ImportanceMetric[]).map((value) => <Chip key={value} active={metric === value} onClick={() => setMetric(value)}>{readable(value.replace("_centrality", ""))}</Chip>)}
      <span className="ml-3 text-[8px] font-bold uppercase tracking-[.12em] text-[#8a7d71]">Minimum confidence</span>
      {[0, 0.5, 0.8].map((value) => <Chip key={value} active={minConfidence === value} onClick={() => setMinConfidence(value)}>{value === 0 ? "All" : value.toFixed(1)}</Chip>)}
    </div>

    <NetworkCanvas nodes={canvas.nodes} edges={canvas.edges} selected={selectedNode} onSelect={selectNode} />

    <div><div className="mb-2 flex items-center gap-2"><Network size={14} className="text-[#8e2d28]" /><Eyebrow>Most important entities / review priority, not guilt</Eyebrow></div>
      {important.length === 0 ? <Blank title="Nothing ranked yet" detail="Ranking needs at least one stated relationship between two resolved identities." /> : <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{important.map((record) => <ImportanceCard key={record.entity_id} record={record} onOpen={() => setOpenEntity(record)} onOpenSource={() => openEntitySource(record.entity_id, record.label)} />)}</div>}
    </div>

    <div className="grid gap-3 xl:grid-cols-2">
      <Card className="p-4 sm:p-5"><div className="mb-3 flex items-center gap-2"><ShieldCheck size={14} className="text-[#8e2d28]" /><Eyebrow>Bridge relationships / verify these first</Eyebrow></div>
        {bridges.length === 0 ? <p className="text-[9px] leading-5 text-[#88796d]">No single relationship is currently holding two parts of this network together.</p> : <div className="space-y-2">{bridges.slice(0, 6).map((bridge, index) => <div key={`${bridge.subject.id}-${bridge.object.id}-${index}`} className="rounded-xl border border-[#e6d9c9] bg-[#fbf7f0] p-3"><div className="flex flex-wrap items-center justify-between gap-2"><b className="text-[10px] text-[#2e2520]">{bridge.subject.label} <span className="text-[#b06058]">—</span> {bridge.object.label}</b><Pill tone="green">{bridge.supporting_evidence_count} sources</Pill></div><p className="mt-1.5 text-[9px] leading-5 text-[#6b5d52]">{bridge.why}</p><p className="mono mt-1 text-[8px] font-bold text-[#9b8a7c]">{bridge.relation_types.map(readable).join(" · ")}</p></div>)}</div>}
      </Card>
      <Card className="p-4 sm:p-5"><div className="mb-3 flex items-center gap-2"><Users size={14} className="text-[#996422]" /><Eyebrow>Connected groups / a pattern, not an organisation</Eyebrow></div>
        {communities.length === 0 ? <p className="text-[9px] leading-5 text-[#88796d]">The network is not yet large enough to separate into groups.</p> : <div className="space-y-2">{communities.slice(0, 6).map((cluster) => <div key={cluster.community_id} className="rounded-xl border border-[#e6d9c9] bg-[#fbf7f0] p-3"><div className="flex items-center justify-between gap-2"><b className="text-[10px] text-[#2e2520]">Group {cluster.community_id + 1}</b><Pill tone="blue">{cluster.size} entities</Pill></div><p className="mt-1.5 text-[9px] leading-5 text-[#6b5d52]">{cluster.members.slice(0, 6).map((member) => member.label).filter(Boolean).join(", ")}{cluster.members.length > 6 ? ` and ${cluster.members.length - 6} more` : ""}</p></div>)}<p className="pt-1 text-[8px] leading-4 text-[#94867a]">{communities[0]?.caveat}</p></div>}
      </Card>
    </div>

    <Card className="p-4 sm:p-5"><div className="mb-3 flex items-center gap-2"><Route size={14} className="text-[#365f70]" /><Eyebrow>Trace a connection / "no path" is a real answer</Eyebrow></div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-[190px] flex-1"><small className="mb-1 block text-[8px] font-bold uppercase tracking-[.1em] text-[#8a7d71]">From</small><select value={pathFrom} onChange={(event) => setPathFrom(event.target.value)} className="w-full rounded-lg border border-[#ded0c0] bg-white px-2.5 py-2 text-[10px] text-[#42342c] outline-none focus:border-[#bd8177]"><option value="">Select an entity</option>{canvas.nodes.map((node) => <option key={node.id} value={node.id}>{node.label}</option>)}</select></label>
        <label className="min-w-[190px] flex-1"><small className="mb-1 block text-[8px] font-bold uppercase tracking-[.1em] text-[#8a7d71]">To</small><select value={pathTo} onChange={(event) => setPathTo(event.target.value)} className="w-full rounded-lg border border-[#ded0c0] bg-white px-2.5 py-2 text-[10px] text-[#42342c] outline-none focus:border-[#bd8177]"><option value="">Select an entity</option>{canvas.nodes.map((node) => <option key={node.id} value={node.id}>{node.label}</option>)}</select></label>
        <Button tone="burgundy" onClick={findPath} disabled={!pathFrom || !pathTo}><ArrowRight size={13} /> Trace</Button>
      </div>
      {path && <div className="mt-3 rounded-xl border border-[#e6d9c9] bg-[#fbf7f0] p-3">{path.found ? <><p className="text-[10px] font-bold text-[#2e2520]">{path.nodes.map((node) => node.label).join("  →  ")}</p><div className="mt-2 flex flex-wrap gap-1.5"><Pill tone="blue">{path.edges.length} steps</Pill><Pill tone={path.weakest_link_confidence >= 0.8 ? "green" : "amber"}>Weakest link {path.weakest_link_confidence?.toFixed(2)}</Pill></div><p className="mt-2 text-[8px] leading-4 text-[#94867a]">{path.caveat}</p></> : <p className="text-[9px] leading-5 text-[#8a5f1c]">{path.reason}</p>}</div>}
    </Card>

    <div><div className="mb-2 flex flex-wrap items-center justify-between gap-2"><Eyebrow>Relationship observations / one row is one source statement</Eyebrow>
      <div className="flex flex-wrap gap-1.5"><Chip active={!typeFilter} onClick={() => setTypeFilter("")}>All</Chip>{relationTypes.map((type) => <Chip key={type} active={typeFilter === type} onClick={() => setTypeFilter(type)}>{readable(type)}</Chip>)}</div>
    </div>
      {relations.length === 0 ? <Blank title="No relationship observations" detail="Nothing in the processed evidence states a relationship of this kind." /> : <Card className="overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[880px] text-left text-[9px] text-[#4f4238]">
        <thead className="bg-[#f6efe6] text-[8px] font-bold uppercase tracking-[.12em] text-[#8a7d71]"><tr><th className="px-4 py-3">Relationship</th><th className="py-3">Type</th><th className="py-3">Read from</th><th className="py-3">Source location</th><th className="py-3">Confidence</th><th className="py-3">Verification</th><th className="py-3" /></tr></thead>
        <tbody className="divide-y divide-[#eadfd3]">{relations.map((relation) => <tr key={relation.id} className="hover:bg-[#fdf8f1]">
          <td className="px-4 py-3"><b className="text-[#2e2520]">{relation.subject.label}</b> <span style={{ color: relationTone(relation.relation_type) }}>{relation.directed ? "→" : "—"}</span> <b className="text-[#2e2520]">{relation.object.label}</b></td>
          <td className="py-3"><span className="inline-flex items-center gap-1.5"><i className="h-1.5 w-1.5 rounded-full" style={{ background: relationTone(relation.relation_type) }} />{readable(relation.relation_type)}</span></td>
          <td className="py-3">{readable(relation.basis)}</td>
          <td className="mono py-3 text-[8px] text-[#8a7d71]">{sourceLocation(relation.source_reference)}</td>
          <td className="py-3">{relation.confidence.toFixed(2)}</td>
          <td className="py-3"><Pill tone={verificationTone(relation.verification_status)}>{readable(relation.verification_status)}</Pill></td>
          <td className="py-3 pr-4 text-right"><Button tone="quiet" onClick={() => setOpenRelation(relation)}>Details</Button><span className="ml-2 inline-block"><Button tone="quiet" onClick={() => openRelationSource(relation)}>Open in file</Button></span></td>
        </tr>)}</tbody>
      </table></div></Card>}
    </div>

    <Trace />
    <RelationDrawer relation={openRelation} caseId={caseId} onClose={() => setOpenRelation(null)} onReviewed={load} say={say} onOpenSource={openRelationSource} />
    <EvidenceSourceViewer request={sourceRequest} close={() => setSourceRequest(null)} />
    <EntityDrawer entity={openEntity} caseId={caseId} onClose={() => setOpenEntity(null)} say={say} />
  </div>;
}
