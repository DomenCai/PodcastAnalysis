import {
  Activity,
  BookOpenText,
  BriefcaseBusiness,
  Plus,
  Podcast,
  Rss,
} from "lucide-react";
import type { ReactNode } from "react";
import type { Health } from "../lib/types";
import { navigate } from "../lib/routing";
import { ThemeToggle } from "./ThemeToggle";

function AppLink({
  href,
  icon,
  children,
}: {
  href: string;
  icon?: ReactNode;
  children: ReactNode;
}) {
  const active =
    href === "/"
      ? location.pathname === "/"
      : location.pathname.startsWith(href);
  return (
    <a
      href={href}
      className={`nav-link${active ? " active" : ""}`}
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

export function Layout({
  health,
  children,
}: {
  health: Health;
  children: ReactNode;
}) {
  const readOnly = health.read_only;
  if (readOnly) return <div className="public-shell"><main className="main">{children}</main></div>;
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          href="/"
          className="brand"
          onClick={(event) => {
            event.preventDefault();
            navigate("/");
          }}
        >
          <span className="brand-mark">
            <Podcast size={21} />
          </span>
          <span>
            <b>Podcast</b>
            <small>{readOnly ? "播客阅读" : "播客工作台"}</small>
          </span>
        </a>
        {!readOnly && (
          <button className="primary full" onClick={() => navigate("/new")}>
            <Plus size={17} />
            新建任务
          </button>
        )}
        <nav>
          <AppLink href="/" icon={<BookOpenText size={18} />}>
            {readOnly ? "播客列表" : "概览"}
          </AppLink>
          {!readOnly && (
            <AppLink href="/jobs" icon={<BriefcaseBusiness size={18} />}>
              任务
            </AppLink>
          )}
          {!readOnly && (
            <AppLink href="/subscriptions" icon={<Rss size={18} />}>
              订阅
            </AppLink>
          )}
        </nav>
        <div className="sidebar-foot">
          {!readOnly && (
            <div className="health-card">
              <span>
                <Activity size={16} />
                系统状态
              </span>
              <small>
                <i className={health.ok ? "ok-dot" : "bad-dot"} />
                {health.ok ? "服务正常" : "服务异常"}
              </small>
              <small>
                单任务 Worker · {health.ffmpeg ? "ffmpeg 就绪" : "缺少 ffmpeg"}
              </small>
              <small>
                {health.analysis?.backend === "pi" ? "Pi · K3 · high" : "Agy · Gemini"}
                {health.analysis?.available ? " 已就绪" : " 不可用"}
              </small>
            </div>
          )}
          <ThemeToggle />
        </div>
      </aside>
      <header className="mobile-header">
        <a
          href="/"
          className="brand"
          onClick={(event) => {
            event.preventDefault();
            navigate("/");
          }}
        >
          <span className="brand-mark">
            <Podcast size={19} />
          </span>
          <b>Podcast</b>
        </a>
        <nav>
          <AppLink href="/" icon={<BookOpenText size={17} />}>
            阅读
          </AppLink>
          {!readOnly && (
            <AppLink href="/jobs" icon={<BriefcaseBusiness size={17} />}>
              任务
            </AppLink>
          )}
          {!readOnly && (
            <AppLink href="/subscriptions" icon={<Rss size={17} />}>
              订阅
            </AppLink>
          )}
        </nav>
        <ThemeToggle />
      </header>
      <main className="main">{children}</main>
    </div>
  );
}
