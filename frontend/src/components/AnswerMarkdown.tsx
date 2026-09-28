import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const CITATION_PREFIX = "#source-";

/** Turn "[1]" citations into links so they can be clicked to open the source. */
function linkCitations(text: string) {
  return text.replace(/\[(\d+)\](?!\()/g, `[\\[$1\\]](${CITATION_PREFIX}$1)`);
}

type Props = {
  content: string;
  streaming?: boolean;
  onCite: (sourceId: number) => void;
};

/** An assistant answer rendered as Markdown, with clickable [n] source citations. */
export default function AnswerMarkdown({ content, streaming, onCite }: Props) {
  return (
    <div className="prose prose-docsqa max-w-none text-[16px] leading-relaxed font-light prose-strong:font-bold prose-code:rounded-md prose-code:bg-ink prose-code:px-1.5 prose-code:py-0.5 prose-code:font-normal prose-code:before:content-none prose-code:after:content-none">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) =>
            href?.startsWith(CITATION_PREFIX) ? (
              <button
                type="button"
                onClick={() => onCite(Number(href.slice(CITATION_PREFIX.length)))}
                className="mx-0.5 rounded-full bg-lilac px-1.5 align-super text-[10px] font-bold text-ink transition-transform hover:scale-110"
              >
                {children}
              </button>
            ) : (
              <a href={href} target="_blank" rel="noreferrer">
                {children}
              </a>
            ),
        }}
      >
        {linkCitations(content)}
      </ReactMarkdown>
      {streaming && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-full bg-flame align-middle" />}
    </div>
  );
}
