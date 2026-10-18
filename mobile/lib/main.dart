import 'package:flutter/material.dart';

void main() => runApp(const NuqatiApp());

const navy = Color(0xFF102A56);
const lime = Color(0xFFB8E638);

class NuqatiApp extends StatelessWidget {
  const NuqatiApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'نقاطي',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: navy, primary: navy, secondary: lime),
        scaffoldBackgroundColor: const Color(0xFFF4F7FB),
        useMaterial3: true,
        fontFamily: 'Arial',
      ),
      home: const DriverHome(),
    );
  }
}

class DriverHome extends StatelessWidget {
  const DriverHome({super.key});
  @override
  Widget build(BuildContext context) {
    return Directionality(
      textDirection: TextDirection.rtl,
      child: Scaffold(
        appBar: AppBar(
          backgroundColor: navy,
          foregroundColor: Colors.white,
          title: const Row(children: [CircleAvatar(backgroundColor: lime, child: Text('ن', style: TextStyle(color: navy, fontWeight: FontWeight.bold))), SizedBox(width: 10), Text('نقاطي | تطبيق السائق')]),
        ),
        body: ListView(
          padding: const EdgeInsets.all(18),
          children: [
            Container(
              padding: const EdgeInsets.all(22),
              decoration: BoxDecoration(color: navy, borderRadius: BorderRadius.circular(22)),
              child: const Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('مرحبًا بك في نقاطي', style: TextStyle(color: Colors.white70)),
                SizedBox(height: 10),
                Text('قيادتك تصنع الفرق', style: TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.bold)),
                SizedBox(height: 18),
                Row(children: [Icon(Icons.stars_rounded, color: lime, size: 32), SizedBox(width: 10), Text('— / 100', style: TextStyle(color: lime, fontSize: 26, fontWeight: FontWeight.bold))]),
                SizedBox(height: 8),
                Text('سيظهر تقييمك بعد تسجيل الرحلات', style: TextStyle(color: Colors.white70)),
              ]),
            ),
            const SizedBox(height: 16),
            const _InfoCard(icon: Icons.speed, title: 'السرعة الحالية', value: '-- كم/س', detail: 'تبدأ القراءة بعد تفعيل التتبع والأذونات'),
            const _InfoCard(icon: Icons.route, title: 'مسافة اليوم', value: '-- كم', detail: 'المسافة التقديرية عبر GPS'),
            const _InfoCard(icon: Icons.notifications_active_outlined, title: 'تذكير الصيانة', value: 'حسب العداد', detail: 'تذكيرات لكل مركبة دون تصوير اللوحة أو ربط الورشة'),
            const _InfoCard(icon: Icons.shield_outlined, title: 'الخصوصية أولًا', value: 'التتبع بإذن واضح', detail: 'سيعرض التطبيق حالة التتبع ويشرح استخدام بيانات الموقع'),
            const SizedBox(height: 12),
            FilledButton.icon(
              style: FilledButton.styleFrom(backgroundColor: lime, foregroundColor: navy, padding: const EdgeInsets.all(16)),
              onPressed: () => showDialog<void>(context: context, builder: (context) => AlertDialog(
                title: const Text('التتبع غير مفعّل بعد'),
                content: const Text('هذه شاشة البداية. قبل تشغيل الرحلات يجب تنفيذ صلاحيات الموقع، وخدمة التتبع الخلفي، والمزامنة الآمنة مع الخادم واختبارها على أجهزة فعلية.'),
                actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('حسنًا'))],
              )),
              icon: const Icon(Icons.play_arrow_rounded),
              label: const Text('بدء رحلة — نموذج أولي'),
            ),
          ],
        ),
      ),
    );
  }
}

class _InfoCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String value;
  final String detail;
  const _InfoCard({required this.icon, required this.title, required this.value, required this.detail});
  @override
  Widget build(BuildContext context) => Card(
    elevation: 0,
    margin: const EdgeInsets.only(bottom: 12),
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Row(children: [
        CircleAvatar(backgroundColor: const Color(0xFFEAF5C9), foregroundColor: navy, child: Icon(icon)),
        const SizedBox(width: 13),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: const TextStyle(color: Colors.blueGrey)),
          const SizedBox(height: 3),
          Text(value, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: navy)),
          Text(detail, style: const TextStyle(fontSize: 12, color: Colors.blueGrey)),
        ])),
      ]),
    ),
  );
}
