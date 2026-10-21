import { Card } from "@/components/ui/basics";
import { useUI } from "@/store/ui";
export function SettingsPage() {
  const { theme, toggleTheme } = useUI();
  return <Card><h3 className="font-bold">Settings</h3><p className="text-sm">Theme: {theme}</p><button onClick={toggleTheme} className="mt-2 rounded-lg border px-3 py-1 text-sm">Toggle theme</button></Card>;
}
