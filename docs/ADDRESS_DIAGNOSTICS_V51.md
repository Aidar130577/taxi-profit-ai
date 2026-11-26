# v51: address matching and the "Уточните адрес" status

Field result for v50: four of four orders showed no price ("Уточните адрес"). v50 accepted only an exact normalised
key in the OSM index or a single geocoder record whose first two comma segments equalled the order text.

v51 keeps the safety rule (a different street or a different house is never accepted) but compares parsed street
tokens and house numbers: full street names in OSM ("Ахмета Байтурсынова" vs "Байтурсынова"), case endings
("Арыковой" vs "Арыкова"), Latin/Cyrillic house letters ("51B" vs "51В"), "блок/корпус" notations, venue and
microdistrict segments, geocoder lines without commas ("улица Шевченко 118, Алматы 050000"). Several geocoder
records of one building are accepted; records more than about 300 m apart are ambiguous. A house that differs only by
a suffix ("17" vs "17/1") is accepted as the same plot; a different number never is.

When an address is still refused the plaque shows a reason code per endpoint, never an address or coordinates:
`Уточните адрес А0 Б+` means point A failed with code 0, point B was found (`+`).

| Code | Meaning |
|---|---|
| + | found |
| 0 | nothing in the offline base and the geocoder returned no records |
| 1 | the geocoder returned records, but none is this street and house |
| 2 | several different places match (ambiguous) |
| 3 | no geocoder service on the phone |
| 4 | geocoder error (network or service) |
| ! | other error |

Checks: `core-tests/RouteQualityCheck.kt` (`addressMatcherChecks`), run in CI with the other pure-JVM checks.
