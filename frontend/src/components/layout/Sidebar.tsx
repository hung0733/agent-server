import { NavLink } from "react-router-dom";
import { useTranslation } from "react-i18next";

const navItems = [
  { key: "overview", path: "/" },
  { key: "usage", path: "/usage" },
  { key: "agents", path: "/agents" },
  { key: "tasks", path: "/tasks" },
  { key: "memory", path: "/memory" },
  { key: "settings", path: "/settings" },
];

export default function Sidebar() {
  const { i18n, t } = useTranslation();

  return (
    <aside className="sidebar">
      <section className="sidebar__brand panel">
        <span className="sidebar__eyebrow">{t("shell.brand")}</span>
        <h1 className="sidebar__title">{t("shell.product")}</h1>
        <div className="sidebar__meta">{t("shell.language")}</div>
        <div className="sidebar__language-switch">
          <button
            type="button"
            className={i18n.language === "zh-HK" ? "is-active" : ""}
            onClick={() => void i18n.changeLanguage("zh-HK")}
            aria-label={t("shell.switchToChinese")}
          >
            zh-HK
          </button>
          <button
            type="button"
            className={i18n.language === "en" ? "is-active" : ""}
            onClick={() => void i18n.changeLanguage("en")}
            aria-label={t("shell.switchToEnglish")}
          >
            en
          </button>
        </div>
      </section>
      <nav aria-label={t("shell.navigation")} className="sidebar__nav">
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === "/"}
            className={({ isActive }) => `sidebar__link${isActive ? " active" : ""}`}
          >
            <span className="sidebar__link-label">{t(`nav.${item.key}`)}</span>
            <span className="sidebar__link-description">{t(`nav.${item.key}Description`)}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
