# GPK Szemud - faktury za wodę (add-on HA)

Czyta maile od `faktury@gpkszemud.pl` z Gmaila (IMAP), parsuje PDF-y (`pdftotext`), zapisuje do SQLite
(`/data/invoices.db`), wystawia sensory przez MQTT discovery i importuje historię do statystyk długoterminowych
(`gpk_water:cost_total`, `cost_home`, `cost_garden`, `usage_home`, `usage_garden`).

## Instalacja
1. Skopiuj folder do `/addons/gpk_water` (Samba / SSH), w HA: Ustawienia → Dodatki → Sklep → ⋮ → Sprawdź aktualizacje → "Lokalne dodatki".
2. Gmail: włącz weryfikację dwuetapową → Konto Google → Bezpieczeństwo → Hasła aplikacji → wygeneruj hasło.
3. Opcje add-onu: `gmail_user`, `gmail_app_password`, dane MQTT (dla add-onu Mosquitto zwykle user/hasło z HA).
4. Start. Przy pierwszym uruchomieniu przejdzie po wszystkich mailach od 2020 r.

## Rozdzielenie dom / ogród
Pozycja "Woda" o ilości równej zużyciu podlicznika to ogród (bez ścieków); reszta wody to dom. Ścieki = główny - podlicznik.

## Znane ograniczenia
- Parser znany z 2 układów (2020, 2026). Maile, których PDF się nie sparsuje, trafiają do `seen_mail` ze statusem `failed`
  i są wypisane w logu - wystarczy dosłać taki PDF, żeby dopisać układ.
- Punkt statystyk = godzina 12:00 UTC w dniu wystawienia faktury (jedna wartość na fakturę, nie rozkład dzienny).
