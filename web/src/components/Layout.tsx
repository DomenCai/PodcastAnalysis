import type { ReactNode } from "react";
import {
  BookOpen,
  CheckCircle2,
  CircleAlert,
  CircleDot,
  Folder,
  KeyRound,
  Loader2,
  Plus,
  Podcast,
  PlusSquare,
  Terminal
} from "lucide-react";
import type { Health } from "../lib/types";
import { navigate } from "../lib/routing";
import { ThemeToggle } from "./ThemeToggle";

type Props = {
  children: ReactNode;
  health: Health | null;
  healthLoading: boolean;
  healthError: string | null;
};

function NavLink({
  href,
  icon,
  children
}: {
  href: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  const active = window.location.pathname === href;

  return (
    <a
      href={href}
      className={active ? "sidebar-nav-link is-active" : "sidebar-nav-link"}
      onClick={(event) => {
        event.preventDefault();
        navigate(href);
      }}
    >
      {icon}
      {children}
    </a>
  );
}

function MobileNavLink({ href, children }: { href: string; children: ReactNode }) {
  const active = window.location.pathname === href;

  return (
    <a
      href={href}
      className={active ? "mobile-nav-link is-active" : "mobile-nav-link"}
      onClick={(event) => {
        event.preventDefault();
        navigate(href);
      }}
    >
      {children}
    </a>
  );
}

function HealthLine({
  icon,
  label,
  ok,
  loading
}: {
  icon: ReactNode;
  label: string;
  ok?: boolean;
  loading?: boolean;
}) {
  const Icon = loading ? Loader2 : ok ? CheckCircle2 : CircleAlert;

  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <div className="sidebar-health-line">
        <span className="sidebar-health-icon">{icon}</span>
        <span className="truncate">{label}</span>
      </div>
      <Icon
        className={
          loading
            ? "h-4 w-4 shrink-0 animate-spin icon-muted"
            : ok
              ? "h-4 w-4 shrink-0 icon-success"
              : "h-4 w-4 shrink-0 text-[var(--color-warn-text)]"
        }
      />
    </div>
  );
}

function SidebarHealth({
  health,
  loading,
  error
}: {
  health: Health | null;
  loading: boolean;
  error: string | null;
}) {
  const ready = !!health && Object.values(health).every(Boolean);

  return (
    <div className="sidebar-health">
      <div className="sidebar-health-title">
        <CircleDot className={ready ? "h-3 w-3 fill-[var(--color-success-strong)] icon-success" : "h-3 w-3 fill-[var(--color-warn-text)] text-[var(--color-warn-text)]"} />
        {loading ? "环境检查中" : error || !health ? "环境状态不可用" : ready ? "环境就绪" : "环境缺项"}
      </div>
      <div className="space-y-2">
        <HealthLine icon={<Folder className="h-4 w-4" />} label="输出目录 output/" ok={health?.output_writable} loading={loading} />
        <HealthLine icon={<Terminal className="h-4 w-4" />} label="ffmpeg / ffprobe" ok={!!health?.ffmpeg && !!health?.ffprobe} loading={loading} />
        <HealthLine icon={<KeyRound className="h-4 w-4" />} label="MIMO API key" ok={health?.mimo_key} loading={loading} />
        <HealthLine icon={<KeyRound className="h-4 w-4" />} label="LLM API key" ok={health?.llm_key} loading={loading} />
      </div>
    </div>
  );
}

export function Layout({ children, health, healthLoading, healthError }: Props) {
  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <button className="flex items-center gap-3 text-left" onClick={() => navigate("/")}>
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl" style={{ background: "var(--color-primary)", color: "var(--color-on-primary)" }}>
            <Podcast className="h-5 w-5" />
          </span>
          <span className="min-w-0">
            <span className="block truncate text-lg font-semibold leading-tight">PodcastAnalysis</span>
            <span className="sidebar-subtitle block">播客分析助手</span>
          </span>
        </button>

        <button className="primary-button mt-7 w-full" onClick={() => navigate("/new")}>
          <Plus className="h-4 w-4" />
          开始新分析
        </button>

        <nav className="mt-6 space-y-1">
          <NavLink href="/" icon={<BookOpen className="h-5 w-5" />}>
            节目库
          </NavLink>
          <NavLink href="/new" icon={<PlusSquare className="h-5 w-5" />}>
            新建处理
          </NavLink>
        </nav>

        <div className="sidebar-bottom">
          <ThemeToggle />
          <SidebarHealth health={health} loading={healthLoading} error={healthError} />
        </div>
      </aside>

      <div className="lg:pl-64">
        <header className="mobile-header">
          <div className="flex flex-col gap-3 px-4 py-4">
            <div className="flex items-start justify-between gap-3">
              <button className="flex min-w-0 items-center gap-2 text-left" onClick={() => navigate("/")}>
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg" style={{ background: "var(--color-primary)", color: "var(--color-on-primary)" }}>
                  <Podcast className="h-5 w-5" />
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-base font-semibold text-[var(--color-text)]">PodcastAnalysis</span>
                  <span className="block text-xs text-muted">播客分析助手</span>
                </span>
              </button>
              <ThemeToggle />
            </div>
            <nav className="flex flex-wrap items-center gap-1">
              <MobileNavLink href="/">节目库</MobileNavLink>
              <MobileNavLink href="/new">新建处理</MobileNavLink>
            </nav>
          </div>
        </header>

        <main className="mx-auto max-w-[1180px] px-4 py-7 sm:px-6 lg:px-10 lg:py-12">
          {children}
        </main>
      </div>
    </div>
  );
}
