import type { Transcript } from "../api/client";

export function clock(ms: number) {
  const seconds = Math.floor(ms / 1000);
  const hours = Math.floor(seconds / 3600);
  const rest = `${Math.floor(seconds / 60) % 60}`.padStart(2, "0") + ":" + `${seconds % 60}`.padStart(2, "0");
  return hours ? `${hours}`.padStart(2, "0") + ":" + rest : rest;
}

export default function Sources({ ids, transcript, onSeek }: {
  ids: string[]; transcript?: Transcript | null; onSeek?: (ms: number) => void;
}) {
  return <div className="sources"><span>课程来源</span>{[...new Set(ids)].map(id => {
    const source = transcript?.segments.find(segment => segment.id === id);
    if (!source) return null;
    const label = `${clock(source.start_ms)}–${clock(source.end_ms)}`;
    return onSeek ? <button key={id} type="button" className="timecode" onClick={() => onSeek(source.start_ms)}
      aria-label={`跳转至 ${clock(source.start_ms)}`}>{label} ↗</button>
      : <span key={id} className="timecode">{label}</span>;
  })}</div>;
}
