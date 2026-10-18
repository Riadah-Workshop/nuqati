# Nuqati v2 — simplified product scope

## Goal
Safer driving through daily scores and weekly challenges, with RAG monthly reporting and independent mileage-based service reminders. No workshop integration and no license-plate or odometer photo/OCR flow. A driver normally has a primary vehicle; manual vehicle selection is an optional fallback if they change cars. Odometer can be estimated from valid GPS trip distances and manually checked/corrected under an audited workflow in a later release. Estimates must be labeled as such.

## Driver app — to implement and test on devices
- Explicit trip tracking consent and clear tracking status, robust GPS filtering and background permissions.
- Record trips, distance, speeding and harsh acceleration/braking with configurable thresholds and severity; avoid double counting braking/deceleration.
- Daily 0–100 score, Green/Amber/Red, zero-event challenge, next-morning encouragement, weekly and monthly summaries. No trips = no score, not 100. Normalize event comparisons by distance and review GPS uncertainty.
- Safe non-distracting alerts; never reward avoidance of necessary braking.
- Show vehicle-specific service reminders and allow odometer verification.

## Manager — to implement
Driver/trip/route/violation review, site/department filtering, monthly RAG, PDF/Excel reports and service reminders.

## Admin — to implement
Editable thresholds, severity, scoring and effective dates; vehicle-specific service intervals and warning distances; role-based access, tenant isolation, retention and audit trails.

## Included in this updated staging starter
Basic company/driver/vehicle CRUD; manual or explicitly labeled GPS-estimate odometer readings; independent per-vehicle engine oil, spark plug and transmission oil schedule CRUD with due/near-due status; dashboard maintenance tab. No OCR, plate capture or WRShah integration. No production GPS, notifications, scoring or authentication yet.

## Default example intervals, NOT universal vehicle specifications
Engine oil 5,000 km; spark plugs 60,000 km; transmission oil 80,000 km. The admin sets the actual interval per vehicle and records last service odometer. Due = last service + interval.
