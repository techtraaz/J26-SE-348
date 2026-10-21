import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Chat text as Markdown (lists, bold, tables, code). Raw HTML is never rendered,
 *  and links open in a new tab. Styles: `.md` in globals.css. */
export function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer">{children}</a>,
          // Wide tables scroll inside the bubble instead of widening the chat.
          table: ({ children }) => <div className="md-table"><table>{children}</table></div>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
