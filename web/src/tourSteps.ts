// Steps of the first-login tour. Every text exists in English and Arabic; backend/test_web_tour_contract.py checks that
// (and that every `target` is a real data-tour="..." element in App.tsx, and every role is a real role).
//
// `target` names an element carrying data-tour="<target>". A step without a target, or whose target is not on screen
// (a narrow layout, a hidden menu), is shown as a centred card instead of a spotlight.
// `roles` limits a step to those roles; no `roles` means everyone.

export type TourText = { en: string; ar: string };
export type TourStep = { id: string; target?: string; roles?: string[]; title: TourText; body: TourText };

const ADMINS = ["super_admin", "company_admin"];

export const TOUR_STEPS: TourStep[] = [
  {
    id: "welcome",
    title: { en: "Welcome to Nuqati", ar: "مرحباً بك في نقاطي" },
    body: {
      en: "A short tour of where things are. You can skip it now and replay it at any time with the “Tour” button at the top.",
      ar: "جولة قصيرة تعرّفك على أماكن الأقسام. يمكنك تخطيها الآن وإعادتها في أي وقت من زر «جولة» في الأعلى.",
    },
  },
  {
    id: "sidebar",
    target: "sidebar",
    title: { en: "The side menu", ar: "القائمة الجانبية" },
    body: {
      en: "Everything is in the side menu, in six groups: Home, Fleet, Safety, Maintenance, Reports and Administration. Click a group to open it.",
      ar: "كل الأقسام في القائمة الجانبية ضمن ست مجموعات: الرئيسية والأسطول والسلامة والصيانة والتقارير والإدارة. اضغط على المجموعة لفتحها.",
    },
  },
  {
    id: "company",
    target: "company",
    roles: ["super_admin"],
    title: { en: "Choose a company first", ar: "اختر الشركة أولاً" },
    body: {
      en: "As a super admin you work inside one company at a time. Pick it here once, and Vehicles, Drivers, Reports and the other pages show that company.",
      ar: "بصفتك مشرفاً عاماً تعمل ضمن شركة واحدة في كل مرة. اخترها من هنا مرة واحدة لتعرض صفحات السيارات والسائقين والتقارير بيانات تلك الشركة.",
    },
  },
  {
    id: "language",
    target: "language",
    title: { en: "English or Arabic", ar: "العربية أو الإنجليزية" },
    body: {
      en: "Switch the language here at any time. Arabic flips the whole screen to right-to-left.",
      ar: "بدّل اللغة من هنا في أي وقت. عند اختيار العربية تنقلب الشاشة بالكامل إلى اتجاه اليمين لليسار.",
    },
  },
  {
    id: "home",
    target: "nav-home",
    title: { en: "Overview", ar: "نظرة عامة" },
    body: {
      en: "Your starting page: a summary of the fleet and its recent activity, with a date range you can change.",
      ar: "صفحة البداية: ملخص للأسطول ونشاطه الأخير، مع نطاق تاريخ يمكنك تغييره.",
    },
  },
  {
    id: "fleet",
    target: "nav-fleet",
    title: { en: "Fleet", ar: "الأسطول" },
    body: {
      en: "Vehicles and Drivers hold your records; open one to edit it. Live Tracking shows where vehicles are now, and Historical Tracking replays past trips on a map. Vehicle Handover records handing a vehicle to a driver and back.",
      ar: "السيارات والسائقون هما سجلاتك؛ افتح أي سجل لتعديله. يعرض التتبع المباشر أماكن المركبات الآن، ويعيد التتبع التاريخي الرحلات السابقة على الخريطة. استلام وتسليم المركبات يوثّق تسليم المركبة للسائق وإرجاعها.",
    },
  },
  {
    id: "driver-access",
    target: "nav-fleet",
    roles: ADMINS,
    title: { en: "A driver cannot sign in?", ar: "سائق لا يستطيع تسجيل الدخول؟" },
    body: {
      en: "Open the driver and use “Phone sign-in & password”. Sign out the old phone after a lost phone or a reinstall, or set a new password if it was forgotten.",
      ar: "افتح صفحة السائق واستخدم «دخول الهاتف وكلمة المرور». سجّل خروج الهاتف القديم بعد فقدانه أو إعادة تثبيت التطبيق، أو عيّن كلمة مرور جديدة إن نسيها.",
    },
  },
  {
    id: "safety",
    target: "nav-safety",
    title: { en: "Safety", ar: "السلامة" },
    body: {
      en: "Geofence Location draws zones that can carry their own speed limits. Configuration sets the speeding and harsh-driving limits. Privacy Audit lists Privacy Mode activity.",
      ar: "مواقع المناطق الجغرافية ترسم مناطق يمكن أن يكون لها حد سرعة خاص. الإعدادات تحدد حدود السرعة والقيادة العنيفة. سجل وضع الخصوصية يعرض نشاط وضع الخصوصية.",
    },
  },
  {
    id: "maintenance",
    target: "nav-maintenance",
    title: { en: "Maintenance", ar: "الصيانة" },
    body: {
      en: "Odometer readings feed Maintenance Alerts, so service reminders arrive on time. Workshop Requests collects help requests from drivers, and App Diagnostics shows problems reported by the driver app.",
      ar: "قراءات العداد تغذّي تنبيهات الصيانة لتصل تذكيرات الخدمة في وقتها. طلبات الورشة تجمع طلبات المساعدة من السائقين، وتشخيص التطبيق يعرض المشكلات التي يبلغ عنها تطبيق السائق.",
    },
  },
  {
    id: "reports",
    target: "nav-reports",
    title: { en: "Reports", ar: "التقارير" },
    body: {
      en: "Fleet Reports summarise trips, distance, drivers and safety. Export them to Excel or PDF, or schedule a report to be sent by e-mail.",
      ar: "تقارير الأسطول تلخّص الرحلات والمسافات والسائقين والسلامة. صدّرها إلى Excel أو PDF، أو جدولها لتُرسل بالبريد الإلكتروني.",
    },
  },
  {
    id: "administration",
    target: "nav-admin",
    roles: ["super_admin"],
    title: { en: "Companies, users and branding", ar: "الشركات والمستخدمون والهوية" },
    body: {
      en: "Companies, Users & Access and Branding & Language are here. A new user receives an invitation e-mail and sets their own password.",
      ar: "الشركات والمستخدمون والصلاحيات والهوية واللغة هنا. يصل المستخدم الجديد بريد دعوة ويختار كلمة مروره بنفسه.",
    },
  },
  {
    id: "account",
    target: "nav-admin",
    title: { en: "Your account", ar: "حسابك" },
    body: {
      en: "In My Account you can change your password and e-mail. Where two-step sign-in is switched on, you can also add an authenticator app to protect your account.",
      ar: "في «حسابي» يمكنك تغيير كلمة المرور والبريد الإلكتروني. وحيث يكون الدخول بخطوتين مفعّلاً يمكنك إضافة تطبيق مصادقة لحماية حسابك.",
    },
  },
  {
    id: "replay",
    target: "tour-replay",
    title: { en: "That is the tour", ar: "هذه هي الجولة" },
    body: {
      en: "Press “Tour” in the top bar to see it again whenever you like.",
      ar: "اضغط «جولة» في الشريط العلوي لمشاهدتها مرة أخرى متى شئت.",
    },
  },
];

/** The steps one role sees, in order. */
export function tourStepsFor(role: string): TourStep[] {
  return TOUR_STEPS.filter((step) => !step.roles || step.roles.includes(role));
}
