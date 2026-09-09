/**
 * DRISHYAM visual reminder: the one claim this product makes, made visible.
 *
 * Every other platform in this space says "traceable" and shows a citation. This shows the box
 * closing around the pixels a value was read from, then the cell, then the line — three shapes of
 * evidence, one gesture, on a loop. A reader should understand what "opens at its source" means
 * before they have finished reading the heading beside it.
 *
 * The three frames are the real ones from the benchmark case: block-2 of a chat screenshot, row 2
 * column a_party of a call record, page 1 line 6 of an FIR. Nothing here is illustrative filler —
 * a landing page that invented a prettier example would be doing the thing this product refuses to
 * do.
 */
import { useEffect, useRef, useState } from "react";
import { ArrowRight, Crosshair } from "lucide-react";

type Frame = {
  kind: string;
  file: string;
  place: string;
  claim: string;
  /** Where the mark sits, as a percentage of the frame, so it scales with the card. */
  mark: { left: string; top: string; width: string; height: string };
  body: React.ReactNode;
};

const SCREENSHOT_LINES = [
  { text: "+919876543210", strong: true },
  { text: "12/07/2026  20:40" },
  { text: "Suresh here. Reporting for the" },
  { text: "Andheri East work." },
  { text: "12/07/2026  20:52" },
  { text: "Send the fee before you travel." },
];

const CDR_ROWS = [
  ["a_party", "b_party", "date", "time"],
  ["+919876543210", "+919988776655", "12/07/2026", "19:47"],
  ["+919876543210", "+919988776655", "12/07/2026", "20:14"],
  ["+919876543210", "+919123456789", "12/07/2026", "20:51"],
];

const FIR_LINES = [
  "FIRST INFORMATION REPORT",
  "FIR No: 0142/2026    PS: Bandra",
  "District: Mumbai Suburban",
  "",
  "Complainant: Protected person A",
  "Accused (1): Suresh Yadav, +919876543210",
  "Accused (2): Ravi Kumar, +919988776655",
];

function ScreenshotFrame() {
  return (
    <div className="h-full w-full bg-[#12140f] p-4 font-mono text-[10px] leading-[1.9] text-[#d8d4c8]">
      <p className="mb-3 text-[8px] tracking-[.14em] text-[#7a776d]">SYNTHETIC BENCHMARK MATERIAL</p>
      {SCREENSHOT_LINES.map((line, index) => (
        <p key={index} className={line.strong ? "text-[13px] font-bold text-[#f4efe2]" : ""}>
          {line.text}
        </p>
      ))}
    </div>
  );
}

function CdrFrame() {
  return (
    <div className="h-full w-full overflow-hidden bg-[#fffdf8] p-4">
      <table className="w-full border-collapse font-mono text-[9px]">
        <tbody>
          {CDR_ROWS.map((row, index) => (
            <tr key={index} className={index === 0 ? "text-[8px] font-bold uppercase tracking-[.1em] text-[#8f493f]" : "text-[#4b3f38]"}>
              <td className="w-6 pr-2 text-right text-[#bcae9f]">{index === 0 ? "#" : index + 1}</td>
              {row.map((cell) => (
                <td key={cell} className="py-[5px] pr-3">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FirFrame() {
  return (
    <div className="h-full w-full bg-white p-5 font-mono text-[9px] leading-[2.1] text-[#3a332c]">
      {FIR_LINES.map((line, index) => (
        <p key={index} className={index === 0 ? "font-bold tracking-[.06em]" : ""}>
          {line || " "}
        </p>
      ))}
    </div>
  );
}

const FRAMES: Frame[] = [
  {
    kind: "Image region",
    file: "screenshot_plain.png",
    place: "region block-2",
    claim: "This number was read from these pixels.",
    mark: { left: "5%", top: "20%", width: "44%", height: "12%" },
    body: <ScreenshotFrame />,
  },
  {
    kind: "Table cell",
    file: "cdr_synthetic.csv",
    place: 'row 2, column "a_party"',
    claim: "This call record names who dialled.",
    mark: { left: "8%", top: "35%", width: "34%", height: "13%" },
    body: <CdrFrame />,
  },
  {
    kind: "Line of text",
    file: "fir_primary.pdf",
    place: "page 1, line 6",
    claim: "This report attaches the number to a stated role.",
    mark: { left: "5%", top: "63%", width: "80%", height: "11%" },
    body: <FirFrame />,
  },
];

export default function SourceProof() {
  const [index, setIndex] = useState(0);
  const [live, setLive] = useState(false);
  const shell = useRef<HTMLDivElement | null>(null);

  // The loop only runs while the section is on screen. An animation nobody is looking at is a
  // battery cost with no reader.
  useEffect(() => {
    const node = shell.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => entries.forEach((entry) => setLive(entry.isIntersecting)),
      { threshold: 0.3 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!live) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = window.setInterval(() => setIndex((value) => (value + 1) % FRAMES.length), 3600);
    return () => window.clearInterval(timer);
  }, [live]);

  const frame = FRAMES[index];

  return (
    <section id="source" ref={shell} className="relative mx-auto max-w-[1360px] px-6 py-24 lg:px-10 lg:py-32">
      <div className="grid items-center gap-14 lg:grid-cols-[.85fr_1.15fr]">
        <div>
          <div className="inline-flex items-center gap-3 text-[10px] font-extrabold uppercase tracking-[0.16em] text-[#7f1d1d]">
            <span className="h-px w-9 bg-[#7f1d1d]" />
            <span>Traceability, shown</span>
          </div>
          <h2 className="display-serif mt-6 text-5xl leading-[1] tracking-[-.035em]">
            Every claim opens at the place it was read.
          </h2>
          <p className="mt-6 max-w-md text-sm leading-7 text-[#605a52]">
            Not a footnote. Not a filename. The exact region of the screenshot, the exact cell of the call record, the
            exact line of the FIR — reachable in one click from anywhere the claim appears.
          </p>

          <dl className="mt-8 space-y-3">
            {FRAMES.map((item, position) => (
              <button
                key={item.file}
                onClick={() => setIndex(position)}
                className={`flex w-full items-start gap-3 rounded-lg border px-4 py-3 text-left transition ${
                  position === index
                    ? "border-[#b36b62] bg-[#fff4f1]"
                    : "border-[#e6ddd2] bg-[#fffdf9] hover:border-[#d8cbbb]"
                }`}
              >
                <span
                  className={`mt-0.5 h-2.5 w-2.5 shrink-0 rounded-full ${position === index ? "bg-[#e0483c]" : "bg-[#ded2c4]"}`}
                />
                <span className="min-w-0">
                  <dt className="text-[11px] font-extrabold text-[#2e2520]">{item.kind}</dt>
                  <dd className="mono mt-0.5 truncate text-[9px] text-[#847468]">
                    {item.file} — {item.place}
                  </dd>
                </span>
              </button>
            ))}
          </dl>

          <p className="mt-7 flex items-center gap-2 text-[10px] font-bold uppercase tracking-[.12em] text-[#777067]">
            <Crosshair size={14} className="text-[#7f1d1d]" />
            Located, never approximated
          </p>
        </div>

        <div data-reveal className="paper-shadow relative overflow-hidden rounded-[24px] border border-[#e2d5c7] bg-[#f4efe6] p-5 sm:p-7">
          <div className="flex items-center justify-between border-b border-[#e6ddd2] pb-4">
            <div className="min-w-0">
              <p className="text-[9px] font-extrabold uppercase tracking-[.14em] text-[#8f3f37]">Source · {frame.kind}</p>
              <p className="mono mt-1 truncate text-[10px] text-[#6b5b51]">{frame.file}</p>
            </div>
            <span className="shrink-0 rounded-full border border-[#c9dfcf] bg-[#f2faf3] px-2.5 py-1 text-[9px] font-bold text-[#34734b]">
              Read here · {frame.place}
            </span>
          </div>

          <div className="source-stage relative mt-5 h-[290px] overflow-hidden rounded-xl border border-[#ded2c4] bg-white">
            {frame.body}
            <span key={`${index}-mark`} className="source-mark" style={frame.mark} aria-hidden="true" />
          </div>

          <p key={`${index}-claim`} className="source-claim mt-5 text-[12px] font-bold leading-6 text-[#2e2520]">
            {frame.claim}
          </p>
          <p className="mt-2 text-[9px] leading-5 text-[#847468]">
            The mark is where the value was read from. It is not a finding about what the evidence means.
          </p>

          <a
            href="#network"
            className="mt-6 inline-flex items-center gap-2 border-b border-[#b34b44] pb-1.5 text-[11px] font-extrabold text-[#7f1d1d]"
          >
            See what these sources build <ArrowRight size={15} />
          </a>
        </div>
      </div>
    </section>
  );
}
