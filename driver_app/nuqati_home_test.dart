import 'dart:async';
import 'package:flutter/material.dart';

/// Isolated deterministic test harness. NEVER sends simulated locations to
/// Android's location provider, the production trip DB, scoring, or backend.
class NuqatiHomeTest extends StatefulWidget {
  const NuqatiHomeTest({super.key, required this.readNativeStatus});
  final Future<Map<String, dynamic>> Function() readNativeStatus;
  @override State<NuqatiHomeTest> createState() => _NuqatiHomeTestState();
}

class _NuqatiHomeTestState extends State<NuqatiHomeTest> {
  Timer? timer;
  int elapsed = 0;
  double speed = 0;
  double distance = 0;
  int movementStart = -1;
  int stationaryStart = -1;
  bool trip = false;
  bool finished = false;
  int speeding = 0, braking = 0, acceleration = 0, cornering = 0;
  String stage = 'Ready';
  Map<String, dynamic> native = {};
  String? nativeError;
  final List<String> trace = [];

  // Every real second represents 5 seconds of a simulated trip.
  // Uses a known deterministic sequence, not real GPS fixes.
  double speedAt(int seconds) {
    if (seconds < 10) return 0;
    if (seconds < 20) return 12;
    if (seconds < 35) return 30;
    if (seconds < 45) return 85;
    if (seconds < 55) return 25;
    if (seconds < 65) return 55;
    return 0;
  }

  void log(String value) {
    trace.insert(0, '${elapsed}s · $value');
    if (trace.length > 15) trace.removeLast();
  }

  void step() {
    if (!mounted) return;
    setState(() {
      const dt = 5;
      final previous = speed;
      elapsed += dt;
      speed = speedAt(elapsed);
      if (speed >= 5) {
        stationaryStart = -1;
        if (movementStart < 0) movementStart = elapsed;
        distance += speed * dt / 3600;
        if (!trip && elapsed - movementStart >= 10 && distance >= 0.02) {
          trip = true;
          stage = 'Trip started';
          log('PASS: automatic trip start');
        }
      } else {
        movementStart = -1;
        if (trip) {
          if (stationaryStart < 0) stationaryStart = elapsed;
          if (elapsed - stationaryStart >= 120) {
            trip = false;
            finished = true;
            stage = 'Trip ended';
            log('PASS: stopped after 120s stationary');
            timer?.cancel();
          }
        }
      }
      if (trip) {
        final delta = (speed - previous) / dt;
        if (delta >= 5 && acceleration == 0) { acceleration++; log('Simulated harsh acceleration'); }
        if (delta <= -5 && braking == 0) { braking++; log('Simulated harsh braking'); }
        if (speed > 80 && speeding == 0) { speeding++; log('Simulated overspeeding'); }
        if (elapsed >= 60 && elapsed < 65 && cornering == 0) { cornering++; log('Simulated harsh cornering'); }
      }
      if (!finished) stage = trip ? 'Simulated driving' : (elapsed < 10 ? 'Waiting for movement' : 'Waiting for 120s stationary');
    });
  }

  void start() {
    timer?.cancel();
    setState(() {
      elapsed = 0; speed = 0; distance = 0; movementStart = -1;
      stationaryStart = -1; trip = false; finished = false;
      speeding = 0; braking = 0; acceleration = 0; cornering = 0;
      stage = 'Starting simulation'; trace.clear();
      log('Isolated simulator: no real trips or uploads');
    });
    timer = Timer.periodic(const Duration(seconds: 1), (_) => step());
  }

  Future<void> refreshNative() async {
    try {
      final value = await widget.readNativeStatus();
      if (mounted) setState(() { native = value; nativeError = null; });
    } catch (e) {
      if (mounted) setState(() => nativeError = e.toString());
    }
  }

  @override void initState() { super.initState(); refreshNative(); }
  @override void dispose() { timer?.cancel(); super.dispose(); }

  @override Widget build(BuildContext context) => AlertDialog(
    title: const Text('Nuqati · Home GPS test'),
    content: SizedBox(width: 450, child: SingleChildScrollView(child: Column(
      mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('SIMULATION ONLY · No GPS spoofing, driver score changes, odometer changes, or dashboard uploads.', style: TextStyle(color: Colors.deepOrange, fontWeight: FontWeight.bold)),
        const SizedBox(height: 12),
        Text('Scenario: $stage'),
        Text('Simulated time: ${elapsed}s  ·  Speed: ${speed.toStringAsFixed(0)} km/h'),
        Text('Trip: ${trip ? 'ACTIVE' : finished ? 'COMPLETED' : 'WAITING'}  ·  Distance: ${distance.toStringAsFixed(3)} km'),
        Text('Events (simulated): OS $speeding · HB $braking · HA $acceleration · HC $cornering'),
        const SizedBox(height: 8),
        ElevatedButton(onPressed: start, child: const Text('Run ~40-second simulation')),
        const Divider(),
        const Text('REAL native GPS status (read-only)', style: TextStyle(fontWeight: FontWeight.bold)),
        if (nativeError != null) Text(nativeError!, style: const TextStyle(color: Colors.red)),
        Text('GPS listener: ${native['gps_state'] ?? 'unknown'}'),
        Text('Provider: ${native['gps_provider_mode'] ?? 'unknown'}  ·  Callbacks: ${native['gps_callback_count'] ?? 0}'),
        Text('Callback accuracy: ${native['last_callback_accuracy_m'] ?? '?'} m'),
        Text('Saved trip fixes: ${native['fixes'] ?? '?'}  ·  Native active trip: ${native['active_trip_id'] ?? 'none'}'),
        Text('Last native speed: ${native['last_speed_kmh'] ?? '?'} km/h'),
        Text('Last GPS callback: ${native['last_gps_callback_ms'] ?? '?'} ms (Unix)'),
        Text('Last accepted fix: ${native['last_accepted_fix_ms'] ?? '?'} ms (Unix)'),
        TextButton(onPressed: refreshNative, child: const Text('Refresh real native status')),
        const Divider(),
        const Text('Simulation trace', style: TextStyle(fontWeight: FontWeight.bold)),
        ...trace.map((e) => Text(e, style: const TextStyle(fontSize: 11))),
      ],
    ))),
    actions: [TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Close'))],
  );
}
