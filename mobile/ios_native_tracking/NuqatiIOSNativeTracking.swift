// iOS companion to Android's NuqatiNativeTrackingService.
// CoreLocation owns location sampling in the background; SQLite retains native
// trips/fixes/events until Flutter imports them using durable ID cursors.
// iOS cannot relaunch a force-quit application after reboot; app relaunch and
// operating-system background-location delivery are controlled by iOS.
import Foundation
import Flutter
import CoreLocation
import UserNotifications
import SQLite3

final class NuqatiIOSNativeTracking: NSObject, CLLocationManagerDelegate {
    static let shared = NuqatiIOSNativeTracking()
    private let location = CLLocationManager()
    private let prefs = UserDefaults.standard
    private var channel: FlutterMethodChannel?
    private var database: OpaquePointer?
    private var lastValid: CLLocation?
    private var movementSince: Date?
    private var movementSamples = 0
    private var movementAnchor: CLLocation?
    private var movementDistance = 0.0
    private var confirmedMovingSegments = 0
    private var stationarySince: Date?
    private var lastAcceleration = 0.0
    private var accelerationValid = false
    private var lastAccelerationAt: Date?
    private var lastCallback: Date?
    private var lastAccepted: Date?
    private var lastSpeedKmh = 0.0
    private var lastEventTimes: [String: Date] = [:]
    private var speedingStarted = false
    private var aggressiveStarted = false
    private var lastGpsState = "waiting"
    private var distance = 0.0
    private let endDelay: TimeInterval = 240

    private var driverId: Int { prefs.integer(forKey: "nuqati_driver_id") }
    private var companyId: Int { prefs.integer(forKey: "nuqati_company_id") }
    private var vehicleId: Int { prefs.integer(forKey: "nuqati_vehicle_id") }
    private var activeTrip: Int { prefs.integer(forKey: "nuqati_active_trip_id") }
    private var privacy: Bool { prefs.bool(forKey: "nuqati_privacy") }

    private override init() {
        super.init()
        location.delegate = self
        location.activityType = .automotiveNavigation
        location.desiredAccuracy = kCLLocationAccuracyBest
        location.distanceFilter = kCLDistanceFilterNone
        location.pausesLocationUpdatesAutomatically = false
        openStore()
        if activeTrip != 0 {
            distance = (query("SELECT distance_m FROM trips WHERE id=?", [activeTrip]).first?["distance_m"] as? Double) ?? 0
        }
    }

    func install(messenger: FlutterBinaryMessenger) {
        channel = FlutterMethodChannel(name: "nuqati/native_tracking", binaryMessenger: messenger)
        channel?.setMethodCallHandler { [weak self] call, reply in
            guard let self = self else { reply(FlutterError(code: "NATIVE_UNAVAILABLE", message: nil, details: nil)); return }
            self.onMethod(call, reply: reply)
        }
        // Restarts only after the app itself launches or iOS delivers a permitted
        // location wakeup. Deliberate force-quit/phone reboot cannot be bypassed.
        if driverId > 0 && companyId > 0 && vehicleId > 0 && !privacy { startTracking() }
    }

    private func onMethod(_ call: FlutterMethodCall, reply: @escaping FlutterResult) {
        let args = call.arguments as? [String: Any] ?? [:]
        switch call.method {
        case "setRecordingOwner":
            guard let d = args["driver_id"] as? Int, let c = args["company_id"] as? Int,
                  let v = args["vehicle_id"] as? Int, d > 0, c > 0, v > 0 else {
                reply(FlutterError(code: "OWNER_REQUIRED", message: "Assigned driver and vehicle required", details: nil)); return
            }
            if activeTrip != 0 && (driverId != d || companyId != c || vehicleId != v) {
                reply(FlutterError(code: "ACTIVE_TRIP", message: "Cannot change driver during a trip", details: nil)); return
            }
            prefs.set(d, forKey: "nuqati_driver_id"); prefs.set(c, forKey: "nuqati_company_id"); prefs.set(v, forKey: "nuqati_vehicle_id")
            reply(true)
        case "clearRecordingOwner":
            if activeTrip != 0 { reply(FlutterError(code: "ACTIVE_TRIP", message: "Finish active trip first", details: nil)); return }
            location.stopUpdatingLocation()
            for key in ["nuqati_driver_id", "nuqati_company_id", "nuqati_vehicle_id"] { prefs.removeObject(forKey: key) }
            reply(true)
        case "setPolicy":
            guard let raw = args["policy"] as? String,
                  let data = raw.data(using: .utf8),
                  let dictionary = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
                  dictionary["speeding_kmh"] is NSNumber,
                  dictionary["harsh_accel_ms2"] is NSNumber,
                  dictionary["harsh_brake_ms2"] is NSNumber,
                  let ownerCompany = dictionary["company_id"] as? Int,
                  ownerCompany == companyId else {
                reply(FlutterError(code: "BAD_POLICY", message: "Invalid or unrelated company policy", details: nil)); return
            }
            prefs.set(raw, forKey: "nuqati_policy")
            reply(["saved": true, "changed": true, "version": dictionary["policy_version"] ?? ""])
        case "clearPolicy": prefs.removeObject(forKey: "nuqati_policy"); reply(true)
        case "setAlertsEnabled": prefs.set(args["enabled"] as? Bool ?? true, forKey: "nuqati_alerts"); reply(true)
        case "setLanguage": prefs.set(args["language"] as? String ?? "en", forKey: "nuqati_language"); reply(true)
        case "isPowerSaveMode": reply(ProcessInfo.processInfo.isLowPowerModeEnabled)
        case "openPowerSaveSettings": reply(false) // iOS has no app-accessible Low Power Mode settings deep link.
        case "start":
            guard !privacy, driverId > 0, vehicleId > 0 else {
                reply(FlutterError(code: "TRACKING_UNAVAILABLE", message: "Sign in and disable Privacy Mode first", details: nil)); return
            }
            startTracking(); reply(true)
        case "stop": location.stopUpdatingLocation(); reply(true)
        case "authorizePrivacy": prefs.set(true, forKey: "nuqati_privacy_approved"); reply(true)
        case "privacyOn":
            guard prefs.bool(forKey: "nuqati_privacy_approved") else {
                reply(FlutterError(code: "PRIVACY_NOT_APPROVED", message: "Server privacy approval required", details: nil)); return
            }
            guard activeTrip == 0 else {
                reply(FlutterError(code: "ACTIVE_TRIP", message: "Cannot enable Privacy Mode during a trip", details: nil)); return
            }
            prefs.set(true, forKey: "nuqati_privacy"); location.stopUpdatingLocation(); reply(true)
        case "privacyOff":
            prefs.set(false, forKey: "nuqati_privacy")
            prefs.set(false, forKey: "nuqati_privacy_approved")
            startTracking(); reply(true)
        case "status": reply(status())
        case "eventCounts":
            let id = args["trip_id"] as? Int ?? 0
            reply(query("SELECT kind AS event_type,COUNT(*) AS total FROM events WHERE trip_id=? GROUP BY kind", [id]))
        case "getRecords":
            let fixCursor = max(0, args["after_fix_id"] as? Int ?? 0)
            let eventCursor = max(0, args["after_event_id"] as? Int ?? 0)
            reply([
                "trips": query("SELECT * FROM trips ORDER BY id DESC LIMIT 2000"),
                "fixes": query("SELECT * FROM fixes WHERE id>? ORDER BY id LIMIT 300", [fixCursor]),
                "events": query("SELECT * FROM events WHERE id>? ORDER BY id LIMIT 300", [eventCursor])
            ])
        default: reply(FlutterMethodNotImplemented)
        }
    }

    private func startTracking() {
        guard !privacy && driverId > 0 && companyId > 0 && vehicleId > 0 else { return }
        // CLLocationManager requires authorization and background location mode.
        location.requestAlwaysAuthorization()
        if CLLocationManager.locationServicesEnabled() {
            location.allowsBackgroundLocationUpdates = true
            location.showsBackgroundLocationIndicator = true
            location.startUpdatingLocation()
        }
    }

    @available(iOS 14.0, *)
    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        if manager.authorizationStatus == .authorizedAlways && !privacy && driverId > 0 { startTracking() }
    }

    func locationManager(_ manager: CLLocationManager, didChangeAuthorization status: CLAuthorizationStatus) {
        if status == .authorizedAlways && !privacy && driverId > 0 { startTracking() }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        lastGpsState = "location_error"
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        for fix in locations { process(fix) }
    }

    private func process(_ fix: CLLocation) {
        lastCallback = Date()
        guard !privacy && driverId > 0 && companyId > 0 && vehicleId > 0 else { return }
        let age = abs(fix.timestamp.timeIntervalSinceNow)
        guard age <= 12, fix.horizontalAccuracy >= 0, fix.horizontalAccuracy <= 30,
              fix.speed >= 0, fix.speed <= 75 else {
            lastGpsState = "rejected_accuracy_or_spike"; return
        }
        if let prev = lastValid {
            let dt = fix.timestamp.timeIntervalSince(prev.timestamp)
            if dt <= 0 { return }
            let displacement = fix.distance(from: prev)
            if displacement > max(40, fix.speed * dt * 2.0 + 60) {
                lastGpsState = "rejected_displacement_spike"; return
            }
        }
        lastGpsState = "valid"
        lastAccepted = Date(); lastSpeedKmh = fix.speed * 3.6
        let speed = lastSpeedKmh
        if activeTrip == 0 {
            // Require sustained speed + coherent displacement, never GPS speed
            // alone (which can spike when stationary in a building).
            if speed >= 10 {
                if movementSince == nil {
                    movementSince = fix.timestamp; movementSamples = 0
                    movementAnchor = fix; movementDistance = 0; confirmedMovingSegments = 0
                }
                movementSamples += 1
                if let previous = lastValid {
                    let dt = fix.timestamp.timeIntervalSince(previous.timestamp)
                    let step = fix.distance(from: previous)
                    if dt > 0 && step >= min(7, max(1.5, 1.4 * dt)) && step <= fix.speed * dt * 1.8 + 20 {
                        movementDistance += step
                        confirmedMovingSegments += 1
                    }
                }
                let net = movementAnchor.map { fix.distance(from: $0) } ?? 0
                if movementSamples >= 3 && confirmedMovingSegments >= 2 &&
                   fix.timestamp.timeIntervalSince(movementSince!) >= 5 &&
                   net >= 12 && movementDistance <= net * 1.8 + 12 {
                    beginTrip(at: fix.timestamp)
                }
            } else { resetMovementCandidate() }
        }
        let tid = activeTrip
        if tid != 0 {
            let timestampMs = Int(fix.timestamp.timeIntervalSince1970 * 1000)
            var acceptedMeters = 0.0
            var acceleration: Double? = nil
            if let previous = lastValid {
                let dt = fix.timestamp.timeIntervalSince(previous.timestamp)
                if dt >= 1 && dt <= 15 {
                    let meters = fix.distance(from: previous)
                    if meters > 1 && meters < max(30, fix.speed * dt * 1.8 + 35) && fix.speed >= 1.5 {
                        acceptedMeters = meters
                    }
                    let measured = (fix.speed - previous.speed) / dt
                    if measured.isFinite && abs(measured) <= 8 { acceleration = measured }
                    evaluateEvents(trip: tid, fix: fix, previous: previous, dt: dt, acceleration: acceleration)
                }
            }
            accelerationValid = acceleration != nil
            lastAcceleration = acceleration ?? 0
            lastAccelerationAt = fix.timestamp
            distance += acceptedMeters
            execute("INSERT INTO fixes(trip_id,at_ms,lat,lon,accuracy,speed_ms,acceleration_ms2,gps_age_seconds) VALUES(?,?,?,?,?,?,?,?)",
                    [tid, timestampMs, fix.coordinate.latitude, fix.coordinate.longitude, fix.horizontalAccuracy, fix.speed, acceleration ?? 0, age])
            execute("UPDATE trips SET distance_m=? WHERE id=?", [distance, tid])
            if speed < 5 {
                if stationarySince == nil { stationarySince = fix.timestamp }
                if fix.timestamp.timeIntervalSince(stationarySince!) >= endDelay { endTrip(at: fix.timestamp) }
            } else { stationarySince = nil }
        }
        lastValid = fix
    }

    private func resetMovementCandidate() {
        movementSince = nil; movementSamples = 0; movementAnchor = nil
        movementDistance = 0; confirmedMovingSegments = 0
    }

    private func beginTrip(at time: Date) {
        execute("INSERT INTO trips(driver_id,company_id,vehicle_id,started_ms,ended_ms,distance_m) VALUES(?,?,?,?,NULL,0)",
                [driverId,companyId,vehicleId,Int(time.timeIntervalSince1970*1000)])
        let id = Int(sqlite3_last_insert_rowid(database))
        guard id > 0 else { return }
        prefs.set(id, forKey: "nuqati_active_trip_id")
        distance = 0; stationarySince = nil; resetMovementCandidate()
        speedingStarted = false; aggressiveStarted = false
    }

    private func endTrip(at time: Date) {
        let id = activeTrip
        if id == 0 { return }
        execute("UPDATE trips SET ended_ms=?,distance_m=? WHERE id=?",
                [Int(time.timeIntervalSince1970 * 1000),distance,id])
        prefs.removeObject(forKey: "nuqati_active_trip_id")
        stationarySince = nil; lastValid = nil; resetMovementCandidate()
        speedingStarted = false; aggressiveStarted = false
    }

    private func policy() -> [String: Any] {
        guard let raw = prefs.string(forKey: "nuqati_policy")?.data(using: .utf8),
              let p = (try? JSONSerialization.jsonObject(with: raw)) as? [String: Any] else { return [:] }
        return p
    }

    private func threshold(_ key: String, _ fallback: Double, from p: [String: Any]) -> Double {
        guard let value = p[key] as? NSNumber, value.doubleValue > 0, value.doubleValue.isFinite else { return fallback }
        return value.doubleValue
    }
    private func enabled(_ key: String, from p: [String: Any]) -> Bool {
        let toggles = p["enabled"] as? [String: Any] ?? [:]
        return toggles[key] as? Bool != false
    }

    private func evaluateEvents(trip: Int, fix: CLLocation, previous: CLLocation, dt: Double, acceleration: Double?) {
        let p = policy(), speed = fix.speed * 3.6
        let limit = threshold("speeding_kmh",100,from:p)
        let margin = threshold("excessive_speed_margin_kmh",20,from:p)
        if speed > limit && enabled("speeding",from:p) {
            if !speedingStarted {
                speedingStarted = true
                emit("speeding", value:speed,trip:trip,at:fix.timestamp)
            }
            if speed >= limit + margin && !aggressiveStarted && enabled("excessive_speeding",from:p) {
                aggressiveStarted = true
                emit("excessive_speeding",value:speed,trip:trip,at:fix.timestamp)
            }
        } else if speed < limit - 3 { speedingStarted = false; aggressiveStarted = false }
        if let acceleration = acceleration {
            let brake = threshold("harsh_brake_ms2",3,from:p)
            let accelerate = threshold("harsh_accel_ms2",3,from:p)
            if acceleration <= -brake && enabled("harsh_braking",from:p) {
                let aggressive = abs(acceleration) >= threshold("aggressive_brake_ms2",brake*1.5,from:p) && enabled("excessive_harsh_braking",from:p)
                emit(aggressive ? "excessive_harsh_braking" : "harsh_braking",value:abs(acceleration),trip:trip,at:fix.timestamp)
            } else if acceleration >= accelerate && enabled("harsh_acceleration",from:p) {
                let aggressive = acceleration >= threshold("aggressive_accel_ms2",accelerate*1.5,from:p) && enabled("excessive_harsh_acceleration",from:p)
                emit(aggressive ? "excessive_harsh_acceleration" : "harsh_acceleration",value:acceleration,trip:trip,at:fix.timestamp)
            }
        }
        let phase4 = p["phase4"] as? [String: Any] ?? [:]
        let minSpeed = threshold("min_cornering_speed_kmh",20,from:phase4)
        let corner = threshold("cornering_ms2",3.5,from:phase4)
        if speed >= minSpeed && dt >= 1 && dt <= 8 && fix.course >= 0 && previous.course >= 0 && enabled("harsh_cornering",from:p) {
            let headingDifference = abs((fix.course - previous.course + 540).truncatingRemainder(dividingBy:360)-180)
            let degreesPerSecond = headingDifference / dt
            let lateral = fix.speed * degreesPerSecond * Double.pi / 180
            if degreesPerSecond >= 18 && lateral >= corner {
                emit("harsh_cornering",value:lateral,trip:trip,at:fix.timestamp)
            }
        }
    }

    private func emit(_ kind: String, value: Double, trip: Int, at: Date) {
        if let last = lastEventTimes[kind], at.timeIntervalSince(last) < 8 { return }
        lastEventTimes[kind] = at
        execute("INSERT INTO events(trip_id,kind,value,at_ms) VALUES(?,?,?,?)",
                [trip,kind,value,Int(at.timeIntervalSince1970*1000)])
        guard prefs.object(forKey:"nuqati_alerts") as? Bool != false else { return }
        let titles: [String: [String: String]] = [
            "speeding": ["en":"Speeding detected", "ar":"تم رصد تجاوز السرعة", "ur":"رفتار زیادہ ہے"],
            "harsh_braking": ["en":"Harsh braking", "ar":"فرملة حادة", "ur":"اچانک بریک"],
            "harsh_acceleration": ["en":"Harsh acceleration", "ar":"تسارع حاد", "ur":"تیز ایکسلریشن"],
            "harsh_cornering": ["en":"Harsh cornering", "ar":"انعطاف حاد", "ur":"تیز موڑ"]
        ]
        let language = prefs.string(forKey:"nuqati_language") ?? "en"
        let content = UNMutableNotificationContent()
        content.title = "Nuqati"
        content.body = titles[kind]?[language] ?? kind.replacingOccurrences(of:"_",with:" ")
        content.sound = .default
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier:"nuqati-\(trip)-\(kind)-\(Int(at.timeIntervalSince1970))",content:content,trigger:nil))
    }

    private func status() -> [String: Any] {
        let fmt: (Date?) -> Int = { value in value.map { Int($0.timeIntervalSince1970 * 1000) } ?? 0 }
        return [
            "active_trip_id": activeTrip == 0 ? NSNull() : activeTrip as Any,
            "last_accepted_fix_ms": fmt(lastAccepted), "last_gps_callback_ms": fmt(lastCallback),
            "last_speed_kmh": lastSpeedKmh, "last_acceleration_ms2": lastAcceleration,
            "last_acceleration_valid": accelerationValid, "last_acceleration_at_ms":fmt(lastAccelerationAt),
            "stationary_since_ms":fmt(stationarySince), "trip_end_delay_s":Int(endDelay),
            "gps_state":lastGpsState,"distance_m":distance
        ]
    }

    private func openStore() {
        guard let dir = FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask).first else { return }
        try? FileManager.default.createDirectory(at:dir,withIntermediateDirectories:true)
        if sqlite3_open(dir.appendingPathComponent("nuqati_ios_tracking.sqlite").path,&database) != SQLITE_OK { database = nil; return }
        execute("PRAGMA journal_mode=WAL")
        execute("CREATE TABLE IF NOT EXISTS trips(id INTEGER PRIMARY KEY AUTOINCREMENT,driver_id INTEGER,company_id INTEGER,vehicle_id INTEGER,started_ms INTEGER NOT NULL,ended_ms INTEGER,distance_m REAL DEFAULT 0)")
        execute("CREATE TABLE IF NOT EXISTS fixes(id INTEGER PRIMARY KEY AUTOINCREMENT,trip_id INTEGER NOT NULL,at_ms INTEGER,lat REAL,lon REAL,accuracy REAL,speed_ms REAL,acceleration_ms2 REAL,gps_age_seconds REAL)")
        execute("CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,trip_id INTEGER NOT NULL,kind TEXT,value REAL,at_ms INTEGER)")
    }

    private func bind(_ values:[Any],to stmt:OpaquePointer?) {
        for (index,value) in values.enumerated() {
            let column = Int32(index + 1)
            if let n = value as? Int { sqlite3_bind_int64(stmt,column,sqlite3_int64(n)) }
            else if let n = value as? Double { sqlite3_bind_double(stmt,column,n) }
            else if let string = value as? String {
                let transient = unsafeBitCast(-1,to:sqlite3_destructor_type.self)
                _ = string.withCString { sqlite3_bind_text(stmt,column,$0,-1,transient) }
            } else { sqlite3_bind_null(stmt,column) }
        }
    }
    private func execute(_ sql:String, _ args:[Any] = []) {
        guard let db = database else { return }
        var stmt:OpaquePointer?
        guard sqlite3_prepare_v2(db,sql,-1,&stmt,nil) == SQLITE_OK else { return }
        defer { sqlite3_finalize(stmt) }
        bind(args,to:stmt)
        _ = sqlite3_step(stmt)
    }
    private func query(_ sql:String, _ args:[Any] = []) -> [[String: Any]] {
        guard let db = database else { return [] }
        var stmt:OpaquePointer?
        guard sqlite3_prepare_v2(db,sql,-1,&stmt,nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }
        bind(args,to:stmt)
        var rows:[[String:Any]]=[]
        while sqlite3_step(stmt) == SQLITE_ROW {
            var row:[String:Any]=[:]
            for i in 0..<sqlite3_column_count(stmt) {
                let key=String(cString:sqlite3_column_name(stmt,i))
                switch sqlite3_column_type(stmt,i) {
                case SQLITE_INTEGER:row[key]=Int(sqlite3_column_int64(stmt,i))
                case SQLITE_FLOAT:row[key]=sqlite3_column_double(stmt,i)
                case SQLITE_TEXT:row[key]=String(cString:sqlite3_column_text(stmt,i))
                default:row[key]=NSNull()
                }
            }
            rows.append(row)
        }
        return rows
    }
}
