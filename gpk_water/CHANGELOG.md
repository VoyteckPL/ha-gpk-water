# Changelog

## 0.6.3
- Powiadomienia: ustawienia zapisują się od razu po zmianie (wcześniej trzeba było kliknąć Zapisz, inaczej po wyjściu z zakładki zaznaczenia znikały).

## 0.6.2
- „Koszt faktur" ma własne filtry: 12 mies. / Rok (jeden lub kilka lat do porównania) / Lata - zawsze w ujęciu miesięcznym lub rocznym, z podziałem na składniki.
- „Ceny za m³" ma własne filtry: 12 mies. / 2 lata / 5 lat / Wszystko (domyślnie cały okres).
- Na wykresie cen punkty tylko tam, gdzie cena się zmieniła; kliknięcie pokazuje datę faktury, „było → jest" i zmianę w %.

## 0.6.1
- Domyślne widoki zużycia: 7 dni i 30 dni po dniach, Rok po miesiącach (24 h po godzinach).
- Wykresy pokazują każdą etykietę osi (obróconą, gdy jest ich dużo) zamiast co drugiej.

## 0.6.0
- Przegląd uporządkowany: 4 kafelki (bieżący okres, prognoza, ostatnia faktura, ceny) i jeden wspólny filtr zakresu dla wszystkich wykresów: 24 h, 7 dni, 30 dni, Rok (z porównaniem lat) i Wszystko.
- Wykres zużycia z wodomierzy ma teraz widok godzinowy (24 h i 7 dni) oraz wybór szczegółowości (godziny, dni, tygodnie, miesiące). Dom i ogród włączasz klikając legendę.
- Usunięte: dodatkowe kafelki, osobne przyciski Dom/Ogród i oddzielne zestawy filtrów przy każdym wykresie.

## 0.5.7
- Przegląd: pierwszy rząd to „Bieżący okres” (koszt narosły od ostatniej faktury wg liczników) i „Prognoza faktury”, drugi to ostatnia faktura i kompaktowy kafel cen o tej samej wielkości.

## 0.5.6
- Nagłówek na telefonie: znacznik synchronizacji to sama kropka (tekst po dotknięciu), podsumowanie „75 faktur · 2020–2026” mieści się w całości.

## 0.5.5
- Nagłówek na telefonie w jednym rzędzie: mniejsze logo, krótszy tytuł, mniejszy znacznik synchronizacji i przycisk odświeżania.

## 0.5.4
- Statystyki z liczników (kafelki, szacunek, wykres zużycia z zakresami) przeniesione na stronę Przegląd; zakładka Liczniki zostaje na ustawienia i kontrolę z fakturami.
- Mniejsze przyciski, lata mieszczą się w jednym rzędzie na telefonie.

## 0.5.3
- Powiadomienia: „Wyślij próbne” używa aktualnie zaznaczonych urządzeń (nie trzeba najpierw zapisywać) i pokazuje błędy zwrócone przez HA (np. nieistniejąca usługa).

## 0.5.2
- Powiadomienia: można zaznaczyć kilka urządzeń naraz (np. telefon swój i żony), każde dostaje powiadomienie.

## 0.5.1
- Powiadomienia: usługa telefonu wybierana z listy usług notify z Home Assistant (telefony z aplikacją na górze).

## 0.5.0
- Przegląd: nowe filtry. Domyślnie bieżący rok, kliknięcie kolejnych lat włącza porównanie lat (koszt i zużycie wg miesięcy), „Wszystkie" pokazuje całą historię. Usunięto „Na 30 dni" i zakresy 12/24 mies.
- Odczyty: odbiorcy wybierani osobno (GPK Szemud, dodatkowe adresy, kopia na konto dodatku), temat „Stan liczników wody" + adres, stany liczników z jednym miejscem po przecinku.
- Nowa zakładka Powiadomienia: nowa faktura (kwota, termin, okres, zużycie, porównanie), zmiana cen, wysoka faktura, nota odsetkowa, nietypowe zużycie domu (wyciek lub woda poza podlicznikiem), brak faktury po odczytach, wysyłka odczytów, problemy z pocztą/PDF. Telefon przez usługę notify, cisza nocna, dziennik wysłanych.

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
