import { Moon, Sun, type LucideIcon } from "lucide-react";
import { useTheme, type Theme } from "../lib/theme";

const options: Array<{ theme: Theme; label: string; icon: LucideIcon }> = [
  { theme: "light", label: "亮色主题", icon: Sun },
  { theme: "dark", label: "暗色主题", icon: Moon }
];

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <div className="theme-toggle" aria-label="主题切换">
      {options.map(({ theme: optionTheme, label, icon: Icon }) => (
        <button
          key={optionTheme}
          type="button"
          className="theme-toggle-button"
          data-active={theme === optionTheme ? "true" : undefined}
          aria-label={label}
          aria-pressed={theme === optionTheme}
          title={label}
          onClick={() => setTheme(optionTheme)}
        >
          <Icon className="h-4 w-4" />
        </button>
      ))}
    </div>
  );
}
