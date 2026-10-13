// B4 adapted from BiliNote MarkdownViewer.tsx (MIT). Rendering pipeline only.
// Removed stores/chat/maps/images/code execution; added HTML/protocol restrictions.
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

const remarkPlugins = [remarkGfm, remarkMath];

export default function SafeMarkdown({ content }: { content: string }) {
  return <div className="markdown"><ReactMarkdown skipHtml remarkPlugins={remarkPlugins}
    rehypePlugins={[[rehypeKatex, { trust: false, strict: "ignore", maxExpand: 1000 }]]}
    components={{
      a: ({ href, children }) => href && /^(https?:\/\/|#)/i.test(href)
        ? <a href={href} target={href.startsWith("#") ? undefined : "_blank"} rel="noopener noreferrer">{children}</a>
        : <span>{children}</span>,
      img: ({ alt }) => <span>{alt || ""}</span>,
    }}>{content}</ReactMarkdown></div>;
}
