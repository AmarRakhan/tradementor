package com.tradementor.app.localization

import android.content.Context

enum class AppLanguage(val code: String, val nativeName: String) {
    Dutch("nl", "Nederlands"), English("en", "English"), Chinese("zh", "简体中文"),
    Hindi("hi", "हिन्दी"), Spanish("es", "Español"), French("fr", "Français"),
    Arabic("ar", "العربية"), Bengali("bn", "বাংলা"), Portuguese("pt", "Português"),
    Russian("ru", "Русский"), Urdu("ur", "اردو"), Indonesian("id", "Bahasa Indonesia"),
    German("de", "Deutsch"), Japanese("ja", "日本語"), Swahili("sw", "Kiswahili"),
    Marathi("mr", "मराठी"), Telugu("te", "తెలుగు"), Turkish("tr", "Türkçe"),
    Tamil("ta", "தமிழ்"), Korean("ko", "한국어"), SrananTongo("srn", "Sranan Tongo")
}

object AppLanguageStore {
    private const val PREFS = "app_language"
    private const val KEY = "selected"
    fun load(context: Context): AppLanguage {
        val code = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, "nl")
        return AppLanguage.entries.firstOrNull { it.code == code } ?: AppLanguage.Dutch
    }
    fun save(context: Context, language: AppLanguage) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .edit().putString(KEY, language.code).putBoolean("chosen", true).apply()
    fun isChosen(context: Context): Boolean = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .getBoolean("chosen", false)
}

private val translations = mapOf(
    "settings" to listOf("Settings", "Settings", "设置", "सेटिंग्स", "Ajustes", "Paramètres", "الإعدادات", "সেটিংস", "Configurações"),
    "settings_subtitle" to listOf("TradeMentor-appinstellingen en informatie", "TradeMentor app settings and information", "TradeMentor 应用设置和信息", "TradeMentor ऐप सेटिंग्स और जानकारी", "Ajustes e información de TradeMentor", "Paramètres et informations TradeMentor", "إعدادات ومعلومات TradeMentor", "TradeMentor অ্যাপ সেটিংস ও তথ্য", "Configurações e informações do TradeMentor"),
    "back_wallet" to listOf("← Terug naar Wallet", "← Back to Wallet", "← 返回钱包", "← वॉलेट पर वापस जाएँ", "← Volver a Wallet", "← Retour au Wallet", "← العودة إلى المحفظة", "← ওয়ালেটে ফিরে যান", "← Voltar à Wallet"),
    "language" to listOf("Taal", "Language", "语言", "भाषा", "Idioma", "Langue", "اللغة", "ভাষা", "Idioma"),
    "language_help" to listOf("Kies de taal van TradeMentor", "Choose the TradeMentor language", "选择 TradeMentor 的语言", "TradeMentor की भाषा चुनें", "Elige el idioma de TradeMentor", "Choisissez la langue de TradeMentor", "اختر لغة TradeMentor", "TradeMentor-এর ভাষা বেছে নিন", "Escolha o idioma do TradeMentor"),
    "app" to listOf("App", "App", "应用", "ऐप", "Aplicación", "Application", "التطبيق", "অ্যাপ", "Aplicativo"),
    "version" to listOf("Versie", "Version", "版本", "संस्करण", "Versión", "Version", "الإصدار", "সংস্করণ", "Versão"),
    "build" to listOf("Build", "Build", "构建", "बिल्ड", "Compilación", "Build", "البنية", "বিল্ড", "Build"),
    "package" to listOf("Pakket", "Package", "软件包", "पैकेज", "Paquete", "Package", "الحزمة", "প্যাকেজ", "Pacote"),
    "main_tabs" to listOf("Hoofdtabbladen", "Main tabs", "主标签页", "मुख्य टैब", "Pestañas principales", "Onglets principaux", "علامات التبويب الرئيسية", "প্রধান ট্যাব", "Abas principais"),
    "security" to listOf("Beveiliging", "Security", "安全", "सुरक्षा", "Seguridad", "Sécurité", "الأمان", "নিরাপত্তা", "Segurança"),
    "scanner_notifications" to listOf("Scanner en meldingen", "Scanner and notifications", "扫描器和通知", "स्कैनर और सूचनाएँ", "Escáner y notificaciones", "Scanner et notifications", "الماسح والإشعارات", "স্ক্যানার ও বিজ্ঞপ্তি", "Scanner e notificações"),
    "backtest" to listOf("Backtest", "Backtest", "回测", "बैकटेस्ट", "Backtest", "Backtest", "اختبار رجعي", "ব্যাকটেস্ট", "Backtest"),
    "markets" to listOf("Markets", "Markets", "市场", "बाज़ार", "Mercados", "Marchés", "الأسواق", "মার্কেট", "Mercados"),
    "signals" to listOf("Signals", "Signals", "信号", "सिग्नल", "Señales", "Signaux", "الإشارات", "সিগন্যাল", "Sinais"),
    "live_positions" to listOf("Live Positions", "Live Positions", "实时持仓", "लाइव पोज़िशन", "Posiciones en vivo", "Positions en direct", "المراكز المباشرة", "লাইভ পজিশন", "Posições ao vivo"),
    "risk" to listOf("Risk", "Risk", "风险", "जोखिम", "Riesgo", "Risque", "المخاطر", "ঝুঁকি", "Risco"),
    "wallet" to listOf("Wallet", "Wallet", "钱包", "वॉलेट", "Wallet", "Wallet", "المحفظة", "ওয়ালেট", "Wallet")
)

private val extra = mapOf(
    "ru" to mapOf("settings" to "Настройки", "settings_subtitle" to "Настройки и информация TradeMentor", "back_wallet" to "← Назад к кошельку", "language" to "Язык", "language_help" to "Выберите язык TradeMentor", "app" to "Приложение", "version" to "Версия", "build" to "Сборка", "package" to "Пакет", "main_tabs" to "Основные вкладки", "security" to "Безопасность", "scanner_notifications" to "Сканер и уведомления", "backtest" to "Бэктест", "markets" to "Рынки", "signals" to "Сигналы", "live_positions" to "Открытые позиции", "risk" to "Риск", "wallet" to "Кошелёк"),
    "ur" to mapOf("settings" to "ترتیبات", "settings_subtitle" to "TradeMentor کی ترتیبات اور معلومات", "back_wallet" to "← والٹ پر واپس", "language" to "زبان", "language_help" to "TradeMentor کی زبان منتخب کریں", "app" to "ایپ", "version" to "ورژن", "build" to "بلڈ", "package" to "پیکیج", "main_tabs" to "مرکزی ٹیبز", "security" to "سیکیورٹی", "scanner_notifications" to "اسکینر اور اطلاعات", "backtest" to "بیک ٹیسٹ", "markets" to "مارکیٹس", "signals" to "سگنلز", "live_positions" to "لائیو پوزیشنز", "risk" to "خطرہ", "wallet" to "والٹ"),
    "id" to mapOf("settings" to "Pengaturan", "settings_subtitle" to "Pengaturan dan informasi TradeMentor", "back_wallet" to "← Kembali ke Wallet", "language" to "Bahasa", "language_help" to "Pilih bahasa TradeMentor", "app" to "Aplikasi", "version" to "Versi", "build" to "Build", "package" to "Paket", "main_tabs" to "Tab utama", "security" to "Keamanan", "scanner_notifications" to "Pemindai dan notifikasi", "backtest" to "Backtest", "markets" to "Pasar", "signals" to "Sinyal", "live_positions" to "Posisi aktif", "risk" to "Risiko", "wallet" to "Wallet"),
    "de" to mapOf("settings" to "Einstellungen", "settings_subtitle" to "TradeMentor-Einstellungen und Informationen", "back_wallet" to "← Zurück zur Wallet", "language" to "Sprache", "language_help" to "TradeMentor-Sprache wählen", "app" to "App", "version" to "Version", "build" to "Build", "package" to "Paket", "main_tabs" to "Haupttabs", "security" to "Sicherheit", "scanner_notifications" to "Scanner und Benachrichtigungen", "backtest" to "Backtest", "markets" to "Märkte", "signals" to "Signale", "live_positions" to "Live-Positionen", "risk" to "Risiko", "wallet" to "Wallet"),
    "ja" to mapOf("settings" to "設定", "settings_subtitle" to "TradeMentor の設定と情報", "back_wallet" to "← ウォレットに戻る", "language" to "言語", "language_help" to "TradeMentor の言語を選択", "app" to "アプリ", "version" to "バージョン", "build" to "ビルド", "package" to "パッケージ", "main_tabs" to "メインタブ", "security" to "セキュリティ", "scanner_notifications" to "スキャナーと通知", "backtest" to "バックテスト", "markets" to "市場", "signals" to "シグナル", "live_positions" to "保有ポジション", "risk" to "リスク", "wallet" to "ウォレット"),
    "sw" to mapOf("settings" to "Mipangilio", "settings_subtitle" to "Mipangilio na taarifa za TradeMentor", "back_wallet" to "← Rudi Wallet", "language" to "Lugha", "language_help" to "Chagua lugha ya TradeMentor", "app" to "Programu", "version" to "Toleo", "build" to "Build", "package" to "Kifurushi", "main_tabs" to "Vichupo vikuu", "security" to "Usalama", "scanner_notifications" to "Kichanganuzi na arifa", "backtest" to "Backtest", "markets" to "Masoko", "signals" to "Ishara", "live_positions" to "Nafasi hai", "risk" to "Hatari", "wallet" to "Wallet"),
    "mr" to mapOf("settings" to "सेटिंग्ज", "settings_subtitle" to "TradeMentor सेटिंग्ज आणि माहिती", "back_wallet" to "← वॉलेटकडे परत", "language" to "भाषा", "language_help" to "TradeMentor भाषा निवडा", "app" to "अॅप", "version" to "आवृत्ती", "build" to "बिल्ड", "package" to "पॅकेज", "main_tabs" to "मुख्य टॅब", "security" to "सुरक्षा", "scanner_notifications" to "स्कॅनर आणि सूचना", "backtest" to "बॅकटेस्ट", "markets" to "बाजार", "signals" to "सिग्नल", "live_positions" to "चालू पोझिशन्स", "risk" to "जोखीम", "wallet" to "वॉलेट"),
    "te" to mapOf("settings" to "సెట్టింగ్‌లు", "settings_subtitle" to "TradeMentor సెట్టింగ్‌లు మరియు సమాచారం", "back_wallet" to "← వాలెట్‌కు తిరిగి", "language" to "భాష", "language_help" to "TradeMentor భాషను ఎంచుకోండి", "app" to "యాప్", "version" to "వెర్షన్", "build" to "బిల్డ్", "package" to "ప్యాకేజ్", "main_tabs" to "ప్రధాన ట్యాబ్‌లు", "security" to "భద్రత", "scanner_notifications" to "స్కానర్ మరియు నోటిఫికేషన్‌లు", "backtest" to "బ్యాక్‌టెస్ట్", "markets" to "మార్కెట్లు", "signals" to "సిగ్నల్స్", "live_positions" to "లైవ్ పొజిషన్లు", "risk" to "రిస్క్", "wallet" to "వాలెట్"),
    "tr" to mapOf("settings" to "Ayarlar", "settings_subtitle" to "TradeMentor ayarları ve bilgileri", "back_wallet" to "← Wallet'a dön", "language" to "Dil", "language_help" to "TradeMentor dilini seç", "app" to "Uygulama", "version" to "Sürüm", "build" to "Derleme", "package" to "Paket", "main_tabs" to "Ana sekmeler", "security" to "Güvenlik", "scanner_notifications" to "Tarayıcı ve bildirimler", "backtest" to "Backtest", "markets" to "Piyasalar", "signals" to "Sinyaller", "live_positions" to "Canlı pozisyonlar", "risk" to "Risk", "wallet" to "Wallet"),
    "ta" to mapOf("settings" to "அமைப்புகள்", "settings_subtitle" to "TradeMentor அமைப்புகள் மற்றும் தகவல்", "back_wallet" to "← வாலெட்டுக்கு திரும்பு", "language" to "மொழி", "language_help" to "TradeMentor மொழியைத் தேர்ந்தெடுக்கவும்", "app" to "செயலி", "version" to "பதிப்பு", "build" to "பில்ட்", "package" to "தொகுப்பு", "main_tabs" to "முதன்மை தாவல்கள்", "security" to "பாதுகாப்பு", "scanner_notifications" to "ஸ்கேனர் மற்றும் அறிவிப்புகள்", "backtest" to "பேக்டெஸ்ட்", "markets" to "சந்தைகள்", "signals" to "சிக்னல்கள்", "live_positions" to "நேரடி நிலைகள்", "risk" to "ஆபத்து", "wallet" to "வாலெட்"),
    "ko" to mapOf("settings" to "설정", "settings_subtitle" to "TradeMentor 설정 및 정보", "back_wallet" to "← 지갑으로 돌아가기", "language" to "언어", "language_help" to "TradeMentor 언어 선택", "app" to "앱", "version" to "버전", "build" to "빌드", "package" to "패키지", "main_tabs" to "기본 탭", "security" to "보안", "scanner_notifications" to "스캐너 및 알림", "backtest" to "백테스트", "markets" to "시장", "signals" to "신호", "live_positions" to "실시간 포지션", "risk" to "위험", "wallet" to "지갑"),
    "srn" to mapOf("settings" to "Seti", "settings_subtitle" to "TradeMentor seti nanga informasie", "back_wallet" to "← Go baka na Wallet", "language" to "Tongo", "language_help" to "Kies a tongo fu TradeMentor", "app" to "App", "version" to "Fersi", "build" to "Build", "package" to "Pakki", "main_tabs" to "Prenspari tabs", "security" to "Sekerheid", "scanner_notifications" to "Scanner nanga boskopu", "backtest" to "Backtest", "markets" to "Markti", "signals" to "Sein", "live_positions" to "Lib positions", "risk" to "Risk", "wallet" to "Wallet")
)

fun tr(language: AppLanguage, key: String): String = extra[language.code]?.get(key)
    ?: translations[key]?.getOrElse(language.ordinal) { translations[key]?.getOrNull(1) ?: translations[key]!!.first() }
    ?: key


fun orderedLanguages(): List<AppLanguage> = AppLanguage.entries.sortedWith(
    compareBy<AppLanguage> { when (it) { AppLanguage.English -> 0; AppLanguage.Dutch -> 1; else -> 2 } }
        .thenBy { it.nativeName }
)

fun languageFlag(language: AppLanguage): String = when (language) {
    AppLanguage.Dutch -> "🇳🇱"; AppLanguage.English -> "🇬🇧"; AppLanguage.Chinese -> "🇨🇳"
    AppLanguage.Hindi -> "🇮🇳"; AppLanguage.Spanish -> "🇪🇸"; AppLanguage.French -> "🇫🇷"
    AppLanguage.Arabic -> "🇸🇦"; AppLanguage.Bengali -> "🇧🇩"; AppLanguage.Portuguese -> "🇵🇹"
    AppLanguage.Russian -> "🇷🇺"; AppLanguage.Urdu -> "🇵🇰"; AppLanguage.Indonesian -> "🇮🇩"
    AppLanguage.German -> "🇩🇪"; AppLanguage.Japanese -> "🇯🇵"; AppLanguage.Swahili -> "🇰🇪"
    AppLanguage.Marathi -> "🇮🇳"; AppLanguage.Telugu -> "🇮🇳"; AppLanguage.Turkish -> "🇹🇷"
    AppLanguage.Tamil -> "🇮🇳"; AppLanguage.Korean -> "🇰🇷"; AppLanguage.SrananTongo -> "🇸🇷"
}
