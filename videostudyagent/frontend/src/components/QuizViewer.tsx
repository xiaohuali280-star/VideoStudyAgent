import type { QuizDocument, Transcript } from "../api/client";
import SafeMarkdown from "./SafeMarkdown";
import Sources from "./Sources";

export default function QuizViewer({ quiz, transcript, onSeek }: {
  quiz: QuizDocument; transcript?: Transcript | null; onSeek?: (ms: number) => void;
}) {
  return <div className="quiz-view"><p className="muted">先尝试回答，再展开参考答案。每道题都保留课程依据。</p>
    {quiz.questions.map((question, i) => <article className="quiz-card" key={question.id}>
      <span className="question-number">QUESTION {`${i + 1}`.padStart(2, "0")}</span>
      <h3>{question.question}</h3><Sources ids={question.source_segment_ids} transcript={transcript} onSeek={onSeek} />
      <details><summary>查看答案与解析</summary><div className="answer-content">
        <h4>参考答案</h4><SafeMarkdown content={question.answer} />
        <h4>解析</h4><SafeMarkdown content={question.explanation} />
        <h4>原文依据</h4>{question.evidence.map((evidence, n) => <blockquote key={n}>{evidence.quote}</blockquote>)}
      </div></details>
    </article>)}
  </div>;
}
