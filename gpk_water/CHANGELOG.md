# Changelog

## 0.4.0
- Zakładka „Odczyty": automatyczna miesięczna wysyłka stanów liczników do GPK (odporna na restarty i brak sieci, ponawianie, ochrona przed dublem, kontrola błędnych odczytów, powiadomienia).
- Panel Energia: cztery serie dzienne (zużycie i koszt, dom i ogród) - historia z faktur od 2020, dalej z wodomierzy.
- Połączony kafelek cen.

## 0.3.3
- Zakładka Liczniki: wybór zakresu (7 dni, 30 dni, ten miesiąc, poprzedni, 90 dni, rok, wszystko) i grupowania (dni, tygodnie, miesiące) oraz podsumowanie zakresu.

## 0.3.2
- Logo i ikona dodatku w sklepie HA, ten changelog.

## 0.3.1
- Połączenie z API HA: token Supervisora jest szukany także w pliku s6, a panel pokazuje dokładny powód błędu.

## 0.3.0
- Nowa zakładka **Liczniki**: wybór wodomierzy z HA (np. ESPHome), dzienne zużycie ze statystyk.
- Szacunek kosztu od ostatniej faktury (dom/ogród, abonament proporcjonalnie) i szacunek następnej faktury.
- Kontrola dokładności: licznik w HA vs odczyt gminy za okres każdej faktury.
- Nowe sensory `est_*` publikowane przez MQTT co 15 minut.

## 0.2.4
- Kafelki Przeglądu w kolorach tematów, z ikonami; klikalne (faktura, ceny, zużycie, koszt).
- Klik w słupek wykresu otwiera fakturę, klik w rok filtruje faktury. Mniejszy nagłówek.

## 0.2.3
- Folder nieodczytanych PDF-ów sam się czyści po udanym odczycie (i z dokumentów niebędących fakturami).

## 0.2.2
- Kompaktowy Przegląd: 3 wykresy (koszt, zużycie, ceny) i tabela rok po roku. Usunięte trendy i zakładka Wykresy.

## 0.2.1
- Usunięto „Do zapłaty” (status płatności nie jest znany) wraz z sensorem `last_payable`.

## 0.2.0
- Panel w pasku bocznym: KPI, wykresy z filtrami, lista faktur (szczegóły, PDF, CSV), encje HA, status.
- Zapis PDF-ów faktur, odczyt prawdziwych encji z rejestru HA, uprawnienie `homeassistant_api`.
- Usunięty wycofany parametr `object_id` z MQTT discovery.

## 0.1.6
- Parser: liczby i daty ze spacjami w PDF (`1 19`, `2022-1 1-02`), znaczniki `(radiowy)`/`(odbiorcy)`; dokumenty niebędące fakturami za wodę są pomijane.

## 0.1.5
- Pobieranie wszystkich nieodczytanych PDF-ów jako jeden ZIP.

## 0.1.4
- Poprawka dostępu do SQLite z wątku panelu.

## 0.1.3
- Panel (ingress) z listą nieodczytanych PDF-ów.

## 0.1.2
- Nieodczytane PDF-y zapisywane w `/share/gpk_water_failed`.

## 0.1.1
- Maile z nieudanym odczytem są ponawiane przy kolejnych przebiegach.

## 0.1.0
- Pierwsza wersja: pobieranie faktur z Gmaila (IMAP), parser PDF, SQLite, sensory MQTT, import historii do statystyk HA.
