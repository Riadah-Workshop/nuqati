import 'package:flutter/material.dart';

// Layout pieces that follow the phone they run on.
//
// Android phones differ in width (280 to 600+ dp), in density and in the user's font-size and display-size settings. Nothing here has
// a fixed height or a fixed pixel size: the ring is sized from the width it is given, text inside it shrinks to fit the circle, and
// tiles in a row always share the height of the tallest one, so a long label (Arabic, Urdu, a large font) makes the row taller instead
// of overflowing. driver_app/test/adaptive_layout_test.dart renders these on many screen sizes and font scales in CI.

/// Largest and smallest system font scale the driver app follows. Beyond these a phone set to "largest font" breaks every screen and a
/// driver glancing at the phone gains nothing. Applied once, at the root, by [nuqatiClampTextScale].
const double nuqatiMaxTextScale = 1.35;
const double nuqatiMinTextScale = 0.85;

/// `MaterialApp.builder`: keeps the system font scale between [nuqatiMinTextScale] and [nuqatiMaxTextScale].
Widget nuqatiClampTextScale(BuildContext context, Widget? child) {
  final media = MediaQuery.of(context);
  return MediaQuery(
    data: media.copyWith(
      textScaler: media.textScaler.clamp(minScaleFactor: nuqatiMinTextScale, maxScaleFactor: nuqatiMaxTextScale),
    ),
    child: child ?? const SizedBox.shrink(),
  );
}

/// Ring diameter for the width available: about half of it, never smaller than 132 or larger than 220 (and never wider than the space).
double nuqatiRingDiameter(double availableWidth) {
  final wanted = (availableWidth * 0.5).clamp(132.0, 220.0).toDouble();
  return wanted > availableWidth ? availableWidth : wanted;
}

/// How many equal columns fit: each tile at least [minTileWidth] wide, at most [maxColumns], never more columns than tiles.
int nuqatiGridColumns({
  required double width,
  required int count,
  required double minTileWidth,
  double spacing = 8,
  int maxColumns = 5,
}) {
  if (count <= 1) return 1;
  var columns = ((width + spacing) / (minTileWidth + spacing)).floor();
  if (columns > maxColumns) columns = maxColumns;
  if (columns > count) columns = count;
  return columns < 1 ? 1 : columns;
}

/// The driver's score as a ring with the points inside and a word (GREEN / AMBER / RED) below. The ring follows the width it is given.
/// Whatever is written inside is scaled down, if needed, to stay inside the circle, whatever the phone's font size.
class NuqatiScoreRing extends StatelessWidget {
  const NuqatiScoreRing({
    super.key,
    required this.value,
    required this.label,
    required this.progress,
    required this.color,
    this.trackColor = Colors.white12,
  });

  final String value;
  final String label;
  final double progress;
  final Color color;
  final Color trackColor;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, constraints) {
      final available = constraints.hasBoundedWidth ? constraints.maxWidth : 220.0;
      final diameter = nuqatiRingDiameter(available);
      final stroke = diameter * 0.078;
      final inner = diameter - 2 * stroke;
      // A rectangle whose corners stay inside the free circle: (0.78 w)^2 + (0.58 w)^2 < w^2.
      final boxWidth = inner * 0.78;
      final boxHeight = inner * 0.58;
      return Center(
        child: SizedBox(
          width: diameter,
          height: diameter,
          child: Stack(
            alignment: Alignment.center,
            children: [
              SizedBox.expand(
                child: CircularProgressIndicator(
                  value: progress.clamp(0.0, 1.0).toDouble(),
                  strokeWidth: stroke,
                  backgroundColor: trackColor,
                  valueColor: AlwaysStoppedAnimation<Color>(color),
                  strokeCap: StrokeCap.round,
                ),
              ),
              SizedBox(
                width: boxWidth,
                height: boxHeight,
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      // Sized from the ring, not from the system font size: the ring itself already follows the screen.
                      Text(
                        value,
                        maxLines: 1,
                        textScaler: TextScaler.noScaling,
                        style: TextStyle(color: color, fontSize: diameter * 0.38, fontWeight: FontWeight.w900, height: 1),
                      ),
                      SizedBox(height: diameter * 0.025),
                      Text(
                        label,
                        maxLines: 1,
                        textScaler: TextScaler.noScaling,
                        style: TextStyle(color: color, fontSize: (diameter * 0.08).clamp(11.0, 16.0).toDouble(), fontWeight: FontWeight.bold),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      );
    });
  }
}

/// An icon, a number and a word below it. No fixed height: [large] only sets a minimum.
class NuqatiMetricTile extends StatelessWidget {
  const NuqatiMetricTile({
    super.key,
    required this.label,
    required this.value,
    required this.icon,
    required this.accent,
    required this.fill,
    this.large = false,
    this.border,
  });

  final String label;
  final String value;
  final IconData icon;
  final Color accent;
  final Color fill;
  final bool large;
  final Color? border;

  @override
  Widget build(BuildContext context) {
    return Container(
      alignment: Alignment.center,
      constraints: BoxConstraints(minHeight: large ? 112 : 0),
      padding: EdgeInsets.symmetric(vertical: large ? 12 : 8, horizontal: large ? 6 : 4),
      decoration: BoxDecoration(
        color: fill,
        borderRadius: BorderRadius.circular(large ? 18 : 12),
        border: border == null ? null : Border.all(color: border!),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, color: accent, size: large ? 24 : 18),
          SizedBox(height: large ? 7 : 2),
          Text(
            value,
            maxLines: 1,
            style: TextStyle(color: Colors.white, fontSize: large ? 25 : 20, fontWeight: large ? FontWeight.w800 : FontWeight.bold),
          ),
          SizedBox(height: large ? 3 : 0),
          Text(
            label,
            textAlign: TextAlign.center,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(color: Colors.white70, fontSize: large ? 11 : 10),
          ),
        ],
      ),
    );
  }
}

/// Lays the tiles out in rows of equal columns. Every row is as tall as its tallest tile and all tiles in it share that height. The
/// number of columns follows the width and the font size, so a larger font gives fewer, wider tiles.
class NuqatiEqualGrid extends StatelessWidget {
  const NuqatiEqualGrid({
    super.key,
    required this.children,
    this.minTileWidth = 92,
    this.spacing = 8,
    this.maxColumns = 5,
  });

  final List<Widget> children;
  final double minTileWidth;
  final double spacing;
  final int maxColumns;

  @override
  Widget build(BuildContext context) {
    if (children.isEmpty) return const SizedBox.shrink();
    final fontScale = MediaQuery.textScalerOf(context).scale(1.0);
    return LayoutBuilder(builder: (context, constraints) {
      final width = constraints.hasBoundedWidth ? constraints.maxWidth : 320.0;
      final columns = nuqatiGridColumns(
        width: width,
        count: children.length,
        minTileWidth: minTileWidth * (fontScale < 1 ? 1.0 : fontScale),
        spacing: spacing,
        maxColumns: maxColumns,
      );
      final rows = <Widget>[];
      for (var start = 0; start < children.length; start += columns) {
        final cells = <Widget>[];
        for (var i = 0; i < columns; i++) {
          if (i > 0) cells.add(SizedBox(width: spacing));
          final index = start + i;
          cells.add(Expanded(child: index < children.length ? children[index] : const SizedBox.shrink()));
        }
        if (rows.isNotEmpty) rows.add(SizedBox(height: spacing));
        rows.add(IntrinsicHeight(child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: cells)));
      }
      return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: rows);
    });
  }
}
