import type { NotesDocument, Transcript } from "../api/client";
import SafeMarkdown from "./SafeMarkdown";
import Sources from "./Sources";

export default function NotesViewer({ notes, transcript, onSeek }: {
  notes: NotesDocument; transcript?: Transcript | null; onSeek?: (ms: number) => void;
}) {
  return <div className="notes-view">
    <section className="objectives"><h3>这节课，你将理解</h3><ul>{notes.learning_objectives.map((item, i) => <li key={i}>{item}</li>)}</ul></section>
    {notes.chapters.map((chapter, i) => <article className="note-chapter" key={chapter.id}>
      <div className="chapter-number">CHAPTER {`${i + 1}`.padStart(2, "0")}</div><h3>{chapter.title}</h3>
      <SafeMarkdown content={chapter.content_markdown} />
      <Sources ids={chapter.source_segment_ids} transcript={transcript} onSeek={onSeek} />
    </article>)}
    <section className="course-summary"><h3>回顾与总结</h3><SafeMarkdown content={notes.summary} />
      <div className="concepts">{notes.key_concepts.map((concept, i) => <span key={i}>{concept}</span>)}</div>
    </section>
  </div>;
}
