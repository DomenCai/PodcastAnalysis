import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

type Theme = "light" | "dark";

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() =>
    document.documentElement.dataset.theme === "dark" ? "dark" : "light",
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    try {
      localStorage.setItem("whisper-theme", theme);
    } catch {
      /* Theme still works in memory. */
    }
  }, [theme]);
  const Icon = theme === "dark" ? Sun : Moon;
  return (
    <button
      type="button"
      className="icon-button"
      aria-label={theme === "dark" ? "切换浅色主题" : "切换深色主题"}
      title={theme === "dark" ? "浅色主题" : "深色主题"}
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
    >
      <Icon size={17} />
    </button>
  );
}
