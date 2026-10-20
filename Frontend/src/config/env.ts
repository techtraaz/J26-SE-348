export const env = {
  c1Base: import.meta.env.VITE_C1_BASE ?? "",
  c2Base: import.meta.env.VITE_C2_BASE ?? "",
  c3Base: import.meta.env.VITE_C3_BASE ?? "http://localhost:8003",
  c4Base: import.meta.env.VITE_C4_BASE ?? "http://localhost:8004",
} as const;
