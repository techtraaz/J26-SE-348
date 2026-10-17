import { useState, useRef, useCallback } from "react";

interface UploadedFile {
  name: string;
  size: string;
  date: string;
  id: string;
}

const formatFileSize = (bytes: number): string => {
  if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)} MB`;
  return `${(bytes / 1024).toFixed(0)} KB`;
};

const formatDate = (): string => {
  return new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
};

export function DocumentsPage() {
  const [files, setFiles] = useState<UploadedFile[]>([
    { id: "1", name: "Project_Requirements.pdf", size: "2.4 MB", date: "Apr 28, 2025" },
    { id: "2", name: "Research_Notes.docx", size: "856 KB", date: "Apr 25, 2025" },
    { id: "3", name: "Product_Roadmap.pdf", size: "1.8 MB", date: "Apr 22, 2025" },
  ]);
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback((fileList: FileList) => {
    const newFiles = Array.from(fileList).map((f) => ({
      id: crypto.randomUUID(),
      name: f.name,
      size: formatFileSize(f.size),
      date: formatDate(),
    }));
    setFiles((prev) => [...newFiles, ...prev]);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
  }, [handleFiles]);

  const removeFile = (id: string) => setFiles((prev) => prev.filter((f) => f.id !== id));

  return (
    <div style={{ maxWidth: "640px", margin: "0 auto", padding: "48px 24px 64px" }}>
      {/* Heading */}
      <h1 className="heading-serif" style={{ fontSize: "42px", textAlign: "center", marginBottom: "8px" }}>
        Your Library
      </h1>
      <p style={{ textAlign: "center", color: "var(--text-muted)", fontSize: "15px", marginBottom: "36px" }}>
        Upload documents to use in your conversations.
      </p>

      {/* Drop Zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        style={{
          border: `2px dashed ${isDragging ? "var(--text-muted)" : "var(--border)"}`,
          borderRadius: "var(--radius-lg)",
          padding: "40px 24px",
          textAlign: "center",
          marginBottom: "36px",
          background: isDragging ? "var(--accent-bg)" : "transparent",
          transition: "all 0.2s ease",
          cursor: "pointer",
        }}
        onClick={() => inputRef.current?.click()}
      >
        {/* Upload Icon */}
        <div style={{ marginBottom: "12px" }}>
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" style={{ margin: "0 auto" }}>
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
        </div>
        <p style={{ fontWeight: 500, color: "var(--text-h)", fontSize: "15px", marginBottom: "4px" }}>
          Drag and drop files here
        </p>
        <p style={{ color: "var(--text-soft)", fontSize: "13px", marginBottom: "16px" }}>
          or browse from your computer
        </p>
        <button
          onClick={(e) => { e.stopPropagation(); inputRef.current?.click(); }}
          style={{
            padding: "8px 24px",
            borderRadius: "var(--radius-pill)",
            border: "1px solid var(--border)",
            background: "var(--surface)",
            color: "var(--text-h)",
            fontSize: "13px",
            fontWeight: 500,
            cursor: "pointer",
            fontFamily: "inherit",
          }}
        >
          Choose files
        </button>
        <input ref={inputRef} type="file" multiple style={{ display: "none" }} onChange={(e) => { if (e.target.files) handleFiles(e.target.files); }} />
      </div>

      {/* Uploaded Files */}
      {files.length > 0 && (
        <div>
          <h3 style={{ fontWeight: 600, fontSize: "16px", color: "var(--text-h)", marginBottom: "16px" }}>
            Uploaded files
          </h3>
          <div style={{ display: "flex", flexDirection: "column" }}>
            {files.map((file) => (
              <div
                key={file.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "14px",
                  padding: "14px 0",
                  borderBottom: "1px solid var(--border-light)",
                }}
              >
                {/* File icon */}
                <div style={{ flexShrink: 0, color: "var(--text-muted)" }}>
                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                  </svg>
                </div>
                {/* File info */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 500, fontSize: "14px", color: "var(--text-h)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {file.name}
                  </div>
                  <div style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "2px" }}>
                    {file.size} · {file.date}
                  </div>
                </div>
                {/* Delete button */}
                <button
                  onClick={() => removeFile(file.id)}
                  style={{ flexShrink: 0, background: "none", border: "none", cursor: "pointer", color: "var(--text-soft)", padding: "4px" }}
                  title="Remove file"
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
