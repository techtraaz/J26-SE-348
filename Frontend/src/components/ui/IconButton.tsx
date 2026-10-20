// A quiet icon button with a CSS tooltip (see .icon-btn in globals.css).
export function IconButton({ tip, shortcut, tipSide = "bottom", bordered, onClick, children, size = 32 }: {
  tip: string;
  shortcut?: string;
  tipSide?: "top" | "bottom" | "bottom-end" | "right";
  bordered?: boolean;
  onClick: () => void;
  children: React.ReactNode;
  size?: number;
}) {
  return (
    <button
      type="button"
      className="icon-btn"
      aria-label={tip}
      data-tip={shortcut ? `${tip}  ${shortcut}` : tip}
      data-tip-side={tipSide}
      onClick={onClick}
      style={{
        width: `${size}px`, height: `${size}px`, flexShrink: 0, borderRadius: bordered ? "50%" : "8px",
        border: bordered ? "1px solid var(--border-strong)" : "none", background: "transparent",
        color: "var(--text-muted)", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
      }}
    >
      {children}
    </button>
  );
}
