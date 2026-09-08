/**
 * The panel that shows a claim where it lives in the file it came from.
 *
 * Everywhere else in this product a statement carries a source reference that can be printed. Here
 * it can be opened: the original screenshot with a box drawn round the pixels the value was read
 * from, the row and column of the call record, the line of the surveillance note, the page and line
 * of the FIR. Four shapes of evidence, one panel, one gesture.
 *
 * The server decides where the highlight goes. This draws what it is given and nothing else -- when
 * the place cannot be found the panel says so plainly and marks nothing, because a box in the wrong
 * place tells a reviewer they have verified something they have not.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Download, FileWarning, Loader2, Minus, Plus, X } from "lucide-react";
import { getOriginalObjectUrl, getSourceView, type SourceTarget, type SourceViewRecord } from "@/api/sourceView";

export type SourceRequest = {
  caseId: string;
  evidenceId: string;
  target: SourceTarget;
  /** What the reader clicked, shown at the top so they know what they are looking for. */
  title: string;
  subtitle?: string;
};

const KIND_LABEL: Record<string, string> = { image: "Image region", table: "Table cell", text: "Line of text" };

function Chip({ tone, children }: { tone: "found" | "unfound"; children: React.ReactNode }) {
  const style = tone === "found"
    ? "border-[#c9dfcf] bg-[#f2faf3] text-[#34734b]"
    : "border-[#ead9b8] bg-[#fff8e8] text-[#97651e]";
  return <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[9px] font-bold ${style}`}>{children}</span>;
}

/** The original image with the located regions drawn over it, in the image's own coordinates. */
function ImageSource({ view, url }: { view: SourceViewRecord; url: string | null }) {
  const [zoom, setZoom] = useState(1);
  const [showAll, setShowAll] = useState(false);
  const marked = view.regions.filter((region) => region.highlight);
  const drawn = showAll ? view.regions : marked;
  const frame = useRef<HTMLDivElement | null>(null);

  // Scroll the first highlight into view, because a screenshot is usually taller than the panel.
  useEffect(() => {
    if (!marked.length || !frame.current || !view.height) return;
    const top = (marked[0].bbox[1] / view.height) * frame.current.scrollHeight;
    frame.current.scrollTo({ top: Math.max(0, top - 120), behavior: "smooth" });
  }, [view.evidence_id, url, zoom]);

  if (!url) return <p className="p-5 text-[11px] text-[#76695e]">Loading the original image…</p>;

  return <div className="flex min-h-0 flex-1 flex-col">
    <div className="flex items-center justify-between border-b border-[#eadfd3] bg-[#fffaf3] px-4 py-2">
      <span className="text-[9px] font-bold uppercase tracking-[.12em] text-[#8f493f]">{view.width}×{view.height} px · {view.regions.length} text regions</span>
      <span className="flex items-center gap-2">
        <label className="flex items-center gap-1.5 text-[9px] font-bold text-[#6b5b51]">
          <input type="checkbox" checked={showAll} onChange={(event) => setShowAll(event.target.checked)} className="accent-[#7f1d1d]"/>
          Show every region
        </label>
        <button onClick={() => setZoom((value) => Math.max(0.5, value - 0.25))} aria-label="Zoom out" className="grid h-6 w-6 place-items-center rounded border border-[#dbcbbd] bg-white text-[#6b5b51]"><Minus size={12}/></button>
        <span className="mono w-9 text-center text-[9px] font-bold text-[#6b5b51]">{Math.round(zoom * 100)}%</span>
        <button onClick={() => setZoom((value) => Math.min(3, value + 0.25))} aria-label="Zoom in" className="grid h-6 w-6 place-items-center rounded border border-[#dbcbbd] bg-white text-[#6b5b51]"><Plus size={12}/></button>
      </span>
    </div>

    <div ref={frame} className="min-h-0 flex-1 overflow-auto bg-[#2a2320] p-4">
      <div className="relative mx-auto" style={{ width: `${(view.width ?? 0) * zoom}px` }}>
        <img src={url} alt={`Original evidence: ${view.original_name}`} className="block w-full select-none" draggable={false}/>
        {view.width && view.height && drawn.map((region) => {
          const [x0, y0, x1, y1] = region.bbox;
          const style = {
            left: `${(x0 / view.width!) * 100}%`,
            top: `${(y0 / view.height!) * 100}%`,
            width: `${((x1 - x0) / view.width!) * 100}%`,
            height: `${((y1 - y0) / view.height!) * 100}%`,
          };
          return <span
            key={region.id}
            title={region.text}
            style={style}
            className={region.highlight
              ? "pointer-events-none absolute rounded-[3px] border-2 border-[#e0483c] bg-[#e0483c]/15 shadow-[0_0_0_9999px_rgba(20,14,11,.45)]"
              : "pointer-events-none absolute rounded-[2px] border border-[#f0c755]/60"}
          />;
        })}
      </div>
    </div>
  </div>;
}

function TableSource({ view }: { view: SourceViewRecord }) {
  const marked = useRef<HTMLTableRowElement | null>(null);
  useEffect(() => { marked.current?.scrollIntoView({ block: "center", behavior: "smooth" }); }, [view.evidence_id]);

  return <div className="min-h-0 flex-1 overflow-auto">
    <table className="w-full min-w-max text-left">
      <thead className="sticky top-0 z-10 border-b border-[#eadfd3] bg-[#fff8f0]">
        <tr className="text-[9px] font-extrabold uppercase tracking-[.1em] text-[#8f493f]">
          <th className="px-3 py-3 text-right">#</th>
          {view.header.map((name) => <th key={name} className="px-3 py-3">{name}</th>)}
        </tr>
      </thead>
      <tbody>
        {view.rows.map((row) => <tr
          key={row.number}
          ref={row.highlight ? marked : undefined}
          className={row.highlight ? "border-b border-[#e7c3bd] bg-[#fff1ee]" : "border-b border-[#f0e6da]"}
        >
          <td className={`mono px-3 py-2.5 text-right text-[9px] ${row.highlight ? "font-extrabold text-[#8f302b]" : "text-[#a2958a]"}`}>{row.number}</td>
          {view.header.map((name) => {
            const cited = row.highlight && row.highlight_columns.includes(name);
            return <td key={name} className={`px-3 py-2.5 text-[10px] ${cited ? "rounded bg-[#e0483c]/20 font-extrabold text-[#7f1d1d] ring-1 ring-[#e0483c]" : "text-[#4b3f38]"}`}>{row.cells[name] ?? ""}</td>;
          })}
        </tr>)}
      </tbody>
    </table>
    {view.truncated && <p className="border-t border-[#eadfd3] px-4 py-3 text-[9px] text-[#97651e]">This table is longer than the panel shows. Download the original to see all of it.</p>}
  </div>;
}

function TextSource({ view }: { view: SourceViewRecord }) {
  const marked = useRef<HTMLDivElement | null>(null);
  useEffect(() => { marked.current?.scrollIntoView({ block: "center", behavior: "smooth" }); }, [view.evidence_id]);

  return <div className="min-h-0 flex-1 overflow-auto bg-[#fffdf8] px-4 py-4">
    {view.lines.map((line) => <div
      key={`${line.page ?? 0}-${line.number}`}
      ref={line.highlight ? marked : undefined}
      className={`flex gap-3 rounded px-2 py-1 ${line.highlight ? "bg-[#e0483c]/15 ring-1 ring-[#e0483c]" : ""}`}
    >
      <span className={`mono w-12 shrink-0 select-none text-right text-[9px] ${line.highlight ? "font-extrabold text-[#8f302b]" : "text-[#bcae9f]"}`}>
        {line.page ? `${line.page}:${line.number}` : line.number}
      </span>
      <span className={`mono whitespace-pre-wrap text-[10px] leading-5 ${line.highlight ? "font-bold text-[#3a2b25]" : "text-[#5b4d45]"}`}>{line.text || " "}</span>
    </div>)}
    {view.truncated && <p className="mt-3 text-[9px] text-[#97651e]">This file is longer than the panel shows. Download the original to read all of it.</p>}
  </div>;
}

export default function EvidenceSourceViewer({ request, close }: { request: SourceRequest | null; close: () => void }) {
  const [view, setView] = useState<SourceViewRecord | null>(null);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const key = useMemo(
    () => (request ? `${request.evidenceId}|${JSON.stringify(request.target)}` : null),
    [request],
  );

  useEffect(() => {
    if (!request) { setView(null); setError(null); return; }
    let live = true;
    setLoading(true);
    setError(null);
    setView(null);
    getSourceView(request.caseId, request.evidenceId, request.target)
      .then((record) => { if (live) setView(record); })
      .catch(() => { if (live) setError("This source could not be opened. You may not have access to it, or it may no longer be stored."); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [key]);

  // The original bytes are only needed to look at a picture; a table and a text file are already
  // rendered from what the server returned.
  useEffect(() => {
    if (!request || view?.kind !== "image") return;
    let live = true;
    let created: string | null = null;
    getOriginalObjectUrl(request.caseId, request.evidenceId).then((url) => {
      created = url;
      if (live) setObjectUrl(url); else URL.revokeObjectURL(url);
    }).catch(() => undefined);
    return () => { live = false; if (created) URL.revokeObjectURL(created); setObjectUrl(null); };
  }, [view?.kind, request?.evidenceId]);

  useEffect(() => {
    const onEscape = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
    if (request) window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, [request, close]);

  const download = async () => {
    if (!request) return;
    const url = objectUrl ?? (await getOriginalObjectUrl(request.caseId, request.evidenceId));
    const link = document.createElement("a");
    link.href = url;
    link.download = view?.original_name ?? "evidence";
    link.click();
  };

  if (!request) return null;

  return <>
    <button aria-label="Close source panel" onClick={close} className="fixed inset-0 z-[85] bg-[#241a15]/45 backdrop-blur-[2px]"/>
    <aside role="dialog" aria-modal="true" aria-label="Evidence source" className="fixed right-0 top-0 z-[86] flex h-full w-full max-w-[min(920px,94vw)] flex-col border-l border-[#e2d5c7] bg-[#fffdf8] shadow-[-24px_0_60px_rgba(63,36,25,.28)]">

      <header className="border-b border-[#eadfd3] bg-[#fffaf3] px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <span className="min-w-0">
            <p className="text-[9px] font-extrabold uppercase tracking-[.15em] text-[#8f3f37]">Source · every statement opens where it was read</p>
            <h2 className="mt-1 truncate font-serif text-lg font-bold text-[#2e2520]">{request.title}</h2>
            {request.subtitle && <p className="mt-0.5 truncate text-[10px] text-[#76695e]">{request.subtitle}</p>}
          </span>
          <span className="flex shrink-0 items-center gap-2">
            <button onClick={download} className="inline-flex items-center gap-1.5 rounded-lg border border-[#dfd0c0] bg-white px-3 py-2 text-[9px] font-bold text-[#6b5b51] transition hover:border-[#b36b62] hover:bg-[#fff7f1]"><Download size={13}/>Original</button>
            <button onClick={close} aria-label="Close" className="grid h-8 w-8 place-items-center rounded-lg border border-[#dfd0c0] bg-white text-[#6b5b51] transition hover:border-[#b36b62]"><X size={15}/></button>
          </span>
        </div>

        {view && <div className="mt-3 flex flex-wrap items-center gap-2">
          <Chip tone={view.located ? "found" : "unfound"}>
            {view.located ? `Found · ${view.highlight_summary}` : "Exact place not found"}
          </Chip>
          <span className="mono text-[9px] text-[#827267]">{view.original_name}</span>
          <span className="rounded-full border border-[#e4d6c6] bg-[#fff6ec] px-2 py-0.5 text-[9px] font-bold text-[#8a6a3a]">{KIND_LABEL[view.kind] ?? view.kind}</span>
        </div>}
      </header>

      {loading && <div className="grid flex-1 place-items-center"><span className="flex items-center gap-2 text-[11px] text-[#76695e]"><Loader2 className="animate-spin" size={15}/>Opening the source…</span></div>}

      {error && <div className="grid flex-1 place-items-center p-8 text-center">
        <span><FileWarning className="mx-auto text-[#a33831]" size={28}/><p className="mt-3 max-w-sm text-[11px] leading-5 text-[#76695e]">{error}</p></span>
      </div>}

      {view && !loading && <>
        {view.note && <p className="border-b border-[#eadfd3] bg-[#fff8e8] px-5 py-3 text-[10px] leading-5 text-[#8a6a3a]">{view.note}</p>}
        {view.kind === "image" && <ImageSource view={view} url={objectUrl}/>}
        {view.kind === "table" && <TableSource view={view}/>}
        {view.kind === "text" && <TextSource view={view}/>}
      </>}

      <footer className="border-t border-[#eadfd3] bg-[#fffaf3] px-5 py-2.5 text-[9px] leading-4 text-[#847468]">
        The marked place is where this value was read from. It is not a finding about what the evidence means.
      </footer>
    </aside>
  </>;
}
