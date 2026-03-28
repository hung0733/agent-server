import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./locales/en/dashboard.json";
import zhHK from "./locales/zh-HK/dashboard.json";

if (!i18n.isInitialized) {
  void i18n.use(initReactI18next).init({
    lng: "zh-HK",
    fallbackLng: "en",
    resources: {
      "zh-HK": { translation: zhHK },
      en: { translation: en },
    },
    interpolation: {
      escapeValue: false,
    },
  });
}

export default i18n;
