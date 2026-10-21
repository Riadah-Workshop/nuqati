# Vehicle registration update

Adds **make and model**, **model year**, and **initial odometer in km** to the existing Add Vehicle form, alongside company and plate number. The initial odometer is also recorded as a MANUAL odometer history entry, including zero.

The existing backend Vehicle schema and database already support these fields; no database migration is required. Existing vehicles are unchanged.

Deploy the entire updated source on the existing GitHub main branch using your normal Coolify deployment. Do not remove your PostgreSQL volume or change secrets. This update does not require rebuilding the Android APK.

Test: create a test vehicle with year 2024 and odometer 85000, confirm the year appears in Vehicles and the initial reading appears in Odometer history.
