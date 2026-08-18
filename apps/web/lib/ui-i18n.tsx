"use client";

import { createContext, useContext, useEffect, type ReactNode } from "react";

import { useLocalStorageState } from "@/lib/use-persisted-state";
import {
  isUiLanguageCode,
  UI_LANGUAGE_OPTIONS,
  type UiLanguageCode,
} from "@/lib/language-options";

type TranslationKey =
  | "navigation.insights"
  | "navigation.creation"
  | "navigation.automation"
  | "navigation.operations"
  | "navigation.dashboard"
  | "navigation.trends"
  | "navigation.videoSearch"
  | "navigation.accounts"
  | "navigation.contents"
  | "navigation.news"
  | "navigation.events"
  | "navigation.topics"
  | "navigation.generate"
  | "navigation.editorial"
  | "navigation.publications"
  | "navigation.rights"
  | "navigation.experiments"
  | "navigation.download"
  | "navigation.rules"
  | "navigation.automations"
  | "navigation.notificationTemplates"
  | "navigation.notificationChannels"
  | "navigation.tasks"
  | "navigation.externalCalls"
  | "navigation.deadLetters"
  | "navigation.slo"
  | "navigation.logs"
  | "navigation.settings"
  | "shell.productSubtitle"
  | "shell.mainNavigation"
  | "shell.openNavigation"
  | "shell.closeNavigation"
  | "shell.expandNavigation"
  | "shell.collapseNavigation"
  | "shell.search"
  | "shell.searchMinChars"
  | "shell.searching"
  | "shell.searchFailed"
  | "shell.searchEmpty"
  | "shell.pageFeature"
  | "shell.syncStatus"
  | "shell.syncTitle"
  | "shell.syncEmpty"
  | "shell.inboxTitle"
  | "shell.inboxSubtitle"
  | "shell.markAllRead"
  | "shell.closeInbox"
  | "shell.inboxEmpty"
  | "shell.inboxMore"
  | "shell.userMenu"
  | "shell.workspaceSettings"
  | "shell.logout"
  | "shell.shortcutsTitle"
  | "shell.close"
  | "shell.language"
  | "shell.languageSavedLocally"
  | "shell.statusChecking"
  | "shell.statusHealthy"
  | "shell.statusBusy"
  | "shell.statusDegraded"
  | "shell.statusUnreachable";

type TranslationTable = Partial<Record<TranslationKey, string>>;

const ZH: Record<TranslationKey, string> = {
  "navigation.insights": "洞察",
  "navigation.creation": "创作",
  "navigation.automation": "自动化",
  "navigation.operations": "运维",
  "navigation.dashboard": "仪表盘",
  "navigation.trends": "热点情报中心",
  "navigation.videoSearch": "视频内容搜索",
  "navigation.accounts": "账号监控",
  "navigation.contents": "作品数据",
  "navigation.news": "新闻热点",
  "navigation.events": "事件中心",
  "navigation.topics": "选题库",
  "navigation.generate": "内容创作",
  "navigation.editorial": "审核队列",
  "navigation.publications": "发布记录",
  "navigation.rights": "素材权利",
  "navigation.experiments": "观察性实验",
  "navigation.download": "视频下载",
  "navigation.rules": "规则中心",
  "navigation.automations": "自动化规则",
  "navigation.notificationTemplates": "通知模板",
  "navigation.notificationChannels": "通知渠道",
  "navigation.tasks": "任务记录",
  "navigation.externalCalls": "调用记录",
  "navigation.deadLetters": "死信管理",
  "navigation.slo": "可靠性 SLO",
  "navigation.logs": "系统日志",
  "navigation.settings": "设置",
  "shell.productSubtitle": "内容智能生产平台",
  "shell.mainNavigation": "主导航",
  "shell.openNavigation": "打开导航",
  "shell.closeNavigation": "关闭导航",
  "shell.expandNavigation": "展开导航",
  "shell.collapseNavigation": "收起导航",
  "shell.search": "搜索页面或功能…",
  "shell.searchMinChars": "至少输入 2 个字符",
  "shell.searching": "正在搜索…",
  "shell.searchFailed": "搜索失败，点击重试",
  "shell.searchEmpty": "未找到匹配结果",
  "shell.pageFeature": "页面功能",
  "shell.syncStatus": "同步状态",
  "shell.syncTitle": "同步状态",
  "shell.syncEmpty": "当前没有正在同步的账号",
  "shell.inboxTitle": "未读信息",
  "shell.inboxSubtitle": "同步、通知与后台任务的最近记录",
  "shell.markAllRead": "全部已读",
  "shell.closeInbox": "关闭未读信息",
  "shell.inboxEmpty": "暂无未读信息",
  "shell.inboxMore": "更多 · 查看信息历史",
  "shell.userMenu": "用户菜单",
  "shell.workspaceSettings": "个人与工作区设置",
  "shell.logout": "退出登录",
  "shell.shortcutsTitle": "键盘快捷键",
  "shell.close": "关闭",
  "shell.language": "界面语言",
  "shell.languageSavedLocally": "语言偏好会保存在当前浏览器",
  "shell.statusChecking": "检查中",
  "shell.statusHealthy": "正常",
  "shell.statusBusy": "同步中",
  "shell.statusDegraded": "降级",
  "shell.statusUnreachable": "不可达",
};

const TRANSLATIONS: Record<UiLanguageCode, TranslationTable> = {
  "zh-CN": ZH,
  "en-US": {
    ...ZH,
    "navigation.insights": "Insights",
    "navigation.creation": "Creation",
    "navigation.automation": "Automation",
    "navigation.operations": "Operations",
    "navigation.dashboard": "Dashboard",
    "navigation.trends": "Hot Intelligence",
    "navigation.videoSearch": "Video Search",
    "navigation.accounts": "Account Monitoring",
    "navigation.contents": "Content Data",
    "navigation.news": "News & Trends",
    "navigation.events": "Events",
    "navigation.topics": "Topic Library",
    "navigation.generate": "Content Creation",
    "navigation.editorial": "Editorial Queue",
    "navigation.publications": "Publications",
    "navigation.rights": "Media Rights",
    "navigation.experiments": "Observational Experiments",
    "navigation.download": "Video Download",
    "navigation.rules": "Rules Center",
    "navigation.automations": "Automation Rules",
    "navigation.notificationTemplates": "Notification Templates",
    "navigation.notificationChannels": "Notification Channels",
    "navigation.tasks": "Task Records",
    "navigation.externalCalls": "External Calls",
    "navigation.deadLetters": "Dead Letters",
    "navigation.slo": "Reliability SLO",
    "navigation.logs": "System Logs",
    "navigation.settings": "Settings",
    "shell.productSubtitle": "Content intelligence workspace",
    "shell.mainNavigation": "Main navigation",
    "shell.openNavigation": "Open navigation",
    "shell.closeNavigation": "Close navigation",
    "shell.expandNavigation": "Expand navigation",
    "shell.collapseNavigation": "Collapse navigation",
    "shell.search": "Search pages or features…",
    "shell.searchMinChars": "Enter at least 2 characters",
    "shell.searching": "Searching…",
    "shell.searchFailed": "Search failed. Click to retry",
    "shell.searchEmpty": "No matching results",
    "shell.pageFeature": "Page feature",
    "shell.syncStatus": "Sync status",
    "shell.syncTitle": "Sync status",
    "shell.syncEmpty": "No accounts are syncing",
    "shell.inboxTitle": "Unread updates",
    "shell.inboxSubtitle": "Recent syncs, notifications and background tasks",
    "shell.markAllRead": "Mark all as read",
    "shell.closeInbox": "Close unread updates",
    "shell.inboxEmpty": "No unread updates",
    "shell.inboxMore": "More · View history",
    "shell.userMenu": "User menu",
    "shell.workspaceSettings": "Personal and workspace settings",
    "shell.logout": "Sign out",
    "shell.shortcutsTitle": "Keyboard shortcuts",
    "shell.close": "Close",
    "shell.language": "Interface language",
    "shell.languageSavedLocally": "Your language preference is saved in this browser",
    "shell.statusChecking": "Checking",
    "shell.statusHealthy": "Healthy",
    "shell.statusBusy": "Syncing",
    "shell.statusDegraded": "Degraded",
    "shell.statusUnreachable": "Unreachable",
  },
  "ja-JP": {
    ...ZH,
    "navigation.insights": "インサイト",
    "navigation.creation": "制作",
    "navigation.automation": "自動化",
    "navigation.operations": "運用",
    "navigation.dashboard": "ダッシュボード",
    "navigation.trends": "ホットインテリジェンス",
    "navigation.videoSearch": "動画検索",
    "navigation.accounts": "アカウント監視",
    "navigation.contents": "コンテンツデータ",
    "navigation.news": "ニュース",
    "navigation.events": "イベント",
    "navigation.topics": "トピックライブラリ",
    "navigation.generate": "コンテンツ制作",
    "navigation.editorial": "審査キュー",
    "navigation.publications": "公開記録",
    "navigation.download": "動画ダウンロード",
    "navigation.settings": "設定",
    "shell.search": "ページや機能を検索…",
    "shell.inboxTitle": "未読情報",
    "shell.inboxEmpty": "未読情報はありません",
    "shell.logout": "ログアウト",
    "shell.language": "表示言語",
  },
  "ko-KR": {
    ...ZH,
    "navigation.insights": "인사이트",
    "navigation.creation": "제작",
    "navigation.automation": "자동화",
    "navigation.operations": "운영",
    "navigation.dashboard": "대시보드",
    "navigation.trends": "핫 인텔리전스",
    "navigation.videoSearch": "동영상 검색",
    "navigation.accounts": "계정 모니터링",
    "navigation.contents": "콘텐츠 데이터",
    "navigation.news": "뉴스",
    "navigation.events": "이벤트",
    "navigation.topics": "주제 라이브러리",
    "navigation.generate": "콘텐츠 제작",
    "navigation.settings": "설정",
    "shell.search": "페이지 또는 기능 검색…",
    "shell.inboxTitle": "읽지 않은 정보",
    "shell.inboxEmpty": "읽지 않은 정보가 없습니다",
    "shell.logout": "로그아웃",
    "shell.language": "인터페이스 언어",
  },
  "es-ES": {
    ...ZH,
    "navigation.insights": "Análisis",
    "navigation.creation": "Creación",
    "navigation.automation": "Automatización",
    "navigation.operations": "Operaciones",
    "navigation.dashboard": "Panel",
    "navigation.trends": "Inteligencia de tendencias",
    "navigation.videoSearch": "Búsqueda de vídeos",
    "navigation.accounts": "Monitoreo de cuentas",
    "navigation.contents": "Datos de contenido",
    "navigation.news": "Noticias",
    "navigation.events": "Eventos",
    "navigation.topics": "Biblioteca de temas",
    "navigation.generate": "Creación de contenido",
    "navigation.settings": "Configuración",
    "shell.search": "Buscar páginas o funciones…",
    "shell.inboxTitle": "Actualizaciones no leídas",
    "shell.inboxEmpty": "No hay actualizaciones no leídas",
    "shell.logout": "Cerrar sesión",
    "shell.language": "Idioma de la interfaz",
  },
  "fr-FR": {
    ...ZH,
    "navigation.insights": "Analyses",
    "navigation.creation": "Création",
    "navigation.automation": "Automatisation",
    "navigation.operations": "Opérations",
    "navigation.dashboard": "Tableau de bord",
    "navigation.trends": "Intelligence des tendances",
    "navigation.videoSearch": "Recherche vidéo",
    "navigation.accounts": "Suivi des comptes",
    "navigation.contents": "Données de contenu",
    "navigation.news": "Actualités",
    "navigation.events": "Événements",
    "navigation.topics": "Bibliothèque de sujets",
    "navigation.generate": "Création de contenu",
    "navigation.settings": "Paramètres",
    "shell.search": "Rechercher des pages ou fonctions…",
    "shell.inboxTitle": "Mises à jour non lues",
    "shell.inboxEmpty": "Aucune mise à jour non lue",
    "shell.logout": "Se déconnecter",
    "shell.language": "Langue de l’interface",
  },
  "de-DE": {
    ...ZH,
    "navigation.insights": "Einblicke",
    "navigation.creation": "Erstellung",
    "navigation.automation": "Automatisierung",
    "navigation.operations": "Betrieb",
    "navigation.dashboard": "Dashboard",
    "navigation.trends": "Trendintelligenz",
    "navigation.videoSearch": "Videosuche",
    "navigation.accounts": "Kontenüberwachung",
    "navigation.contents": "Inhaltsdaten",
    "navigation.news": "Nachrichten",
    "navigation.events": "Ereignisse",
    "navigation.topics": "Themenbibliothek",
    "navigation.generate": "Content-Erstellung",
    "navigation.settings": "Einstellungen",
    "shell.search": "Seiten oder Funktionen suchen…",
    "shell.inboxTitle": "Ungelesene Updates",
    "shell.inboxEmpty": "Keine ungelesenen Updates",
    "shell.logout": "Abmelden",
    "shell.language": "Oberflächensprache",
  },
  "pt-BR": {
    ...ZH,
    "navigation.insights": "Insights",
    "navigation.creation": "Criação",
    "navigation.automation": "Automação",
    "navigation.operations": "Operações",
    "navigation.dashboard": "Painel",
    "navigation.trends": "Inteligência de tendências",
    "navigation.videoSearch": "Busca de vídeos",
    "navigation.accounts": "Monitoramento de contas",
    "navigation.contents": "Dados de conteúdo",
    "navigation.news": "Notícias",
    "navigation.events": "Eventos",
    "navigation.topics": "Biblioteca de temas",
    "navigation.generate": "Criação de conteúdo",
    "navigation.settings": "Configurações",
    "shell.search": "Pesquisar páginas ou funções…",
    "shell.inboxTitle": "Atualizações não lidas",
    "shell.inboxEmpty": "Nenhuma atualização não lida",
    "shell.logout": "Sair",
    "shell.language": "Idioma da interface",
  },
};

type UiLanguageContextValue = {
  locale: UiLanguageCode;
  setLocale: (locale: UiLanguageCode) => void;
  t: (key: TranslationKey, fallback?: string) => string;
};

const UiLanguageContext = createContext<UiLanguageContextValue | null>(null);

export function UiLanguageProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useLocalStorageState<UiLanguageCode>(
    "ui-language",
    "zh-CN",
  );

  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dataset.uiLanguage = locale;
  }, [locale]);

  const t = (key: TranslationKey, fallback?: string): string =>
    TRANSLATIONS[locale]?.[key] ?? ZH[key] ?? fallback ?? key;

  return (
    <UiLanguageContext.Provider value={{ locale, setLocale, t }}>
      {children}
    </UiLanguageContext.Provider>
  );
}

export function useUiLanguage(): UiLanguageContextValue {
  const context = useContext(UiLanguageContext);
  if (context) return context;

  // Keeps isolated component tests and any future embedded usage safe while
  // the normal application path always renders inside UiLanguageProvider.
  return {
    locale: "zh-CN",
    setLocale: () => undefined,
    t: (key, fallback) => fallback ?? ZH[key] ?? key,
  };
}

export function languageOptionLabel(value: UiLanguageCode): string {
  const option = UI_LANGUAGE_OPTIONS.find((item) => item.value === value);
  return option?.nativeLabel ?? value;
}

export function normalizeUiLanguage(value: string): UiLanguageCode {
  return isUiLanguageCode(value) ? value : "zh-CN";
}
