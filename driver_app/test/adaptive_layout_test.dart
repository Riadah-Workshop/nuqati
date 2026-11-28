// Renders the driver app's adaptive layout pieces (nuqati_adaptive.dart) on many screen sizes and system font sizes, in English, Arabic
// and Urdu, and fails on any overflow, on text leaving the score circle, on a tile leaving the screen, or on tiles of one row having
// different heights. Run by CI (ci-flutter.yml, job "Driver app analyze"): `flutter test test/adaptive_layout_test.dart`.
//
// The test font in flutter_test (Ahem) draws every character as a full-size square, which is wider than any real font, so passing here
// is a conservative result.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nuqati_driver/nuqati_adaptive.dart';

const lime = Color(0xffa8d941);
const navy = Color(0xff0b1c30);
const blue = Color(0xff17334d);

// Logical sizes: a very small phone / "largest display size", common phones, a large phone, a small tablet, a tablet.
const screens = <Size>[Size(280, 500), Size(320, 568), Size(360, 640), Size(393, 852), Size(411, 891), Size(600, 960), Size(820, 1180)];
// System font scales a user can pick (Android goes up to about 2.0); the app clamps them to 0.85 .. 1.35.
const fontScales = <double>[0.85, 1.0, 1.15, 1.35, 1.8, 2.0];

const labelSets = <String, List<String>>{
  'en': ['Speeding', 'Braking', 'Acceleration', 'Cornering', 'Excessive'],
  'ar': ['السرعة', 'الفرملة', 'التسارع', 'الانعطاف', 'شديد'],
  'ur': ['رفتار', 'بریک لگانا', 'رفتار میں اضافہ', 'موڑ کاٹنا', 'شدید'],
  'long': ['Harsh acceleration events', 'Harsh braking events', 'تجاوز السرعة المسموحة', 'Harsh cornering events', 'Excessive events today'],
};

/// Shows [child] the way the driver app does: a 18 px page padding, a 18 px panel padding, the system font scale [fontScale], and (as in
/// main()) the app's own clamp on top of it unless [clamp] is false.
Future<void> pumpScreen(
  WidgetTester tester, {
  required Size size,
  required double fontScale,
  required Widget child,
  bool clamp = true,
  TextDirection direction = TextDirection.ltr,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      builder: (context, app) => MediaQuery(
        data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(fontScale)),
        child: Builder(builder: (inner) => clamp ? nuqatiClampTextScale(inner, app) : app!),
      ),
      home: Directionality(
        textDirection: direction,
        child: Scaffold(
          backgroundColor: navy,
          body: ListView(
            padding: const EdgeInsets.all(18),
            children: [
              Container(width: double.infinity, padding: const EdgeInsets.all(18), color: blue, child: child),
            ],
          ),
        ),
      ),
    ),
  );
  await tester.pump();
}

void expectNoException(WidgetTester tester, String where) {
  final exception = tester.takeException();
  expect(exception, isNull, reason: '$where raised: $exception');
}

bool inside(Rect r, Offset center, double radius) =>
    [r.topLeft, r.topRight, r.bottomLeft, r.bottomRight].every((p) => (p - center).distance <= radius + 0.01);

List<Widget> tilesFor(List<String> labels, {required bool large, int? take}) {
  final shown = take == null ? labels : labels.take(take).toList();
  const icons = <IconData>[Icons.speed, Icons.warning_amber, Icons.trending_up, Icons.turn_right, Icons.priority_high];
  return [
    for (var i = 0; i < shown.length; i++)
      NuqatiMetricTile(
        label: shown[i],
        value: '${i * 7 + 3}',
        icon: icons[i % icons.length],
        accent: lime,
        fill: large ? blue : navy,
        large: large,
        border: large ? Colors.white12 : null,
      ),
  ];
}

void main() {
  group('helpers', () {
    test('ring diameter follows the width and stays between 132 and 220', () {
      expect(nuqatiRingDiameter(200), 132);
      expect(nuqatiRingDiameter(300), 150);
      expect(nuqatiRingDiameter(400), 200);
      expect(nuqatiRingDiameter(900), 220);
      expect(nuqatiRingDiameter(100), 100, reason: 'never wider than the space it is given');
    });

    test('grid columns follow the width and the tile count', () {
      expect(nuqatiGridColumns(width: 320, count: 5, minTileWidth: 92, spacing: 7), 3);
      expect(nuqatiGridColumns(width: 900, count: 5, minTileWidth: 92, spacing: 7), 5);
      expect(nuqatiGridColumns(width: 900, count: 4, minTileWidth: 92, spacing: 7), 4);
      expect(nuqatiGridColumns(width: 100, count: 5, minTileWidth: 92, spacing: 7), 1);
      expect(nuqatiGridColumns(width: 600, count: 1, minTileWidth: 92), 1);
      expect(nuqatiGridColumns(width: 360, count: 4, minTileWidth: 140, spacing: 10, maxColumns: 2), 2);
    });

    testWidgets('the app clamps the system font scale to 0.85 .. 1.35', (tester) async {
      Future<double> scaledTenAt(double systemScale) async {
        double? seen;
        await pumpScreen(
          tester,
          size: const Size(360, 640),
          fontScale: systemScale,
          child: Builder(builder: (context) {
            seen = MediaQuery.textScalerOf(context).scale(10);
            return const SizedBox.shrink();
          }),
        );
        return seen!;
      }

      expect(await scaledTenAt(2.0), closeTo(13.5, 0.001));
      expect(await scaledTenAt(1.0), closeTo(10.0, 0.001));
      expect(await scaledTenAt(0.5), closeTo(8.5, 0.001));
    });
  });

  group('score ring', () {
    for (final size in screens) {
      for (final scale in fontScales) {
        for (final value in const ['100', '92', '100.0', '—', '7']) {
          testWidgets('${size.width.toInt()}x${size.height.toInt()} font ${scale}x shows "$value" inside the circle', (tester) async {
            await pumpScreen(
              tester,
              size: size,
              fontScale: scale,
              child: NuqatiScoreRing(value: value, label: value == '7' ? 'NO DATA' : 'GREEN', progress: 0.92, color: lime),
            );
            expectNoException(tester, 'ring at ${size.width.toInt()}x${size.height.toInt()}, font ${scale}x');

            final ring = tester.getRect(find.byType(CircularProgressIndicator));
            final stroke = tester.widget<CircularProgressIndicator>(find.byType(CircularProgressIndicator)).strokeWidth ?? 4.0;
            expect(ring.left, greaterThanOrEqualTo(0));
            expect(ring.right, lessThanOrEqualTo(size.width));
            expect(ring.width, greaterThanOrEqualTo(100));

            final freeRadius = ring.width / 2 - stroke;
            for (final text in [value, value == '7' ? 'NO DATA' : 'GREEN']) {
              final r = tester.getRect(find.text(text));
              expect(inside(r, ring.center, freeRadius), isTrue, reason: '"$text" $r leaves the free circle (centre ${ring.center}, radius $freeRadius)');
            }
            // The word is below the points.
            expect(tester.getRect(find.text(value == '7' ? 'NO DATA' : 'GREEN')).top, greaterThanOrEqualTo(tester.getRect(find.text(value)).bottom - 0.5));
          });
        }
      }
    }
  });

  group('tiles in rows', () {
    for (final entry in labelSets.entries) {
      for (final large in [false, true]) {
        for (final size in screens) {
          for (final scale in fontScales) {
            testWidgets('${large ? 'event cards' : 'live metrics'} ${entry.key} ${size.width.toInt()}x${size.height.toInt()} font ${scale}x', (tester) async {
              await pumpScreen(
                tester,
                size: size,
                fontScale: scale,
                direction: entry.key == 'en' || entry.key == 'long' ? TextDirection.ltr : TextDirection.rtl,
                child: large
                    ? NuqatiEqualGrid(spacing: 10, minTileWidth: 140, maxColumns: 2, children: tilesFor(entry.value, large: true, take: 4))
                    : NuqatiEqualGrid(spacing: 7, children: tilesFor(entry.value, large: false)),
              );
              expectNoException(tester, '${entry.key} tiles at ${size.width.toInt()}x${size.height.toInt()}, font ${scale}x');

              final rects = [for (final e in find.byType(NuqatiMetricTile).evaluate()) tester.getRect(find.byWidget(e.widget))];
              expect(rects.length, large ? 4 : 5);
              final rows = <int, List<Rect>>{};
              for (final r in rects) {
                expect(r.left, greaterThanOrEqualTo(0), reason: 'tile $r leaves the screen on the left');
                expect(r.right, lessThanOrEqualTo(size.width), reason: 'tile $r leaves the screen on the right');
                rows.putIfAbsent((r.top * 2).round(), () => []).add(r);
              }
              for (final row in rows.values) {
                final heights = row.map((r) => r.height).toSet().map((h) => h.toStringAsFixed(1)).toSet();
                expect(heights.length, 1, reason: 'tiles of one row have different heights: $row');
              }
            });
          }
        }
      }
    }
  });

  group('control (proves the checks can fail)', () {
    // The tile as it was before: fixed 124 px height. On a phone with a large font it overflows. If this test ever stops failing the
    // overflow check above is no longer measuring anything.
    testWidgets('the old fixed-height tile overflows at font 2.0', (tester) async {
      await pumpScreen(
        tester,
        size: const Size(360, 640),
        fontScale: 2.0,
        clamp: false,
        child: SizedBox(
          width: 160,
          child: Container(
            height: 124,
            padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 5),
            color: blue,
            child: const Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.speed, color: lime, size: 24),
                SizedBox(height: 7),
                Text('3', style: TextStyle(fontSize: 25, fontWeight: FontWeight.w800, color: Colors.white)),
                SizedBox(height: 3),
                Text('Harsh acceleration', textAlign: TextAlign.center, maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11, color: Colors.white70)),
              ],
            ),
          ),
        ),
      );
      final exception = tester.takeException();
      expect(exception, isNotNull);
      expect(exception.toString(), contains('overflowed'));
    });

    testWidgets('the new tile does not overflow in the same situation', (tester) async {
      await pumpScreen(
        tester,
        size: const Size(360, 640),
        fontScale: 2.0,
        clamp: false,
        child: SizedBox(width: 160, child: tilesFor(const ['Harsh acceleration'], large: true).first),
      );
      expectNoException(tester, 'new tile at font 2.0 without the clamp');
    });
  });
}
