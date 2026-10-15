import { cn } from "@/lib/utils";

export function Button({ className, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button {...p} className={cn("rounded-lg bg-[var(--primary)] px-4 py-2 text-white font-semibold hover:opacity-90 disabled:opacity-60", className)} />;
}

export function Card({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div {...p} className={cn("rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4", className)} />;
}
